# ADR-0033: Relax free-tier burst rate limits (requests/min and tokens/min)

**Status:** Accepted
**Date:** 2026-06-08
**Deciders:** @Koufan-De-king

## Context

Multiple colleagues on the **free** billing plan are hitting HTTP 429
("Too Many Requests") from the Envoy Gateway rate-limit rules defined in
ADR-0021. The current free-tier burst limits — **20 requests/min** and
**50,000 tokens/min** — are too tight for normal interactive usage:

- **opencode's tool-calling loop** fires multiple model calls per user action
  (tool invocation → result → follow-up), easily burning through 20 requests
  in under a minute during an active coding session.
- **A single large-context request** (codebase summary, long conversation
  history) can consume the entire 50k token budget in one shot, blocking every
  subsequent request for the remainder of the minute.

The monthly budget backstop ($30 free / $200 pro) already caps total spend and
is not affected by this change, so the burst limits should serve as a
"don't-DDoS-the-backend" safeguard rather than a user-facing throttle.

The pro tier (120 req/min, 400k tokens/min) is not the source of complaints
but is also low relative to the service/internal tiers (600 req/min, 2M
tokens/min). The gap between free and pro should remain meaningful but the
free tier shouldn't punish normal interactive use.

## Decision

Raise the **global default** burst limits in `charts/ai-models/values.yaml`
(`rateLimitBudgeting.plans`):

| Plan | Field | Before | After |
|---|---|---|---|
| **free** | `requestsPerMin` | 20 | **200** |
| **free** | `tokensPerMin` | 50,000 | **200,000** |
| **pro** | `requestsPerMin` | 120 | **400** |

All other limits stay unchanged:

- **pro** `tokensPerMin` remains 400,000 (already adequate).
- **service** and **internal** stay at 600 req/min / 2M tokens/min (uncapped
  budget).
- **Monthly budgets** ($30 free, $200 pro, uncapped service/internal) are
  unaffected — they remain the real spend backstop.
- **Per-model budget overrides** (glm-5 $10/$50, adorsys-planner $10/$50,
  adorsys-planner-pro $5/$25) are unaffected.

## Consequences

**Positive**

- Eliminates the 429 storm that free-tier colleagues experience during normal
  opencode sessions.
- Burst limits now function as backend-protection guards (their intended role
  per ADR-0021) rather than user-facing throttles.
- Monthly budgets still cap total spend, so the financial exposure is unchanged.

**Negative**

- A misbehaving free-tier client can now sustain a higher burst against the
  backends for up to a minute before the per-minute window resets. The
  circuit-breaker and outlier-detection on the gateway-wide
  BackendTrafficPolicy (50k max connections/pending/parallel) is the safety
  net, though it was sized for much higher throughput.
- The gap between free (200 req/min) and pro (400 req/min) is now 2×; it was
  6× before (20 vs 120). This reduces the "upgrade incentive" of the burst
  cap, but the monthly budget gap ($30 vs $200) and the token/min gap
  (200k vs 400k) still differentiate the tiers.

**Neutral / follow-ups**

- Monitor 429 rates after deployment to confirm the complaints resolve.
- If the relaxed limits cause backend pressure, per-model overrides
  (`.models.<name>.rateLimitBudgeting`) can tighten individual expensive
  models without reverting the global change.

## Alternatives considered

- **Remove burst rate limits entirely** — rejected because some per-minute
  guard is still valuable against runaway clients or leaked tokens; the
  monthly budget alone wouldn't stop a spike from overwhelming backends
  within a single minute.
- **Only raise requests/min, keep tokens/min at 50k** — rejected because the
  rules are composed (ANY exhausted bucket → 429). Raising requests without
  raising tokens just shifts the 429 trigger from the request counter to the
  token counter; a large-context request would still cap out.
- **Switch to per-model burst overrides instead of changing global defaults**
  — rejected because the complaints span multiple models and the current
  global defaults are universally too low for interactive use. Per-model
  overrides are for making expensive models *tighter*, not for fixing a
  baseline that's wrong.

## Related

- Amends: [ADR-0021](./0021-burst-budget-billing-and-dual-plane-authconfigs.md) (burst-control tier definitions)
- Charts touched: `charts/ai-models/values.yaml` (`rateLimitBudgeting.plans`)
- Rendered by: `charts/ai-model/templates/backendtrafficpolicy.yaml`
