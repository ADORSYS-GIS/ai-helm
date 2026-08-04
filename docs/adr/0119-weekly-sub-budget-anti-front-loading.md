# ADR-0119: Weekly sub-budget, additive to the monthly cap, to stop front-loading

**Status:** Accepted
**Date:** 2026-08-04
**Deciders:** @stephane-segning

## Context

The gateway-wide shared monthly budget (#532, [ADR-0021](./0021-burst-budget-billing-and-dual-plane-authconfigs.md),
[ADR-0111](./0111-calendar-aligned-billing-period.md), [ADR-0112](./0112-year-unit-so-the-billing-period-is-the-only-rotation.md))
caps each `(account, plan)` at a fixed monthly micro-USD ceiling (`free` $50,
`pro` $200, `enterprise` $1000), keyed on `x-account-id` + `x-billing-plan` +
`x-billing-period` (a calendar `YYYY-MM` marker). A user is free to spend the
entire monthly allowance in the first days of the month — the rule has no
notion of pacing. That reads as unfair to anyone who logs in later in the
month and finds the shared model backends already saturated by a handful of
heavy early users, and it produces a predictable complaint: "I only used the
gateway for two days and I'm already capped for the rest of the month."

We considered dynamically pooling *unused* budget across users (light users'
headroom stretching a power user's cap on demand), but that requires a
genuinely shared counter across accounts with no per-account isolation, is
first-come-first-served rather than fair, and is a materially different and
riskier design (sizing a pool needs a live headcount input, and a single
account could still exhaust it before others get a turn). Deferred; not
attempted here.

## Decision

Add a **second, independent, per-user weekly ceiling that composes with the
existing monthly one** — Envoy Gateway ANDs multiple `rateLimit.global.rules`
together (a request is denied if *any* matched bucket is exhausted), so this
only ever tightens the effective cap within a week; it never raises the
monthly ceiling.

- **Week boundary: ISO-8601, Monday-start.** The same Lua `EnvoyExtensionPolicy`
  that already stamps `x-billing-period` (ADR-0111) now also stamps
  `x-billing-week: os.date("!%G-W%V")` — `%G` is the ISO week-numbering year
  and `%V` the ISO week number (01–53, weeks start Monday by definition), so a
  week that spans a year boundary keys correctly instead of colliding with the
  wrong year under a naive `%Y-W%V`.
- **Same shared, cross-model shape as the monthly rule** — lives on the
  gateway-wide `BackendTrafficPolicy` (`charts/core-gateway`) with
  `shared: true`, keyed on `x-account-id` (Distinct) + `x-billing-plan`
  (Exact) + `x-billing-week` (Distinct) instead of `x-billing-period`. A
  per-model weekly cap would let a user front-load a *different* model each
  week and defeat the point, so this is deliberately NOT added to the dormant
  per-model rule in `charts/ai-model` (which only exists today for a
  `sharedBudget` rollback — see Neutral/follow-ups).
- **`unit: Year`, reusing ADR-0112's reasoning as-is.** The window epoch
  (`floor(now/unit_seconds)*unit_seconds`) only needs to hold still *longer
  than a week* for the calendar marker to be the sole rotation trigger; `Year`
  already does that for the monthly rule and does it identically here. No new
  epoch math.
- **Rendered as a second pass over the *same* `monthlyBudget.plans` ordered
  list**, strictly after the existing monthly loop, driven by a new optional
  `weeklyBudgetUsd` field on each plan entry. This reuses the one canonical
  plan order instead of introducing a second independently-ordered list that
  could drift out of sync with it, and — critically — only ever *appends* new
  rule-index slots after the existing monthly rules, so it cannot renumber or
  re-key any live monthly counter (the ADR-0084 append-only contract).
- **Default weekly figures: `monthlyBudgetUsd / 4`** (enterprise $250, free
  $12.50, pro $50) — a starting formula, not a verified business number. Flag
  this for the maintainer to confirm/adjust; nothing about the mechanism
  depends on the exact ratio. Using `/4` rather than the calendar-accurate
  `/4.33` is deliberately slightly tighter, and doesn't affect the ultimate
  monthly ceiling either way (the monthly rule still enforces the real total,
  since the rules are ANDed) — it only affects how far a user can front-load
  within a single week.
- **The actual `plans` list — including `weeklyBudgetUsd` — lives in
  `ai-helm-values`, not `ai-helm` (ADR-0055/0056).** It is workload config,
  not a structural chart default, same class as `redactExtproc.image` on this
  same chart ("moved out after that's exactly where it landed by mistake
  during initial wiring"). `ai-helm`'s `charts/core-gateway/values.yaml`
  ships only `monthlyBudget: {enabled: false, plans: []}` — a safe,
  standalone-renderable default with zero real business figures. The
  authoritative `enabled: true` + full `plans` list (monthly and weekly) is
  added to `ai-helm-values` `environments/prod/values/core-gateway.yaml` in
  the *same* change, verified render-neutral by diffing `helm template`
  output before/after the split (byte-identical).

## Consequences

**Positive**
- Directly answers the "I got capped for the rest of the month after two
  days" complaint without touching the monthly contract at all.
- Zero risk to the existing monthly counters — additive-only rendering,
  verified against the ADR-0084 append-only contract.
- Reuses every existing mechanism (Lua marker, `shared: true`, `unit: Year`
  TTL trick) — no new components, no new CRDs, no new failure mode class.

**Negative**
- **Higher Redis key churn.** A weekly counter mints a new key every Monday
  instead of every 1st — roughly 52 stale keys/year/account/plan instead of
  12, each carrying the same `unit: Year` (365-day) TTL as the monthly ones
  (ADR-0112 already accepted this trade for the monthly case; this is a
  further ~4x on top of it for the new rule family alone). Worth revisiting if
  `redis-ha`'s footprint or `prometheus-redis-exporter`'s `SCAN` surface
  becomes a real cost.
- **Not fair-share, still per-user only.** This does not solve "let idle
  users' headroom go to power users" — that was explicitly out of scope (see
  Context) and remains unsolved.
- **The `/4` default is a guess, not a confirmed number**, and needs the
  maintainer to sign off on real weekly figures per plan before this is
  considered tuned rather than merely wired up.
- Same residual ADR-0112 annual epoch blip applies identically here (~2x cap
  around the epoch's yearly rollover) — already documented, not new.
- **Values-repo-first cutover risk.** `ai-helm-values` must merge to `main`
  before (or in the same deploy window as) this `ai-helm` chart change. If the
  `ai-helm` PR (which blanks the chart default to `enabled: false`) reaches
  Hetzner via ArgoCD before `ai-helm-values` carries the real `plans` list,
  the gateway briefly enforces **no budget at all** for every plan — the same
  class of hazard already documented for `security-policies` (ADR-0056:
  "DROPS the gateway AuthConfig" if sequenced wrong). Mitigated by review
  gating, not tooling — same as every other `valuesFromRepo` cutover in this
  repo.

**Neutral / follow-ups**
- Only wired into the currently-live shared path (`charts/core-gateway`).
  The dormant per-model budget rule in `charts/ai-model` (kept only in case
  `sharedBudget` is ever rolled back) does **not** get a weekly counterpart —
  that would be new dormant code for a rollback path that isn't in use. If
  `sharedBudget` is ever rolled back, a per-model weekly design is a decision
  for that moment, not this one.
- `prometheus-redis-exporter`'s quota dashboard (already flagged as needing
  re-pointing at the shared-key shape, `docs/patterns/shared-cross-model-budget.md`)
  will need a parallel `x-billing-week`-keyed panel if per-week visibility is
  wanted later. Not built here — the enforcement rule doesn't depend on the
  dashboard existing.

## Alternatives considered

- **Pooled/elastic budget across users** (unused allowance from light users
  stretches a power user's cap). Rejected for this change: needs a live
  headcount input to size the pool, is first-come-first-served rather than
  fair, and is a materially larger design than "stop front-loading" required.
  May be worth a separate ADR later if the actual complaint turns out to be
  about fairness across users rather than pacing within a month.
- **Replace the monthly cap with a weekly one outright** (e.g. flat $10/week,
  no monthly rule). Rejected per explicit direction: the monthly cap and its
  existing contract (ADR-0021/0035/0084/0111/0112) stay untouched; this is
  additive only.
- **A separate, independently-ordered `weeklyBudget.plans` list** mirroring
  `monthlyBudget.plans`. Rejected: two lists that must stay in the same order
  is strictly worse than one list with an extra optional field — a future
  edit to one list without the other silently breaks the append-only
  guarantee for whichever list drifts.
- **`%Y-W%V` instead of `%G-W%V` for the week marker.** Rejected: `%Y` is the
  Gregorian calendar year, which disagrees with the ISO week-numbering year
  for the few days at the start/end of most years (e.g. 2027-01-01 falls in
  ISO week 53 of 2026) — using it would either collide two different weeks
  onto one key or silently skip a rotation at the year boundary. `%G` is the
  ISO week-numbering year specifically to avoid this.

## Related

- Builds on ADR-0021 (burst/budget descriptors), ADR-0035 (per-person
  budget), ADR-0055/0056 (`ai-helm`/`ai-helm-values` split), ADR-0084
  (append-only rule ordering), ADR-0111 (calendar period marker), ADR-0112
  (`unit: Year` TTL trick).
- Docs: `docs/patterns/shared-cross-model-budget.md`.
- Charts/files touched (`ai-helm`): `charts/core-gateway/templates/envoyextensionpolicy-billing-period.yaml`,
  `charts/core-gateway/templates/backendtrafficpolicy.yaml`,
  `charts/core-gateway/values.yaml` (structural default only).
- Companion change (`ai-helm-values`, private repo):
  `environments/prod/values/core-gateway.yaml` — the authoritative
  `backendTrafficPolicy.monthlyBudget` block (`enabled: true` + the full
  `plans` list, monthly and weekly figures).
