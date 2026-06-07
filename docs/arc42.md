# arc42 — Camer Digital AI Platform (ai-helm)

> [arc42](https://arc42.org) architecture description for the AI platform
> deployed by this repository. arc42's twelve sections, applied to the
> steady state on `claude/magical-bohr-390242`. Cross-references the
> [architecture map](./architecture.md), the [ADR index](./adr/README.md),
> the [architectural-shift narrative](./architectural-shift-main-to-magical-bohr.md),
> and the [OpenAI-alternative plan](../plans/openai-alternative-plan.md).

**Maintainer:** @stephane-segning · **Date:** 2026-06-04

---

## 1. Introduction and goals

The platform delivers a **multi-tenant, OpenAI-compatible inference service**
plus the tools around it (a chat UI, a CLI integration, dev environments, MCP
servers) for Camer Digital. It is delivered entirely as Helm charts reconciled
by ArgoCD; there is no application build in this repo.

### Core quality goals

| Priority | Quality | Concrete goal |
|---|---|---|
| 1 | **Scalability** | Serve ~2000 concurrent clients sustained, ~5000 at peak, on the OpenAI-compatible endpoint without latency collapse |
| 2 | **Observability / attribution** | Every request attributable to a user, org, plan, and model; usage and cost queryable in Grafana in near-real-time |
| 3 | **Security / multi-tenancy** | Keycloak JWT is the authorization boundary; per-plan burst + monthly budget enforced at the gateway; tenant isolation by claim |
| 4 | **Operability (GitOps)** | Every change is a reviewed Git diff; reproducible, declarative, env-overlayable |
| 5 | **Cost control** | Per-org monthly USD budget enforced; self-hosted object storage; no per-request Python hop |

### Stakeholders

| Role | Concern |
|---|---|
| Platform maintainer (@stephane-segning) | Operability, cost, the deploy branch staying green |
| End users (humans via LibreChat, devs via opencode/CLI) | Latency, model availability, fair quota |
| Service accounts (CI runners) | Programmatic access without human auth |
| Finance / billing | Per-org spend, charge-back data |
| Security | JWT boundary, tenant isolation, secret hygiene |

---

## 2. Constraints

| Constraint | Implication |
|---|---|
| **GitOps only** — no imperative deploys | Everything is a chart; `kubectl rollout restart` is reverted by ArgoCD selfHeal |
| **Two clusters** — ArgoCD on Talos `admin@homeos`, workloads on Hetzner k3s `home-remote` | Control objects in-cluster, workloads `home-remote` (ADR-0017) |
| **Cilium default-deny-egress** baseline | Every API-server / S3 reach needs an additive `CiliumNetworkPolicy`; plain `NetworkPolicy` ipBlock does not match |
| **Infra owned externally** (`home-os`, `hetzner-k8s`) | cert-manager, ESO, Redis, Traefik, CNPG, OTel-operator referenced by name only |
| **k3s `baseline` Pod Security** cluster-wide | Observability collectors' namespace must be `privileged` |
| **OpenAI API compatibility** | Routes, `/v1/models`, `/v1/models/info` (OpenRouter shape) must match client expectations |
| **Verification = `helm template` + `helm lint`** | No app test loop; dashboards Python is the only runnable code |
| **Single env today (`prod`/Hetzner)** | A second env is a drop-in `environments/<env>/` sibling |

---

## 3. Context and scope

### Business context

```
   Humans (browser) ─┐
   Devs (opencode/CLI)┤
   CI service accounts┘
            │  OIDC / API key (JWT)
            ▼
   ┌────────────────────────────────────────────┐
   │      Camer Digital AI Platform (ai-helm)    │
   │   OpenAI-compatible inference + chat + IDE  │
   └───────┬───────────────────────────┬────────┘
           │ provider API calls        │ identity
           ▼                           ▼
   Model backends                   Keycloak IdP
   (DeepInfra, Fireworks,           (auth.verif.fyi,
    Google AI)                       realm camer-digital)
```

### Technical context (external systems consumed, not owned)

| External system | Role | Owner repo |
|---|---|---|
| Keycloak (`auth.verif.fyi`) | OIDC IdP, JWT issuer, billing-plan claim source | (separate) |
| cert-manager + ClusterIssuers | TLS (ACME HTTP-01 + internal CA) | `home-os` |
| External Secrets Operator + `ssegning-aws` store | Secret sync | external |
| redis-ha (TLS-only) | LibreChat sessions, Envoy ratelimit counters | `home-os` |
| Traefik | Ingress controller (non-gateway ingresses) | external |
| CloudNativePG + Barman | Postgres for Coder, backups | external |
| Hetzner Object Storage (`nbg1.your-objectstorage.com`) | Mimir/Loki/Tempo/CNPG/LibreChat S3 | Hetzner |
| Hetzner Cloud LB | Public data-plane LB (`46.225.38.138`) | Hetzner |
| Model providers (DeepInfra/Fireworks/Google AI) | Actual inference | SaaS |

### System scope (owned by ai-helm)

The Envoy AI Gateway, AuthConfigs/security policies, per-model routing + budget
policies, LibreChat, opencode well-known + models-info catalog, Coder, MCP
servers, the observability stack, dashboards, and all the GitOps glue.

---

## 4. Solution strategy

| Goal | Strategy | Realised by |
|---|---|---|
| Scale to 2000/5000 clients | HTTP/2 multiplexing + data-plane HPA + circuit breaking | `core-gateway` ClientTrafficPolicy / EnvoyProxy HPA / BackendTrafficPolicy (ADR-0021, commits `ab39aed`/`d3257b6`) |
| Attribution | JWT → Authorino `x-oidc-*` headers → Envoy access log → Alloy → Loki labels | ADR-0005/0011, `per-user-observability.md` |
| Authorization | Keycloak JWT as the boundary; per-host AuthConfig differentiation | ADR-0003/0021 |
| Quota & billing | Per-plan burst + per-org monthly budget in `BackendTrafficPolicy`; metering via counters | ADR-0021 |
| Operability | GitOps + umbrella apps + env overlays + App-of-Apps | ADR-0016–0020 |
| Provider abstraction | Envoy AI Gateway `AIGatewayRoute` per model, fan-out via ApplicationSet | ADR-0012 |
| Dashboards reproducibility | Python (grafana-foundation-sdk) → `GrafanaDashboard` CRs, drift-checked | ADR-0004/0008 |

---

## 5. Building block view

### Level 1 — system decomposition

```
                         Internet (TLS: Let's Encrypt HTTP-01)
                                     │
                          ┌──────────▼───────────┐
                          │  Envoy AI Gateway     │  charts/core-gateway
                          │  (core-gateway)       │  + eg/aieg controllers
                          │  external + internal  │
                          │  planes; Authorino    │
                          │  ext_authz            │
                          └─┬─────────┬────────┬──┘
            ┌───────────────┘         │        └──────────────┐
            ▼                         ▼                       ▼
   ┌─────────────────┐   ┌─────────────────────┐   ┌───────────────────┐
   │ LibreChat       │   │ AI models (per-model│   │ Coder             │
   │ (librechart     │   │ AIGatewayRoute +    │   │ (coder + coder-db │
   │  orchestrator)  │   │ BackendTrafficPolicy│   │  CNPG)            │
   │ + opencode      │   │ ; ai-models →       │   │                   │
   │  well-known     │   │ ai-model leaves)    │   │                   │
   │ + models-info   │   │ + ai-models-backends│   │                   │
   └─────────────────┘   └─────────────────────┘   └───────────────────┘
            │                         │                       │
            └──────────────┬──────────┴───────────┬───────────┘
                           ▼                       ▼
                  ┌─────────────────┐     ┌─────────────────────┐
                  │ MCP servers     │     │ Observability       │
                  │ (mcpo + mcps)   │     │ (LGTM + Alloy +     │
                  │                 │     │  grafana-operator)  │
                  └─────────────────┘     └─────────────────────┘
```

### Level 2 — key building blocks

| Chart | Responsibility | Pattern |
|---|---|---|
| `core-gateway` | Envoy AI Gateway, listeners (external + internal), ClientTrafficPolicy, BackendTrafficPolicy, ACME issuer, OTel collector | Direct |
| `kuadrant-policies` | Authorino instance + per-host AuthConfigs + SecurityPolicy | Direct |
| `ai-models` → `ai-model` | Orchestrator ApplicationSet → one Application per model (route + budget policy) | Orchestrator + leaves (ADR-0012) |
| `ai-models-backends` | `AIServiceBackend`/`Backend`/`BackendSecurityPolicy`/`BackendTLSPolicy` + key ExternalSecrets | Direct |
| `model-serving` | Self-hosted model on the home GPU: a **bjw-template StatefulSet** (always-on) with TWO containers — the huggingfaceserver model (vLLM + in-pod LMCache) + a Caddy auth-proxy sidecar (proxy → model over localhost) — + seed Job + Certificate/IngressRoute. Federated into the gateway as a backend; reference model Qwen3-4B | Hybrid bjw, `homeCluster: true` (ADR-0022/0028/0029/0030) |
| `ai-models-info` | OpenRouter-shape `/v1/models/info` catalog (nginx static) | Direct (ADR-0015) |
| `librechart` → `librechat-app` / `librechat-search` / `librechat-opencode-wellknown` | Chat UI + Meili + opencode discovery | Orchestrator + leaves (ADR-0014) |
| `observability` | LGTM + Alloy + grafana-operator + dashboards | App-of-Apps (ADR-0020) |
| `coder` → `coder-db` / `coder-app` | Cloud dev environments | App-of-Apps (ADR-0019) |
| `apps` | Root chart: emits one Application per workload (umbrella multi-source) | Root (ADR-0018) |
| `bjw-common` / `bjw-template` | Forked bjw-s common library | Library (ADR-0016) |

### Level 3 — the gateway request path (the load-bearing block)

```
client ──HTTP/2──▶ EnvoyProxy (HPA 3–20, LeastRequest LB)
                      │ ext_authz gRPC
                      ▼
                   Authorino (replicas 2, JWKS ttl 3600)
                      │ verify Keycloak JWT
                      │ stamp x-oidc-* + x-account-id/x-org-id/x-billing-plan
                      ▼
                   AIGatewayRoute (per model)
                      │ BackendTrafficPolicy:
                      │   burst req/min + tokens/min (per user)
                      │   monthly USD budget (per org)
                      │   circuit breaker + outlier detection
                      ▼
                   AIServiceBackend → provider (DeepInfra/Fireworks/Google)
                      │ token-cost metadata (llmRequestCosts)
                      ▼
                   access log (JSON, x-oidc-*) → OTLP → Alloy → Loki/Mimir
```

---

## 6. Runtime view

### Scenario A — human dev via opencode (external plane, full attribution)

1. `opencode auth login` → Keycloak code+PKCE → JWT (carries `sub`, `azp`,
   `billing_plan`, org).
2. Request to `api.ai.camer.digital` with the user's JWT.
3. Authorino verifies (JWKS cached), stamps `x-oidc-*` + `x-account-id` (=`sub`)
   + `x-org-id` + `x-billing-plan`.
4. `BackendTrafficPolicy` checks burst (per user) and monthly budget (per org);
   denies on any exhausted bucket.
5. Request proxied to provider; response token cost extracted.
6. Access log → Alloy → Loki (labels `user_id`, `azp`) + Mimir counters.

### Scenario B — human via LibreChat (internal plane, service-level attribution)

1. User logs into LibreChat (Keycloak OIDC); LibreChat holds a shared identity.
2. LibreChat calls `core-gateway-internal.…svc` with a **service-account JWT**.
3. Internal AuthConfig stamps `x-billing-plan: internal` (uncapped budget,
   burst-only); metered under LibreChat's `azp`.
4. Per-user budgeting for LibreChat's humans is LibreChat's own concern (it keeps
   per-user balances). Gateway-side per-user attribution is structurally
   impossible here (ADR-0021) — by design.

### Scenario C — CI service account

JWT with `azp` in `serviceAccountClients` → `x-billing-plan: service` (uncapped,
burst-protected, metered). Historically skipped OPA (ADR-0003); OPA now removed.

### Scenario D — rollout under load

EnvoyProxy rollout drains for 60s (`minDrainDuration` 15s) so long-lived
SSE/token streams aren't cut; HPA keeps ≥3 replicas; PDB `maxUnavailable: 1`.

---

## 7. Deployment view

### Two-cluster, two-tier GitOps

```
admin@homeos (Talos, ArgoCD)                home-remote (Hetzner k3s, workloads)
  ns argocd:                                  ns apps / data / observability / platform:
  ┌──────────────────────────┐                ┌────────────────────────────────────┐
  │ ai-apps-v2 (manual root) │── deploys ───▶ │ Envoy AI Gateway, LibreChat, models,│
  │ charts/apps              │                │ Coder, MCP, LGTM, dashboards         │
  │  emits 1 App per workload│                │ (each its own ArgoCD Application,    │
  │  (control objects here)  │                │  destination home-remote)            │
  └──────────────────────────┘                └────────────────────────────────────┘
```

- **Workloads** target `home-remote` (`argocd.destination`); a render guard
  hard-fails an in-cluster workload destination unless `allowInCluster`.
- **Control objects** (orchestrators emitting ApplicationSets) set
  `controlPlane: true` → target `https://kubernetes.default.svc` / `argocd` ns.
- **Per-env knobs** live in `environments/prod/cluster.yaml`; umbrella apps fold
  in a kustomize dep overlay (`environments/prod/deps/<app>/`) for the ingress
  `Certificate`, per-app `ExternalSecret`, and any `CiliumNetworkPolicy`.

### Sync waves (infrastructure → storage → collection → visualisation)

| Wave | What |
|---|---|
| −2 | Storage backends (Mimir, Loki, Tempo, kube-state-metrics, node-exporter) |
| −1 | Operators + grafana-operator + Alloy collector |
| 0 | Workloads (gateway, LibreChat, per-model apps, Coder) |
| 1 | Content (dashboards, opencode-wellknown) |
| 2+ | Post-sync |

Violating this order cost a day once — `MONITORING_FIX.md` is the postmortem.

### Networking realities

Cilium deny-egress: API-server reach needs `toEntities: [kube-apiserver]`; S3
needs `toFQDNs: "*.your-objectstorage.com"`. Hetzner LB targets workers only
(control-plane nodes excluded) and needs `use-private-ip: true`.

---

## 8. Crosscutting concepts

| Concept | How it's realised |
|---|---|
| **Identity** | Keycloak JWT (RS256); three surfaces: human/browser (LibreChat), human/API (opencode + self-service keys), service account (CI). `x-oidc-*` contract (ADR-0011). |
| **Authorization** | JWT validity = entry; per-host AuthConfig differentiates plane/plan; no OPA in path (ADR-0003/0021). |
| **Multi-tenancy** | `x-account-id` (user), `x-org-id` (org), `x-billing-plan` (Keycloak claim) → rate-limit tiers. |
| **Quota** | Burst (req/min + tokens/min, per user) + monthly USD budget (per org) in `BackendTrafficPolicy`; Redis-backed counters. |
| **Observability** | LGTM + Alloy; per-user Loki labels; dashboards-as-code; traces via Tempo. |
| **Secrets** | ESO + `ssegning-aws`; chart-owned ExternalSecrets; app-scoped vs platform-scoped split. |
| **TLS** | External: ACME HTTP-01 through the Gateway. Internal: `self-signed-ca` (Home Root CA), same trust model as redis-ha. |
| **Config portability** | `environments/<env>/` overlays; `global.namespacePodSecurity`; per-cluster LB annotations. |
| **Cost metadata** | Native Envoy `llmRequestCosts` extraction (Lua filter removed). |

---

## 9. Architecture decisions

The complete set lives in [`docs/adr/`](./adr/). The load-bearing ones:

| ADR | Decision |
|---|---|
| 0002 | Phoenix → Tempo for LLM traces |
| 0003 | `azp`-allowlist for SA-skip-OPA (OPA later removed entirely) |
| 0004 | grafana-operator external mode + dashboards-as-code |
| 0005 | Per-user attribution via Authorino headers → Loki labels |
| 0008 | Python dashboard generation (grafana-foundation-sdk) |
| 0011 | Canonical `x-oidc-*` downstream header contract |
| 0012 | `ai-models` orchestrator ApplicationSet split |
| 0014 | `librechart` split + opencode well-known |
| 0015 | OpenRouter-shape `/v1/models/info` catalog |
| 0016 | Fork bjw-s app-template/common locally |
| 0017 | Two-tier destinations (control in-cluster, workloads home-remote) |
| 0018 | Umbrella apps + `environments/` overlays |
| 0019 | Coder App-of-Apps orchestrator |
| 0020 | Observability App-of-Apps orchestrator |
| 0021 | Burst/budget/billing via dual-plane AuthConfigs |
| 0022 | Self-hosted GPU model federated into the gateway (cluster-local + Caddy auth-proxy; `homeCluster: true` exception to 0017) |
| 0028 | Cost-recovery pricing for owned-hardware models (€/hour TCO → weighted per-token; replaces 0022's flat $0) |
| 0029 | Self-hosted model as a plain Deployment (drop KServe/Knative) — always-on + Recreate on the dedicated GPU (supersedes 0022 serving mode) |
| 0030 | Model + Caddy auth-proxy co-located in ONE StatefulSet (proxy → model over localhost), via bjw-template (refines 0029) |

ADRs are immutable once Accepted; supersede with a new ADR.

---

## 10. Quality requirements

### Quality tree (scenarios)

| Quality | Scenario | Target | Status |
|---|---|---|---|
| **Performance** | 2000 sustained clients, 5000 peak, mixed streaming | p95 added gateway latency < 50 ms; no window stalls | Tuned (ADR-0021); needs validated load test (see plan §load) |
| **Scalability** | Traffic doubles | HPA scales data plane 3→20; Authorino HA | Configured |
| **Availability** | A model backend starts erroring | Outlier detection ejects it in ≤30 s; clients reroute | Configured |
| **Resilience** | Proxy rollout under load | No stream cut (60 s drain) | Configured |
| **Observability** | "What did org X spend on model Y this month?" | Answerable in Grafana from Mimir counters | Partially shipped (ADR-0021 metering) |
| **Security** | Forged/expired JWT | Rejected at Authorino; no backend reached | Enforced |
| **Cost** | Org exceeds monthly budget | Budget bucket denies; alert at 80% | Designed (ADR-0021) |
| **Operability** | Add a model | List edit in `ai-models` values → new Application | Mechanical |

---

## 11. Risks and technical debt

| Risk / debt | Impact | Mitigation / status |
|---|---|---|
| **Load test for 2000/5000 not yet re-run on Hetzner** | Capacity claims unvalidated | Plan §load — artillery suites exist (`plans/artillery/`) |
| **Keycloak `billing_plan` / org mappers not landed** | Plan falls back to `free`; org budget can't bucket | ADR-0021 external dependency |
| **`enforce-valid-key` commented out** | No API-key revocation enforcement at gateway | SA-skip marker preserved for mechanical re-enable |
| **Cilium deny-egress fragility** | New egress needs a CiliumNetworkPolicy or silent crashloop | Documented in cutover doc; overlay pattern established |
| **`ai-gitops` referenced but never created** | Stale ADRs (0010/0013) mislead | CLAUDE.md flags it; env overrides in-repo |
| **Single env (`prod`) only** | No staging to validate before deploy branch | Second env is a drop-in `environments/<env>/` |
| **Deploy branch is not `main`** | Drift risk; manual root Application | Intentional (tag-based deploys are the next step) |
| **LibreChat per-user gateway attribution impossible** | Coarse billing for chat users | By design (ADR-0021); handled inside LibreChat |
| **Mimir 6.0 deferred (breaking)** | Pinned on 5.x | Currency audit tracks it |
| **Mimir ring wedges if memberlist blocked at startup** | Distributor sees 0 ingesters (`InstancesCount <= 0`) → metrics silently dropped | **Guarded:** durable `allow-same-namespace` (observability-secrets child, wave -3) lands before stores + Mimir `memberlist.rejoin_interval: 1m` self-heals the residual ordering race (audit 2026-06-07) |

---

## 12. Glossary

| Term | Meaning |
|---|---|
| **AIGatewayRoute** | Envoy AI Gateway CR: a model route + provider mapping |
| **BackendTrafficPolicy** | Envoy Gateway CR enforcing rate limits, budget, circuit breaking on a route |
| **AuthConfig** | Authorino CR: per-host auth/identity/response rules |
| **Authorino** | Kuadrant ext_authz service verifying JWT and stamping headers |
| **App-of-Apps** | Orchestrator chart rendering child `Application` CRs directly |
| **Orchestrator + leaves** | Chart emitting an ApplicationSet that fans out to sibling leaf charts |
| **Umbrella Application** | Multi-source ArgoCD App: workload + app-scoped deps overlay |
| **home-remote** | Registered ArgoCD destination = the Hetzner workload cluster |
| **External / internal plane** | Public LB host vs in-cluster ClusterIP host on the same gateway |
| **`x-oidc-*`** | Canonical downstream identity headers (ADR-0011) |
| **LGTM** | Loki / Grafana / Tempo / Mimir observability stack |
| **Alloy** | Grafana's OTel-collector/agent (metrics scrape, log tail, OTLP) |
| **ssegning-aws** | The external `ClusterSecretStore` ESO reads from |
| **Plane plan / tier** | `free` / `pro` / `service` / `internal` rate-limit + budget tier |
