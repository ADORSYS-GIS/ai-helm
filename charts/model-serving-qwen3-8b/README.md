# model-serving-qwen3-8b

Self-hosted LLM on the **home GPU** (RTX A2000, 12 GB): **Qwen3-8B-AWQ**
(AWQ 4-bit quantized, 8.2B params, ~5 GB) served via **vLLM**
(`kserve/huggingfaceserver`) with a **Caddy auth-proxy sidecar**. A single
**`bjw-template StatefulSet`** (always-on, `replicas: 1`) with **two containers
in one pod** — the model + the proxy. Weights are fed from a **pre-seeded PVC**
(local mount, no per-start HuggingFace download). AWQ INT4 fits the full 32K
context in 12GB VRAM with room for KV cache.

- **Why:** [ADR-0022](../../docs/adr/0022-self-hosted-gpu-model-federated-into-gateway.md) (federation) + [ADR-0028](../../docs/adr/0028-owned-hardware-model-pricing.md) (pricing) + [ADR-0029](../../docs/adr/0029-self-hosted-model-plain-deployment.md) (serving mode) + [ADR-0030](../../docs/adr/0030-merge-model-and-proxy-into-one-statefulset-bjw.md) (one STS via bjw)
- **How:** [`docs/patterns/self-hosted-model-serving.md`](../../docs/patterns/self-hosted-model-serving.md)

## Unusual things about this chart

- **Hybrid bjw chart** (like `charts/librechat-app`): the `bjw-template` subchart
  (values under `modelServing:`) renders the **whole workload** — the StatefulSet,
  the seed `Job` (a bjw `job` controller), the Service, and the Ingress. The chart's
  own `templates/` render only the PVC, the ExternalSecrets, and the Caddyfile
  ConfigMap.
- **⚠️ Port layout:** the model server binds HTTP `:8080` **and** KServe gRPC `:8081`;
  the Caddy sidecar is on **`:8090`** (a sidecar on 8081 crashes the model's gRPC).
- **It targets the HOME cluster**, not `home-remote` — the GPU lives on the home
  Talos cluster. The single sanctioned exception to ADR-0017 (`homeCluster: true`).
- **The model image ignores `VLLM_API_KEY`**, so the **Caddy sidecar** enforces the
  Bearer and is the only exposed port (`:8090`); the model's `:8080` is pod-local.
- **The gateway side is elsewhere.** This chart only stands up the model + proxy.
  It's federated into the Hetzner Envoy AI Gateway as an ordinary OpenAI backend
  (`vllm-local-8b-01` + the `qwen3-8b-local` model) in
  `charts/ai-models/values.yaml`.

## What it renders (in sync-wave order)

| Wave | Resource | Rendered by | Purpose |
|---|---|---|---|
| -2 | `ExternalSecret vllm-local-api-key` + `hf-token` | own templates | the API key (Bearer the sidecar enforces) + the HF download token |
| -1 | `PVC qwen3-8b-models` | own template | the weights volume (Longhorn, **RWX**) |
| 0 | `Job qwen3-8b-seed` (ArgoCD Sync hook) | **bjw** (`controllers.seed`, `type: job`) | downloads weights into the PVC **once**; ArgoCD waits for it |
| 1 | `StatefulSet qwen3-8b` (containers `model` + `proxy`) + `Service qwen3-8b:8090` + `Ingress` | **bjw** | the model + Caddy sidecar; the Service → the Ingress (className traefik, cert-manager annotation) |
| — | `ConfigMap qwen3-8b-caddy` | own template | the Caddyfile mounted into the proxy sidecar |

## Key knobs (`values.yaml`)

- `model.{name,hfRepo,storagePath}` — drives the own templates (PVC subPath etc.).
  ⚠️ the bjw seed Job hardcodes the repo/path (it can't read parent values from the
  subchart scope) — keep `modelServing.controllers.seed` in sync with these.
- `modelServing.controllers.main.containers.model.args` — vLLM flags include
  `--quantization=awq`, `--dtype=float16`, `--max-model-len=32768` (full native
  context fits with AWQ INT4). ⚠️ model probes use bjw `custom: true` so they hit
  `:8080` (not the Service port `:8090`).
- `modelServing.ingress.main` — the public Ingress: `host`, `className: traefik`,
  the `cert-manager.io/cluster-issuer` annotation, and `tls`. The host MUST match
  `charts/ai-models` `vllmLocal8b.hostname`.
- `apiKey.externalSecret.{key,property}` — reuses the `vllm_local_api_key` property
  from `ssegning-aws` (same key as the other self-hosted vLLM models).
- `edgeAuth.proxyResponseTimeout` — the Caddy sidecar's upstream timeout (600s).