# 01 · System context (C4 Level 1)

The platform as a single box, with everyone who talks to it and everything it
depends on. No internals here — that's [02 Containers](02-containers.md).

## The one-box view

```mermaid
flowchart TB
    subgraph people["People & automated callers"]
        HUMAN["👤 End user<br/>browser (chat)"]:::actor
        DEV["🧑‍💻 Developer<br/>opencode / OpenAI-compatible CLI"]:::actor
        CI["🤖 CI runner<br/>GitHub Actions"]:::actor
        OPS["🛠️ Platform maintainer"]:::actor
        FIN["📊 Finance / billing"]:::actor
    end

    PLATFORM["🟢 <b>Camer Digital AI Platform</b><br/>(ai-helm)<br/><br/>OpenAI-compatible inference,<br/>chat UI, MCP tools, dev observability"]:::platform

    subgraph ext["External systems (consumed, not owned)"]
        KC["🔑 Keycloak IdP<br/>auth.verif.fyi<br/>realm camer-digital"]:::ext
        PROV["🧠 Model providers<br/>DeepInfra · Fireworks · Google AI"]:::ext
        GH["🐙 GitHub<br/>source · Actions OIDC · App webhooks"]:::ext
        EXTMCP["🔌 Hosted MCP servers<br/>context7 · firecrawl · refero"]:::ext
        S3["🪣 Hetzner Object Storage<br/>nbg1.your-objectstorage.com"]:::ext
        HCLOUD["☁️ Hetzner Cloud LB"]:::ext
    end

    HUMAN -->|"OIDC login, chat"| PLATFORM
    DEV -->|"API key / JWT, /v1 calls"| PLATFORM
    CI -->|"GHA OIDC token → gateway"| PLATFORM
    OPS -->|"git push (GitOps)"| PLATFORM
    FIN -->|"reads Grafana"| PLATFORM

    PLATFORM -->|"verify JWT (JWKS)"| KC
    PLATFORM -->|"proxy inference"| PROV
    PLATFORM -->|"clone charts; resolve repo→account"| GH
    PLATFORM -->|"proxy tool calls (via in-cluster proxies)"| EXTMCP
    PLATFORM -->|"metrics/logs/traces + DB backups"| S3
    HCLOUD -->|"public ingress"| PLATFORM

    classDef actor fill:#fff,stroke:#555,color:#222;
    classDef platform fill:#eaf3ea,stroke:#4a8a4a,color:#1a401a,stroke-width:2px;
    classDef ext fill:#eee,stroke:#888,color:#333,stroke-dasharray:4 3;
```

## Actors

| Actor | How they reach the platform | Identity |
|---|---|---|
| **End user** | LibreChat browser UI at `ai.camer.digital` | Keycloak OIDC (code + PKCE) |
| **Developer** | `opencode` / any OpenAI-compatible client at `api.ai.camer.digital/v1` | API key from the self-service portal, or a Keycloak JWT |
| **CI runner** | GitHub Actions calling the gateway | **GitHub Actions OIDC token** → resolved to a billing account by `lightbridge-repo-auth` (no shared key — see [05](05-auth-identity.md)) |
| **Platform maintainer** | `git push` → ArgoCD reconciles | Git + cluster RBAC |
| **Finance / billing** | Grafana dashboards | Read-only |

## External systems (the platform's hard dependencies)

These are **referenced by name only** — installed and owned by the companion
repos (`home-os`, `hetzner-k8s`) or by SaaS vendors. See
[07 Data & secrets](07-data-secrets.md) and
[06 Networking & TLS](06-networking-tls.md) for how each is wired in.

| System | Role | Owner |
|---|---|---|
| **Keycloak** (`auth.verif.fyi`) | The OIDC identity provider; issues every human/SA JWT; source of the `billing_plan` claim | external |
| **Model providers** | The actual inference (DeepInfra, Fireworks, Google AI Studio) | SaaS |
| **GitHub** | Chart source repo; **GHA OIDC** issuer for CI auth; **App webhooks** for `lightbridge-repo-auth` org→account binding | SaaS |
| **Hosted MCP servers** | Third-party tools (context7, firecrawl, refero) — fronted by in-cluster normalizing proxies | SaaS |
| **Hetzner Object Storage** | S3 for Mimir/Loki/Tempo blocks, CNPG/Mongo backups, LibreChat files | Hetzner |
| **Hetzner Cloud LB** | The public data-plane load balancer (`46.225.38.138`) | Hetzner |
| **cert-manager · ESO · Redis · CNPG · Traefik** | TLS, secret sync, sessions/counters, Postgres, ingress | `home-os` / `hetzner-k8s` |

## Scope boundary

**Inside** the box (this repo owns): the Envoy AI Gateway + auth policies,
per-model routing + budgets, LibreChat, the opencode discovery + model catalog,
MCP servers + proxies, the self-hosted GPU model, the observability stack +
dashboards, and all the GitOps glue.

**Outside** the box: every dashed node above, plus the ArgoCD control plane
itself (it runs on a *separate* cluster — see [04 GitOps](04-gitops-deployment.md)).

→ Next layer: [02 · Containers](02-containers.md)
