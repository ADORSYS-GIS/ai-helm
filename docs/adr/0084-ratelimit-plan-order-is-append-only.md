# ADR-0084: Rate-limit plan order is an append-only list, not a sorted map

**Status:** Accepted
**Date:** 2026-07-20
**Deciders:** @stephane-segning

## Context

The gateway-wide monthly budget (ADR-0021 / [#532](https://github.com/ADORSYS-GIS/ai-helm/issues/532))
renders one `BackendTrafficPolicy` rate-limit rule per billing plan by iterating a
`plans` collection in Helm. The Lyft ratelimit service stores each counter in
redis-ha under a key that embeds the rule's **position** in that list (`.../rule/N/...`),
while the plan name itself is **masked** — it is an `Exact` header match, so it renders
in the key as a constant (`rule-N-match-1_rule-N-match-1`), not as the literal `free`.
The rule index is therefore the *only* carrier of plan identity in the counter key.

`plans` was a **map**, and Helm's `range` iterates map keys in sorted order. On
**2026-07-16** the `enterprise` tier was added ([#663](https://github.com/ADORSYS-GIS/ai-helm/issues/663)).
Because `enterprise` sorts alphabetically first, it was not appended — it was
**inserted at index 0**, pushing `free` from `rule/0` to `rule/1` and `pro` from
`rule/1` to `rule/2`, **mid-window**. The ratelimit service has no notion that a rule
was renumbered; it simply began writing to new key names. Every user's accumulated
monthly spend was orphaned under the old index and a fresh zeroed counter was created
alongside it. **The entire fleet silently received a new monthly budget**, and nobody
was throttled who should have been. Confirmed live: a single account held live
`rule/0` (old `free`), `rule/1` (new `free`) and `rule/2` (`pro`) counters within one
window (`1783296000`).

## Decision

Change `monthlyBudget.plans` from a **map** to an **ordered list** of
`{id, monthlyBudgetUsd}`, pinned to the order that was live on 2026-07-20
(`enterprise`, `free`, `pro`), and treat that order as **append-only**: a new plan is
added at the tail, where it cannot shift an existing counter. Never reorder, insert,
or remove an entry. The template gained a `fail` guard on a missing `id` (so the old
map shape errors loudly instead of rendering a rule with an empty plan match) and now
emits the resolved index into the rendered comment (`# rule/1 · free …`) so the
index↔plan mapping is greppable from the manifest.

The order is deliberately **not alphabetical** and must not be "tidied".

## Consequences

**Positive**
- Adding a plan is now safe at any time: it lands at the tail and renumbers nothing.
- The change is **render-neutral** — the parsed manifest is byte-identical to the
  pre-change render, so it re-keys nothing and can merge on any day. It is a pure
  fragility fix, not a migration.
- The index↔plan mapping is explicit in both the values file and the rendered output,
  instead of being an emergent property of alphabetical sorting.

**Negative**
- The list order looks arbitrary to a newcomer and *invites* the exact tidying that
  breaks it. Mitigated only by comments and this ADR — there is no mechanical guard
  against a reorder, because any such guard would need to know the historical order.
- Removing a retired plan is now a breaking operation rather than a cleanup. A plan
  that is no longer sold must be left in the list (its rule simply stops matching).

**Neutral / follow-ups**
- The **`charts/ai-models` `rateLimitBudgeting.plans`** map has the identical flaw. It
  is lower-severity today because `sharedBudget.enabled: true` gates its per-model
  *budget* rules off, leaving only per-minute *burst* rules whose counters churn every
  minute and so reset harmlessly. It should get the same treatment before
  `sharedBudget` is ever rolled back. **Not fixed here** — deliberately out of scope to
  keep this change render-neutral and reviewable.
- A stronger fix would put the plan **name** in the key so the index stops being
  load-bearing at all (see Alternatives). Deferred; if adopted, it must land at a
  30-day window boundary because it re-keys every counter.
- The 2026-07-16 budget forgiveness is **not recoverable** — the orphaned counters
  expire on their own TTL and the spend they held cannot be merged into the live ones.

## Alternatives considered

- **Add a second, `Distinct` selector on `x-billing-plan`** so the plan name lands in
  the key as `_rule-N-match-2_<plan>_` and the index stops mattering. The CRD permits
  it (`headers` is a plain list with no uniqueness constraint on `name`), but Envoy
  Gateway v1.8.2's translation of two selectors on one header is **unverified**, and
  the change re-keys every counter — so it would have to wait for the 2026-08-05
  window boundary and carry real risk of breaking rate limiting outright. Rejected as
  the immediate fix; retained as possible future hardening, since the list-ordering
  fix delivers the same practical guarantee at zero risk today.
- **Keep the map, pin order with numeric-prefixed keys** (`00-free`, `10-pro`).
  Rejected: the map key *is* the `x-billing-plan` header value that Authorino stamps,
  so it cannot be renamed without changing the auth contract.
- **Do nothing, document the hazard.** Rejected: the hazard was already documented
  ("budget rule index is stable") in the exporter config, and that comment is exactly
  what went stale and misled.

## Related

- Charts/files touched: `charts/core-gateway/values.yaml`,
  `charts/core-gateway/templates/backendtrafficpolicy.yaml`
- Builds on: ADR-0021 (burst/budget descriptors), ADR-0035 (per-person budget),
  ADR-0070 (ratelimit quota observability)
- Docs: `docs/patterns/ratelimit-quota-observability.md`
- Companion change in `ai-helm-values`: repoint the `prometheus-redis-exporter` at the
  gateway-wide shared-budget keys (it still scans the dead per-model `rule-2`/`rule-7`
  budget keys, abandoned at the 2026-07-09 shared-budget cutover).
