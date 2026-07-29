# 09 · Model serving

How an OpenAI-compatible model id resolves to actual inference — provider
fan-out for the cloud models, plus the self-hosted models on the Hetzner GPU fleet.
Source ADRs: **0012** (orchestrator split), **0094/0095** (GPU-fleet serving +
cluster-local federation), **0022/0028/0029/0030/0032** (the legacy home-GPU
generation, still running on the other cluster), **0035** (per-person budgets).

## Fan-out: one model id → one route → one backend

```mermaid
flowchart TB
    REQ["client: model='adorsys-reviewer-pro'"]
    subgraph orch["ai-models orchestrator (ApplicationSet)"]
        AS["List generator: 1 child App per model"]
    end
    subgraph leaf["per-model leaf (charts/ai-model)"]
        ROUTE["AIGatewayRoute<br/>model id → backend"]
        BUDGET["BackendTrafficPolicy<br/>burst + monthly budget by plan"]
    end
    subgraph backends["AIServiceBackends (ai-models-backends)"]
        FW["Fireworks · fw-01/02"]
        DI["DeepInfra · deepinfra-01/02"]
        GA["Google AI · google-ai-studio-01/02"]
        LOC["&lt;model&gt;.inference.svc<br/>GPU fleet, cluster-local"]
        OLD["*--poc.ssegning.com<br/>legacy, other cluster"]
    end

    REQ --> AS --> ROUTE --> BUDGET --> backends

```

- **Adding a model is a list edit** in `charts/ai-models/values.yaml` → the
  ApplicationSet generates a new child Application (route + budget). No new chart.
- Models are **branded aliases** over provider backends — e.g. `adorsys-reviewer`
  → MiniMax M2.7, `adorsys-reviewer-pro` / `adorsys-coder-pro` → GLM-5.2 (ADR-0075).
  ~30 models are live across Fireworks / DeepInfra / Google AI + the 2 local ones.
- The catalog clients see is `ai-models-info` — an OpenRouter-shape
  `/v1/models/info` static endpoint (ADR-0015).

## Budget & burst, per model

Every leaf's `BackendTrafficPolicy` enforces the plan tiers from
`rateLimitBudgeting.plans`, keyed on `x-account-id` + `x-billing-plan`:

```mermaid
flowchart LR
    subgraph tiers["plan → limits (per person, ADR-0035)"]
        FREE["free · $50/mo · 200 rpm · 1M tpm"]
        PRO["pro · $200/mo · 400 rpm · 2M tpm"]
        SVC["service · uncapped · 600 rpm · 2M tpm"]
        INT["internal · uncapped · 600 rpm · 2M tpm"]
    end
```

**Per-model overrides:** a model can override the plan defaults with its own
`rateLimitBudgeting:` block in `charts/ai-models/values.yaml` — e.g. the
`adorsys-*` brand models use a unified lower budget rather than the table above.
The plan tiers are the default; the per-model block wins where present.

Cost is metered natively (`llmRequestCosts` token extraction) — no Python/Lua hop.

## Self-hosted models — the GPU fleet (ADR-0094/0095)

Two Hetzner Robot GPU nodes (RTX 4000 SFF Ada, 20 GiB each) joined **`home-remote`**
— the same cluster as the gateway. So a self-hosted model is now an ordinary
workload reached over the pod network: **no Ingress, no DNS record, no TLS
certificate, no static API key, no auth-proxy sidecar**. A `CiliumNetworkPolicy` is
the access control.

```mermaid
flowchart TB
    subgraph orch2["charts/inference (ApplicationSet)"]
        CAT["catalog: 1 entry per model<br/>engine profiles expand it"]
    end
    subgraph inf["ns: inference (home-remote, GPU nodes)"]
        subgraph ss["StatefulSet (charts/inference-server)"]
            ENG["ONE container: llama-server | vLLM<br/>/v1 · /health · /metrics<br/>nvidia.com/gpu: 1"]
        end
        PVC["RWX Longhorn PVC (pre-seeded weights)"]
        SEED["seed Job (Sync hook)"]
        CNP["CiliumNetworkPolicy<br/>ingress: gateway + observability<br/>+ host/remote-node/health (kubelet probes)"]
        SEED --> PVC --> ENG
        CNP -.guards.-> ENG
    end
    GW["Envoy AI Gateway<br/>(envoy-gateway-system)"]
    CAT --> ss
    GW -->|"ClusterIP :8080 · plain HTTP"| ENG
```

**Two GPUs ⇒ two concurrent models.** Placement is an `nvidia.com/gpu: 1` request,
so a third enabled model queues as `Pending` rather than requiring a human to
disable another. Adding a model is a ~15-line catalog entry — no new chart.

### Three engines, one container each

| | `llamacpp` | `vllm` | `localai` |
|---|---|---|---|
| Serves | text | text | **images** (`/v1/images/generations`) |
| Image | `ghcr.io/ggml-org/llama.cpp:server-cuda` | `lmcache/vllm-openai` | `quay.io/go-skynet/local-ai:v4.7.1-gpu-nvidia-cuda-12` |
| Weights | GGUF | safetensors (AWQ/GPTQ/FP8/BF16) | GGUF, fetched by the engine itself |
| Seed Job | yes | yes | **no** — LocalAI downloads model *and* backend |
| Containers | **1** | **1** | **1** |
| Optional key | native `--api-key-file` | native `VLLM_API_KEY` | native `API_KEY` |
| `/metrics` | `llamacpp:*` | `vllm:*` | yes (behind the admin key) |
| Extras | — | opt-in LMCache + `/dev/shm` | writable weights volume |

The weight format selects the engine (`inference-ops` ADR-0002 for text, ADR-0003
for images) — GGUF on vLLM is ~8× slower, and neither text engine can do
diffusion at all. **No engine has a Caddy sidecar**: that was only ever required
by `kserve/huggingfaceserver`, which ignores `VLLM_API_KEY` (ADR-0022), and that
wrapper is not an engine profile here.

**All three engines are now off the shelf.** There was briefly a fourth, `zimage`,
backed by a first-party Rust/Candle server we maintained ourselves (ADR-0100).
ADR-0102 replaced it with `localai` on the grounds that an OpenAI-compatible
multi-backend image server is a commodity we should never have been building; the
Rust source was deleted, and the chart that deployed it was deleted in turn by
ADR-0106 after a stale-branch merge briefly resurrected it referencing an image
that no longer exists.

`localai` differs from the text engines in two structural ways, both expressed as
profile data rather than engine-name branches: it has **no seed Job** (it fetches
its own weights and its own inference backend at start-up), and its weights volume
is therefore **writable**. The pinned-bytes guarantee the other engines get from a
pinned HF revision comes instead from a `sha256` per file in `download_files`, and
the backend gallery, backend image tag and cosign policy are all pinned alongside
the server (ADR-0105) — pinning the server alone does **not** pin what executes
the model.

### Legacy generation

Seven `charts/model-serving-*` charts target the **other** cluster
(`admin@homeos`) over a public edge with `homeCluster: true`. **All are
`enabled: false` since 2026-07-27** (ADR-0100): `zimage-turbo`, the last live
one, moved to the fleet — and its chart was **deleted outright** in ADR-0106,
because an image that does not exist is not a rollback surface. The rest are
retained as a rollback surface until that cluster is decommissioned; not a
template for anything new.

Pricing for owned hardware is **cost-recovery** (€/hour TCO → weighted per-token,
ADR-0028), not flat-zero.

The GitOps *how* is [`../patterns/self-hosted-model-serving.md`](../patterns/self-hosted-model-serving.md).
The inference knowledge — VRAM budgeting, quantization, engine choice, benchmarks,
runbooks — lives in the team's **`inference-ops`** repository. Legacy per-model
papers: [`../models/`](../models/qwen3.5-4b-q4.md).

→ Related: [03 Gateway request path](03-gateway-components.md) · [05 Auth & tiers](05-auth-identity.md)
