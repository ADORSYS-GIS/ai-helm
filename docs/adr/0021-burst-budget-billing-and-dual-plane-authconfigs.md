# ADR-0021: Burst control, budgeting & billing via dual-plane AuthConfigs

**Status:** Proposed
**Date:** 2026-06-04
**Deciders:** @stephane-segning

## Context

With OPA removed from the auth path (the `lightbridge-validation` metadata +
`enforce-valid-key` step, see the security-policies AuthConfig change of
2026-06-04), authorization is now "a valid Keycloak JWT = you're in our system
and may use the gateway." That leaves three *separate* concerns unaddressed for
both human users (opencode-like clients, LibreChat) and machine callers (GitHub
runners, k8s service accounts):

- **Burst control** — protect the gateway/backends from short-term spikes
  (seconds–minutes).
- **Budgeting** — cap monthly spend (already partly done: the per-model
  `BackendTrafficPolicy` enforces a monthly micro-USD limit using the AI
  gateway's token-cost metadata).
- **Billing / metering** — record actual per-caller consumption for
  dashboards/charge-back; never blocks.

Two facts shaped the design. (1) All three enforcement mechanisms key on the
same two request headers Authorino stamps from the JWT, so the design reduces to
"resolve account + plan correctly per caller, then define limits per plan."
(2) Per-user accounting only works if the **end-user identity reaches the
gateway** — opencode forwards each user's JWT, but LibreChat proxies its users
through a shared identity, so attributing LibreChat's individual users at the
gateway is impossible.

## Decision

### Two planes, one gateway, AuthConfig-per-host

The split is by **network reachability** (which maps onto trust), not human-vs-machine:

- **External plane** — `api.ai-v2.camer.digital` on the public LoadBalancer
  (ACME TLS). Serves internet callers: humans **and** remote service accounts
  (GitHub runners). Full Keycloak JWT required.
- **Internal plane** — a **raw k8s service DNS** name
  (`core-gateway-internal.converse-gateway.svc.cluster.local`) on a ClusterIP
  Service (never on the LB; in-cluster only, fronted by Cilium NetworkPolicy).
  Serves in-cluster services. The internal AuthConfig accepts **two credentials,
  chosen by client lifecycle** (no Keycloak either way):
  - **One-time tasks** (cron-jobs / Jobs) → their **Kubernetes ServiceAccount
    token**, validated via the apiserver **`kubernetesTokenReview`** (the cluster
    is the issuer); the projected token must carry the audience
    `core-gateway-internal`. A short job finishes before the token expires, so
    there's no rotation to manage and no sidecar.
  - **Long-running services** (LibreChat, …) → a **static apiKey** (Authorino
    `apiKey` identity matching a labeled Secret in `converse-gateway`,
    ESO-provisioned). No token rotation, no sidecar, no entrypoint hack. LibreChat
    keeps sending its existing `CONVERSE_OPENAI_API_KEY` unchanged.

  Both map to per-service identity for metering (`x-account-id` = the SA username
  or the apiKey Secret name, picked by a CEL `has(auth.identity.user)` check). TLS
  from the internal `self-signed-ca` ClusterIssuer (clients already trust the Home
  Root CA, same pattern as redis-ha).

Authorino indexes AuthConfigs by `Host`, so two AuthConfigs
(`kuadrant-policies-external`, `kuadrant-policies-internal`) coexist under one
Authorino instance and one gateway-wide `SecurityPolicy`. The kuadrant-policies
chart already loops `.Values.authConfigs`, so this is a values-only addition.
The model `AIGatewayRoute`s + the models-info route gain the internal hostname
and a second `parentRef` (the `api-internal` listener) so the same backends
serve both planes. **The per-host AuthConfig is the single policy-differentiation
point** — same routes, same `BackendTrafficPolicy`; each AuthConfig stamps
different descriptors that select different rate-limit tiers.

### Descriptor model (Authorino response headers)

| Caller (via plane) | `x-account-id` | `x-org-id` | `x-billing-plan` |
|---|---|---|---|
| Human (external) | `auth.identity.sub` | Keycloak org claim | `auth.identity.billing_plan` (default `free`) |
| Remote SA (external) | `auth.identity.azp` | — | `service` |
| In-cluster svc (internal) | `auth.identity.user.username` (the SA: `system:serviceaccount:<ns>:<name>`) | — | static `internal` |

`x-billing-plan` is a CEL expression: `azp ∈ serviceAccountClients ? "service"
: (auth.identity.billing_plan or "free")` on the external AuthConfig; a static
`"internal"` on the internal one. The plan **lives in Keycloak** (a `billing_plan`
protocol-mapper claim, sourced from a user attribute/group) — consistent with
"authz moved to Keycloak." Org likewise comes from a Keycloak claim. The
ADR-0011 `x-oidc-*` contract is unchanged.

### Three rule families in the per-model `BackendTrafficPolicy`

1. **Burst, requests/min (static)** — `[x-account-id Distinct, x-billing-plan,
   x-ai-eg-model]`, `unit: Minute`, `cost.request.number: 1`. Per **user**.
2. **Burst, tokens/min (dynamic)** — same selectors, `unit: Minute`,
   `cost.response.from: Metadata` (TotalToken, extracted via an `llmRequestCosts`
   entry on the `AIGatewayRoute`). Per **user**.
3. **Budget, monthly micro-USD** — `[x-org-id Distinct, x-billing-plan,
   x-ai-eg-model]`, `unit: Month`, `cost.response.from: Metadata` (the existing
   micro-USD cost). Per **org**. **Rendered only for plans with a
   `monthlyBudgetUsd`** — `service`/`internal` get none → uncapped budget,
   burst-only.

Tiers live statically in `charts/ai-models/values.yaml` (`rateLimitBudgeting`),
per-model overrides as today:

```yaml
plans:
  free:     { monthlyBudgetUsd: 30,  burst: { requestsPerMin: 20,  tokensPerMin: 50000   } }
  pro:      { monthlyBudgetUsd: 200, burst: { requestsPerMin: 120, tokensPerMin: 400000  } }
  service:  {                        burst: { requestsPerMin: 600, tokensPerMin: 2000000 } }  # uncapped
  internal: {                        burst: { requestsPerMin: 600, tokensPerMin: 2000000 } }  # uncapped
```

### Billing / metering (no enforcement)

Alloy converts the Envoy access logs (which already carry `x-oidc-*` identity +
token cost, ADR-0005/0011) into Mimir counters
`llm_cost_micro_usd_total{user,org,plan,model}` and `llm_tokens_total{…}` →
a billing dashboard + an alert at 80% of each org's monthly budget. Redis already
holds live month-to-date consumption if a "remaining budget" client surface is
wanted later.

### LibreChat

LibreChat takes the **internal plane** — billed/limited as one trusted service
(`internal` tier, uncapped, burst-only, metered under its own `azp`). Per-user
budgeting for LibreChat's humans is LibreChat's own concern (it keeps per-user
balances). opencode users take the external plane with their own JWT → real
per-user/per-org accounting. This makes the attribution limitation a *design
choice*, not a leak.

## Consequences

- **Positive.** One policy-differentiation point (per-host AuthConfig); the
  rate-limit chart and routes stay generic. Burst/budget compose (Envoy denies on
  any exhausted bucket). The LibreChat attribution problem is structurally
  resolved. Internal traffic stops hairpinning through the public LB. SAs/internal
  services are uncapped but still burst-protected and fully metered.
- **External dependencies (not chart-only).**
  - **Keycloak** (`charts/keycloak-baseline` + realm): protocol mappers emitting
    `billing_plan` and an org claim. Without them, plan falls back to `free` and
    org-budget bucketing can't key per-org.
  - **Internal cert + Service**: an internal-CA `Certificate` (SAN = the svc-DNS
    FQDN) and a ClusterIP Service selecting the Envoy proxy pods.
  - **NetworkPolicy**: a Cilium policy confining the internal plane to allowed
    in-cluster namespaces.
- **Negative / watch-outs.** More moving parts (two AuthConfigs, an extra
  listener, token metadata extraction). `tokensPerMin` requires the AIEG
  `llmRequestCosts` token extraction to be correct. Monthly budget is now keyed on
  **org**, not user — a missing org claim means no budget bucket (fails open on
  budget; burst still applies). Static plan defaults to `free` until Keycloak
  mappers land.

## Alternatives considered

- **Single AuthConfig / single host.** Rejected — can't differentiate trust or
  policy by entry point, and forces per-user attribution on LibreChat (impossible
  with its shared identity).
- **Keep OPA for plan/account resolution.** Rejected/deferred — authz moved to
  Keycloak; OPA is reserved for future *burst control* logic (not needed yet),
  and re-adding it reintroduces the `lightbridge-opa-auth`/backend dependency that
  just caused a gateway outage.
- **Per-user budget at the gateway for LibreChat.** Rejected — LibreChat's shared
  identity makes gateway-side per-user attribution impossible; handle it inside
  LibreChat.
- **Network-trust (no auth) on the internal plane.** Rejected — loses per-service
  identity, so internal usage can't be metered/attributed.
- **Friendly internal FQDN (`api.internal.…`) via CoreDNS rewrite.** Rejected for
  now — raw k8s service DNS resolves natively with zero extra DNS config; revisit
  if a friendlier name is wanted.
- **Plaintext internal listener.** Rejected — internal-CA TLS is consistent with
  the existing redis-ha trust model and keeps in-cluster traffic encrypted at low
  cost.
