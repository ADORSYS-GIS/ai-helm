# model-serving-zimage-turbo

Self-hosted image generation on the **home GPU** (RTX A2000, 12 GB): **Z-Image-Turbo**
(Tongyi-MAI, 6.15B params) served via a **custom Rust/Candle server** (Actix-web)
with FP8 quantization. A single **`bjw-template Deployment`** (always-on,
`replicas: 1`) with **one container** — the model server. No sidecar, no
authentication (intended for internal cluster use behind the Envoy AI Gateway).
Weights are fed from a **pre-seeded PVC** (local mount, no per-start HuggingFace
download). FP8 fits the full model (~8 GB weights + VAE + activations) in 12 GB
VRAM with headroom for 1024×1024 generation.

- **Why:** [ADR-0022](../../docs/adr/0022-self-hosted-gpu-model-federated-into-gateway.md) (federation) + [ADR-0028](../../docs/adr/0028-owned-hardware-model-pricing.md) (pricing) + [ADR-0029](../../docs/adr/0029-self-hosted-model-plain-deployment.md) (serving mode)
- **How (VRAM math, tuning, runbook):** [`docs/patterns/self-hosted-model-serving.md`](../../docs/patterns/self-hosted-model-serving.md)

## Unusual things about this chart

- **Hybrid bjw chart** (like `charts/model-serving-qwen3-4b`): the `bjw-template`
  subchart (values under `modelServing:`) renders the **whole workload** — the
  Deployment, the seed `Job` (a bjw `job` controller), the Service, and the
  Ingress. The chart's own `templates/` render only the PVC and the HF-token
  ExternalSecret.
- **No sidecar, no auth proxy** — the server is directly accessible on `:8000`.
  No `apiKey` or `edgeAuth` values section. Authentication is delegated to the
  Envoy AI Gateway (the `zimage-local-01` backend in `charts/ai-models/`).
- **Uses a `Deployment`**, not a `StatefulSet` — image generation is stateless
  (the weights are mounted read-only from the PVC; no stable instance identity
  or ordinal storage needed).
- **Custom Rust server** (`docker/`) — not vLLM. Written in Rust with
  [Candle](https://github.com/huggingface/candle) for GPU inference. Serves the
  OpenAI `/v1/images/generations` endpoint (compatible with the Envoy AI Gateway).
- **It targets the HOME cluster**, not `home-remote`. The GPU lives on the home
  Talos cluster; the Application sets `destination.server:
  https://kubernetes.default.svc` + `allowInCluster: true` — the single sanctioned
  exception to ADR-0017.
- **The gateway side is elsewhere.** This chart only stands up the model server.
  It's federated into the Hetzner Envoy AI Gateway as an ordinary OpenAI image
  backend (`zimage-local-01` + the `z-image-turbo-local` model) in
  `charts/ai-models/values.yaml`.

## What it renders (in sync-wave order)

| Wave | Resource | Rendered by | Purpose |
|---|---|---|---|
| -2 | `ExternalSecret hf-token` | own template | the HuggingFace download token for the seed Job |
| -1 | `PVC zimage-models` | own template | the weights volume (Longhorn, **RWX**, 20 Gi) |
| 0 | `Job z-image-turbo-seed` (ArgoCD Sync hook) | **bjw** (`controllers.seed`, `type: job`) | downloads weights into the PVC **once**; ArgoCD waits for it |
| 1 | `Deployment z-image-turbo` + `Service :8000` + `Ingress` | **bjw** | the Rust/Candle model server; no sidecar |

## Re-seeding the weights

The seed Job is an ArgoCD Sync hook (delete+recreate each sync) and `hf download`
is idempotent — it skips files already on the PVC. To force a clean re-seed
(e.g. after corrupting the weights): delete the PVC's contents (or the PVC itself)
and re-sync. Day-to-day config changes reuse the PVC.

## Key knobs (`values.yaml`)

- `model.{name,hfRepo,storagePath}` — drives the own templates (PVC name, seed
  Job paths, etc.). ⚠️ the bjw seed Job hardcodes the repo/path — keep
  `modelServing.controllers.seed` in sync.
- `pvc.size` — the weights volume: Z-Image-Turbo is ~12 GB in BF16, 20 Gi is the
  default (room for downloads + extraction).
- `modelServing.controllers.main.containers.model.resources` — tune for the card.
  RTX A2000 (12 GB): request 4 Gi memory, limit 16 Gi (CUDA memory-maps the
  weights; the limit is a Kubernetes ceiling, not a direct VRAM control).
- `modelServing.controllers.seed.job.activeDeadlineSeconds` — 7200 (2 hours)
  gives headroom for the full model download. The seed container requests 2 Gi
  memory for `hf download`.
- `modelServing.service.main.ports` — the single HTTP port `:8000` (no gRPC,
  no sidecar).
- `modelServing.ingress.main` — the public Ingress: `host`, `className: traefik`,
  the `cert-manager.io/cluster-issuer` annotation, and `tls`. The host MUST match
  `charts/ai-models` `zimage-local-01.hostname`.
