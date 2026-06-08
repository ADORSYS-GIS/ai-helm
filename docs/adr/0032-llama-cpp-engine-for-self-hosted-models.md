# ADR-0032: llama.cpp (`llama-server`) as a second self-hosted serving engine

**Status:** Accepted
**Date:** 2026-06-08
**Deciders:** @stephane-segning

## Context

The home-GPU serving pattern (ADR-0022/0028/0029/0030) was built around **vLLM** via
the `kserve/huggingfaceserver` image + in-pod LMCache, with a **Caddy auth-proxy
sidecar** (the huggingfaceserver image ignores `VLLM_API_KEY`, so something else must
enforce the Bearer). That stack shipped Qwen3-4B (`charts/model-serving-qwen3-4b`).

The next model, **Qwen3.5-4B** (Feb 2026, Apache-2.0), is a different beast: a
**Gated DeltaNet + sparse-MoE** hybrid, natively multimodal, 262k native context. Two
findings (full study in `docs/models/qwen3.5-4b.md` / `docs/models/qwen3.5-4b-q4.md`):

1. **vLLM's Qwen3.5 support is turbulent** — it broke on the 0.18.0 bump
   (vllm#37749), the multimodal classes drew "not supported for now" reports
   (vllm#35344/#35391), there is **no text-only `Qwen3_5ForCausalLM` class**, and it
   needs a bleeding-edge `transformers`. On Ampere there's also **no FP8** and **no
   official AWQ/GPTQ**, so a vLLM 4-bit path would need a non-vetted community AWQ or
   vLLM's slow GGUF loader.
2. **llama.cpp already runs the model today** via reputable community **GGUF** quants
   (bartowski / unsloth), the `Q4_K_M`-class artifact the maintainer wanted. Its
   `llama-server` is OpenAI-compatible, has **native API-key auth** (`--api-key-file`),
   a simple `/health` probe, and the model's linear-attention KV makes long context
   cheap on the 12 GB A2000.

A `Q4_K_M` GGUF is **not** a vLLM-native artifact (vLLM's GGUF throughput is poor and
its own docs say to use llama.cpp). So the quant choice and the engine choice are the
same decision.

## Decision

Adopt **llama.cpp (`llama-server`) as a second sanctioned serving engine** for
self-hosted models on the home GPU, alongside the existing vLLM/huggingfaceserver
engine. The ADR-0030 chart *shape* is unchanged (a `bjw-template` StatefulSet, RWX
pre-seeded PVC, plain Ingress + `cert-cloudflare`, `homeCluster: true`, federation via
`charts/ai-models`); only the **model container** differs:

- **Image** `ghcr.io/ggml-org/llama.cpp:server-cuda` (CUDA 12; **not** `server-cuda13`,
  which fails on some GPUs — ggml-org/llama.cpp#22561). Pin a recent digest (the GDN
  operators need a current build).
- **Single container, no Caddy sidecar** — `llama-server` enforces the Bearer natively
  via `--api-key-file`. The long-generation timeout (formerly the Caddy
  `response_header_timeout`) moves to the **Traefik Ingress + the Envoy
  `BackendTrafficPolicy`** (600 s).
- **Quant** unsloth **`UD-Q4_K_XL`** GGUF (imatrix; ~2.7 GB); seeded as a single file.
- **Gateway** backend `prefix: /v1` (not `/openai/v1`); probes `httpGet /health`.

First model on this engine: **Qwen3.5-4B Q4** — a NEW chart `charts/model-serving-qwen3-5`
(copy of `charts/model-serving-qwen3-4b`), a NEW app + backend (`llama-local-01`) +
model (`qwen3-5-4b-local`), served **text-only**. Because one GPU runs one model at a
time, it is a **swap** of `qwen3-4b-local`: the new deployment is created **staged
(`enabled: false`)** behind a load-gate, and cutover flips the enabled flags (new on /
old off). vLLM remains the engine of record for `qwen3-4b-local` and any future
safetensors/AWQ model.

## Consequences

- **Two engines to keep in mind.** The `docs/self-hosted-model-serving.md` guide now
  carries a vLLM-vs-llama.cpp choice table; pick per model.
- **Simpler chart for GGUF models** — one container, native auth, `/health` probe; the
  vLLM-only gotchas (LMCache↔vLLM skew, the gRPC `:8081` probe collision, the
  `VLLM_API_KEY`-ignored trap, the `/v2/health/ready` dance, the fp8 ban) **do not
  apply**.
- **New caveat:** llama.cpp must be a **recent** build for new architectures, and the
  long-stream timeout now depends on Traefik's entrypoint `respondingTimeouts` (no
  Caddy) — verify it doesn't cut streams.
- **Lower peak throughput/concurrency** than vLLM — acceptable for the low-concurrency
  owned/cheap tier (`--parallel` + continuous batching give modest concurrency).
- **Gate before live:** a recent `server-cuda` build must be proven to load the GGUF on
  the A2000 (GDN operators present, `/health` → 200) before the cutover release.

## Alternatives considered

- **Keep vLLM, BF16** (`docs/models/qwen3.5-4b.md`) — viable for full precision / a
  future vision path, but blocked today by the vLLM Qwen3.5 turbulence above. Kept
  documented as the fallback; not chosen.
- **vLLM + GGUF** — vLLM can load GGUF but throughput is poor (~93 vs ~741 tok/s vs
  Marlin-AWQ) and its docs recommend llama.cpp for GGUF. Rejected.
- **vLLM + community AWQ** — no official AWQ; "no random artifacts" posture + the arch
  turbulence make it riskier than the already-running GGUFs. Rejected for now.

## References

- Papers: [`docs/models/qwen3.5-4b-q4.md`](../models/qwen3.5-4b-q4.md) (chosen),
  [`docs/models/qwen3.5-4b.md`](../models/qwen3.5-4b.md) (rejected alternative),
  [`docs/models/qwen3-4b.md`](../models/qwen3-4b.md) (the vLLM reference).
- Pattern: [`docs/self-hosted-model-serving.md`](../self-hosted-model-serving.md).
- Builds on [0030](./0030-merge-model-and-proxy-into-one-statefulset-bjw.md) /
  [0029](./0029-self-hosted-model-plain-deployment.md) (serving shape) and
  [0022](./0022-self-hosted-gpu-model-federated-into-gateway.md) (federation);
  pricing per [0028](./0028-owned-hardware-model-pricing.md).
- Charts: `charts/model-serving-qwen3-5`, `charts/ai-models` (`llama-local-01` /
  `qwen3-5-4b-local`), `charts/apps` (`model-serving-qwen3-5`, staged + a new per-app
  `enabled` gate).
