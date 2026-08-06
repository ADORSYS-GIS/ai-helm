# ADR-0118: FP8 KV-cache dtype as the fleet default for vLLM models

**Status:** Accepted
**Date:** 2026-08-03
**Deciders:** @stephane-segning

## Context

Self-hosted models on the Hetzner GPU fleet (RTX 4000 SFF Ada, 20475 MiB) are
VRAM-bound: the whole budget for a model is `gpuMemoryUtilization` × 19.99 GiB,
and weights consume most of it, leaving a small remainder for the KV cache,
CUDA graphs and activations (for a 30B-A3B MoE at 0.90: ~2.33 GiB after
~15.66 GiB of AWQ weights). vLLM's default KV-cache dtype is 16-bit (bf16/fp16),
which limits how many tokens fit in that remainder.

A spike (#839) validated fp8 KV cache on this hardware: `fp8_e4m3` (the
E4M3FN format — vLLM's `fp8_e4m3`) stores 8-bit values with a per-tensor
scale, roughly halving the KV footprint — for
`qwen3-vl-4b-thinking` the measured ~1.14 GiB budget holds ~16 500 tokens vs
~8 288 in BF16 (about 2× context capacity in the same VRAM). Nothing else
changes: weights and activations stay in `--dtype`.

This is a fleet-wide default with a measured-but-per-model quality cost, so it
warrants an ADR rather than a silent values change.

## Decision

Adopt `defaults.kvCacheDtype: fp8_e4m3` in `charts/inference` as the fleet
default applied to **every** vLLM model, unless a catalog entry overrides it
with its own `serving.kvCacheDtype`. Per-model `auto` (16-bit, the
pre-quantization behaviour) is the opt-out for a model that fails its fp8
quality gate. `fp8_e5m2` (5-bit exponent / 2-bit mantissa) remains available as
the plan B for models with KV outliers (e.g. vision heads).

Scope is vLLM-only, enforced by render-time guards:

- llama.cpp has no fp8 vocabulary — its 8-bit cache type is `q8_0` (int8 block
  quant), set explicitly per model via `serving.kvCacheType`; no fleet default.
- LocalAI's diffusion backend has no KV cache to quantize.
- `serving.kvCacheDtype` on a non-vLLM engine, or a value vLLM does not accept,
  fails the render (`_helpers.tpl` fail-fast guards, ADR-0118 scope only —
  the knob list itself is validated against the engine's accepted set).
- **LMCache + fp8 is UNVERIFIED on this fleet** and fails the render too:
  LMCache serializes KV tensors as stored on the GPU, and its fp8 path has
  never been exercised here. Use `kvCacheDtype: auto` with LMCache.

## Consequences

**Positive**
- ~2× context capacity in the same VRAM budget for every vLLM model, without
  touching weights or activations.
- One declarative fleet knob; per-model override is a single line; `auto` is
  an instant per-model rollback to 16-bit if a quality gate fails.

**Negative**
- fp8 KV cache is lossy; the quality cost is small but must be **measured per
  model, not assumed** (ADR-0101 discipline). A model whose KV headroom was
  measured in BF16 changes its baseline silently the moment it is re-enabled.
- Today the blast radius is one enabled vLLM model — but the default persists
  for any model re-enabled later. ⚠️ Note: that model **opts out** of the fp8
  default (`serving.kvCacheDtype: auto`, 16-bit), so today no live model
  actually runs fp8 KV. The default still applies to any vLLM model that does
  not override it.
- `fp8_e5m2`/`fp8_e4m3` are passed verbatim to `--kv-cache-dtype`; a future
  vLLM version that renames the accepted set requires the guard list to move
  in lockstep.

**Neutral / follow-ups**
- Benchmark reports for models measured with fp8 go to `inference-ops`
  `docs/benchmarks/` (team convention — inference knowledge lives there).
- The LMCache + fp8 combination stays guarded-off until verified on a live pod.
- Follow-up: an ADR (or benchmark data) for each self-hosted model that
  switches to fp8, once load-gated.
