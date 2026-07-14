# model-serving-deepseek-r1-1-5b

Self-hosted LLM on the **home GPU** (RTX A2000, 12 GB):
**DeepSeek-R1-Distill-Qwen-1.5B** (BF16, ~1.5B params) — a reasoning model
distilled from DeepSeek-R1 onto a Qwen2.5-Math-1.5B base — served via **vLLM**
(`kserve/huggingfaceserver`) with a **Caddy auth-proxy sidecar**. A single
**`bjw-template StatefulSet`** (always-on, `replicas: 1`) with **two containers
in one pod** — the model + the proxy. Weights are fed from a **pre-seeded PVC**
(local mount, no per-start HuggingFace download). BF16 at 1.5B fits 32K context
trivially in 12GB VRAM (~2 GB weights + KV headroom).

- **Why:** [ADR-0022](../../docs/adr/0022-self-hosted-gpu-model-federated-into-gateway.md) (federation) + [ADR-0028](../../docs/adr/0028-owned-hardware-model-pricing.md) (pricing) + [ADR-0029](../../docs/adr/0029-self-hosted-model-plain-deployment.md) (serving mode) + [ADR-0030](../../docs/adr/0030-merge-model-and-proxy-into-one-statefulset-bjw.md) (one STS via bjw)
- **How:** [`docs/patterns/self-hosted-model-serving.md`](../../docs/patterns/self-hosted-model-serving.md)
- **Model card:** [deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B](https://huggingface.co/deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B) (MIT)

## Unusual things about this chart

- **Hybrid bjw chart** (like `charts/model-serving-qwen25-3b-awq`): the
  `bjw-template` subchart (values under `modelServing:`) renders the **whole
  workload** — the StatefulSet, the seed `Job` (a bjw `job` controller), the
  Service, and the Ingress. The chart's own `templates/` render only the PVC,
  the ExternalSecrets, and the Caddyfile ConfigMap.
- **⚠️ Port layout:** the model server binds HTTP `:8080` **and** KServe gRPC
  `:8081`; the Caddy sidecar is on **`:8090`** (a sidecar on 8081 crashes the
  model's gRPC).
- **It targets the HOME cluster**, not `home-remote` — the GPU lives on the home
  Talos cluster. The single sanctioned exception to ADR-0017 (`homeCluster: true`).
- **The model image ignores `VLLM_API_KEY`**, so the **Caddy sidecar** enforces
  the Bearer and is the only exposed port (`:8090`); the model's `:8080` is
  pod-local.
- **No tool calling:** the base is Qwen2.5-Math-1.5B distilled for **reasoning**,
  not instruction-tuned for tool/function calling — `--enable-auto-tool-choice`
  and `--tool-call-parser` are deliberately omitted.
- **Reasoning usage (client-side, NOT chart):** per the R1 model card —
  temperature 0.5–0.7 (0.6 recommended), **no system prompt**, and enforce output
  starting with `\n` to engage the thinking trace. Long chain-of-thought →
  `maxOutputTokens` 32768.
- **The gateway side is elsewhere.** This chart only stands up the model + proxy.
  It's federated into the Hetzner Envoy AI Gateway as an ordinary OpenAI backend
  (`vllm-deepseek-01` + the `deepseek-r1-1-5b-local` model) in
  `charts/ai-models/values.yaml`.

## What it renders (in sync-wave order)

| Wave | Resource | Rendered by | Purpose |
|---|---|---|---|
| -2 | `ExternalSecret vllm-local-api-key` + `hf-token` | own templates | the API key (Bearer the sidecar enforces) + the HF download token |
| -1 | `PVC deepseek-r1-1-5b-models` | own template | the weights volume (Longhorn, **RWX**) |
| 0 | `Job deepseek-r1-1-5b-seed` (ArgoCD Sync hook) | **bjw** (`controllers.seed`, `type: job`) | downloads weights into the PVC **once**; ArgoCD waits for it |
| 1 | `StatefulSet deepseek-r1-1-5b` (containers `model` + `proxy`) + `Service deepseek-r1-1-5b:8090` + `Ingress` | **bjw** | the model + Caddy sidecar; the Service → the Ingress (className traefik, cert-manager annotation) |
| — | `ConfigMap deepseek-r1-1-5b-caddy` | own template | the Caddyfile mounted into the proxy sidecar |

## Key knobs (`values.yaml`)

- `model.{name,hfRepo,storagePath}` — drives the own templates (PVC subPath etc.).
  ⚠️ the bjw seed Job hardcodes the repo/path (it can't read parent values from the
  subchart scope) — keep `modelServing.controllers.seed` in sync with these.
- `modelServing.controllers.main.containers.model.args` — vLLM flags: BF16
  (`--dtype=float16`), `--max-model-len=32768` (full native Qwen2.5-1.5B context),
  `--max-num-seqs=4`, `--enforce-eager`, LMCache KV connector. ⚠️ model probes
  use bjw `custom: true` so they hit `:8080` (not the Service port `:8090`).
- `modelServing.ingress.main` — the public Ingress: `host`, `className: traefik`,
  the `cert-manager.io/cluster-issuer` annotation, and `tls`. The host MUST match
  `charts/ai-models` `vllmDeepseek.hostname`.
- `apiKey.externalSecret.{key,property}` — reuses the `vllm_local_api_key` property
  from `ssegning-aws` (same key as the other self-hosted vLLM models).
- `edgeAuth.proxyResponseTimeout` — the Caddy sidecar's upstream timeout (600s).