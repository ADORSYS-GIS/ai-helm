# ADR-0005: Propagate per-user identity via Authorino response headers → Loki labels

**Status:** Accepted
**Date:** 2026-05-24
**Deciders:** @stephane-segning

## Context

The Envoy AI Gateway access log already carries useful per-request fields
(model, provider, tokens, cost, latency, request id). What it does NOT carry
is who made the request. Authenticated identity stops at Authorino — by
the time the gateway emits its access log, the JWT has been validated and
discarded.

We want dashboards that break down by user (volume per user, latency per
user, token spend per user, error rate per user) for both human callers
and service accounts. That requires the user identity flowing into one of
our telemetry signals — and given the access log is already structured JSON
exported via OTLP, the cheapest path is to make Authorino expose identity
as response headers, and let the access log include them.

Three options for getting user identity into telemetry were considered:
1. An **extProc** step on the gateway that, after Authorino, copies JWT
   claims into OTLP span attributes + Envoy stat labels.
2. An **Envoy Lua filter** that pulls claims from the validated JWT.
3. **Authorino response headers** picked up by the existing access-log JSON
   sink and promoted to Loki labels in Alloy.

Option 3 requires zero new components — it extends configuration that
already exists.

## Decision

Authorino's AuthConfig `response.success.headers` emits three headers on
every successful auth:
- `x-cd-user-id` ← `auth.identity.sub` (Keycloak user UUID)
- `x-cd-user-name` ← `auth.identity.preferred_username` (display only)
- `x-cd-azp` ← `auth.identity.azp` (client_id)

The Envoy access-log JSON sink adds the headers as `user_id`, `user_name`,
`azp` fields. Alloy's OTel→Loki pipeline gains a
`loki.process "ai_gateway_user_attribution"` stage that promotes `user_id`
and `azp` to Loki labels. `user_name` stays in the body — too
high-cardinality for a label.

Headers are unconditional (set for SAs and humans alike). SAs get the
Keycloak-internal SA user UUID as `sub` and `service-account-<clientid>`
as `preferred_username`.

## Consequences

**Positive**
- Per-user dashboards work for every authenticated request, human or SA.
- No new pods, no new dependency. The change is three small edits across
  three files (Authorino values, Envoy access-log JSON, Alloy config).
- Granularity is right for current scale (≤ a few thousand users → fine
  for Loki cardinality).
- Composable with the SA-skip allowlist (ADR-0003): dashboards can split
  human vs SA via the `azp` label.

**Negative**
- `user_id` cardinality scales with the user count. Fine today; documented
  fallbacks (drop label, hash to bucket, separate Loki tenant) for when it
  isn't.
- Tempo traces are NOT labeled by user. Per-user dashboards live entirely in
  Loki. Tempo traces still surface the JWT claims if the spans are sampled,
  but querying is via TraceQL field filters, not labels.

**Neutral / follow-ups**
- If a per-user metrics view in Mimir becomes a need (e.g. cost-per-user
  recording rules at minutely granularity), the right place to add it is
  the gateway's metric attributes — likely via the same extProc step that
  was rejected here, scoped to a small set of bounded labels. Defer until
  needed.

## Alternatives considered

- **extProc copies JWT claims into OTLP spans + Envoy stat labels** —
  cleanest semantically (every signal — logs, traces, stats — gets the same
  labels). Rejected for cost: adds a new container, new code path, new
  failure mode. The access-log path satisfies the current requirement
  with less surface.
- **Envoy Lua filter** — no new container, but Lua is brittle, only labels
  Envoy stats (not full OTLP spans), and harder to test. Rejected.
- **All three** — belt and suspenders. Rejected today; the access-log
  path alone is sufficient. Can layer extProc later if Tempo per-user
  filtering becomes a hard requirement.

## Related

- Commit: `48e8526`
- Doc: `docs/per-user-observability.md` (end-to-end flow diagram, label
  cardinality budget, SA semantics, troubleshooting matrix, LogQL recipes)
- Files touched: `charts/apps/values.yaml` (security-policies AuthConfig +
  Alloy extraConfig), `charts/core-gateway/templates/envoy-proxy.yaml`
  (access-log JSON)
