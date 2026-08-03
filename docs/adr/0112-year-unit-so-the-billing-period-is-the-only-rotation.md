# ADR-0112: `unit: Year` so the calendar billing period is the ONLY budget rotation

**Status:** Accepted
**Date:** 2026-08-01
**Deciders:** @stephane-segning

## Context

[ADR-0111](./0111-calendar-aligned-billing-period.md) (merged 2026-07-31) added an
`x-billing-period` descriptor — a calendar `YYYY-MM` marker stamped by a Lua
`EnvoyExtensionPolicy` — to every `unit: Month` rate-limit rule, so budgets would
roll over on the 1st of the calendar month instead of on Envoy Gateway's fixed
30-day epoch grid.

**That fix was incomplete, and this ADR closes the gap it left open.**

Adding the descriptor did not *replace* the window epoch; it sits alongside it.
Lyft/Envoy unconditionally append `floor(now/unit_seconds)*unit_seconds` to every
Redis key, so the live key is:

```
..._rule-2-match-2_2026-07_1783296000
                   ^^^^^^^ ^^^^^^^^^^
                   period   window epoch (still present)
```

A counter therefore rotates whenever **either** segment changes. ADR-0111 fixed
the calendar boundary but left the 30-day epoch rotating on its own drifting
grid, so a *second*, spurious reset still fires mid-month — handing every account
a fresh budget on top of the intended one, roughly 12 times a year.

This was not theoretical. A live `SCAN` of `redis-ha` found the same account
holding counters under **two different window epochs** (`1780704000` and
`1783296000`) — direct evidence that an epoch rollover mints a new counter and
abandons the old balance. Computed against the deployed data, the next such
rollover was **2026-08-05 00:00 UTC**: four days into August, every account's
spend would have silently reset to zero.

The failure mode is fail-*open* (users get more budget, never less), which is why
it produced no alerts and no complaints — and why it survived ADR-0111's review.

## Decision

Set **`unit: Year`** on all four monthly-budget rule families, leaving
`x-billing-period` as the sole rotation trigger.

`Year` = 31,536,000s (365 days), so the window epoch holds still for a full year.
Within that span the only thing that changes the key is the calendar marker,
which flips exactly at 00:00 UTC on the 1st. Verified against the deployed CRD
that `Year` is a permitted value:

```
+kubebuilder:validation:Enum=Second;Minute;Hour;Day;Month;Year
```

Rules changed (all four carry the identical defect):

| Chart | Rule |
|---|---|
| `charts/core-gateway` | shared cross-model plan budget (`shared: true`, #532) |
| `charts/ai-model` | per-model plan budget (dormant while `sharedBudget.enabled`) |
| `charts/ai-model` | per-member quota-tier budget (ADR-0110) |
| `charts/ai-model` | per-project envelope (ADR-0110) |

Burst rules stay `unit: Minute` — those *should* rotate per minute.

**`unit` is now a TTL, not a billing period.** The `requests` value remains the
**monthly** budget in micro-USD and must **not** be multiplied by 12. This is the
single most likely way for a future change to break this quietly, so it is called
out in a comment on every one of the four rules.

### Residual limitation, accepted

One epoch rollover per year survives, at **~2026-12-18** (then annually), because
`Year` is the longest unit the enum offers and the boundary is epoch-anchored —
we cannot move it. December's effective cap is therefore ~2x (free $50 → ~$100).
This is a 12x improvement over the status quo and is documented rather than
engineered away, because the alternatives cost more than the defect:

- **A year-boundary counter-migration CronJob** would fight Lyft's own TTL
  handling — Lyft sets expiry only when it *creates* a key, so a job that
  pre-creates keys via `INCRBY` risks leaving them with **no TTL at all**,
  trading one predictable annual blip for permanently immortal counters, on a
  code path exercised once a year.
- **Moving budget enforcement off Envoy's global rate limiter** is a genuine
  architecture change — see Alternatives.

## Consequences

**Positive**

- Removes ~11 of 12 spurious annual budget resets; the calendar marker now does
  exactly what ADR-0111 intended it to do.
- One-line-per-rule change; no new components, no new dependencies.
- Ships before the 2026-08-05 rollover, so August is the first month enforced as
  a real calendar month.

**Negative**

- **Re-keys every budget counter once more**, zeroing accumulated spend at
  deploy — the third such event after the #532 cutover and ADR-0111. Deliberately
  timed to 2026-08-01, when total tracked spend across all accounts was ~$0.45;
  the same change mid-month would discard real balances.
- **TTL grows 30d → 365d**, so abandoned period keys linger a year instead of a
  month. Roughly 12x the key count and 12x the `gateway_ratelimit_spend_micro_usd`
  series in Mimir. They are tiny integer counters and the extra history is useful
  to the `$billing_period` dashboard filter, but it is a real cardinality
  increase and a larger `SCAN` surface for `prometheus-redis-exporter`.
- `unit` no longer means what it says. A reader who "corrects" `Year` back to
  `Month` silently reintroduces the defect — mitigated only by comments and this
  ADR, as with ADR-0084's ordering hazard.

**Neutral / follow-ups**

- The annual blip should be revisited before **2026-12-18** with real spend data,
  to decide whether it is worth engineering away.
- Upstream ask worth filing: a longer `Duration` on Envoy AI Gateway's
  `QuotaPolicy` (see Alternatives) — the cheapest path to a properly-modelled fix.

## Alternatives considered

- **Keep `unit: Month` and accept the mid-month reset.** Rejected: it is a
  budget leak that makes the enforced cap roughly double the configured one, and
  ADR-0111 was specifically undertaken to stop exactly this.
- **Envoy AI Gateway `QuotaPolicy`** (`aigateway.envoyproxy.io/v1alpha1`).
  Purpose-built for this: CEL `costExpression` over token variables, a
  first-class `mode: Shared` that expresses #532's `shared: true` natively,
  `shadowMode` for safe dry-runs, `perModelQuotas`, and selector-keyed (not
  ordinal) rules that would retire ADR-0084's hazard. **Rejected today on two
  hard blockers:** `QuotaValue.duration` is
  `+kubebuilder:validation:Enum="1s";"1m";"1h";"1d"` — a monthly budget is
  literally inexpressible, and unlike `BackendTrafficPolicy` no descriptor trick
  rescues it (a 1d window resets daily regardless of selectors); and
  [ai-gateway#2460](https://github.com/envoyproxy/ai-gateway/issues/2460) (open)
  reports `bucketRules`/`clientSelectors` are counted in Redis but **never
  enforced**. Still the most promising long-term destination — it needs one enum
  value and one bug fix.
- **Kuadrant `RateLimitPolicy` / `TokenRateLimitPolicy` (Limitador).** Its
  counter model is genuinely better: Redis Lua sets `EXPIRE` only on key
  creation, with no `floor(now/seconds)*seconds` anywhere, so there is no epoch
  grid to fight at all; and counter identity is content-derived rather than
  positional, which would retire ADR-0084's hazard. **Rejected:** the cost
  addend is not user-settable — `TokenRateLimitPolicy` hardcodes
  `responseBodyJSON("/usage/total_tokens")`, there is no CRD field for it, and
  the wasm-shim's CEL walker has no `Expr::Index` arm, so
  `metadata.filter_metadata['io.envoy.ai_gateway'][...]` is unreachable (bracket
  indexing is required because the namespace contains dots). Budgets would have
  to be re-denominated in **tokens**, destroying per-model price weighting — the
  entire purpose of `llm_custom_total_cost` (ADR-0028/0096/0104). Kuadrant also
  declares `TokenRateLimitPolicy` not-GA in
  [RFC 0021](https://github.com/Kuadrant/architecture/blob/main/rfcs/0021-token-rate-limit-reservations.md):
  nothing reserves capacity between check and report, so "a limit intended to cap
  usage at X tokens/window can be exceeded by an unbounded multiple of X".
  Additionally it emits no `authorized_hits` for SSE (streaming would
  undercount), it requires re-adopting an `EnvoyPatchPolicy` — the mechanism this
  repo deliberately retired in ADR-0040 — and its operator pins Envoy Gateway
  `v1.3.3` against ai-gateway's `v1.8.1`, with no evidence anyone has run the two
  together (zero cross-references in either issue tracker).
- **A budget service behind Authorino / OPA.** Exact calendar semantics, zero
  blips. Rejected for now: a new service on the hot path, plus an extra hop,
  re-opening an architectural decision ADR-0021 closed. Reconsider only if
  precise budget windows become a contractual rather than a fairness concern.

## Related

- Amends [ADR-0111](./0111-calendar-aligned-billing-period.md) (whose
  `x-billing-period` mechanism stands unchanged — this ADR only changes `unit`).
- Builds on ADR-0021 (burst/budget descriptors), ADR-0035 (per-person budget),
  ADR-0070 (which first documented the 2,592,000s constant), ADR-0084
  (append-only rule ordering), ADR-0110 (tiers + project envelope).
- Files touched: `charts/core-gateway/templates/backendtrafficpolicy.yaml`,
  `charts/ai-model/templates/backendtrafficpolicy.yaml`,
  `docs/patterns/shared-cross-model-budget.md`.
