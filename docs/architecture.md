# Architecture overview

The single-page map of how this repo's charts compose into a running system.
Read after the top-level [README](../README.md). For depth, follow the
**[layered architecture suite](architecture/README.md)** (C4 context → container →
component, plus one page per subsystem) or the formal
**[arc42 description](arc42.md)**. Every *why* lives in the
[ADR index](adr/README.md).

> Reflects `release-2026.06.14-v03`. Coder was removed (ADR-0027) and is not shown.

## Where to go for what

```mermaid
flowchart LR
    HERE["📍 architecture.md<br/><i>you are here — the map</i>"]:::own
    SUITE["architecture/ suite<br/><i>11 layered, mermaid pages</i>"]:::own
    ARC["arc42.md<br/><i>formal 12-section</i>"]:::own
    ADR["adr/<br/><i>the why</i>"]:::own
    HERE --> SUITE & ARC & ADR
    classDef own fill:#eaf3ea,stroke:#4a8a4a;
```

| You want… | Go to |
|---|---|
| Who uses it & what it depends on | [suite · 01 Context](architecture/01-context.md) |
| What's deployed where | [suite · 02 Containers](architecture/02-containers.md) |
| How a request flows | [suite · 03 Gateway components](architecture/03-gateway-components.md) |
| How charts become workloads; releases | [suite · 04 GitOps](architecture/04-gitops-deployment.md) |
| Auth, identity, the `x-oidc-*` contract | [suite · 05 Auth](architecture/05-auth-identity.md) |
| Networking, Cilium, TLS | [suite · 06 Networking & TLS](architecture/06-networking-tls.md) |
| Data, secrets, object storage | [suite · 07 Data & secrets](architecture/07-data-secrets.md) |
| The observability pipeline | [suite · 08 Observability](architecture/08-observability.md) |
| Model fan-out + the GPU model | [suite · 09 Model serving](architecture/09-model-serving.md) |
| MCP routing + proxies | [suite · 10 MCP](architecture/10-mcp.md) |

## Cluster topology (the one-glance view)

```mermaid
flowchart TB
    NET["🌐 Internet"]:::ext
    LB["Hetzner LB → Traefik / Envoy data-plane"]:::ext

    subgraph gw["Gateway (converse-gateway + envoy-*-system + authorino-system)"]
        CG["Envoy AI Gateway (core-gateway)<br/>ai.camer.digital → LibreChat<br/>api.ai.camer.digital → /v1 (Authorino)<br/>api.ai.camer.digital/mcp/* → MCP (native JWT)"]:::own
    end

    subgraph app["Application plane"]
        LC["LibreChat<br/>(converse-chat)"]:::ctrl
        MODELS["AI models<br/>(converse)"]:::ctrl
        MCP["MCP servers<br/>(converse-mcp)"]:::ctrl
        REPO["lightbridge-repo-auth<br/>(converse)"]:::own
    end

    subgraph infra["Platform plane"]
        GPU["Self-hosted model 🟢<br/>(converse-poc, home GPU)"]:::gpu
        OBS["Observability LGTM<br/>(observability)"]:::ctrl
    end

    KC["Keycloak"]:::ext
    PROV["Model providers"]:::ext

    NET --> LB --> CG
    CG --> LC & MODELS & MCP
    CG -.-> REPO
    MODELS --> PROV & GPU
    CG -.OIDC.-> KC
    LC --> OBS
    MODELS --> OBS

    classDef own fill:#eaf3ea,stroke:#4a8a4a;
    classDef ctrl fill:#e8eef7,stroke:#4a6fa5;
    classDef ext fill:#eee,stroke:#888,stroke-dasharray:4 3;
    classDef gpu fill:#f7e8f0,stroke:#a54a81;
```

## GitOps in one diagram

Two clusters: ArgoCD runs on `admin@homeos`; workloads run on Hetzner
`home-remote`. The root `ai-apps-v2` Application is **applied manually** and pins
an **immutable release tag** (never `main` — ADR-0031). Detail:
[suite · 04 GitOps](architecture/04-gitops-deployment.md).

```mermaid
flowchart LR
    ROOT["ai-apps-v2 (root, in-cluster/argocd)<br/>→ charts/apps"]:::ctrl
    APPS["~21 Applications/ApplicationSets<br/>(control objects in argocd ns)"]:::ctrl
    WL["workloads → home-remote"]:::own
    ROOT --> APPS ==> WL
    classDef own fill:#eaf3ea,stroke:#4a8a4a;
    classDef ctrl fill:#e8eef7,stroke:#4a6fa5;
```

## Auth in one diagram

Dual-plane, AuthConfig-per-Host (ADR-0021). A valid Keycloak JWT is the
authorization boundary; CI uses GitHub OIDC via `lightbridge-repo-auth`. OPA was
removed (2026-06-04). Detail: [suite · 05 Auth](architecture/05-auth-identity.md).

```mermaid
flowchart LR
    H["human / dev"]:::ext -->|JWT / API key| EXT["EXTERNAL plane<br/>api.ai.camer.digital"]:::own
    CI["CI runner"]:::ext -->|GHA OIDC| EXT
    SVC["in-cluster svc"]:::ext -->|SA token / apiKey| INT["INTERNAL plane<br/>core-gateway-internal.svc"]:::own
    EXT --> A["Authorino<br/>x-oidc-* + x-account-id/x-billing-plan"]:::own
    INT --> A
    A --> RL["per-model burst + monthly budget"]:::own
    classDef own fill:#eaf3ea,stroke:#4a8a4a;
    classDef ext fill:#eee,stroke:#888,stroke-dasharray:4 3;
```

> ⚠️ `/mcp/*` is the one carve-out from Authorino — Envoy-native JWT verification
> + RFC 9728 discovery (ADR-0038), with external MCPs fronted by in-cluster
> normalizing proxies (ADR-0040/0041). See [suite · 10 MCP](architecture/10-mcp.md).

## Observability in one diagram

LGTM + Alloy, per-user attribution from JWT → Loki labels. Detail:
[suite · 08 Observability](architecture/08-observability.md).

```mermaid
flowchart BT
    SRC["workloads · ksm · node-exporter ·<br/>pod logs · Envoy access log · traces"]:::own
    ALLOY["Alloy (collect)"]:::own
    STORE["Mimir / Loki / Tempo → S3"]:::own
    GRAF["Grafana (+ operator dashboards)"]:::own
    SRC --> ALLOY --> STORE --> GRAF
    classDef own fill:#eaf3ea,stroke:#4a8a4a;
```

## What is *not* in this repo

Shared cluster infrastructure is owned externally — this repo only *consumes* it
by name (no Application here): **Traefik**, **CloudNativePG** + Barman,
**cert-manager** + ClusterIssuers, **redis-ha**, the **External Secrets
Operator** + the `ssegning-aws` store, and the **OpenTelemetry Operator**. There
is also **no `ai-gitops` repo** — per-env config lives in `environments/` and the
root Application is applied manually with its tag pinned in `home-os`
`charts/cd`. Detail: [suite · 07 Data & secrets](architecture/07-data-secrets.md).

## Glossary

- **AI Gateway** — Envoy AI Gateway (`aieg`); the OpenAI-compatible reverse proxy fronting upstream LLM providers.
- **lightbridge-repo-auth** — the GitHub-OIDC → billing-account binding for CI (ADR-0047).
- **LGTM stack** — Loki + Grafana + Tempo + Mimir.
- **MCP** — Model Context Protocol; the tool-server protocol exposed at `/mcp/*`.
- **ESO** — External Secrets Operator. **CNPG** — CloudNativePG. **Authorino** — Kuadrant ext_authz enforcing our AuthConfig.
