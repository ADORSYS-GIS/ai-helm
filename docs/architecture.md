# Architecture overview

One document mapping how this repo's charts compose into a running
system. Read after the top-level [README](../README.md), before diving
into any specific subsystem.

## Cluster topology

```
                          ┌────────────────────────────────────────┐
                          │             Internet                   │
                          └────────────────┬───────────────────────┘
                                           │ TLS (Let's Encrypt + Cloudflare DNS-01)
                                           ▼
                          ┌────────────────────────────────────────┐
                          │ Traefik / Envoy AI Gateway             │
                          │   (`core-gateway`)                     │
                          │   ├── ai.camer.digital      → librechat│
                          │   ├── ai.camer.digital/opencode/...    │
                          │   │                          → opencode-wellknown
                          │   ├── api.ai.camer.digital  → AI       │
                          │   │                            backend │
                          │   │     (Authorino auth + AIGateway-   │
                          │   │      Routes per model)             │
                          │   └── auth.verif.fyi        → Keycloak │
                          │       (separate cluster, federated)    │
                          └────────────────┬───────────────────────┘
                                           │
                      ┌────────────────────┼────────────────────┐
                      ▼                    ▼                    ▼
        ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
        │  LibreChat       │   │ Lightbridge      │   │ Coder            │
        │  (charts/        │   │ (lightbridge-    │   │ (coder + coder-db│
        │   librechart)    │   │  backend)        │   │  CNPG cluster)   │
        │   ├── librechat- │   │ Validates API    │   │ Dev environments │
        │   │   app +Mongo │   │ keys; injects    │   │ in cloud         │
        │   ├── librechat- │   │ x-project-id, ...│   │                  │
        │   │   search    │   │                  │   │                  │
        │   │   (Meili)    │   │                  │   │                  │
        │   └── opencode-  │   │                  │   │                  │
        │       wellknown  │   │                  │   │                  │
        └──────────────────┘   └──────────────────┘   └──────────────────┘
                                           │
                  ┌────────────────────────┼────────────────────────────┐
                  ▼                        ▼                            ▼
        ┌──────────────────┐   ┌──────────────────┐         ┌──────────────────┐
        │ AI models        │   │ MCP servers      │         │ Observability    │
        │ (charts/         │   │ (mcpo + mcps:    │         │ (Mimir / Loki /  │
        │  ai-models, fans │   │  brave, terraform│         │  Tempo / Alloy / │
        │  out to one App  │   │  firecrawl, ...) │         │  Grafana)        │
        │  per model)      │   │                  │         │                  │
        │  ├── DeepInfra   │   │                  │         │  + dashboards    │
        │  ├── Fireworks   │   │                  │         │    via grafana-  │
        │  └── Google AI   │   │                  │         │    operator      │
        └──────────────────┘   └──────────────────┘         └──────────────────┘
```

## ArgoCD topology

Everything is GitOps:

The **entrypoint** is a single root Application that lives in the
`ai-gitops` repo (not here) and points at `charts/apps` in this repo:

```yaml
# ai-gitops — the GitOps entrypoint
- name: ai-apps-v2
  project: ai
  source:
    repoURL: https://github.com/ADORSYS-GIS/ai-helm
    targetRevision: <branch>      # main on merge; the PR branch while testing
    path: charts/apps
  destination:
    name: home-remote             # registered cluster name (see ADR-0017)
    namespace: argocd
  syncPolicy:
    automated: { prune: true, selfHeal: true }
```

`charts/apps` is reconciled onto the `home-remote` cluster; the
Application CRDs it emits land in that cluster's `argocd` namespace and
are reconciled there. **Every** generated Application references the same
cluster by the same registered name `home-remote` — never ArgoCD's
built-in in-cluster handle (a render-time guard enforces this; ADR-0017).

```
ArgoCD (on home-remote)
  ├─ Application: ai-apps-v2               (entry point; points at charts/apps)
  │
  └─ charts/apps emits 1 Application per workload (all → cluster home-remote):
       │
       ├─ Application: cnpg                 (cloudnative-pg operator)
       ├─ Application: kube-state-metrics, node-exporter
       ├─ Application: mimir, loki, tempo, alloy, grafana, grafana-operator
       ├─ Application: observability-dashboards
       ├─ Application: traefik, eg, aieg, aieg-crd
       ├─ Application: core-gateway, authorino-operator, security-policies
       ├─ Application: keycloak-baseline    (keycloak-config-cli realm sync)
       ├─ Application: librechat            ─┐
       ├─ Application: models               ─┤  These three emit
       ├─ Application: <future orchestrators>┘  ApplicationSets that
       │                                        fan out further
       └─ Application: <≈ 25 more apps>
```

**Two render patterns** for complex charts:

1. **Direct** — chart renders its workloads directly. Most charts. One
   ArgoCD `Application` per chart.
2. **Orchestrator + leaves** — the chart emits a single `ApplicationSet`
   (List generator) that fans out to N child Applications, each pointing
   at a leaf chart in this same repo. Used by `ai-models` (ADR-0012) and
   `librechart` (ADR-0014). One `Application` becomes one
   `ApplicationSet` becomes N `Application`s.

Choose pattern (2) when the components inside the chart have
**different lifecycles** (sync waves, restart cadence, per-component
rollback) or when adding/removing components should be a list edit
rather than a values diff.

## Sync waves

Lower waves sync first. Conventions:

| Wave | What |
|---|---|
| `-5` to `-3` | (reserved for namespace bootstrap, ResourceQuota / LimitRange — see [SYNC_WAVE_PATTERN.md](../SYNC_WAVE_PATTERN.md)) |
| `-2` | Storage / observability backends (Mimir, Loki, Tempo, kube-state-metrics, node-exporter) |
| `-1` | Operators + grafana-operator + collectors (Alloy). NOTE: **cert-manager and the External Secrets Operator (ESO) are no longer synced here** — both their controllers/CRDs, the shared ClusterIssuers (`cert-home-cert-http`, `self-signed-ca`, …), and the `ssegning-aws` ClusterSecretStore are provisioned externally (home-os / cluster bootstrap). This repo only references the issuers + Secret names. |
| `0` | Workloads (LibreChat, AI Gateway, Coder, all per-model apps) |
| `1` | Content (Grafana dashboards, opencode-wellknown, anything that depends on a running gateway) |
| `2+` | Per-app post-sync work |

The rule is **infrastructure before storage before collection before
visualisation** (and the postmortem in [MONITORING_FIX.md](../MONITORING_FIX.md)
explains why a violation cost us a day).

## Auth & identity

```
Browser / CLI ──── OIDC code+PKCE / device-code ─────► Keycloak (auth.verif.fyi)
                                                       realm: camer-digital
                                                       ↓
                                                       JWT (RS256)
                                                       ↓
       ┌───────────────────────────────────────────────┴────────┐
       │                                                        │
       ▼                                                        ▼
  api.ai.camer.digital                                    Self-service portal
  (Envoy AI Gateway)                                      (selfServiceMcpApi
  ↓                                                       Keycloak client)
  Authorino ext_authz                                     ↓
  ↓                                                       Issues API keys
  ├── verify JWT (Keycloak JWKS)                          (Lightbridge-managed)
  ├── if azp ∈ SA allowlist → skip OPA (ADR-0003)
  ├── else → call lightbridge-opa for project/account/api-key validation
  ├── inject x-oidc-* headers downstream (ADR-0011):
  │    user_id, user_name, azp, iss, roles, scope, jti, email, name
  └── inject x-project-id, x-account-id, x-api-key-id, x-billing-plan
  ↓
  Envoy access log (JSON) → OTLP → Alloy → Loki labels {user_id, azp}
```

**Three identity surfaces** to know:
- **Human users via LibreChat browser** — Keycloak code+PKCE, returns
  a JWT; LibreChat's session represents it; calls to backends carry
  LibreChat-templated headers (X-USER-ID, X-USER-EMAIL, etc.) per
  [`docs/librechat_headers_tracing_doc.md`](librechat_headers_tracing_doc.md).
- **Humans via the OpenAI-compatible endpoint** — API keys from the
  Lightbridge self-service portal. Used by `opencode`, third-party
  CLIs, scripts. Backed by Keycloak OAuth flows via the
  `@vymalo/opencode-oauth2` plugin (ADR-0014, [`opencode-well-known.md`](opencode-well-known.md)).
- **Service accounts (CI)** — Keycloak service-account tokens; `azp`
  in the SA allowlist skips OPA (ADR-0003). ADR-0009 deferred a
  Python token-exchange step for GH Actions OIDC → Keycloak; not
  shipped yet.

## Observability

```
                  ┌──────────────────────────────────────┐
                  │              Grafana                 │
                  │  (datasources: mimir, loki, tempo,   │
                  │   alertmanager)                      │
                  └──────────────┬───────────────────────┘
                                 │
       ┌─────────────────────────┼─────────────────────────┐
       ▼                         ▼                         ▼
  ┌──────────┐              ┌──────────┐              ┌──────────┐
  │  Mimir   │              │   Loki   │              │  Tempo   │
  │ metrics  │              │   logs   │              │  traces  │
  └──────────┘              └──────────┘              └──────────┘
       ▲                         ▲                         ▲
       │                         │                         │
       └───────────┬─────────────┴─────────────┬───────────┘
                   ▼                            ▼
              ┌──────────┐                ┌──────────┐
              │   Alloy  │                │   Alloy  │
              │  (DaemonSet, ServiceMonitor / PodMonitor discovery,
              │   pod-log tail, OTLP receiver, ai_gateway_user_attribution
              │   stage promotes user_id/azp to Loki labels)
              └──────────┘
                   ▲
                   │
    OTLP from core-gateway -traces & -usage OTel collectors
    /metrics scrape from kube-state-metrics, node-exporter, every
    workload that ships a Service/PodMonitor
```

**Dashboards** ship as `GrafanaDashboard` CRs via `grafana-operator`
(external mode — see [ADR-0004](adr/0004-grafana-operator-external-mode.md))
and are generated from Python in `tools/dashboards/`
(see [ADR-0008](adr/0008-python-dashboard-generation.md)).

## Where every architectural choice is documented

In one place: [`docs/adr/`](adr/). Read [ADR-0001](adr/0001-record-architecture-decisions.md)
first for the format and conventions, then the index in
[`docs/adr/README.md`](adr/README.md).

The high-impact ones:

- [ADR-0002](adr/0002-replace-phoenix-with-tempo.md) — Arize Phoenix retired, Tempo is the LLM trace backend
- [ADR-0003](adr/0003-skip-opa-for-service-accounts.md) — `azp`-allowlist for SA-skip-OPA
- [ADR-0004](adr/0004-grafana-operator-external-mode.md) — grafana-operator + dashboards-as-code
- [ADR-0005](adr/0005-per-user-attribution-via-authorino-headers.md) — JWT identity → Loki labels pipeline
- [ADR-0011](adr/0011-oidc-downstream-headers.md) — canonical `x-oidc-*` header contract
- [ADR-0012](adr/0012-split-ai-models-applicationset.md) — `ai-models` orchestrator split
- [ADR-0014](adr/0014-split-librechart-and-opencode-wellknown.md) — `librechart` orchestrator split + opencode well-known

## What is *not* in this repo

- **Secrets + the External Secrets Operator.** ESO itself (controller +
  CRDs) is installed externally — *not* by this repo. The
  `ClusterSecretStore` in use is `ssegning-aws` (cluster-scoped,
  external). ExternalSecret CRs come from `ai-ops-secrets.git` (the
  `secrets` Application) and other external sources; they all reference
  `ssegning-aws`. This repo only references the resulting Secret names.
- **ai-gitops state.** Per-cluster image-tag overrides, environment
  config, the actual ArgoCD `Application` for the root umbrella —
  all in the separate `ai-gitops` repo.
- **Realm config secrets** — Keycloak client secrets are ESO-injected
  at sync time; the realm structure is in
  `charts/keycloak-baseline/values.yaml`.
- **Backups themselves** — only the backup-job definitions
  (`charts/*-backup/`); the S3 buckets and contents are operated
  out-of-band.

## Glossary

- **AI Gateway** — Envoy AI Gateway (`aieg`); the OpenAI-compatible
  reverse proxy fronting upstream LLM providers.
- **Lightbridge** — first-party authz/authn service that validates
  API keys + tracks usage per project/account.
- **LGTM stack** — Grafana Labs' Loki + Grafana + Tempo + Mimir
  observability set.
- **MCP** — Model Context Protocol; the protocol LibreChat uses to
  talk to first-party tool servers (Coder, GitHub, Lightbridge
  self-service).
- **ESO** — External Secrets Operator.
- **CNPG** — CloudNativePG, the Postgres operator.
- **Authorino** — Kuadrant project's ext_authz implementation;
  enforces our AuthConfig.
