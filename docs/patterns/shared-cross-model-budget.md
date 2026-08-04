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
           limit: { requests: 15000000, unit: Year }    # micro-USD/MONTH; unit is a TTL only (ADR-0112)
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
| window | `floor(now / unit_seconds) × unit_seconds` (Year = 31536000 since ADR-0112; was Month = 2592000) | same |
| `x-billing-period` (ADR-0111, since 2026-07-31) | live value in the key (the calendar `YYYY-MM` string, e.g. `2026-08`) | same |

Live examples:

```
OLD (per-model):  …core-gateway/api-https_httproute/converse/glm-5/rule/0/…_rule-2-match-0_<ACCOUNT>_rule-2-match-1_<WINDOW>
NEW (shared, pre-ADR-0111):  converse-gateway/core-gateway_converse-gateway/core-gateway/rule/0_rule-0-match-0_<ACCOUNT>_rule-0-match-1_<WINDOW>
NEW (shared, ADR-0111+):     converse-gateway/core-gateway_converse-gateway/core-gateway/rule/0_rule-0-match-0_<ACCOUNT>_rule-0-match-1_<PERIOD>_<WINDOW>
```

⚠️ **The `<WINDOW>` epoch segment is NOT a calendar month.** It's
`floor(now/unit_seconds)*unit_seconds`, anchored to the Unix epoch — confirmed
against Envoy Gateway's own translator source. No Redis operation can move that
boundary; it's a pure function of wall-clock time.

Two changes make the budget calendar-aligned, and **both are load-bearing**:

1. **ADR-0111** — a Lua `EnvoyExtensionPolicy`
   (`charts/core-gateway/templates/envoyextensionpolicy-billing-period.yaml`)
   stamps `x-billing-period: <UTC YYYY-MM>` on every request, and every monthly
   rule keys on it as an extra `Distinct` header. This is what rotates the
   counter on the 1st.
2. **ADR-0112** — `unit: Year`, so the `<WINDOW>` epoch stops rotating
   underneath it.

⚠️ **Why (2) is not optional.** The period marker did NOT replace the window
epoch — both are in the key, so the counter rotates whenever **either** changes.
With `unit: Month` the epoch kept rolling on its own 30-day grid (next would
have been **2026-08-05**, mid-month), granting a spurious second budget ~12x a
year *on top of* the intended 1st-of-month reset. Proven live: one account was
found holding counters under two epochs (`1780704000` and `1783296000`). It
fails **open** — more budget, never less — so nothing alerts. `unit: Year`
(31,536,000s, the longest the CRD enum allows) freezes the epoch for a year,
leaving the marker as the sole trigger.

⚠️ **`unit` is a TTL, not a billing period.** `requests` stays the MONTHLY
budget — never multiply it by 12. Reverting to `Month` silently restores the
defect.

One epoch rollover per year survives (~**2026-12-18**, then annually — December's
effective cap is ~2x). Known, documented, accepted; see ADR-0112 for why a
migration job was rejected. Pre-fix keys simply stop being written and age out
on their own TTL — no migration needed.

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
# rules (burst/req-per-min counters lived on the separate per-model route
# domain, `.../converse/<model>/...`, never here — and since 2026-08-01 no
# burst rule renders at all) — so this pattern cannot accidentally catch a
# burst key. It also never touches LibreChat's session
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

## Weekly sub-budget (ADR-0119) — additive, not a replacement

**Status:** live since 2026-08-04.
**TL;DR:** a SECOND, independent rule composes (AND) with the monthly budget
above — same shared cross-model shape, same `unit: Year` TTL trick, but keyed
on `x-billing-week` (an ISO-8601, **Monday-start** `GGGG-Www` marker) instead
of `x-billing-period`. It stops a user spending their whole month's budget in
the first few days; it never raises the monthly ceiling — a request is denied
if *either* bucket is exhausted.

The week marker is stamped by the same Lua function that stamps
`x-billing-period` (only one `EnvoyExtensionPolicy` may target a Gateway, see
that template's header note):

```lua
request_handle:headers():replace("x-billing-week", os.date("!%G-W%V"))
```

`%G` is the ISO week-numbering year (not `%Y`, the Gregorian year) — a week
spanning a year boundary (e.g. 2027-01-01, which is ISO week 53 of *2026*)
must key against the ISO year or it collides with the wrong year's week 1.

Config lives on the **same** `backendTrafficPolicy.monthlyBudget.plans` list
in `charts/core-gateway/values.yaml`, as an optional `weeklyBudgetUsd` field
per entry — deliberately not a second, separately-ordered list (two lists
that must stay in the same order is strictly worse than one list with an
extra field). The template renders the weekly rules as a **second pass over
the same list, strictly after** the monthly rules, so it only ever appends
new `rule/N` slots and can never renumber a live monthly counter
(ADR-0084's append-only contract).

⚠️ Current default figures are `monthlyBudgetUsd / 4` (enterprise $250, free
$12.50, pro $200/pro $50) — a starting formula, not a confirmed business
number. Tune per plan; nothing about the mechanism depends on the ratio.

⚠️ Only wired into this gateway-wide shared path. The dormant per-model
budget rule in `charts/ai-model` (kept only for a `sharedBudget` rollback)
does **not** get a weekly counterpart — see ADR-0119's Neutral/follow-ups.

⚠️ Redis key churn is ~4x higher than the monthly rule alone: a fresh key
mints every Monday instead of every 1st (~52/year/account/plan vs ~12),
each still carrying the `unit: Year` TTL from ADR-0112.

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
| 2026-07-31 | ADR-0111 — `x-billing-period` calendar marker folds into every monthly-budget key |
| 2026-08-01 | ADR-0112 — `unit: Month` → `Year`: 0111 alone left the 30-day epoch still rotating (a spurious mid-month reset, next due 2026-08-05). The marker is now the sole rotation trigger |
| 2026-07-31 | per-minute burst limits raised 10x on every plan (spurious 429s on bursty-but-cheap usage) |
| 2026-08-01 | free tier restored $15 → **$50** shared (back to ADR-0035), and per-minute burst **commented out entirely** — the per-model BTP now emits no rules at all, so this shared budget is the only enforced cap |
| 2026-08-04 | ADR-0119 — additive weekly sub-budget (`x-billing-week`, Monday-start ISO week) composes with the monthly rule to stop front-loading; monthly contract untouched |
