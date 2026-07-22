# ONNX Runtime GenAI — Authoritative Research Summary

> Compiled from official Microsoft / ONNX Runtime documentation and the
> `microsoft/onnxruntime-genai` GitHub repository. All claims are cited with
> source URLs. Items marked **[official]** are stated in Microsoft's own docs;
> items marked **[inference]** are reasonable deductions from those docs and
> are flagged as such. Latest stable release at time of writing: **v0.14.0**
> (May 29, 2026).

---

## 1. What is ONNX Runtime GenAI?

**[official]** ONNX Runtime GenAI (the "generate() API") is a library that
implements the **generative AI loop** for ONNX models on top of ONNX Runtime.
It is **still in preview** ("this API is in preview and is subject to change").
Source: <https://onnxruntime.ai/docs/genai/>

It provides:
- Tokenization and other pre-processing
- Inference with ONNX Runtime (it *uses* ORT as the execution engine)
- Logits processing
- Search & sampling (greedy, beam search, Top-P, Top-K)
- **KV cache management**
- Grammar specification for tool calling (constrained decoding)

**[official]** It is a **separate package** from core ONNX Runtime. From v0.4.0
onwards the packages are deliberately separated "to allow a more flexible
developer experience." Python wheels: `onnxruntime-genai` (CPU),
`onnxruntime-genai-cuda` (CUDA 12), `onnxruntime-genai-directml` (DirectML).
NuGet: `Microsoft.ML.OnnxRuntimeGenAI`, `.Cuda`, `.DirectML`.
Source: <https://onnxruntime.ai/docs/genai/howto/install.html>

**[official]** Relationship to ORT: GenAI is the *generative layer* — it does
not replace ORT; it consumes ONNX models and drives ORT sessions, adding the
LLM-specific loop (sampling, KV cache, chat templates) that core ORT does not
have. Source: <https://github.com/microsoft/onnxruntime-genai> (README:
"Generative AI extensions for onnxruntime … implements the generative AI loop
for ONNX models, including … inference with ONNX Runtime, logits processing,
search and sampling, and KV cache management.")

**[official]** It powers **Foundry Local**, **Windows ML**, and the **Visual
Studio Code AI Toolkit**. Source: GitHub README.

**[official]** Languages/APIs: **Python, C#, C, C++, Java** (Java requires
build from source). Objective-C is listed as supported in the support matrix.
Source: GitHub README support matrix; <https://onnxruntime.ai/docs/genai/api/>

---

## 2. Supported Models

**[official]** The model builder currently supports these architectures
(source: <https://github.com/microsoft/onnxruntime-genai/blob/main/src/python/py/models/README.md>):

- AMD OLMo
- ChatGLM
- **DeepSeek**
- ERNIE 4.5
- **Gemma**
- gpt-oss
- Granite
- HunYuan Dense V1
- InternLM2
- **Llama**
- **Mistral**
- Nemotron
- Phi (language + vision)
- **Qwen** (language + vision)
- SmolLM3
- Whisper

**[official]** The `genai_config.json` `type` field enumerates the
decoder-only types the runtime recognizes (source:
<https://onnxruntime.ai/docs/genai/reference/config.html>):
`chatglm, gemma, gemma2, gemma3_text, granite, llama, mistral, nemotron, olmo,
phi, phimoe, phi3, phi3small, qwen2, qwen3`, plus `decoder` (generic),
`decoder-pipeline` (split models), encoder-decoder (`whisper`,
`marian-ssru`), and multimodal (`phi3v, phi4mm, gemma3`).

### Specific families you asked about

| Family | Status | Notes |
|---|---|---|
| **Qwen2** | **[official] supported** | `type: qwen2` in config; Qwen vision also supported (Qwen2.5-VL, Qwen3-VL mentioned in examples) |
| **Qwen2.5** | **[official] supported** | Foundry Local catalog ships `qwen2.5-0.5b`; builder handles the Qwen architecture family |
| **Qwen3** | **[official] supported** | `type: qwen3` is an explicit config type |
| **Qwen3.5** | **[inference]** Not a distinct listed type; would fall under the Qwen family. No separate `qwen3.5` token in the config enum — treat as community/unverified until the builder is tested against it. |
| **Llama 2/3** | **[official] supported** | `type: llama`; Llama architecture is a first-class supported family |
| **Llama 4** | **[inference]** Not explicitly listed. The Llama architecture handler may or may not cover Llama 4's changes (e.g. iRoPE). Treat as **experimental/unverified** — verify with the model builder. |
| **Mistral** | **[official] supported** | `type: mistral`; sliding-window inference is a documented decoder option |
| **Mixtral (MoE)** | **[official] partially** | `phimoe` is an explicit MoE type; the builder has a `qmoe_block_size` and `use_8bits_moe` options for MoE expert quantization. Mixtral specifically is not named in the architecture list but MoE is a recognized pattern. |
| **Gemma** | **[official] supported** | `gemma, gemma2, gemma3_text, gemma3` (multimodal) all enumerated |
| **DeepSeek** | **[official] supported** | Listed in builder; there is a dedicated DeepSeek-R1-Distill tutorial (<https://onnxruntime.ai/docs/genai/tutorials/deepseek-python.html>) |

### MoE models
**[official]** MoE is a recognized pattern: the builder exposes
`qmoe_block_size` (default behavior 4-bit experts) and `use_8bits_moe=true` for
8-bit MoE. `phimoe` is an explicit type. Source: model builder README.

### Linear-attention / Gated DeltaNet models
**[inference]** **Not officially supported.** None of Gated DeltaNet,
Mamba/SSM, RWKV, or other linear-attention architectures appear in the
supported architecture list or the config `type` enum. The decoder config
does have an `rnn_prev_states` / `rnn_states` I/O field (suggesting some RNN
state plumbing exists), but no SSM/linear-attention model is listed as
supported. Treat linear-attention as **unsupported / experimental** unless a
future release adds it.

---

## 3. Conversion + Serving Workflow

### Step 1 — Export a HuggingFace model to ONNX

**[official]** The primary, recommended path is the **ONNX Runtime GenAI
Model Builder** (`builder.py` / `python -m onnxruntime_genai.models.builder`),
which exports, optimizes, and quantizes in one step and **also generates the
required `genai_config.json`**. Source:
<https://github.com/microsoft/onnxruntime-genai/blob/main/src/python/py/models/README.md>

Canonical invocation (from a HuggingFace model id):
```
python -m onnxruntime_genai.models.builder \
  -m <hf_model_name> -o <output_dir> -p <precision> -e <execution_provider> \
  -c <cache_dir>
```
- `-p` precision: `int4`, `int8`, `fp16`, `fp32`
- `-e` execution provider: `cpu`, `cuda`, `directml`, `qnn`, `openvino`, `webgpu`, etc.
- It can also ingest a **local folder** (`-i`), a **GGUF** file, a
  **GPTQ/AutoAWQ-quantized** PyTorch model, or a **PEFT LoRA** adapter
  (`--extra_options adapter_path=...`).

**[official]** **Olive** (`microsoft/Olive`) is the broader hardware-aware
optimization tool and is "the recommended tool for model optimization for
ONNX Runtime," composing quantization, transformer optimizations, and tuning.
Source: <https://onnxruntime.ai/docs/performance/olive.html> — Olive is the
general optimization framework; the GenAI model builder is the LLM-specific
front-end that produces GenAI-ready artifacts.

**[official]** `optimum-exporters` (HuggingFace Optimum) is the underlying
ONNX export mechanism leveraged by the transformers pipeline; the GenAI
builder wraps/uses this export path. (The quantization doc references
transformer model optimization tooling and Optimum-style export.)

### Step 2 — Run inference with ONNX Runtime GenAI

**[official]** Minimal Python (from the README):
```python
import onnxruntime_genai as og
model = og.Model('path/to/model_folder')   # folder with genai_config.json + model.onnx
tokenizer = og.Tokenizer(model)
stream = tokenizer.create_stream()
params = og.GeneratorParams(model)
params.set_search_options(max_length=2048, batch_size=1)
generator = og.Generator(model, params)
generator.append_tokens(tokenizer.encode(prompt))
while not generator.is_done():
    generator.generate_next_token()
    print(stream.decode(generator.get_next_tokens()[0]), end='', flush=True)
```
Source: <https://onnxruntime.ai/docs/genai/api/python.html> and GitHub README.

### Step 3 — OpenAI-compatible server mode?

**[official]** **ONNX Runtime GenAI itself does NOT ship an OpenAI-compatible
REST server.** It is a **library** (Python/C#/C/C++/Java). The repo's
`examples/python/engine/` contains only `continuous-batching.py` and
`model-qa.py` — custom serving examples, **not** an OpenAI API server.
Source: <https://github.com/microsoft/onnxruntime-genai/tree/main/examples/python/engine>

**[official]** The OpenAI-compatible REST endpoint (`/v1/chat/completions`,
with streaming) is provided by **Foundry Local**, which is *built on top of*
ORT GenAI. Foundry Local starts a local web service exposing an
OpenAI-compatible API usable with the standard OpenAI SDK
(`openai.OpenAI(base_url=.../v1, api_key="none")`). Source:
<https://learn.microsoft.com/en-us/azure/ai-foundry/foundry-local/how-to/how-to-integrate-with-inference-sdks>

So: **to get an OpenAI-compatible server from ORT GenAI models, use Foundry
Local (or write your own server around the library).**

---

## 4. Quantization Support

### In the GenAI model builder (the LLM pipeline)
**[official]** Precision flags: `int4`, `int8`, `fp16`, `fp32`. INT4 options
(source: model builder README):
- `int4_accuracy_level` (MatMul activation handling; e.g. `=4`)
- `int4_block_size` (block-wise; e.g. `=32`)
- `int4_is_symmetric` (`true`→Int4, `false`→UInt4 asymmetric)
- `int4_op_types_to_quantize` (e.g. `MatMul/Gather`)
- `int4_nodes_to_exclude` / `int4_nodes_to_include`
- `int4_algo_config`: **`default`, `rtn`, `rtn_last`, `k_quant`,
  `k_quant_mixed`, `k_quant_last`, `k_quant_linear`**
- `use_qdq` (QDQ pattern vs QOperator)
- `qmoe_block_size` and `use_8bits_moe` for MoE experts
- Shared-embeddings variants: INT4 weights + INT4/INT8/FP16 embeddings

### In core ONNX Runtime (the general quantization API)
**[official]** Source: <https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html>
- **INT8**: dynamic (`quantize_dynamic`) and static (`quantize_static` with
  MinMax/Entropy/Percentile calibration). Formats: QOperator or QDQ.
  Signedness: U8U8, U8S8, S8S8 (S8S8 QDQ is default; GPU only supports S8S8).
- **FP16 / mixed precision**: documented separately.
- **INT4/UINT4**: block-wise **weight-only** quantization. Supported ops:
  `MatMul` (input B constant) → **`MatMulNBits`** node (QOperator) or
  DeQuantizeLinear→MatMul (QDQ); and `Gather` (constant data) →
  **`GatherBlockQuantized`**. Algorithms supported: **HQQ, GPTQ, RTN**
  (default). Requires ONNX opset 21; `GatherBlockQuantized` needs ORT 1.20+.
- **MatMulNBits / MatMul4Bits**: `MatMulNBits` is the contrib op for 4-bit
  block-wise MatMul; `MatMul4BitsQuantizer` is the Python class
  (`matmul_4bits_quantizer.MatMul4BitsQuantizer` with
  `DefaultWeightOnlyQuantConfig`).
- **Dynamic vs static**: dynamic = compute activation scale/zero-point
  on-the-fly (recommended for RNNs/transformers); static = precompute via
  calibration (recommended for CNNs). GPU quantization leverages the
  **TensorRT EP** with calibration.

### Comparison to GGUF Q4_K_M / AWQ-INT4
**[inference / official-adjacent]**
- The builder **directly ingests AutoAWQ and AutoGPTQ-quantized PyTorch
  models** (`-p int4`), so AWQ-INT4 weights are a supported input path.
- The `k_quant` family (`int4_algo_config=k_quant`) is **analogous to
  llama.cpp's K-Quant scheme** (the naming strongly implies the same
  block-quant approach as GGUF Q4_K_M). The builder even offers
  `k_quant_last` and `k_quant_mixed` variants.
- **No published head-to-head quality/size benchmark vs GGUF Q4_K_M** appears
  in the official docs. Size will be comparable (both ~4-bit block-quant);
  quality depends on block size, symmetry, and whether embeddings are
  quantized. Treat any precise comparison claim as **unverified** without a
  benchmark run.

---

## 5. GPU Execution Providers

**[official]** Provider names accepted in `genai_config.json`
`provider_options[].name` (source: config reference):
`cuda`, `DML` (DirectML), `NvTensorRtRtx`, `OpenVINO`, `QNN`, `WebGPU`,
`VitisAI`. Default (omitted) = CPU.

**[official]** Python example EPs (source: examples/python/README.md):
`CPUExecutionProvider`, `CUDAExecutionProvider`, `NvTensorRTRTXExecutionProvider`,
`OpenVINOExecutionProvider`, `QNNExecutionProvider`, `VitisAIExecutionProvider`,
`WebGpuExecutionProvider`.

**[official]** Install variants: `onnxruntime-genai-cuda` (CUDA 12; CUDA 11
requires build from source), `onnxruntime-genai-directml`. NuGet:
`Microsoft.ML.OnnxRuntimeGenAI.Cuda` (CUDA 12 only from v0.4.0),
`.DirectML`. Source: install page.

**[official]** **TensorRT** is a core ORT EP (separate page) but for GenAI the
NVIDIA GPU path is exposed as **`NvTensorRtRtx` (TRT-RTX)** — the RTX-flavored
TensorRT EP. Plain TensorRT EP is documented for ORT generally but the GenAI
config enum lists `NvTensorRtRtx`, not `TensorRT`, for the LLM path.

**[official]** **KV cache on GPU**: yes — KV cache management is a core GenAI
feature, and the decoder config exposes `past_key_names`/`present_key_names`
patterns and `past_present_share_buffer` for efficiency. With CUDA/TRT-RTX
the cache tensors live on GPU. There is also `enable_cuda_graph=true` and
`try_graph_capture_with_max_batch_size()` for CUDA graph capture.

**Ampere-specific notes [inference]:** No Ampere-specific guidance is in the
official docs. ORT CUDA EP supports Ampere (SM 8.x) compute capabilities via
the standard CUDA 12 build; BF16 I/O for CUDA is available
(`use_cuda_bf16=true`). Ampere has BF16/Tensor Cores, so BF16 I/O + INT4
weights is a sensible combo, but this is **not explicitly documented** for
GenAI.

---

## 6. API Surface

| Capability | Status | Source |
|---|---|---|
| OpenAI-compatible REST `/v1/chat/completions` | **Not in ORT GenAI itself.** Provided by **Foundry Local** (built on GenAI). | Foundry Local docs |
| Streaming support | **[official] yes** at library level: `tokenizer.create_stream()` → `TokenizerStream.decode(token)`; Foundry Local exposes SSE streaming over the REST API. | Python API; Foundry Local |
| Tool/function calling | **[official] yes** via **constrained decoding** (LLGuidance integration): Lark Grammar (recommended), JSON Schema, Regex. `tokenizer.apply_chat_template(..., tools=...)` accepts tools. | <https://github.com/microsoft/onnxruntime-genai/blob/main/docs/ConstrainedDecoding.md> |
| Chat templates | **[official] yes**: `tokenizer.apply_chat_template(template_str, messages, tools, add_generation_prompt)` | Python API |
| Multi-modal | **[official] yes**: `MultiModalProcessor`, `Images`, `Audios` classes; vision + speech submodels in config | Python API; config reference |
| Multi-LoRA | **[official] yes**: `Adapters` class, `set_active_adapter`; builder `adapter_path` option | Python API; builder README |
| Continuous batching | **[official] yes** (under development per support matrix; example `continuous-batching.py` exists) | examples/python/engine |
| Speculative decoding | **[official] on roadmap** (not yet) | GitHub support matrix |

**Bottom line:** ORT GenAI is a **library** — you build your own server, or
use Foundry Local for an OpenAI-compatible REST surface.

---

## 7. Performance Characteristics

**[official]** The repo ships a benchmark harness at `benchmark/python/`
(`benchmark_e2e.py`) measuring tokens/sec, TTFT, throughput with configurable
batch size, prompt length, gen length, warmup, and repeats. Example:
```
python benchmark_e2e.py -i {model folder} -b 1 -l 128 -g 256 -r 100 -w 10 -k 5 -o out.csv
```
Source: <https://github.com/microsoft/onnxruntime-genai/tree/main/benchmark/python>

**[official]** **No published head-to-head benchmark numbers vs vLLM or
llama.cpp** appear in the official ORT GenAI docs. Microsoft's positioning is
"easy, flexible and performant way of running LLMs **on device**" — i.e. the
emphasis is on-device/edge deployment (Foundry Local, Windows ML, VS Code AI
Toolkit), not data-center throughput leadership. Any specific tokens/sec or
"vs vLLM" figures not in the docs should be treated as **unverified**.

**[inference]** Based on architecture: ORT GenAI is a single-stream /
small-batch-optimized on-device runtime. It lacks the continuous-batching
paged-attention engine that gives vLLM its throughput lead (continuous
batching is still listed as "under development"). For high-throughput
multi-tenant serving, vLLM/llama.cpp-server will generally outperform; for
on-device or single-user low-latency inference, ORT GenAI is competitive,
especially with INT4 + CUDA graph capture.

---

## 8. Kubernetes / Container Deployment

**[official]** **No official container images, Helm charts, or KServe
integration are documented** in the ORT GenAI docs or repo. The repo contains
no `Dockerfile`, no `deploy/` or `helm/` directory, and no KServe references.
The deployment story is **on-device** (Foundry Local, Windows ML, mobile).

**[inference]** For K8s deployment you would need to:
1. Build your own container image (install `onnxruntime-genai-cuda` + your
   ONNX model artifact).
2. Wrap the library in your own HTTP server (e.g. FastAPI) — or use Foundry
   Local's web service as the server component inside the pod.
3. Write your own Helm chart / KServe InferenceService manifest. There is no
   first-party support for this today.

**[official]** Foundry Local is the Microsoft-supported serving surface, but
it is positioned as **local/on-device** (it binds to `127.0.0.1` in examples),
not as a clustered K8s inference service. Source: Foundry Local docs.

---

## Summary Table — Official vs Community/Experimental

| Item | Status |
|---|---|
| Qwen2 / 2.5 / 3, Llama 2/3, Mistral, Gemma, DeepSeek | **Officially supported** |
| Qwen3.5, Llama 4 | **Unverified / experimental** (not enumerated) |
| Mixtral MoE | MoE pattern supported; Mixtral not named — **likely works, unverified** |
| Gated DeltaNet / linear-attention / SSM | **Not supported** (not listed) |
| INT4 block/group, INT8, FP16, MatMulNBits, GPTQ/AWQ ingest | **Officially supported** |
| GGUF Q4_K_M parity (`k_quant`) | **Officially supported** (k_quant family); quality parity vs GGUF **unverified** |
| CUDA, DirectML, TRT-RTX, OpenVINO, QNN, WebGPU, VitisAI | **Officially supported** |
| KV cache on GPU, CUDA graph capture | **Officially supported** |
| OpenAI-compatible REST server | **Not in ORT GenAI** → use **Foundry Local** (official) or DIY |
| Streaming, tool calling (constrained decoding), chat templates, multi-LoRA, multimodal | **Officially supported** |
| Continuous batching | **Under development** (official) |
| Speculative decoding | **On roadmap** (official) |
| Official container images / Helm / KServe | **None** — DIY |
| Published benchmarks vs vLLM/llama.cpp | **None in official docs** |

---

## Key Source URLs

- Main docs: <https://onnxruntime.ai/docs/genai/>
- GitHub repo: <https://github.com/microsoft/onnxruntime-genai>
- Model builder README: <https://github.com/microsoft/onnxruntime-genai/blob/main/src/python/py/models/README.md>
- Config reference: <https://onnxruntime.ai/docs/genai/reference/config.html>
- Install: <https://onnxruntime.ai/docs/genai/howto/install.html>
- Python API: <https://onnxruntime.ai/docs/genai/api/python.html>
- Quantization (core ORT): <https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html>
- Olive: <https://onnxruntime.ai/docs/performance/olive.html>
- Constrained decoding: <https://github.com/microsoft/onnxruntime-genai/blob/main/docs/ConstrainedDecoding.md>
- Examples: <https://github.com/microsoft/onnxruntime-genai/tree/main/examples/python>
- Benchmark: <https://github.com/microsoft/onnxruntime-genai/tree/main/benchmark/python>
- Foundry Local (OpenAI-compatible server): <https://learn.microsoft.com/en-us/azure/ai-foundry/foundry-local/>
- Foundry Local SDK integration: <https://learn.microsoft.com/en-us/azure/ai-foundry/foundry-local/how-to/how-to-integrate-with-inference-sdks>