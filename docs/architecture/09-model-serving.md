# 09 · Model serving

How an OpenAI-compatible model id resolves to actual inference — provider
fan-out for the cloud models, plus the one self-hosted model on the home GPU.
Source ADRs: **0012** (orchestrator split), **0022/0028/0029/0030/0032**
(self-hosted serving), **0035** (per-person budgets).

## Fan-out: one model id → one route → one backend

```mermaid
flowchart TB
    REQ["client: model='adorsys-reviewer-pro'"]:::ext
    subgraph orch["ai-models orchestrator (ApplicationSet)"]
        AS["List generator: 1 child App per model"]:::ctrl
    end
    subgraph leaf["per-model leaf (charts/ai-model)"]
        ROUTE["AIGatewayRoute<br/>model id → backend"]:::own
        BUDGET["BackendTrafficPolicy<br/>burst + monthly budget by plan"]:::own
    end
    subgraph backends["AIServiceBackends (ai-models-backends)"]
        FW["Fireworks · fw-01/02"]:::ext
        DI["DeepInfra · deepinfra-01/02"]:::ext
        GA["Google AI · google-ai-studio-01/02"]:::ext
        VL["vllm-local-01 → Qwen3-4B (standby)"]:::gpu
        LL["llama-local-01 → Qwen3.5-4B 🟢"]:::gpu
    end

    REQ --> AS --> ROUTE --> BUDGET --> backends

    classDef own fill:#eaf3ea,stroke:#4a8a4a;
    classDef ctrl fill:#e8eef7,stroke:#4a6fa5;
    classDef ext fill:#eee,stroke:#888,stroke-dasharray:4 3;
    classDef gpu fill:#f7e8f0,stroke:#a54a81;
```

- **Adding a model is a list edit** in `charts/ai-models/values.yaml` → the
  ApplicationSet generates a new child Application (route + budget). No new chart.
- Models are **branded aliases** over provider backends — e.g. `adorsys-reviewer`
  → MiniMax M2.7, `adorsys-reviewer-pro` → GLM-5, `adorsys-coder-pro` → GLM-5.1.
  ~30 models are live across Fireworks / DeepInfra / Google AI + the 2 local ones.
- The catalog clients see is `ai-models-info` — an OpenRouter-shape
  `/v1/models/info` static endpoint (ADR-0015).

## Budget & burst, per model

Every leaf's `BackendTrafficPolicy` enforces the plan tiers from
`rateLimitBudgeting.plans`, keyed on `x-account-id` + `x-billing-plan`:

```mermaid
flowchart LR
    subgraph tiers["plan → limits (per person, ADR-0035)"]
        FREE["free · $50/mo · 200 rpm · 1M tpm"]:::t
        PRO["pro · $200/mo · 400 rpm · 2M tpm"]:::t
        SVC["service · uncapped · 600 rpm · 2M tpm"]:::t
        INT["internal · uncapped · 600 rpm · 2M tpm"]:::t
    end
    classDef t fill:#eaf3ea,stroke:#4a8a4a;
```

Cost is metered natively (`llmRequestCosts` token extraction) — no Python/Lua hop.

## The self-hosted model (home GPU)

The **one** sanctioned `homeCluster: true` workload (ADR-0022): it must run on the
cluster ArgoCD itself runs on because it needs the home GPU (A2000 12 GB).

```mermaid
flowchart TB
    subgraph poc["ns: converse-poc (home GPU cluster)"]
        subgraph ss["StatefulSet (bjw-template) — LIVE"]
            LS["llama-server (llama.cpp)<br/>Qwen3.5-4B UD-Q4_K_XL GGUF<br/>native --api-key · /v1 · /health<br/>128k ctx · 4 slots · ~52 tok/s"]:::gpu
        end
        PVC["RWX PVC (pre-seeded GGUF)"]:::own
        SEED["seed Job"]:::own
        ING["Ingress"]:::own
        SEED --> PVC --> LS
        LS --> ING
    end

    GW["Envoy AI Gateway<br/>(home-remote)"]:::own
    ING -->|"federated as qwen3-5-4b-local (/v1)"| GW

    classDef own fill:#eaf3ea,stroke:#4a8a4a;
    classDef gpu fill:#f7e8f0,stroke:#a54a81;
```

### Two engines, two shapes

```mermaid
flowchart LR
    subgraph llama["llama.cpp (LIVE · qwen3-5)"]
        L1["ONE container<br/>llama-server"]:::gpu
        L2["native --api-key<br/>(no proxy needed)"]:::gpu
        L1 --- L2
    end
    subgraph vllm["vLLM (standby · qwen3-4b)"]
        V1["huggingfaceserver (vLLM + LMCache)"]:::gpu
        V2["+ Caddy auth-proxy sidecar<br/>(huggingfaceserver ignores VLLM_API_KEY)"]:::gpu
        V1 --- V2
    end
    classDef gpu fill:#f7e8f0,stroke:#a54a81;
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
[`../self-hosted-model-serving.md`](../self-hosted-model-serving.md) and
[`../models/`](../models/qwen3.5-4b-q4.md).

→ Related: [03 Gateway request path](03-gateway-components.md) · [05 Auth & tiers](05-auth-identity.md)
