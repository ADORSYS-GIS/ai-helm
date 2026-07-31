# Shared cross-model monthly budget (#532)

**Status:** live since 2026-07-08 (EG v1.8.2, cutover PR #616).
**TL;DR:** the per-user monthly budget used to be silently enforced **per model**; it is now **one shared counter per (user, plan) across all models**, via a `shared: true` rate-limit rule on the gateway-wide BackendTrafficPolicy that per-model policies merge with.

## The bug

Every model gets its own HTTPRoute + a route-scoped `BackendTrafficPolicy` (charts/ai-model). The monthly-budget rule's `clientSelectors` were model-agnostic — `(x-account-id: Distinct, x-billing-plan: Exact)` — so it *looked* like one bucket per user per plan.

It wasn't. **Envoy Gateway always injects an extra scoping dimension you never wrote: the route identity.** From the `RateLimitRule` API doc:

> If the policy targets a Gateway, the rule applies to each Route of the Gateway. Please note that **each Route has its own rate limit counters.**

So the real bucket key was `(route, account, plan)` — one budget **per model**. Confirmed live in Redis: one account held **29 separate budget counters**, i.e. an effective cap of `$budget × models-used`. Removing the `x-ai-eg-model` header selector did nothing, because the model dimension was never a selector — it came from the route.

`clientSelectors` are **dimensions**, not **scope**. The scope is auto-injected, and only `shared: true` changes it.

## The fix

Three changes, all `BackendTrafficPolicy`-level (Gateway/routes/SecurityPolicy untouched):

1. **Gateway-wide BTP** (`charts/core-gateway`, `BackendTrafficPolicy/core-gateway` in `converse-gateway`): gained a `rateLimit.global` block with one budget rule per capped plan, each marked **`shared: true`**. `shared` swaps the auto-injected scoping descriptor from *route identity* to *policy identity* — and since the rule lives on exactly one policy, that means exactly one bucket per (account, plan).

   ```yaml
   rateLimit:
     type: Global
     global:
       rules:
         - clientSelectors:
             - headers:
                 - { name: x-account-id, type: Distinct }
                 - { name: x-billing-plan, type: Exact, value: "free" }
           limit: { requests: 15000000, unit: Month }   # micro-USD
           shared: true                                  # ← the lever
           cost:
             request: { from: Number, number: 0 }
             response:
               from: Metadata
               metadata: { namespace: io.envoy.ai_gateway, key: llm_custom_total_cost }
   ```

2. **Per-model BTPs** (`charts/ai-model`): dropped their `unit: Month` budget rule, and added
   - `mergeType: StrategicMerge` — EG is closest-wins/no-merge by default, so without this each route-scoped BTP would *replace* the gateway BTP on its route and wipe the shared budget off it;
   - `retry: { numRetries: 0 }` — merging inherits the gateway policy's retry, and model routes must not retry LLM calls.

   Burst rules (req/min, tokens/min) stay per-model on these policies. Everything is gated by `sharedBudget.enabled` (ai-models umbrella, threaded to every child) paired with `backendTrafficPolicy.monthlyBudget.enabled` (core-gateway) — **flip both together**; per-model behaviour returns if both are off.

3. **Envoy Gateway v1.8.1 → v1.8.2** (`charts/apps` `aii-eg` targetRevision). **Hard prerequisite:** on 1.8.0/1.8.1, bug [envoyproxy/gateway#9244](https://github.com/envoyproxy/gateway/issues/9244) drops the per-request cost on rules that are both `shared: true` **and** cost-bearing — the counter ticks +1/request instead of +micro-USD, making the budget effectively unlimited. Fixed in v1.8.2 ([PR #9245](https://github.com/envoyproxy/gateway/pull/9245)). Never enable the shared budget on ≤1.8.1.

## Counter-key anatomy (how to verify / test)

Lyft ratelimit composes the Redis key as `<domain>_<generic-key>_<header-descriptors…>_<window-epoch>` (built in EG's `internal/xds/translator/ratelimit.go`):

| Piece | Non-shared rule | Shared rule |
|---|---|---|
| domain | listener name | `<ns>/<policy>` |
| generic key (scope) | route identity (`…/converse/<model>/rule/…`) | `<ns>/<policy>/rule/<idx>` |
| `Distinct` header | live value in the key (the account UUID) | same |
| `Exact` header | position only (`rule-N-match-M`); the literal value is encoded by *which rule* matched | same |
| window | `floor(now / unit_seconds) × unit_seconds` (Month = 2592000) | same |
| `x-billing-period` (ADR-0111, since 2026-07-31) | live value in the key (the calendar `YYYY-MM` string, e.g. `2026-08`) | same |

Live examples:

```
OLD (per-model):  …core-gateway/api-https_httproute/converse/glm-5/rule/0/…_rule-2-match-0_<ACCOUNT>_rule-2-match-1_<WINDOW>
NEW (shared, pre-ADR-0111):  converse-gateway/core-gateway_converse-gateway/core-gateway/rule/0_rule-0-match-0_<ACCOUNT>_rule-0-match-1_<WINDOW>
NEW (shared, ADR-0111+):     converse-gateway/core-gateway_converse-gateway/core-gateway/rule/0_rule-0-match-0_<ACCOUNT>_rule-0-match-1_<PERIOD>_<WINDOW>
```

⚠️ **ADR-0111: the `unit: Month`/`<WINDOW>` epoch segment above is NOT a
calendar month** — it's a fixed 2,592,000-second (30-day) rolling bucket
anchored to the Unix epoch, confirmed against Envoy Gateway's own translator
source. It drifts off the real calendar by ~5 days/year and no Redis
operation can move that boundary (it's a pure function of wall-clock time).
Since 2026-07-31, a Lua `EnvoyExtensionPolicy`
(`charts/core-gateway/templates/envoyextensionpolicy-billing-period.yaml`)
stamps `x-billing-period: <UTC YYYY-MM>` on every request, and every
`unit: Month` rule keys on it as an extra `Distinct` header — so a **new**
key (with a new `<PERIOD>` segment) is used automatically starting every 1st
of the month, regardless of where the old 30-day `<WINDOW>` epoch happens to
land. Pre-fix keys (no `<PERIOD>` segment) simply stop being written and age
out on their existing TTL — no migration needed. See ADR-0111 for the full
design and rationale.

The only structural difference is the scope segment: route identity (contains the model) → policy identity (no model). On the gateway policy, `rule/0` = free budget, `rule/1` = pro.

To see keys without reverse-engineering: read the generated ratelimit ConfigMap (`kubectl -n envoy-gateway-system get cm -l app.kubernetes.io/name=envoy-ratelimit -o yaml`) — it lists every domain/descriptor verbatim.

**Testing enforcement:** find the account's *shared* key (no `/converse/<model>/` segment), inflate it past the limit (`redis-cli` against `redis-ha` in `redis-system`, TLS + auth), then call **any** model with that account → 429. Inflating an old per-model key proves nothing — those counters are no longer consulted (they expire on their own TTL; historical per-model spend did not carry over at cutover).

**Verifying the #9244 fix is active:** the budget rule's request-cost is `number: 0`, so a non-zero counter can *only* come from the response micro-USD cost. Any shared counter > 0 after real traffic proves cost-charging works.

## Fallback: manual reset for the current cycle (only if ADR-0111 hasn't deployed yet)

If a calendar-month boundary passes before the ADR-0111 chart change has
merged and deployed, the new `x-billing-period`-keyed counters won't exist yet
and the old key keeps accumulating against the drifting 30-day window. As a
one-time fallback (not needed once ADR-0111 is live — every month after that
resets itself automatically), scope a manual Redis delete to *only* the
monthly-budget rule keys, run a few minutes after 00:00 UTC on the 1st (not
before, or it zeroes legitimate remaining spend early):

```bash
# Read-only first: confirm the live key shape before deleting anything —
# it has changed shape before (this doc's own OLD/NEW history above).
redis-cli --tls --cacert /etc/redis-ca/ca.crt \
  -h redis-ha-haproxy.redis-system.svc.cluster.local -p 6379 \
  --scan --pattern 'converse-gateway/core-gateway*'

# Scoped delete: this domain is structurally exclusive to the plan-budget
# rules (burst/req-per-min counters live on the separate per-model route
# domain, `.../converse/<model>/...`, never here) — so this pattern cannot
# accidentally catch a burst key. It also never touches LibreChat's session
# keys (distinct `librechat-prod-v2*` prefix, same redis-ha instance).
redis-cli --tls --cacert /etc/redis-ca/ca.crt \
  -h redis-ha-haproxy.redis-system.svc.cluster.local -p 6379 \
  --scan --pattern 'converse-gateway/core-gateway_converse-gateway/core-gateway/rule/*' \
| xargs -r -n1 redis-cli --tls --cacert /etc/redis-ca/ca.crt \
  -h redis-ha-haproxy.redis-system.svc.cluster.local -p 6379 DEL
```

No model-disable window is needed for this — it's a live, near-instant key
deletion, not a data migration; worst case is one in-flight request
re-checking a freshly-zeroed counter.

## Knock-on effects / gotchas

- **`prometheus-redis-exporter`** (ai-helm-values) parses the *old* per-model key shape (`…/converse/<model>/…`, `rule-2`/`rule-7` indices). The shared keys don't match those regexes — the quota dashboard needs re-pointing at the new key shape (open follow-up). ADR-0111 adds a further `x-billing-period` segment on top of this same open gap — both need addressing together when that dashboard work happens.
- The dormant per-model `monthlyBudgetUsd` in `charts/ai-models` is kept in sync with the live core-gateway value so a flag rollback keeps the same cap.
- Budget changes apply to the **current** month window immediately — lowering the cap 429s anyone already past it on their next request.

## History

| Date | Change |
|---|---|
| 2026-07-07 | #598 — interim band-aid: per-model free cap $50 → $30 |
| 2026-07-08 | #606 — shared-budget machinery, flag-gated OFF |
| 2026-07-08 | #607 — EG v1.8.1 → v1.8.2 (#9244 prerequisite) |
| 2026-07-08 | #616 — cutover: both flags ON; verified live (shared keys, µ$ charging) |
| 2026-07-08 | #623 — free tier set to $15 shared |
| 2026-07-31 | ADR-0111 — `x-billing-period` calendar marker folds into every `unit: Month` key; fixes the 30-day-vs-calendar-month drift permanently |
