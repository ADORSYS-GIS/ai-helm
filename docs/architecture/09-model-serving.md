# 09 · Model serving

How an OpenAI-compatible model id resolves to actual inference — provider
fan-out for the cloud models, plus the one self-hosted model on the home GPU.
Source ADRs: **0012** (orchestrator split), **0022/0028/0029/0030/0032**
(self-hosted serving), **0035** (per-person budgets).

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
        VL["vllm-local-01 → Qwen3-4B (standby)"]
        LL["llama-local-01 → Qwen3.5-4B 🟢"]
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

## The self-hosted model (home GPU)

The **one** sanctioned `homeCluster: true` workload (ADR-0022): it must run on the
cluster ArgoCD itself runs on because it needs the home GPU (A2000 12 GB).

```mermaid
flowchart TB
    subgraph poc["ns: converse-poc (home GPU cluster)"]
        subgraph ss["StatefulSet (bjw-template) — LIVE"]
            LS["llama-server (llama.cpp)<br/>Qwen3.5-4B UD-Q4_K_XL GGUF<br/>native --api-key · /v1 · /health<br/>128k ctx · 4 slots · ~52 tok/s"]
        end
        PVC["RWX PVC (pre-seeded GGUF)"]
        SEED["seed Job"]
        ING["Ingress"]
        SEED --> PVC --> LS
        LS --> ING
    end

    GW["Envoy AI Gateway<br/>(home-remote)"]
    ING -->|"federated as qwen3-5-4b-local (/v1)"| GW

```

### Two engines, two shapes

```mermaid
flowchart LR
    subgraph llama["llama.cpp (LIVE · qwen3-5)"]
        L1["ONE container<br/>llama-server"]
        L2["native --api-key<br/>(no proxy needed)"]
        L1 --- L2
    end
    subgraph vllm["vLLM (standby · qwen3-4b)"]
        V1["huggingfaceserver (vLLM + LMCache)"]
        V2["+ Caddy auth-proxy sidecar<br/>(huggingfaceserver ignores VLLM_API_KEY)"]
        V1 --- V2
    end
```

| | llama.cpp (`model-serving-qwen3-5`) 🟢 | vLLM (`model-serving-qwen3-4b`) |
|---|---|---|
| Model | Qwen3.5-4B Q4 (GGUF) | Qwen3-4B (BF16) |
| Containers | 1 (native `--api-key`) | 2 (vLLM + Caddy auth-proxy) |
| Status | **LIVE** since 2026-06-08 | standby / rollback |
| ADRs | 0030, 0032 | 0029, 0030 |

Pricing for owned hardware is **cost-recovery** (€/hour TCO → weighted per-token,
ADR-0028), not flat-zero. The model-agnostic "deploy the next one" checklist and
per-model capacity papers live in
[`../self-hosted-model-serving.md`](../patterns/self-hosted-model-serving.md) and
[`../models/`](../models/qwen3.5-4b-q4.md).

→ Related: [03 Gateway request path](03-gateway-components.md) · [05 Auth & tiers](05-auth-identity.md)
