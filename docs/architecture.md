# Architecture overview

The single-page map of how this repo's charts compose into a running system.
Read after the top-level [README](../README.md). For depth, follow the
**[layered architecture suite](architecture/README.md)** (C4 context → container →
component, plus one page per subsystem) or the formal
**[arc42 description](arc42.md)**. Every *why* lives in the
[ADR index](adr/README.md).

> Reflects `release-2026.06.14-v09`. Coder was removed (ADR-0027) and is not shown.

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

> **Vanity-domain redirects (ADR-0053).** We own `kivoyo.com`; its DNS already
> points at these LBs. `api.ai.kivoyo.com` is `307`-redirected to
> `api.ai.camer.digital` at the Envoy Gateway (`charts/core-gateway`
> `gateway.redirectHosts`), and `ai.kivoyo.com` is `302`-redirected to
> `ai.camer.digital` at Traefik (a `redirectRegex` Middleware + Ingress in
> `charts/librechat-app`). Temporary + path-preserving; `camer.digital` stays
> canonical.

## GitOps in one diagram

Two clusters: ArgoCD runs on `admin@homeos`; workloads run on Hetzner
`home-remote`. The root `ai-apps-v2` Application is **applied from `home-os`** and
pins an **immutable release tag** (never `main` — ADR-0031). Detail:
[suite · 04 GitOps](architecture/04-gitops-deployment.md).

> ⚠️ **Migrating to continuous delivery (ADR-0055):** tag-based deploys are being
> replaced by OCI-published charts floated on a semver range + argocd-image-updater
> write-back to the private `ai-helm-values` repo. Per-app opt-in (`chart:`); the
> tag model applies until each app is cut over. Runbook:
> [`continuous-delivery.md`](continuous-delivery.md).

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

LGTM + Alloy, per-user attribution from JWT → Loki labels; opaque `user_id`
UUIDs + offline grants resolved via a read-only Keycloak datasource
([`keycloak-identity-datasource.md`](keycloak-identity-datasource.md),
ADR-0063/0064). Detail: [suite · 08 Observability](architecture/08-observability.md).

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
root Application is applied from `home-os` with its tag pinned in `home-os`
`charts/cd`. (ADR-0055 introduces a private **`ai-helm-values`** repo for the
written-back image tags + the migrated `environments/` overlays — values-only;
the root still lives in `home-os`.) Detail:
[suite · 07 Data & secrets](architecture/07-data-secrets.md).

## Glossary

- **AI Gateway** — Envoy AI Gateway (`aieg`, **v1.0** on Envoy Gateway v1.8.1; ADR-0069); the OpenAI-compatible reverse proxy fronting upstream LLM providers. Our AIEG CRs are authored as `aigateway.envoyproxy.io/v1beta1`.
- **lightbridge-repo-auth** — the GitHub-OIDC → billing-account binding for CI (ADR-0047).
- **LGTM stack** — Loki + Grafana + Tempo + Mimir.
- **MCP** — Model Context Protocol; the tool-server protocol exposed at `/mcp/*`.
- **ESO** — External Secrets Operator. **CNPG** — CloudNativePG. **Authorino** — Kuadrant ext_authz enforcing our AuthConfig.
