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

Live examples:

```
OLD (per-model):  …core-gateway/api-https_httproute/converse/glm-5/rule/0/…_rule-2-match-0_<ACCOUNT>_rule-2-match-1_<WINDOW>
NEW (shared):     converse-gateway/core-gateway_converse-gateway/core-gateway/rule/0_rule-0-match-0_<ACCOUNT>_rule-0-match-1_<WINDOW>
```

The only structural difference is the scope segment: route identity (contains the model) → policy identity (no model). On the gateway policy, `rule/0` = free budget, `rule/1` = pro.

To see keys without reverse-engineering: read the generated ratelimit ConfigMap (`kubectl -n envoy-gateway-system get cm -l app.kubernetes.io/name=envoy-ratelimit -o yaml`) — it lists every domain/descriptor verbatim.

**Testing enforcement:** find the account's *shared* key (no `/converse/<model>/` segment), inflate it past the limit (`redis-cli` against `redis-ha` in `redis-system`, TLS + auth), then call **any** model with that account → 429. Inflating an old per-model key proves nothing — those counters are no longer consulted (they expire on their own TTL; historical per-model spend did not carry over at cutover).

**Verifying the #9244 fix is active:** the budget rule's request-cost is `number: 0`, so a non-zero counter can *only* come from the response micro-USD cost. Any shared counter > 0 after real traffic proves cost-charging works.

## Knock-on effects / gotchas

- **`prometheus-redis-exporter`** (ai-helm-values) parses the *old* per-model key shape (`…/converse/<model>/…`, `rule-2`/`rule-7` indices). The shared keys don't match those regexes — the quota dashboard needs re-pointing at the new key shape (open follow-up).
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
