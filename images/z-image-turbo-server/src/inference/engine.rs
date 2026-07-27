//! Z-Image-Turbo inference engine powered by Candle.
//!
//! # Memory management (RTX 4000 SFF Ada — 20475 MiB)
//!
//! ⚠️ The published repo is **not** FP8 and not 8 GB, whatever the model's
//! marketing says. `Tongyi-MAI/Z-Image-Turbo` ships FP32 safetensors:
//! transformer 24.62 GB, text encoder 8.05 GB, VAE 0.17 GB — ~33 GB on disk,
//! which is also why the weights PVC is sized at 45 GiB and not 20.
//!
//! Loaded at BF16 (`VarBuilder` converts on load) that becomes ~12.3 GB of
//! transformer + ~0.09 GB of VAE on the GPU and ~4.0 GB of text encoder in host
//! RAM. So:
//!
//! 1. Keep the **text encoder on CPU** always — its weights live in system RAM.
//!    Text encoding runs on CPU (acceptable latency for short prompts), and only
//!    the output embeddings tensor (~1 MB) is moved to GPU.
//! 2. Keep the **transformer and VAE on GPU** — they need GPU for fast inference.
//! 3. Use **BF16 precision** everywhere (2× memory saving vs the FP32 on disk).
//! 4. Enforce **max 1024×1024 resolution** at default; 512×512 for tight memory.
//! 5. Use **single-request serialization** via Mutex — only one inference at a time.
//!
//! ~12.4 GB resident of a 20 GiB card leaves ~7 GiB for activations, which is
//! comfortable at 1024×1024 — unlike the 12 GB A2000 this server was first
//! written for, where it did not fit without offload gymnastics.

use std::path::{Path, PathBuf};

use anyhow::Result;
use candle_core::{DType, Device, IndexOp, Tensor};
use candle_nn::VarBuilder;
use candle_transformers::models::z_image::{
    calculate_shift, get_noise, postprocess_image, AutoEncoderKL, Config,
    FlowMatchEulerDiscreteScheduler, SchedulerConfig, TextEncoderConfig, VaeConfig,
    ZImageTextEncoder, ZImageTransformer2DModel,
};
use hf_hub::api::sync::Api;
use tokenizers::Tokenizer;
use tracing::{info, warn};

use crate::config::Config as ServerConfig;

// ── Scheduler constants (from Z-Image paper) ──────────────────────────────
const BASE_IMAGE_SEQ_LEN: usize = 256;
const MAX_IMAGE_SEQ_LEN: usize = 4096;
const BASE_SHIFT: f64 = 0.5;
const MAX_SHIFT: f64 = 1.15;

/// The inference engine holds all model components.
///
/// Created once (lazily on first request) and reused for the lifetime of the
/// server. All GPU-resident components are stored here.
#[allow(dead_code)]
pub struct InferenceEngine {
    /// DiT transformer — always on GPU.
    transformer: ZImageTransformer2DModel,
    /// VAE decoder — always on GPU.
    vae: AutoEncoderKL,
    /// Text encoder — kept on CPU, loaded there to save VRAM.
    text_encoder: Option<ZImageTextEncoder>,
    /// Tokenizer (lightweight, CPU).
    tokenizer: Tokenizer,
    /// Cached text encoder config (no need to reload).
    text_encoder_cfg: TextEncoderConfig,
    /// Transformer config (holds patch_size etc.).
    transformer_cfg: Config,
    /// Scheduler config (stateless, recreated per request).
    scheduler_cfg: SchedulerConfig,
    /// GPU device.
    device: Device,
    /// Data type (BF16 on CUDA, F32 fallback).
    dtype: DType,
    /// Total VRAM available (for memory checks).
    vram_bytes: u64,
}

impl InferenceEngine {
    /// Load the model from disk and initialise all components.
    ///
    /// # Memory strategy
    ///
    /// - Text encoder: loaded on CPU via separate `VarBuilder`.
    /// - Transformer + VAE: loaded on GPU via separate `VarBuilder`.
    /// - Tokenizer: loaded on CPU (always).
    pub fn load(cfg: &ServerConfig) -> Result<Self> {
        let model_path = &cfg.model_dir;
        let use_local = model_path.join("transformer").join("config.json").exists();

        // ── Device setup ──────────────────────────────────────────────────
        // CUDA path: requires the `cuda` feature to be enabled.
        #[cfg(feature = "cuda")]
        let device = if cfg.cpu {
            warn!("CPU mode forced — inference will be very slow");
            Device::Cpu
        } else if candle_core::utils::cuda_is_available() {
            match Device::new_cuda(0) {
                Ok(dev) => {
                    match dev.cuda_free_and_total() {
                        Ok((free, total)) => info!(
                            free_vram_mb = free / (1024 * 1024),
                            total_vram_mb = total / (1024 * 1024),
                            "CUDA device initialised"
                        ),
                        Err(_) => info!("CUDA device initialised"),
                    }
                    dev
                }
                Err(e) => {
                    warn!("CUDA device creation failed: {e}, falling back to CPU");
                    Device::Cpu
                }
            }
        } else {
            warn!("CUDA not available, falling back to CPU");
            Device::Cpu
        };

        // Non-CUDA path: CPU only.
        #[cfg(not(feature = "cuda"))]
        let device = {
            warn!("Compiled without CUDA feature — running on CPU will be very slow");
            Device::Cpu
        };

        let _is_cpu = matches!(device, Device::Cpu);

        let dtype = device.bf16_default_to_f32();

        let repo = if use_local {
            None
        } else {
            let api = Api::new()?;
            Some(api.model("Tongyi-MAI/Z-Image-Turbo".to_string()))
        };

        let cpu_device = Device::Cpu;

        // ── Load tokenizer (CPU) ──────────────────────────────────────────
        info!("Loading tokenizer...");
        let tokenizer_path = resolve_path(model_path, repo.as_ref(), "tokenizer/tokenizer.json")?;
        let tokenizer = Tokenizer::from_file(&tokenizer_path)
            .map_err(|e| anyhow::anyhow!("Failed to load tokenizer: {e}"))?;

        // ── Load text encoder (CPU only to save VRAM) ─────────────────────
        info!("Loading text encoder on CPU...");
        let text_encoder_cfg_path = resolve_path(
            model_path,
            repo.as_ref(),
            "text_encoder/config.json",
        )?;
        let text_encoder_cfg: TextEncoderConfig = if text_encoder_cfg_path.exists() {
            serde_json::from_reader(std::fs::File::open(&text_encoder_cfg_path)?)?
        } else {
            TextEncoderConfig::z_image()
        };

        let text_encoder_weights = load_safetensors(
            model_path,
            repo.as_ref(),
            "text_encoder",
            &["model-00001-of-00003.safetensors",
              "model-00002-of-00003.safetensors",
              "model-00003-of-00003.safetensors"],
            dtype,
            &cpu_device,
        )?;
        let text_encoder = ZImageTextEncoder::new(&text_encoder_cfg, text_encoder_weights)?;
        info!("Text encoder loaded on CPU.");

        // ── Load transformer (GPU) ────────────────────────────────────────
        info!("Loading transformer on GPU...");
        let transformer_cfg_path = resolve_path(
            model_path,
            repo.as_ref(),
            "transformer/config.json",
        )?;
        let transformer_cfg: Config = if transformer_cfg_path.exists() {
            serde_json::from_reader(std::fs::File::open(&transformer_cfg_path)?)?
        } else {
            Config::z_image_turbo()
        };

        let transformer_weights = load_safetensors(
            model_path,
            repo.as_ref(),
            "transformer",
            &[
                "diffusion_pytorch_model-00001-of-00003.safetensors",
                "diffusion_pytorch_model-00002-of-00003.safetensors",
                "diffusion_pytorch_model-00003-of-00003.safetensors",
            ],
            dtype,
            &device,
        )?;
        let transformer = ZImageTransformer2DModel::new(
            &transformer_cfg,
            transformer_weights,
        )?;
        let patch_size = transformer_cfg.all_patch_size[0];
        info!(patch_size, "Transformer loaded on GPU.");

        // ── Load VAE (GPU) ────────────────────────────────────────────────
        info!("Loading VAE on GPU...");
        let vae_cfg_path = resolve_path(model_path, repo.as_ref(), "vae/config.json")?;
        let vae_cfg: VaeConfig = if vae_cfg_path.exists() {
            serde_json::from_reader(std::fs::File::open(&vae_cfg_path)?)?
        } else {
            VaeConfig::z_image()
        };

        let vae_weights = load_safetensors(
            model_path,
            repo.as_ref(),
            "vae",
            &["diffusion_pytorch_model.safetensors"],
            dtype,
            &device,
        )?;
        let vae = AutoEncoderKL::new(&vae_cfg, vae_weights)?;
        info!("VAE loaded on GPU.");

        // ── Scheduler config ──────────────────────────────────────────────
        let scheduler_cfg = SchedulerConfig::z_image_turbo();

        // ── VRAM info ─────────────────────────────────────────────────────
        #[cfg(feature = "cuda")]
        let vram_bytes = if _is_cpu {
            0
        } else {
            device.cuda_free_and_total()
                .map(|(_, total)| total)
                .unwrap_or(0)
        };
        #[cfg(not(feature = "cuda"))]
        let vram_bytes = 0u64;

        info!("Model initialisation complete.");
        Ok(Self {
            transformer,
            vae,
            text_encoder: Some(text_encoder),
            tokenizer,
            text_encoder_cfg,
            transformer_cfg,
            scheduler_cfg,
            device,
            dtype,
            vram_bytes,
        })
    }

    /// Generate one or more images from a text prompt.
    ///
    /// Returns PNG-encoded bytes for each generated image.
    pub fn generate(
        &self,
        prompt: &str,
        num_images: u32,
        width: usize,
        height: usize,
        cfg: &ServerConfig,
    ) -> Result<Vec<Vec<u8>>, crate::ServerError> {
        let num_steps = cfg.num_steps;
        let guidance_scale = cfg.guidance_scale;

        // ── Validate dimensions ───────────────────────────────────────────
        let vae_align = 16;
        if !height.is_multiple_of(vae_align) || !width.is_multiple_of(vae_align) {
            return Err(crate::ServerError::BadRequest(format!(
                "Image dimensions must be divisible by {vae_align}. Got {width}x{height}."
            )));
        }

        // Latent dimensions: VAE has 8× upsampling, formula from Z-Image code
        let latent_h = 2 * (height / vae_align);
        let latent_w = 2 * (width / vae_align);

        // Check estimated VRAM usage against the fleet card (20475 MiB). The
        // threshold is 18 GiB, i.e. warn while there is still ~2 GiB of slack
        // rather than after the allocation has already failed.
        if !cfg.cpu {
            let estimated_mib = self.estimate_vram_usage(latent_h, latent_w) as f64 / (1024.0 * 1024.0);
            if estimated_mib > 18432.0 {
                warn!(
                    estimated_vram_mib = estimated_mib,
                    "Estimated VRAM exceeds 18 GiB — risk of OOM on a 20 GiB RTX 4000 SFF Ada"
                );
            }
        }

        // ── Tokenize ──────────────────────────────────────────────────────
        let formatted = format_prompt_for_qwen3(prompt);
        let encoding = self.tokenizer
            .encode(formatted.as_str(), true)
            .map_err(|e| crate::ServerError::Inference(format!("Tokenization failed: {e}")))?;
        let token_ids = encoding.get_ids();
        let num_tokens = token_ids.len();

        if num_tokens == 0 {
            return Err(crate::ServerError::BadRequest(
                "Prompt tokenized to zero tokens".into(),
            ));
        }

        info!(
            prompt = prompt.chars().take(80).collect::<String>(),
            num_tokens,
            width,
            height,
            "Generating image(s)"
        );

        // ── Text encoding (CPU) ───────────────────────────────────────────
        let cap_feats = {
            let input_ids = Tensor::from_vec(
                token_ids.to_vec(),
                (1, num_tokens),
                &Device::Cpu, // Text encoder weights are on CPU
            )
            .map_err(|e| crate::ServerError::Inference(format!("Tensor creation: {e}")))?;

            // Quick encoding via text encoder (on CPU for memory efficiency)
            let text_encoder = self.text_encoder.as_ref().ok_or_else(|| {
                crate::ServerError::ModelLoad("Text encoder not loaded".into())
            })?;
            let cap_feats = text_encoder
                .forward(&input_ids)
                .map_err(|e| crate::ServerError::Inference(format!("Text encoding failed: {e}")))?;

            // Ensure cap_feats is on GPU
            if !cfg.cpu {
                cap_feats.to_device(&self.device)
                    .map_err(|e| crate::ServerError::Inference(format!("Move to GPU: {e}")))?
            } else {
                cap_feats
            }
        };

        // Mask: all ones (no padding masking needed for simple prompts)
        let cap_mask = Tensor::ones((1, num_tokens), DType::U8, &self.device)
            .map_err(|e| crate::ServerError::Inference(format!("Mask creation: {e}")))?;

        // ── CFG negative prompt ───────────────────────────────────────────
        // We use the empty string as negative prompt for CFG, matching the
        // original Z-Image-Turbo behaviour when no negative prompt is given.
        let (neg_cap_feats, neg_cap_mask) = if guidance_scale > 1.0 {
            let neg_formatted = format_prompt_for_qwen3("");
            let neg_encoding = self.tokenizer
                .encode(neg_formatted.as_str(), true)
                .map_err(|e| crate::ServerError::Inference(format!("Neg tokenization: {e}")))?;
            let neg_ids = neg_encoding.get_ids();

            let neg_input_ids = Tensor::from_vec(
                neg_ids.to_vec(),
                (1, neg_ids.len()),
                &Device::Cpu, // Text encoder weights are on CPU
            )
            .map_err(|e| crate::ServerError::Inference(format!("Neg tensor: {e}")))?;

            let text_encoder = self.text_encoder.as_ref().ok_or_else(|| {
                crate::ServerError::ModelLoad("Text encoder not loaded".into())
            })?;
            let nfeats = text_encoder
                .forward(&neg_input_ids)
                .map_err(|e| crate::ServerError::Inference(format!("Neg encoding: {e}")))?;
            let nfeats = if !cfg.cpu {
                nfeats.to_device(&self.device)
                    .map_err(|e| crate::ServerError::Inference(format!("Neg to GPU: {e}")))?
            } else {
                nfeats
            };
            let nmask = Tensor::ones((1, neg_ids.len()), DType::U8, &self.device)
                .map_err(|e| crate::ServerError::Inference(format!("Neg mask: {e}")))?;
            (Some(nfeats), Some(nmask))
        } else {
            (None, None)
        };

        // ── Scheduler initialisation ──────────────────────────────────────
        let patch_size = self.diag_patch_size();
        let image_seq_len = (latent_h / patch_size) * (latent_w / patch_size);
        let _mu = calculate_shift(
            image_seq_len,
            BASE_IMAGE_SEQ_LEN,
            MAX_IMAGE_SEQ_LEN,
            BASE_SHIFT,
            MAX_SHIFT,
        );

        let mut scheduler = FlowMatchEulerDiscreteScheduler::new(self.scheduler_cfg.clone());
        // NOTE: We pass None for mu because use_dynamic_shifting=false in SchedulerConfig.
        // The Candle scheduler only applies the static shift when mu=None.
        // Passing Some(mu) skips the shift when use_dynamic_shifting=false (a bug in
        // candle-transformers 0.11's set_timesteps implementation).
        scheduler.set_timesteps(num_steps, None);

        // ── Generate initial noise ────────────────────────────────────────
        let mut latents = get_noise(1, 16, latent_h, latent_w, &self.device)
            .map_err(|e| crate::ServerError::Inference(format!("Noise generation: {e}")))?
            .to_dtype(self.dtype)
            .map_err(|e| crate::ServerError::Inference(format!("Noise dtype: {e}")))?;

        // Add frame dimension: (B, C, H, W) -> (B, C, 1, H, W)
        latents = latents
            .unsqueeze(2)
            .map_err(|e| crate::ServerError::Inference(format!("Unsqueeze frame: {e}")))?;

        // ── Denoising loop ────────────────────────────────────────────────
        info!("Starting denoising loop ({num_steps} steps)...");
        for step in 0..num_steps {
            let t = scheduler.current_timestep_normalized();
            let t_tensor = Tensor::from_vec(vec![t as f32], (1,), &self.device)
                .map_err(|e| crate::ServerError::Inference(format!("t tensor: {e}")))?
                .to_dtype(self.dtype)
                .map_err(|e| crate::ServerError::Inference(format!("t dtype: {e}")))?;

            // Model prediction (conditioned)
            let noise_pred = self.transformer
                .forward(&latents, &t_tensor, &cap_feats, &cap_mask)
                .map_err(|e| crate::ServerError::Inference(format!("Step {step} forward: {e}")))?;

            // Apply CFG if guidance_scale > 1.0
            let noise_pred = if guidance_scale > 1.0 {
                if let (Some(nf), Some(nm)) = (&neg_cap_feats, &neg_cap_mask) {
                    let neg_pred = self.transformer
                        .forward(&latents, &t_tensor, nf, nm)
                        .map_err(|e| crate::ServerError::Inference(format!("Step {step} neg: {e}")))?;
                    // CFG: pred = neg + scale * (pos - neg)
                    let diff = (&noise_pred - &neg_pred)
                        .map_err(|e| crate::ServerError::Inference(format!("CFG diff: {e}")))?;
                    (&neg_pred + (diff * guidance_scale)?)
                        .map_err(|e| crate::ServerError::Inference(format!("CFG add: {e}")))?
                } else {
                    noise_pred
                }
            } else {
                noise_pred
            };

            // Negate the prediction (Z-Image-specific flow matching)
            let noise_pred = noise_pred
                .neg()
                .map_err(|e| crate::ServerError::Inference(format!("Negate: {e}")))?;

            // Remove frame dimension for scheduler: (B, C, 1, H, W) -> (B, C, H, W)
            let noise_pred_4d = noise_pred
                .squeeze(2)
                .map_err(|e| crate::ServerError::Inference(format!("Squeeze pred: {e}")))?;
            let latents_4d = latents
                .squeeze(2)
                .map_err(|e| crate::ServerError::Inference(format!("Squeeze latents: {e}")))?;

            // Scheduler step
            let prev_latents = scheduler
                .step(&noise_pred_4d, &latents_4d)
                .map_err(|e| crate::ServerError::Inference(format!("Scheduler step {step}: {e}")))?;

            // Add back frame dimension
            latents = prev_latents
                .unsqueeze(2)
                .map_err(|e| crate::ServerError::Inference(format!("Unsqueeze back: {e}")))?;
        }

        // ── VAE Decode ────────────────────────────────────────────────────
        info!("Decoding latents with VAE...");
        // Remove frame dimension
        let latents_4d = latents
            .squeeze(2)
            .map_err(|e| crate::ServerError::Inference(format!("Final squeeze: {e}")))?;
        let image_tensor = self.vae
            .decode(&latents_4d)
            .map_err(|e| crate::ServerError::Inference(format!("VAE decode: {e}")))?;

        // Post-process: [-1, 1] tensor -> [0, 255] u8 image
        let image_tensor = postprocess_image(&image_tensor)
            .map_err(|e| crate::ServerError::Inference(format!("Postprocess: {e}")))?;

        // ── Generate requested number of images ───────────────────────────
        let mut results = Vec::with_capacity(num_images as usize);
        let batch_size = image_tensor.dims()[0];
        let num_to_generate = if num_images <= 1 {
            1
        } else {
            // For now, always generate 1 image and duplicate if n>1.
            // Multi-image generation (batch > 1) would require more VRAM.
            // TODO: support multi-image batch generation when VRAM allows.
            num_images.min(4) as usize
        };

        // If we only have 1 image in the batch but need N, duplicate it
        for i in 0..num_to_generate {
            let img_idx = if i < batch_size { i } else { 0 };
            let img_t = image_tensor
                .i(img_idx)
                .map_err(|e| crate::ServerError::Inference(format!("Image index {img_idx}: {e}")))?;

            let png_bytes = tensor_to_png(&img_t, width, height)
                .map_err(|e| crate::ServerError::Inference(format!("PNG encoding: {e}")))?;
            results.push(png_bytes);
        }

        Ok(results)
    }

    /// Estimate VRAM usage for given latent dimensions.
    ///
    /// Rough by design — it exists to log a warning before an allocation fails,
    /// not to budget precisely. Replace the constant with a measured figure once
    /// the load gate has run (inference-ops `how-to/measure-a-model.md`).
    fn estimate_vram_usage(&self, latent_h: usize, latent_w: usize) -> u64 {
        // GPU-resident weights: transformer 24.62 GB + VAE 0.17 GB of FP32 on
        // disk, loaded at BF16 ⇒ ~12.4 GB. The text encoder (8.05 GB FP32 ⇒
        // ~4.0 GB BF16) stays on CPU and costs no VRAM at all.
        // Activations scale with image_seq_len = (latent_h/2) * (latent_w/2).
        // For 1024×1024: latent 128×128, seq_len=64×64=4096 → ~0.1 GB.
        let _patches_h = latent_h / 2; // patch_size=2
        let _patches_w = latent_w / 2;
        let image_seq_len = _patches_h * _patches_w;
        // Activation memory: seq_len * 4096 (hidden_dim) * 2 bytes (BF16) * ~2
        let activation_bytes = (image_seq_len * 4096 * 2 * 2) as u64;
        let weights_bytes = 12_400_000_000u64;
        weights_bytes + activation_bytes
    }

    /// Get the patch size from the transformer config.
    fn diag_patch_size(&self) -> usize {
        if self.transformer_cfg.all_patch_size.is_empty() {
            2 // Default fallback
        } else {
            self.transformer_cfg.all_patch_size[0]
        }
    }
}

// ── Helper functions ──────────────────────────────────────────────────────

/// Format a user prompt for the Qwen3 chat template.
///
/// Format:
/// ```text
/// <|im_start|>user
/// {prompt}<|im_end|>
/// <|im_start|>assistant
/// ```
fn format_prompt_for_qwen3(prompt: &str) -> String {
    format!(
        "<|im_start|>user\n{}<|im_end|>\n<|im_start|>assistant\n",
        prompt
    )
}

/// Resolve a model file path: local directory first, then HuggingFace cache.
fn resolve_path<'a>(
    local_dir: &'a Path,
    repo: Option<&'a hf_hub::api::sync::ApiRepo>,
    relative_path: &str,
) -> Result<PathBuf> {
    let local_path = local_dir.join(relative_path);
    if local_path.exists() {
        return Ok(local_path);
    }

    if let Some(repo) = repo {
        return repo.get(relative_path).map_err(anyhow::Error::msg);
    }

    anyhow::bail!(
        "File not found at {} and no HuggingFace repo available",
        local_path.display()
    );
}

/// Load safetensor files and create a VarBuilder.
///
/// Tries local directory first, falls back to HuggingFace cache.
fn load_safetensors<'a>(
    local_dir: &'a Path,
    repo: Option<&'a hf_hub::api::sync::ApiRepo>,
    subdir: &str,
    filenames: &[&str],
    dtype: DType,
    device: &Device,
) -> Result<VarBuilder<'a>> {
    let local_subdir = local_dir.join(subdir);

    let files: Vec<PathBuf> = if local_subdir.exists() {
        filenames
            .iter()
            .map(|f| local_subdir.join(f))
            .filter(|p| p.exists())
            .collect()
    } else if let Some(repo) = repo {
        filenames
            .iter()
            .map(|f| repo.get(&format!("{subdir}/{f}")))
            .filter_map(|r| r.ok())
            .collect()
    } else {
        Vec::new()
    };

    if files.is_empty() {
        anyhow::bail!(
            "No safetensors files found for {subdir} (looked for: {})",
            filenames.join(", ")
        );
    }

    let paths: Vec<&str> = files.iter().map(|p| p.to_str().unwrap()).collect();
    unsafe { VarBuilder::from_mmaped_safetensors(&paths, dtype, device) }
        .map_err(anyhow::Error::msg)
}

/// Convert a Candle image tensor (C, H, W) with u8 values [0..255] to PNG bytes.
///
/// `postprocess_image` returns (B, C, H, W) in u8 range [0, 255].
/// The caller should `.i(batch_idx)` to get (C, H, W) before calling this.
fn tensor_to_png(tensor: &Tensor, expected_width: usize, expected_height: usize) -> Result<Vec<u8>> {
    let dims = tensor.dims();
    anyhow::ensure!(
        dims.len() == 3,
        "Expected 3D tensor (C, H, W), got {}-D",
        dims.len()
    );

    let (channels, _img_h, _img_w) = tensor.dims3()?;
    anyhow::ensure!(
        channels == 3,
        "Expected 3 colour channels, got {channels}"
    );

    // Candle's postprocess_image returns (C, H, W) — permute to (H, W, C) for the image crate.
    let hwc = tensor.permute((1, 2, 0))?;
    let flattened = hwc.flatten_all()?;
    let pixels: Vec<u8> = flattened.to_vec1()?;

    anyhow::ensure!(
        pixels.len() == expected_width * expected_height * 3,
        "Pixel buffer mismatch: got {} px, expected {expected_width}×{expected_height}×3 = {}",
        pixels.len(),
        expected_width * expected_height * 3,
    );

    let img_buf = image::RgbImage::from_raw(expected_width as u32, expected_height as u32, pixels)
        .ok_or_else(|| anyhow::anyhow!("Failed to create RgbImage from pixel data"))?;

    use std::io::Cursor;
    let mut png_bytes = Vec::new();
    let dyn_img = image::DynamicImage::ImageRgb8(img_buf);
    {
        let mut cursor = Cursor::new(&mut png_bytes);
        dyn_img
            .write_to(&mut cursor, image::ImageFormat::Png)
            .map_err(|e| anyhow::anyhow!("PNG encoding failed: {e}"))?;
    }
    Ok(png_bytes)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_format_prompt_for_qwen3() {
        let formatted = format_prompt_for_qwen3("hello world");
        assert!(formatted.contains("<|im_start|>user"));
        assert!(formatted.contains("hello world"));
        assert!(formatted.contains("<|im_end|>"));
        assert!(formatted.contains("<|im_start|>assistant"));
    }

    #[test]
    fn test_format_prompt_empty() {
        let formatted = format_prompt_for_qwen3("");
        assert_eq!(
            formatted,
            "<|im_start|>user\n<|im_end|>\n<|im_start|>assistant\n"
        );
    }
}
