# model-serving

Self-hosted LLM on the **home GPU** (RTX A2000, 12 GB): a single **`bjw-template`
`StatefulSet`** (always-on, `replicas: 1`) with **two containers in one pod** — the
**`kserve/huggingfaceserver` model** (**vLLM + in-pod LMCache**) and a **Caddy
auth-proxy sidecar** that reaches the model over `localhost`. Weights are fed from
a **pre-seeded PVC** (local mount, no per-start HuggingFace download). **NOT**
KServe/Knative — serverless is the wrong fit for a single owned, dedicated GPU
(ADR-0029); one STS via bjw-template (ADR-0030).

- **Why:** [ADR-0022](../../docs/adr/0022-self-hosted-gpu-model-federated-into-gateway.md) (federation) + [ADR-0028](../../docs/adr/0028-owned-hardware-model-pricing.md) (pricing) + [ADR-0029](../../docs/adr/0029-self-hosted-model-plain-deployment.md) (serving mode) + [ADR-0030](../../docs/adr/0030-merge-model-and-proxy-into-one-statefulset-bjw.md) (one STS via bjw)
- **How (VRAM math, flags, runbook, verification):** [`docs/self-hosted-model-serving.md`](../../docs/self-hosted-model-serving.md)

## Unusual things about this chart

- **Hybrid bjw chart** (like `charts/librechat-app`): the `bjw-template` subchart
  (values under `modelServing:`) renders the StatefulSet + Service; the chart's own
  `templates/` render the PVC, ExternalSecrets, seed Job, Caddyfile ConfigMap, and
  the Certificate + IngressRoute.
- **It targets the HOME cluster**, not `home-remote`. The GPU lives on the home
  Talos cluster; the Application sets `destination.server:
  https://kubernetes.default.svc` + `allowInCluster: true` — the single sanctioned
  exception to ADR-0017.
- **The model image ignores `VLLM_API_KEY`**, so the **Caddy sidecar** enforces the
  Bearer and is the only exposed port (`:8081`); the model's `:8080` is pod-local.
- **The gateway side is elsewhere.** This chart only stands up the model + proxy.
  It's federated into the Hetzner Envoy AI Gateway as an ordinary OpenAI backend
  (`vllm-local-01` + the `qwen3-4b-local` model) in `charts/ai-models/values.yaml`.

## What it renders (in sync-wave order)

| Wave | Resource | Rendered by | Purpose |
|---|---|---|---|
| -2 | `ExternalSecret vllm-local-api-key` + `hf-token` | own templates | the API key (Bearer the sidecar enforces) + the HF download token |
| -1 | `PVC qwen3-4b-models` | own template | the weights volume (Longhorn, **RWX**) |
| 0 | `Job qwen3-4b-seed` (ArgoCD Sync hook) | **bjw** (`controllers.seed`, `type: job`) | downloads weights into the PVC **once**; ArgoCD waits for it |
| 1 | `StatefulSet qwen3-4b` (containers `model` + `proxy`) + `Service qwen3-4b:8081` + `Ingress qwen3-4b` | **bjw** | the model + Caddy sidecar; the Service → the Ingress (className traefik, cert-manager annotation) |
| — | `ConfigMap qwen3-4b-caddy` | own template | the Caddyfile mounted into the proxy sidecar |

## Re-seeding the weights

The seed Job is an ArgoCD Sync hook (delete+recreate each sync) and `hf download`
is idempotent (skips files already on the PVC). To force a clean re-seed (e.g.
after wiping the PVC or switching quant): delete the PVC's contents (or the PVC,
which re-seeds) and re-sync. Day-to-day config changes reuse the PVC.

## Key knobs (`values.yaml`)

- `model.{name,hfRepo,storagePath}` — drives the own templates (PVC subPath etc.).
  ⚠️ the bjw seed Job hardcodes the repo/path (it can't read parent values from the
  subchart scope) — keep `modelServing.controllers.seed` in sync with these.
- `pvc.accessMode` — `ReadWriteMany` (RWX, Longhorn); lets the seed Job + model
  mount concurrently.
- `modelServing.controllers.main.containers.model.args` — vLLM/huggingfaceserver
  passthrough (tune for the card); includes `--model_dir=/mnt/models` + the agentic
  tool-calling flags. ⚠️ model probes use bjw `custom: true` so they hit `:8080`
  (not the Service port `:8081`).
- `modelServing.ingress.main` — the public Ingress: `host`, `className: traefik`,
  the `cert-manager.io/cluster-issuer` annotation, and `tls`. The host MUST match
  `charts/ai-models` `vllmLocal.hostname`.
- `apiKey.externalSecret.{key,property}` — the `ssegning-aws` coordinates of the
  API key (maintainer populates the property in AWS SM).
- `edgeAuth.proxyResponseTimeout` — the Caddy sidecar's upstream timeout (600s).
