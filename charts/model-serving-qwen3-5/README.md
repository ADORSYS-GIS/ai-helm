# model-serving-qwen3-5

Self-hosted **Qwen3.5-4B (Q4_K_M GGUF)** on the **home GPU** (RTX A2000, 12 GB),
served by **llama.cpp** (`llama-server`) — a single `bjw-template` StatefulSet with
**one container** (no Caddy sidecar; `llama-server` enforces the Bearer natively via
`--api-key-file`). Weights are a single GGUF fed from a pre-seeded RWX PVC.

Federated into the Hetzner Envoy AI Gateway as an OpenAI backend (`prefix: /v1`),
model id `qwen3-5-4b-local`. Deploys to the **home** cluster (`homeCluster: true`).

**Full deployment paper:** [`docs/models/qwen3.5-4b-q4.md`](../../docs/models/qwen3.5-4b-q4.md).
**Pattern:** [`docs/self-hosted-model-serving.md`](../../docs/self-hosted-model-serving.md).
**Decisions:** ADR-0022 (federation) · ADR-0028 (pricing) · ADR-0030 (one bjw STS) ·
ADR-0032 (llama.cpp engine).

> ⚠️ **Staged.** Wired but disabled (`charts/apps` `model-serving-qwen3-5`
> `enabled: false`; `charts/ai-models` `qwen3-5-4b-local` `enabled: false`) until
> the load-gate passes — a recent `server-cuda` build must load the GGUF on the
> A2000. Cutover = enable these + disable the `qwen3-4b` ones (one GPU → one model).
