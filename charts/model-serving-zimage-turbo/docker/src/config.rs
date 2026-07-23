//! Server configuration, parsed from environment variables and CLI args.

use clap::Parser;
use std::path::PathBuf;

/// Z-Image-Turbo inference server — OpenAI-compatible /v1/images/generations.
#[derive(Parser, Debug, Clone)]
#[command(name = "zimage-turbo-server", version, about)]
pub struct Config {
    /// Path to the model weights directory.
    #[arg(long = "model-dir", env = "MODEL_DIR", default_value = "/mnt/models")]
    pub model_dir: PathBuf,

    /// HuggingFace token for gated models.
    #[arg(long = "hf-token", env = "HF_TOKEN")]
    pub hf_token: Option<String>,

    /// API key for Bearer token authentication (Authorization: Bearer <key>).
    /// If not set, authentication is disabled (public endpoint).
    #[arg(long = "api-key", env = "API_KEY")]
    pub api_key: Option<String>,

    /// Host address to bind.
    #[arg(long = "host", env = "HOST", default_value = "0.0.0.0")]
    pub host: String,

    /// Port to listen on.
    #[arg(long = "port", env = "PORT", default_value_t = 8000)]
    pub port: u16,

    /// Maximum image size (width/height) in pixels. Must be divisible by 16.
    #[arg(long = "max-size", env = "MAX_IMAGE_SIZE", default_value_t = 1024)]
    pub max_image_size: usize,

    /// Default number of inference steps.
    #[arg(long = "num-steps", env = "NUM_STEPS", default_value_t = 8)]
    pub num_steps: usize,

    /// Classifier-free guidance scale.
    #[arg(long = "guidance-scale", env = "GUIDANCE_SCALE", default_value_t = 5.0)]
    pub guidance_scale: f64,

    /// Default image width.
    #[arg(long = "default-width", env = "DEFAULT_WIDTH", default_value_t = 1024)]
    pub default_width: usize,

    /// Default image height.
    #[arg(long = "default-height", env = "DEFAULT_HEIGHT", default_value_t = 1024)]
    pub default_height: usize,

    /// Run on CPU (slow) instead of GPU.
    #[arg(long = "cpu", env = "CPU", default_value_t = false)]
    pub cpu: bool,

    /// Use flash attention (requires Ampere+ GPU, e.g. RTX 3090/4090/A2000).
    #[arg(long = "flash-attn", env = "FLASH_ATTN", default_value_t = false)]
    pub flash_attn: bool,

    /// Enable verbose logging.
    #[arg(long = "verbose", short = 'v', env = "VERBOSE", default_value_t = false)]
    pub verbose: bool,
}

impl Config {
    /// Validate configuration at startup.
    pub fn validate(&self) -> Result<(), String> {
        if !self.model_dir.exists() {
            return Err(format!(
                "Model directory does not exist: {}",
                self.model_dir.display()
            ));
        }

        if !self.max_image_size.is_multiple_of(16) {
            return Err(format!(
                "max_image_size must be divisible by 16, got {}",
                self.max_image_size
            ));
        }

        if self.default_width > self.max_image_size {
            return Err(format!(
                "default_width ({}) exceeds max_image_size ({})",
                self.default_width, self.max_image_size
            ));
        }

        if self.default_height > self.max_image_size {
            return Err(format!(
                "default_height ({}) exceeds max_image_size ({})",
                self.default_height, self.max_image_size
            ));
        }

        if self.num_steps == 0 || self.num_steps > 50 {
            return Err(format!(
                "num_steps must be between 1 and 50, got {}",
                self.num_steps
            ));
        }

        if !(0.0..=20.0).contains(&self.guidance_scale) {
            return Err(format!(
                "guidance_scale must be between 0.0 and 20.0, got {}",
                self.guidance_scale
            ));
        }

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_validate_ok() {
        let cfg = Config {
            model_dir: PathBuf::from("/tmp"),
            max_image_size: 1024,
            default_width: 1024,
            default_height: 1024,
            num_steps: 8,
            guidance_scale: 5.0,
            ..Config::parse_from(&["test"])
        };
        assert!(cfg.validate().is_ok());
        // We expect model_dir not found, but validate should not check if /tmp doesn't exist
        // Actually /tmp exists on every Unix. Let me use a known-existing path.
    }

    #[test]
    fn test_validate_invalid_size() {
        let cfg = Config {
            model_dir: PathBuf::from("/tmp"),
            max_image_size: 100, // not divisible by 16
            ..Config::parse_from(&["test"])
        };
        assert!(cfg.validate().is_err());
    }

    #[test]
    fn test_validate_invalid_steps() {
        let cfg = Config {
            model_dir: PathBuf::from("/tmp"),
            num_steps: 0,
            ..Config::parse_from(&["test"])
        };
        assert!(cfg.validate().is_err());
    }

    #[test]
    fn test_validate_invalid_guidance() {
        let cfg = Config {
            model_dir: PathBuf::from("/tmp"),
            guidance_scale: -1.0,
            ..Config::parse_from(&["test"])
        };
        assert!(cfg.validate().is_err());
    }
}
