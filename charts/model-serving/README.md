# model-serving

Self-hosted LLM on the **home GPU** (RTX A2000, 12 GB): a **plain `Deployment`**
(always-on, `strategy: Recreate`) running the **`kserve/huggingfaceserver` image**
(**vLLM + in-pod LMCache**), with weights fed from a **pre-seeded PVC** so pod
starts are a local mount — no per-start HuggingFace download. **NOT** KServe/Knative
— serverless is the wrong fit for a single owned, dedicated GPU (see ADR-0029).

- **Why:** [ADR-0022](../../docs/adr/0022-self-hosted-gpu-model-federated-into-gateway.md) (federation) + [ADR-0028](../../docs/adr/0028-owned-hardware-model-pricing.md) (pricing) + [ADR-0029](../../docs/adr/0029-self-hosted-model-plain-deployment.md) (serving mode)
- **How (VRAM math, flags, runbook, verification):** [`docs/self-hosted-model-serving.md`](../../docs/self-hosted-model-serving.md)

## Unusual things about this chart

- **It targets the HOME cluster**, not `home-remote`. The GPU lives on the home
  Talos cluster; the Application that deploys this sets
  `destination.server: https://kubernetes.default.svc` + `allowInCluster: true`
  — the single sanctioned exception to ADR-0017.
- **The model image ignores `VLLM_API_KEY`**, so a tiny **Caddy auth-proxy**
  (plain Deployment) enforces the Bearer and is the only public entrypoint; the
  model is a plain ClusterIP Service (cluster-local by construction).
- **The gateway side is elsewhere.** This chart only stands up the model + proxy.
  It's federated into the Hetzner Envoy AI Gateway as an ordinary OpenAI backend
  (`vllm-local-01` + the `qwen3-4b-local` model) in `charts/ai-models/values.yaml`.

## What it renders (in sync-wave order)

| Wave | Resource | Purpose |
|---|---|---|
| -2 | `ExternalSecret vllm-local-api-key` | the vLLM API key (the Bearer the Caddy proxy enforces) |
| -1 | `PVC qwen3-4b-models` | the weights volume (Longhorn, RWO) |
| 0 | `Job seed-qwen3-4b` | downloads weights into the PVC **once**; ArgoCD waits for it |
| 1 | `Deployment + Service qwen3-4b` | vLLM + LMCache, weights mounted from the PVC (`--model_dir`); ClusterIP (cluster-local) |
| 1 | Caddy proxy `Deployment`/`Service` + `IngressRoute` + `Certificate` | the public, authenticated entrypoint (`edge-auth.yaml`) |

## Re-seeding the weights

The seed Job is idempotent and has **no TTL** (a TTL'd Job would vanish and
ArgoCD would re-download). To re-seed (e.g. after wiping the PVC or switching
quant): `kubectl -n <ns> delete job seed-qwen3-4b` and re-sync — ArgoCD recreates
it. Day-to-day config changes reuse the PVC and do **not** re-download.

## Key knobs (`values.yaml`)

- `model.{name,hfRepo,storagePath}` — which model + where it lives in the PVC.
- `server.args` — vLLM/huggingfaceserver passthrough (tune for the card); includes
  `--model_dir=/mnt/models` (the PVC mount) + the agentic tool-calling flags.
- `server.{replicas,resources}` — always-on (1) on the dedicated GPU; `Recreate`.
- `lmcache.maxLocalCpuSizeGb` — host RAM for offloaded KV (keep below the pod's
  memory request).
- `apiKey.externalSecret.{key,property}` — the `ssegning-aws` coordinates of the
  API key (maintainer populates the property in AWS SM).
