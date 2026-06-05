# model-serving

Self-hosted LLM on the **home GPU** (RTX A2000, 12 GB): a KServe
`InferenceService` (Knative Serverless) running **vLLM + in-pod LMCache**, with
weights fed from a **pre-seeded PVC** so pod starts are a local mount — no
per-start HuggingFace download.

- **Why:** [ADR-0022](../../docs/adr/0022-self-hosted-gpu-model-federated-into-gateway.md)
- **How (VRAM math, flags, runbook, verification):** [`docs/2026-self-hosted-gpu-inference.md`](../../docs/2026-self-hosted-gpu-inference.md)

## Unusual things about this chart

- **It targets the HOME cluster**, not `home-remote`. The GPU + KServe + Knative
  live on the home Talos cluster; the Application that deploys this sets
  `destination.server: https://kubernetes.default.svc` + `allowInCluster: true`
  — the single sanctioned exception to ADR-0017.
- **The gateway side is elsewhere.** This chart only stands up the model. It's
  federated into the Hetzner Envoy AI Gateway as an ordinary OpenAI backend
  (`vllm-local-01` + the `qwen3-4b-local` model) in `charts/ai-models/values.yaml`.

## What it renders (in sync-wave order)

| Wave | Resource | Purpose |
|---|---|---|
| -2 | `ExternalSecret vllm-local-api-key` | the vLLM API key (sole gate on the public FQDN) |
| -1 | `PVC qwen3-4b-models` | the weights volume (Longhorn, RWO) |
| 0 | `Job seed-qwen3-4b` | downloads weights into the PVC **once**; ArgoCD waits for it |
| 1 | `InferenceService qwen3-4b` | vLLM + LMCache, `storageUri: pvc://…` (never downloads) |

## Re-seeding the weights

The seed Job is idempotent and has **no TTL** (a TTL'd Job would vanish and
ArgoCD would re-download). To re-seed (e.g. after wiping the PVC or switching
quant): `kubectl -n <ns> delete job seed-qwen3-4b` and re-sync — ArgoCD recreates
it. Day-to-day config changes reuse the PVC and do **not** re-download.

## Key knobs (`values.yaml`)

- `model.{name,hfRepo,storagePath}` — which model + where it lives in the PVC.
- `inferenceService.args` — vLLM/huggingfaceserver passthrough (tune for the card).
- `lmcache.maxLocalCpuSizeGb` — host RAM for offloaded KV (keep below the pod's
  memory request).
- `apiKey.externalSecret.{key,property}` — the `ssegning-aws` coordinates of the
  API key (maintainer populates the property in AWS SM).
