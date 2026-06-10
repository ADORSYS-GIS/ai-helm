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

The **entrypoint** is a single root Application, `ai-apps-v2`, that points at
`charts/apps` in this repo. There is **no `ai-gitops` repo** — the root is
**applied manually** (from a maintainer-held manifest) onto the ArgoCD cluster.
Deploys are **tag-based** (immutable `release-YYYY.MM.DD`, never `main` — ADR-0031):

```yaml
# applied manually on the ArgoCD cluster (admin@homeos) — no ai-gitops repo
- name: ai-apps-v2
  project: ai
  source:
    repoURL: https://github.com/ADORSYS-GIS/ai-helm
    targetRevision: release-2026.06.08-v02   # immutable release tag — never main (ADR-0031)
    path: charts/apps
  destination:
    server: https://kubernetes.default.svc   # in-cluster/argocd: the root is a
    namespace: argocd                         # control object (ADR-0017); children → home-remote
  syncPolicy:
    automated: { prune: true, selfHeal: true }
```

`charts/apps` is reconciled onto the `home-remote` cluster; the
Application CRDs it emits land in that cluster's `argocd` namespace and
are reconciled there. **Every** generated Application references the same
cluster by the same registered name `home-remote` — never ArgoCD's
built-in in-cluster handle (a render-time guard enforces this; ADR-0017).

Two-tier destination (ADR-0017): the `Application` / `ApplicationSet`
CRs themselves live **in-cluster** (the `argocd` namespace where ArgoCD's
controllers run); the **workloads** they deploy target **`home-remote`**.

```
ArgoCD (in-cluster)                         ← Application/ApplicationSet CRs live here (argocd ns)
  ├─ Application: ai-apps-v2               (entry point; points at charts/apps; dest in-cluster)
  │
  └─ charts/apps emits 1 Application per workload (workloads → home-remote):
       │
       ├─ Application: kube-state-metrics, node-exporter
       ├─ Application: mimir, loki, tempo, alloy, grafana, grafana-operator
       ├─ Application: observability-dashboards
       ├─ Application: eg, aieg, aieg-crd
       ├─ Application: core-gateway, authorino-operator, security-policies
       ├─ Application: keycloak-baseline    (keycloak-config-cli realm sync)
       ├─ Application: librechat  ─┐  controlPlane:true → the ApplicationSet
       ├─ Application: models     ─┤  lands in-cluster; its child Applications
       │                           ┘  deploy workloads to home-remote
       └─ Application: <≈ 25 more apps>     (workloads → home-remote)
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
  Authorino ext_authz  (DUAL-PLANE, AuthConfig-per-host — ADR-0021)
  ↓
  ├── EXTERNAL host (api.ai-v2…) → verify Keycloak JWT (JWKS)
  ├── INTERNAL host (core-gateway-internal.svc) → k8s SA TokenReview OR apiKey
  ├── (OPA REMOVED 2026-06-04 — a valid JWT/SA/apiKey = access; OPA was the old
  │    lightbridge-validation step, now gone; reserved for future burst control)
  ├── inject x-oidc-* headers downstream (ADR-0011):
  │    user_id, user_name, azp, iss, roles, scope, jti, email, name
  └── inject rate-limit descriptors: x-account-id, x-org-id, x-billing-plan
       (CEL: Keycloak claims w/ defaults; or a LibreChat-forwarded end-user sub)
  ↓
  per-model BackendTrafficPolicy → burst (x-account-id) + budget (x-org-id) by tier
  ↓
  Envoy access log (JSON) → Alloy → Loki labels {user_id, azp}
```

> **Exception — `/mcp/*` (ADR-0038):** the five MCPRoutes carry their own
> `securityPolicy.oauth` (MCP-spec OAuth), which displaces Authorino on those
> routes: Envoy's native JWT filter verifies the same Keycloak issuer, the
> gateway itself serves the RFC 9728 discovery surface unauthenticated
> (`/.well-known/oauth-protected-resource/mcp/<name>` + AS-metadata aliases +
> the path-appended PRM alias + the 401 `resource_metadata` challenge), and
> `claimToHeaders` re-stamps the ADR-0011 `x-oidc-*` set. Rate-limit
> descriptors are NOT stamped on `/mcp/*` (no MCP rate limiting today).
>
> ⚠️ **External HTTPS MCP backends need a TLS-socket fix (ADR-0039).** AIEG
> stamps a `dummy.transport_socket` (empty SNI) on the cluster it generates for
> an external MCP backend, which `BackendTLSPolicy` can't reach → the upstream
> TLS handshake to CDN-fronted servers fails. An `EnvoyPatchPolicy` in
> `charts/core-gateway` injects a real TLS socket (SNI + system-CA) — fixes the
> **RSA-cert** externals (firecrawl, refero). **context7's ECDSA cert is rejected
> by Envoy's BoringSSL** regardless, and self-hosting it needs a custom image +
> Upstash Redis (against repo constraints) — so context7 was **dropped**. Full diagnosis:
> [`docs/2026-06-10-mcp-external-server-proxy-debug.md`](2026-06-10-mcp-external-server-proxy-debug.md).

**Three identity surfaces** to know:
- **Human users via LibreChat browser** — Keycloak code+PKCE, returns
  a JWT; LibreChat's session represents it; calls to backends carry
  LibreChat-templated headers (X-USER-ID, X-USER-EMAIL, etc.) per
  [`docs/librechat_headers_tracing_doc.md`](librechat_headers_tracing_doc.md).
- **Humans via the OpenAI-compatible endpoint** — API keys from the
  Lightbridge self-service portal. Used by `opencode`, third-party
  CLIs, scripts. Backed by Keycloak OAuth flows via the
  `@vymalo/opencode-oauth2` plugin (ADR-0014, [`opencode-well-known.md`](opencode-well-known.md)).
- **Service accounts (CI / remote)** — Keycloak service-account tokens on the
  external plane. **In-cluster** services use the internal plane instead:
  a k8s SA token (one-time jobs) or a static apiKey (long-running, e.g.
  LibreChat) — ADR-0021. (OPA / the `azp`-skip of ADR-0003 are removed.)

> ⚠️ The OPA-era detail above (lightbridge-opa validation, the SA-skip-OPA path,
> the `x-project-id`/`x-api-key-id` headers) is **historical** — OPA was removed
> 2026-06-04. See **ADR-0021** + `docs/2026-hetzner-cutover.md` for the current
> dual-plane / Keycloak-JWT model.

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
    OTLP: traces via the core-gateway -traces OTel collector;
          Envoy access logs pushed direct to Alloy (the -usage
          collector was removed — usage/billing is via the AI
          Gateway + OAuth2 path)
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
- [ADR-0021](adr/0021-burst-budget-billing-and-dual-plane-authconfigs.md) — burst/budget/billing via dual-plane AuthConfigs (OPA removed; Keycloak JWT is the boundary)
- [ADR-0022](adr/0022-self-hosted-gpu-model-federated-into-gateway.md) — self-hosted GPU model federated into the gateway (cluster-local + Caddy auth-proxy; `homeCluster: true`); the *how* is [`self-hosted-model-serving.md`](self-hosted-model-serving.md)
- [ADR-0028](adr/0028-owned-hardware-model-pricing.md) — cost-recovery pricing for owned-hardware models (€/hour TCO → weighted per-token)
- [ADR-0029](adr/0029-self-hosted-model-plain-deployment.md) — self-hosted model as a plain Deployment (drop KServe/Knative); always-on + Recreate on the dedicated GPU
- [ADR-0030](adr/0030-merge-model-and-proxy-into-one-statefulset-bjw.md) — model + Caddy auth-proxy co-located in one StatefulSet (proxy → model over localhost), via bjw-template
- [ADR-0032](adr/0032-llama-cpp-engine-for-self-hosted-models.md) — llama.cpp (`llama-server`) as a 2nd serving engine; **Qwen3.5-4B Q4 is the LIVE self-hosted model** (2026-06-08, `charts/model-serving-qwen3-5`, GGUF/`/v1`/native-`--api-key`), Qwen3-4B (vLLM) on standby. Per-model papers + measured capacity in [`docs/models/`](models/qwen3.5-4b-q4.md)

## What is *not* in this repo

- **Shared cluster infrastructure (installed externally).** Several
  platform components are deployed/owned outside this repo — this repo
  only *consumes* them by name. None of them have an Application here:
  - **Traefik** — the ingress controller + `traefik` IngressClass (runs
    in the `traefik` namespace). Charts here set `ingressClassName:
    traefik`.
  - **CloudNativePG** — the `cnpg` Postgres operator + the Barman Cloud
    backup plugin (`cnpg-system`). This repo defines CNPG `Cluster` CRs
    (e.g. `charts/coder-db`) that the external operator reconciles.
  - **cert-manager** — controller, CRDs, and the shared ClusterIssuers
    (home-os). This repo references `cert-manager.io/cluster-issuer:`.
  - **Redis** — `redis-ha` (home-os, `redis-system`).
- **Secrets + the External Secrets Operator.** ESO itself (controller +
  CRDs) is installed externally — *not* by this repo. The
  `ClusterSecretStore` in use is `ssegning-aws` (cluster-scoped,
  external). ExternalSecret CRs are now **chart-owned** (in-chart +
  `environments/<env>/deps/*` overlays), all referencing `ssegning-aws` —
  the old wholesale `secrets` Application from `ai-ops-secrets.git` was
  **removed (2026-06-04)**. App secrets pull from key
  `ai/camer/digital/prod/env`, platform secrets from `prod/meta/test-app`.
- **Deploy state (no `ai-gitops` repo).** It was planned (ADR-0010/0013) but
  never built. Instead: per-env config lives **in this repo** under
  `environments/<env>/` (ADR-0018); the root `ai-apps-v2` `Application` is
  **applied manually** on the ArgoCD cluster; and the deployed version is an
  **immutable release tag** `release-YYYY.MM.DD` that every self-reference pins
  (ADR-0031 — see `docs/releasing.md` + `tools/release.sh`). Image-tag defaults
  stay in `charts/<x>/values.yaml`, not chart logic (ADR-0013).
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
