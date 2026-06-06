# Architectural shift: `main` → `claude/magical-bohr-390242`

> **Scope.** This document describes the *full* architectural shift represented
> by the diff `main..claude/magical-bohr-390242` (≈393 files, +21.6k/−7.9k).
> It is the narrative companion to [`docs/architecture.md`](./architecture.md)
> (the steady-state map) and the [ADR index](./adr/README.md) (the per-decision
> "why"). Read this when you need to understand *what changed and why the
> platform looks different now*, not just how it is wired today.

**Status:** descriptive (the shift has shipped to the deploy branch).
**Date:** 2026-06-04 · **Maintainer:** @stephane-segning

---

## 1. One-sentence summary

The platform moved from a **single-cluster Linode/LKE deployment with in-repo
infrastructure, a LiteLLM proxy, OPA-based authorization, and Phoenix tracing**
to a **two-cluster Hetzner topology where ai-helm owns only AI workloads**,
infrastructure is externalised to companion repos, the Envoy AI Gateway is the
sole inference data plane (LiteLLM gone), Keycloak JWT is the authorization
boundary (OPA removed), and observability is a self-hosted Grafana LGTM stack
(Loki/Grafana/Tempo/Mimir) with per-user attribution and dashboards-as-code.

If you remember one framing: **ai-helm stopped being a "whole platform" repo and
became an "AI workloads" repo that consumes a platform owned elsewhere.**

---

## 2. The eight shifts

| # | Shift | From (`main`) | To (`magical-bohr`) | ADR / evidence |
|---|---|---|---|---|
| 1 | **Cluster & infra ownership** | Single LKE cluster, infra in-repo | Two clusters (ArgoCD on Talos `admin@homeos`, workloads on Hetzner k3s `home-remote`); infra in `home-os` + `hetzner-k8s` | ADR-0017, `2026-hetzner-cutover.md`, CLAUDE.md |
| 2 | **Inference data plane** | LiteLLM proxy (`models-proxy`) + Envoy | Envoy AI Gateway only; LiteLLM removed | commit `c366c4c`, `ai-model`/`ai-models` charts |
| 3 | **Authorization model** | Authorino → OPA (lightbridge) per request | Keycloak JWT *is* authz; OPA dropped from the path | ADR-0003, ADR-0021, commits `8c601cc`/`2504a85` |
| 4 | **Observability** | Arize Phoenix traces, ad-hoc dashboards | LGTM (Loki/Grafana/Tempo/Mimir) + Alloy; dashboards-as-code from Python | ADR-0002/0004/0005/0008, App-of-Apps ADR-0020 |
| 5 | **GitOps structure** | Flat ArgoCD apps, vendored bjw chart | Two-tier destinations, umbrella apps + `environments/` overlays, App-of-Apps orchestrators, forked bjw library | ADR-0016/0017/0018/0019/0020 |
| 6 | **Secrets** | `ai-ops-secrets` "secrets" app pushes everything | Chart-owned `ExternalSecret`s via `ssegning-aws`; secrets app retired | commits `0b98066`/`aea3842`/`02bd855` |
| 7 | **Scale & resilience** | Envoy pinned at 2 replicas, placeholder resources | Data-plane HPA 3→20, HTTP/2 multiplexing tuned for 2000+ clients, circuit-breaking, outlier detection | commits `ab39aed`/`d3257b6`, ADR-0021 |
| 8 | **Identity & domain** | `ai.camer.digital`, OPA-issued keys | `ai.camer.digital`, dual-plane gateway (external + internal), Keycloak-claim billing plans | commit `bbbe3ec`, ADR-0021 |

The rest of this doc takes each shift in turn.

---

## 3. Shift 1 — From one cluster to two; from owning infra to consuming it

**Before.** ai-helm deployed onto a single Linode LKE cluster (`lke560142-ctx`
was hard-coded in templates). The repo carried cert-manager, the External
Secrets Operator, Redis, Traefik, CloudNativePG, and Barman as in-repo charts —
it was the platform.

**After.** Two clusters with two kubeconfigs:

- **ArgoCD control plane** runs on a separate Talos cluster, context
  `admin@homeos`. All `Application`/`ApplicationSet` CRs live there (ns
  `argocd`).
- **Workloads** run on Hetzner k3s, the registered ArgoCD destination
  `home-remote`.

Everything platform-shaped was **externalised** and is now only *referenced* by
name:

- cert-manager + ClusterIssuers (`cert-home-cert-http`, `self-signed-ca`,
  `cert-cloudflare`) → `home-os` (commit `932605b`).
- External Secrets Operator + the `ssegning-aws` ClusterSecretStore → external
  (`f4c42ce`).
- `redis-ha` → `home-os`, TLS-only, consumed over `rediss://` (`6d0eec0`,
  `ac9c698`).
- Traefik, CloudNativePG, Barman → external (`dc8a59b`).
- OpenTelemetry Operator → external; this repo only ships
  `OpenTelemetryCollector` CRs.

This is the **central architectural inversion**: the render-time guard
`<chart>.argocd.destinationClusterRef` now *hard-fails* if a workload resolves to
the in-cluster handle (ADR-0017). Control objects target in-cluster; workloads
target `home-remote`. The magic cluster string is gone.

**Why it matters operationally.** The Hetzner cluster runs **Cilium with a
default-deny-egress baseline**. Every namespace has a manual `allow-dns`
NetworkPolicy and nothing else by default, so any pod that reaches the API
server or external object storage needs an *additive* `CiliumNetworkPolicy`
(`toEntities: [kube-apiserver]` or `toFQDNs`). A plain `NetworkPolicy` `ipBlock`
does **not** match on Cilium — this caused several crash-loops during cutover
(grafana-operator, kube-state-metrics, mimir/loki/tempo egress). The full
narrative is `docs/2026-hetzner-cutover.md`.

---

## 4. Shift 2 — LiteLLM is gone; Envoy AI Gateway is the only data plane

**Before.** Requests to a model could traverse LiteLLM (`models-proxy`), which
did provider routing, cost tracking, and rate limiting in one Python process —
plus a Lua filter on Envoy forwarding cost metadata.

**After.** LiteLLM is removed entirely (`c366c4c`, "unused"), and the Lua
cost-forwarding filter is gone (`ded626a` on main, carried forward). The Envoy AI
Gateway owns the whole inference path:

- **`charts/ai-models`** is now an **orchestrator** (ADR-0012): it emits one
  `ApplicationSet` that fans out to one Application per model, each rendering
  `charts/ai-model` (singular).
- **`charts/ai-model`** renders per-model `AIGatewayRoute` +
  `BackendTrafficPolicy` (the budget/rate-limit enforcer).
- **`charts/ai-models-backends`** owns the `AIServiceBackend` / `Backend` /
  `BackendSecurityPolicy` / `BackendTLSPolicy` and now provisions backend API
  keys via chart-owned `ExternalSecret`s (`0b98066`), with independent keys per
  backend (`b5d4042`).
- Token-cost metadata is unified on a single key and forwarded by the gateway's
  native `llmRequestCosts` extraction, not Lua.

Net effect: one fewer hop, one fewer language in the hot path, and cost/rate
enforcement moved from a Python sidecar into Envoy's `BackendTrafficPolicy`.

---

## 5. Shift 3 — Authorization collapsed onto the Keycloak JWT

**Before.** Authorino verified the JWT, then called **lightbridge-opa** for
project/account/api-key validation (`enforce-valid-key`). OPA was an inline
authorization dependency on every request.

**After.** "A valid Keycloak JWT = you're in our system and may use the gateway"
(`8c601cc`, ADR-0021 context). OPA was dropped from the AuthConfig; the
`enforce-valid-key` step is commented out (SA-skip marker preserved for
mechanical re-enable). Defaults for `billing_plan`/`organization` are supplied
via CEL when the claims are absent (`2504a85`).

Why: the OPA/lightbridge dependency had caused a gateway outage, and authz
semantics were better expressed as Keycloak claims. The decision deliberately
*reserves* OPA for future burst-control logic rather than account resolution.

The canonical downstream header contract (`x-oidc-*`, ADR-0011) is unchanged —
Authorino still stamps identity headers; they just aren't gated on an external
metadata call anymore.

---

## 6. Shift 4 — Observability became a first-class, self-hosted LGTM stack

**Before.** Arize Phoenix for LLM traces; a `-usage` collector; dashboards
managed ad hoc.

**After.** A full LGTM stack, all GitOps:

- **Tempo replaces Phoenix** (ADR-0002, `docs/migrations/phoenix-to-tempo.md`).
- **Mimir / Loki / Tempo** back metrics / logs / traces; **Alloy** is the
  collector (DaemonSet, ServiceMonitor/PodMonitor discovery, OTLP receiver, pod
  log tail).
- **grafana-operator in external mode** (ADR-0004) renders dashboards as
  `GrafanaDashboard` CRs.
- **Dashboards-as-code from Python** (`tools/dashboards/`, ADR-0008) using
  `grafana-foundation-sdk`, with a CI drift check
  (`.github/workflows/dashboards-drift.yml`).
- **Per-user attribution** (ADR-0005): Envoy access logs carry the `x-oidc-*`
  identity; Alloy promotes `user_id` + `azp` to Loki labels; dashboards break
  down requests/latency/tokens/cost per user (`docs/per-user-observability.md`).
- The whole stack was factored into an **App-of-Apps orchestrator**
  (`charts/observability`, ADR-0020) carrying a `podSecurityEnforce: privileged`
  for the namespace (Alloy/node-exporter need hostPath).
- Stores moved to **Hetzner Object Storage** (`df3dafd`), region `us-east-1`,
  alphanumeric Mimir `storage_prefix`.

This is the foundation the OpenAI-alternative plan builds on (see
[`plans/openai-alternative-plan.md`](../plans/openai-alternative-plan.md)).

---

## 7. Shift 5 — GitOps grew real structure

Five ADRs reshaped how charts compose:

- **ADR-0016 — fork bjw's app-template + common library locally.** The upstream
  `bjw-s` common library was vendored into `charts/bjw-common` (and
  `bjw-template`) so renders don't depend on a fragile OCI dependency
  (`e8b0d2c`).
- **ADR-0017 — two-tier destinations.** Control objects in-cluster; workloads
  `home-remote`; render-time guard hard-fails violations.
- **ADR-0018 — umbrella Applications + `environments/` overlays.** A workload
  and its app-scoped prerequisites (ingress `Certificate`, per-app
  `ExternalSecret`) sync as one multi-source Application. Per-env knobs
  (`clusterIssuer`, `secretStore`, `ingressClass`, `storageClass`, `domainBase`)
  live in `environments/<env>/cluster.yaml` and are kustomize-patched into the
  dep CRs. Only `environments/prod/` (Hetzner) exists today; a second env is a
  sibling directory. A latent bug where the custom-`syncPolicy` branch dropped
  the `syncPolicy:` wrapper (≈13 apps silently running manual sync) was fixed
  here (`cb342d7`).
- **ADR-0019 / ADR-0020 — App-of-Apps orchestrators** for `coder` (db + app) and
  `observability` (10 components + secrets), where children are fixed and
  heterogeneous (local + upstream charts with large inline values) and an
  ApplicationSet List generator handles them poorly.
- The ArgoCD app prefix was renamed `ai-` → `aii-` (`3d62da8`), and the giant
  `charts/apps/values.yaml` shrank dramatically (≈2562 lines removed) as logic
  moved into umbrellas/overlays.

There is a documentation honesty note worth carrying: **`ai-gitops` was never
created.** Older ADRs (0010/0013) reference it as the planned deployment-state
repo; in reality per-env overrides live in *this* repo under `environments/`,
and the root `ai-apps-v2` Application is applied manually (`4d7f3dc`, CLAUDE.md).

---

## 8. Shift 6 — Secrets ownership moved into the charts

**Before.** A central `ai-ops-secrets` "secrets" Application pushed every Secret.

**After.** Each chart owns the `ExternalSecret`s for the secrets *it* needs,
referencing the external `ssegning-aws` ClusterSecretStore by name, and the
central secrets app was retired (`aea3842`). LibreChat, Grafana, the AI backends,
the Envoy ratelimit Redis auth, and the apprise channels all pull their own keys
(`02bd855`, `0b98066`, `b98da37`, `4b82830`). The ownership split is explicit:
umbrellas own **app-scoped** secrets/certs; **platform/shared** secrets (S3,
Keycloak, redis-auth) stay external. The store is never defined here.

---

## 9. Shift 7 — Scale & resilience tuned for 2000+ concurrent clients

This is the shift the OpenAI-alternative plan extends. Two commits did the work:

- **`ab39aed` — `ClientTrafficPolicy` for 2000+ HTTP/2 clients.** HTTP/2
  multiplexing (`maxConcurrentStreams: 1000`), large flow-control windows (1Mi
  stream / 16Mi connection), `connectionLimit: 100000`, long idle timeouts and
  TCP keepalive for laptops behind NAT and long-lived SSE/token streams.
- **`d3257b6` — scale + harden the client path (tiers 1–3):**
  - **Data plane:** `envoyProxy.hpa` min 3 / max 20 at 60% CPU (supersedes the
    static 2-replica pin), real resources (1 CPU/512Mi → 4 CPU/2Gi), topology
    spread, 60s drain so streams aren't cut on rollout.
  - **Upstream:** `BackendTrafficPolicy` with `LeastRequest` LB (better tail
    latency for variable-duration streams), generous circuit breakers, passive
    outlier detection (eject after 5 consecutive 5xx), upstream keepalive, Gzip.
  - **Auth:** Authorino `replicas: 2` (HA — every request hits it), JWKS/OIDC
    config cached with `ttl: 3600`.

The Envoy AI Gateway itself was bumped 0.5.0 → 0.6.0 (`b3e9b89`).

---

## 10. Shift 8 — Dual-plane gateway, Keycloak-claim billing, `ai-v2` domain

**Before.** `ai.camer.digital`, OPA-issued API keys, single entry point.

**After (ADR-0021, Proposed → partially shipped):**

- Domain switched to `ai.camer.digital` (`bbbe3ec`).
- **Two planes, one gateway, AuthConfig-per-host:**
  - **External plane** — `api.ai.camer.digital` on the public LB (ACME TLS),
    full Keycloak JWT, per-user/per-org accounting (opencode forwards each user's
    JWT).
  - **Internal plane** — `core-gateway-internal.…svc.cluster.local` on a
    ClusterIP (internal-CA TLS, Cilium-confined), service-account JWT only.
    LibreChat takes this plane and is billed as one trusted service (its shared
    identity makes gateway-side per-user attribution structurally impossible —
    so it's a *design choice*, not a leak).
- **Billing plan lives in Keycloak** (a `billing_plan` claim) and selects a
  rate-limit tier (`free`/`pro`/`service`/`internal`); burst (req/min +
  tokens/min) and monthly USD budget are enforced in the per-model
  `BackendTrafficPolicy`; metering (never blocks) is Alloy → Mimir counters →
  Grafana.

This is the direct on-ramp to "concrete OpenAI alternative" — it is the billing
and quota spine. See the plan doc for how it's completed.

---

## 11. Smaller-but-notable changes

- **OpenRouter-shape `/v1/models/info` catalog** (`charts/ai-models-info`,
  ADR-0015) so opencode and OpenAI-compatible clients can fetch context length,
  pricing, modalities, and capability flags; per-model `context_length` capped at
  400k, grounded in backend specs (`44e688b`, `df7eb...`).
- **opencode well-known split** (`charts/librechat-opencode-wellknown`,
  ADR-0014) — proprietary `.well-known/opencode` discovery, not OIDC.
- **HTTP→HTTPS redirect that keeps the ACME HTTP-01 solver on :80**
  (`ab21aca`), with `api-https` TLS issued via an in-chart ns ACME Issuer
  through the Gateway (`de628ae`).
- **Removed:** adminer (`0804a6f`), librechat-admin-panel (`0b5d416`), the
  deprecated pg_dump backup path, Gemini patch workaround docs.
- **CI:** `release-helm-charts.yml` (chart releases) and `dashboards-drift.yml`
  added.

---

## 12. What did *not* change (and is easy to assume did)

- The `x-oidc-*` downstream header contract (ADR-0011) — same names.
- LibreChat as the human browser UI; Keycloak as the IdP (`auth.verif.fyi`,
  realm `camer-digital`).
- The orchestrator-plus-leaves pattern for `ai-models`/`librechart` — extended,
  not replaced.
- GitOps-via-ArgoCD as the only deploy mechanism. `helm template` + `helm lint`
  remain the verification cycle (no app build/test loop).

---

## 13. Reading order for someone new to the shift

1. This document (the *what changed*).
2. `docs/architecture.md` (the steady-state map).
3. `docs/2026-hetzner-cutover.md` (the operational cutover log + live gotchas).
4. ADRs in dependency order: 0016 → 0017 → 0018 → 0019/0020 → 0021.
5. [`docs/arc42.md`](./arc42.md) for the formal architecture description.
6. [`plans/openai-alternative-plan.md`](../plans/openai-alternative-plan.md) for
   where this is heading.
