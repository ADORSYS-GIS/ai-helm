# ADR-0110: Project quota-tier rate-limit rules use an append-only list — and fix `ai-model`'s `plans` map along the way

**Status:** Accepted
**Date:** 2026-07-26
**Deciders:** @stephane-segning, @Koufan-De-King

## Context

Epic [ai-helm#531](https://github.com/ADORSYS-GIS/ai-helm/issues/531) and ticket
[#570](https://github.com/ADORSYS-GIS/ai-helm/issues/570) add a discrete quota-tier menu
(`t-xs`/`t-s`/`t-m`/`t-l`, governance-defined) that a project **lead** assigns per member —
delegated in `lightbridge-authz` (`project_members.quota_tier`, see that repo's ADR-0003) — plus a
per-project envelope ceiling. Both need new `BackendTrafficPolicy` rate-limit rules in
`charts/ai-model`, composed alongside the existing per-plan burst/budget rules (ADR-0021/0035).

**ADR-0084** (2026-07-20) already established why this is dangerous to get wrong: the Lyft
ratelimit service keys each counter in redis-ha on the rule's **position** in the rendered
`rateLimit.global.rules` list, not on the plan/tier name (`Exact`-match headers render as masked
constants). `charts/core-gateway`'s `monthlyBudget.plans` was a **map** — Helm sorts map keys — and
adding the `enterprise` plan (which sorts alphabetically first) silently inserted a rule at index 0
mid-window, shifting `free`/`pro` to new indices and **orphaning every account's accumulated
monthly spend** (a live incident, confirmed via `SCAN`, not theoretical). The fix there was to make
`plans` an explicit, ordered, append-only list.

ADR-0084's own "Neutral / follow-ups" section flagged that **`charts/ai-model`'s
`rateLimitBudgeting.plans` has the identical flaw**, deliberately left unfixed there to keep that
change small and reviewable. It is lower-severity today only because `sharedBudget.enabled: true`
(the #532 cutover) drops the per-model monthly-budget rule, leaving only per-minute burst rules
whose counters churn every 60s and so reset harmlessly if reordered. Confirmed live: `ai-models`
`rateLimitBudgeting.plans` (`enterprise, free, internal, pro, service` keys) renders in Helm's
sorted order `enterprise, free, internal, pro, service` — the same latent hazard, just currently
inert.

This ADR's tier rules land in the **same** `charts/ai-model/templates/backendtrafficpolicy.yaml`
`rules` list as `plans`. Adding a map-shaped `tiers` next to an unfixed map-shaped `plans` would
compound the hazard (two independent sort-order-derived rule blocks in one list); since this change
already has to touch that exact file, this ADR also executes ADR-0084's flagged follow-up for
`ai-model` as part of the same, render-neutral pass.

This ADR was originally drafted as ADR-0085 on 2026-07-22, alongside a companion ADR for the
Authorino metadata step that would populate the headers this ADR's rules match on. Both were
shelved mid-implementation when the epic pivoted; ADR numbers 0085–0093 were taken by unrelated
work in the interim, so this decision lands here as ADR-0110 instead. Its companion is **not**
re-landed alongside it — see the note at the end of the Decision section.

## Decision

1. **Convert `rateLimitBudgeting.plans` in `charts/ai-model` and `charts/ai-models` from a map to
   an ordered, append-only list** of `{id, monthlyBudgetUsd?, burst}`, exactly mirroring ADR-0084's
   shape and the template's `fail`-guard-on-missing-`id` pattern. The pinned order is the sorted
   order live today — `enterprise, free, internal, pro, service` — so this half of the change is
   **render-neutral** (byte-identical rendered rules, verified by diffing `helm template` before/
   after against the `ci/lint-values.yaml` fixture). Never reorder, insert, or remove an entry;
   a new plan is always appended at the tail.

2. **Add `rateLimitBudgeting.tiers`** as a **new**, separately ordered, append-only list of
   `{id, monthlyBudgetUsd?, burst?}` — same shape and same rules (append-only, `fail`-guarded,
   comment carries the resolved `rule/N`). Rendered as **one rule per tier**, keyed:
   ```
   clientSelectors:
     - headers:
         - {name: x-project-id, type: Distinct}
         - {name: x-account-id, type: Distinct}
         - {name: x-quota-tier, type: Exact, value: "<tier id>"}
   ```
   per member-in-project (ticket #570's spec). The tier rule block is rendered **strictly after**
   the (now-list) `plans` rule block, so introducing tiers **never shifts an existing plan rule's
   index** — the two lists occupy disjoint, independently-stable index ranges within the same
   `rules` array. Default `tiers: []` (no rules rendered) is safe: no tier is defined, no rule
   exists to (mis)match, every caller falls through to the existing plan rules unchanged — ticket
   #570's own AC ("callers with no project context fall through to existing plan rules only").

3. **Add one per-project envelope rule** (not a list — one rule, `shared`-style, always rendered
   when `.Values.rateLimitBudgeting.projectEnvelope` is set), keyed:
   ```
   clientSelectors:
     - headers:
         - {name: x-project-id, type: Distinct}
         - {name: x-project-quota, type: Exact, value: "<project's quota tier>"}
   ```
   This has no per-value list to order — it's a single static rule — so it carries none of the
   append-only hazard; it's placed after the tier block purely for readability. The header is named
   `x-project-quota` (not `x-project-plan`, its original working name) to match the vision doc's
   `projectQuota` vocabulary and the JWT claim (`project_quota`, `lightbridge-authz` epic#531) that
   will populate it.

4. **`x-quota-tier` / `x-project-id` / `x-project-quota` are not yet stamped by any AuthConfig.**
   This ADR defines the rule *shape* the epic's architecture calls for; something else has to
   populate these headers before the rules do anything. **That "something else" is deliberately not
   this ADR's companion Authorino wiring as originally drafted.** The 2026-07-22 companion ADR
   (`0086-authorino-project-context-metadata-step`, never landed) designed a live per-request
   `resolve-context` metadata call against `lightbridge-authz`; that design is superseded by the
   epic's pivot to JWT-claims-only introspection (`lightbridge-authz` mints `role`/`quota_tier`/
   `project_quota` into the API-key JWT at issue time, per that repo's Phase E) — a lighter, no-extra
   -hop mechanism that fits the same header contract. Wiring it is separate work in
   `ai-helm-values`, tracked for when that slice lands; a fresh ADR will document it there instead of
   resurrecting the shelved 0086 design. Until then, `tiers`/`projectEnvelope` default to
   empty/unset and these rules render as inert no-ops — safe to merge ahead of that work.

5. **Tier menu placement: `charts/ai-models/values.yaml` for now, not `ai-helm-values`.** Ticket
   #570 says "ADR-0056 placement" (implying the values repo), but ADR-0056 explicitly excludes
   `ai-models` — it has no inline `valuesObject` and no `valuesFromRepo` wiring today (leaf-chart
   config, ADR-0012). Wiring that up is a real, separate structural change (adding a values-repo
   override entry point to a chart that's never had one), not a one-line addition. Deferred as an
   explicit follow-up; the tier menu lands next to the existing `plans` map (same file, same
   deploy path, same review surface) until that wiring is a deliberate decision on its own.

## Consequences

**Positive**

- `ai-model`'s pre-existing plan-ordering hazard (ADR-0084's flagged follow-up) is closed, not just
  the new tier code.
- Adding, retiring, or reordering-in-appearance a tier is safe at any time — new tiers always land
  at the tail.
- The tier/envelope rule shapes are defined and reviewable now, decoupled from the (larger, still
  undesigned) claims-based header-stamping wiring — that work can proceed independently against a
  stable target.

**Negative**

- Same as ADR-0084: the list order looks arbitrary and *invites* "tidying" that would break it.
  Mitigated only by comments + this ADR + ADR-0084 — no mechanical guard exists.
- Retiring a tier is a breaking operation (must leave a dead slot), not a cleanup, forever.
- The tier menu still lives in a chart-owned file (`charts/ai-models/values.yaml`), so a
  governance-only tier change requires an `ai-helm` PR + release, not just an `ai-helm-values`
  merge — same friction the existing `plans` map already has. Ticket #570's "no GitOps commit per
  change" framing refers to *lead* self-service (which never touches this file — leads only ever
  write `quota_tier` into `lightbridge-authz`'s `project_members` table), not to governance
  changing the tier menu itself.

**Neutral / follow-ups**

- Moving the tier menu (and `plans`, while at it) into `ai-helm-values` via a new
  `valuesFromRepo`-equivalent for `charts/ai-models` is real future work; not bundled here.
- The header-stamping wiring that populates `x-quota-tier`/`x-project-id`/`x-project-quota` — now
  planned as claims-based rather than a live metadata call — is separate, tracked work this ADR's
  rules are inert until. Lands with the `ai-helm-values` slice of epic#531.
- `charts/core-gateway`'s gateway-wide shared budget (ADR-0084) is untouched — project envelopes
  and tiers are model-route-scoped (`charts/ai-model`), same placement as the existing per-model
  burst rules, not the shared cross-model budget.

## Alternatives considered

- **Put tier rules in `charts/core-gateway` (gateway-wide, `shared: true`) instead of per-model.**
  Rejected for this ADR: the per-member tier is meant to bound a member's usage the same way plan
  burst limits do today (per-model), and mirroring the existing per-model placement keeps this
  change small. A shared cross-model tier counter is a plausible future evolution, symmetric to the
  #532 shared-budget cutover, deferred.
- **Single `Distinct` rule on `x-quota-tier` instead of one rule per tier.** Rejected: verified
  against current Envoy Gateway docs that `Distinct` only splits one shared *limit* into per-value
  *buckets* — it cannot give different observed values different numeric limits, which is required
  here (each tier has its own budget). One rule per tier is unavoidable with today's
  `BackendTrafficPolicy` capabilities.
- **Wire `ai-helm-values` placement for the tier menu now, per ticket #570's literal wording.**
  Rejected for this ADR: `ai-models` has no `valuesFromRepo` entry point (ADR-0056 explicitly
  excluded it), and building one is a separate, non-trivial structural change deserving its own
  review, not a rider on the rule-shape/ordering fix this ADR is about.
- **Re-land the shelved 0086 Authorino `resolve-context` metadata-step design as-is.** Rejected: it
  predates the epic's pivot to JWT-claims-only introspection and would add a live per-request call
  to `lightbridge-authz` the pivot was specifically meant to avoid. A replacement design belongs to
  the `ai-helm-values` slice, not this chart-logic ADR.

## Related

- Builds on: ADR-0021 (burst/budget descriptors), ADR-0035 (per-person budget), **ADR-0084**
  (append-only list contract — this ADR applies that contract to `ai-model`/tiers).
- Companion: `lightbridge-authz` epic#531 (project-scoped membership + lead delegation — the
  `quota_tier` source of truth this feeds from; Phase E mints it into the API-key JWT).
- Charts/files touched: `charts/ai-model/values.yaml`,
  `charts/ai-model/templates/backendtrafficpolicy.yaml`, `charts/ai-model/ci/lint-values.yaml`,
  `charts/ai-models/values.yaml`.
- Tracks: ai-helm#531 (epic), ai-helm#570 (this ticket).
- Supersedes in intent (never landed): the 2026-07-22 draft companion
  `0086-authorino-project-context-metadata-step`, whose live-metadata-call design is superseded by
  the claims-based approach above; a fresh ADR will document the actual `ai-helm-values` wiring.
