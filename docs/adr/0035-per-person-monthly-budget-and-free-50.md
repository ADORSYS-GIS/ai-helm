# ADR-0035: Per-person monthly budget (drop the shared org bucket); free tier → $50

**Status:** Accepted
**Date:** 2026-06-09
**Deciders:** @stephane-segning

## Context

ADR-0021 keyed the per-model monthly spend budget on **`x-org-id`** — a single
pool shared across everyone in an organization — while the per-minute burst
limits stayed per-person (`x-account-id`). In practice colleagues on the same
org contend for one monthly budget: one heavy user can exhaust the shared pool
and 429 everyone else for the rest of the month. The free tier's $30/month pool
made this sharper. The maintainer wants the free tier relaxed and the budget to
be genuinely per-person, not shared.

`x-account-id` is already stamped per-person by the AuthConfig on both planes
(external: Keycloak `sub`; internal: the forwarded `X-LibreChat-User`) and is
already the key for the burst rules, so no new descriptor is needed.

## Decision

- **Key the monthly budget rule on `x-account-id`** (per person) instead of
  `x-org-id`, in `charts/ai-model/templates/backendtrafficpolicy.yaml`. The
  shared-org budget bucket is removed; every plan's monthly budget is now
  per-person. Burst rules were already per-person — unchanged.
- **Raise the free-tier monthly budget $30 → $50** in
  `charts/ai-models/values.yaml` (`rateLimitBudgeting.plans.free.monthlyBudgetUsd`).

All other limits are unchanged: pro $200/mo (now per-person), service/internal
uncapped, the burst caps from ADR-0033 (free 200 req/min · 200k tok/min; pro 400
· 400k), and the per-model budget overrides (glm-5 $10/$50, adorsys-planner
$10/$50, adorsys-planner-pro $5/$25 — all now per-person).

## Consequences

**Positive**

- A heavy user can no longer exhaust a colleague's spend budget — each person
  gets their own $50 (free) / $200 (pro) monthly pool.
- The free tier is more generous ($50), reducing budget-exhaustion 429s.

**Negative**

- **Total platform spend exposure rises**: the cap is now N × per-person budget
  instead of one per-org pool. With many free users this raises the theoretical
  monthly ceiling. The per-model pricing CEL + per-model overrides remain the
  per-model controls; monitor aggregate spend and tighten per-model overrides if
  it runs hot.
- Org-level billing/attribution via the budget bucket is gone. `x-org-id` is
  still stamped and available in access logs for reporting, just not used for
  enforcement. Re-introducing an org-level cap later would need a new rule (and
  ADR).

**Neutral / follow-ups**

- If a true org-level ceiling is ever needed *alongside* the per-person one, add
  a second monthly rule keyed on `x-org-id` (rules compose — ANY exhausted
  bucket 429s) rather than switching the key back.

## Alternatives considered

- **Keep `x-org-id`, just raise free to $50** — rejected: it relaxes the amount
  but leaves the shared-bucket contention the maintainer explicitly wants gone.
- **Per-person budget AND a per-org ceiling** — deferred: more rules to reason
  about and no current need for an org cap; revisit if spend exposure becomes a
  problem.

## Related

- Amends: [ADR-0021](./0021-burst-budget-billing-and-dual-plane-authconfigs.md)
  (budget descriptor: `x-org-id` → `x-account-id`); relates to
  [ADR-0033](./0033-relax-free-tier-burst-limits.md) (the burst relax).
- Charts touched: `charts/ai-model/templates/backendtrafficpolicy.yaml`,
  `charts/ai-models/values.yaml` (`rateLimitBudgeting.plans.free`).
</content>
