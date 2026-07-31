# ADR-0111: Fold a calendar billing-period marker into monthly-budget rate-limit keys

**Status:** Accepted
**Date:** 2026-07-31
**Deciders:** @stephane-segning

## Context

Every per-account/per-plan/per-tier monthly budget rule in this repo
(`charts/core-gateway/templates/backendtrafficpolicy.yaml`'s shared plan budget,
ADR-0084/#532; `charts/ai-model/templates/backendtrafficpolicy.yaml`'s per-model
plan budget, tier budget and project envelope, ADR-0021/0035/0110) sets
`rateLimit.rules[].limit.unit: Month` on an Envoy Gateway `BackendTrafficPolicy`.

The intent has always been "resets on the 1st, runs to the last day of the
month." That is **not what `unit: Month` does**. Verified against Envoy
Gateway's own translator source (not just observed behavior): the underlying
Lyft ratelimit service computes the window as a **fixed 2,592,000-second
(30-day) rolling bucket**, `bucket = floor(unix_time / 2592000)`, anchored to
the Unix epoch (1970-01-01 UTC) — the same fact independently documented in
ADR-0070 and `docs/patterns/shared-cross-model-budget.md`. This has two
consequences neither doc previously drew out to a conclusion:

1. **The window has never been calendar-aligned**, and drifts further from
   calendar months every cycle — real months run 28–31 days (2,419,200 to
   2,678,400 seconds), a fixed 30-day cycle does not, so the boundary walks
   across the calendar by roughly 5 days/year.
2. **No amount of clearing Redis data fixes this.** The bucket boundary is a
   pure function of wall-clock time, not of when a key was last written or
   deleted. A Redis flush timed to "line up with Aug 1" only holds for that one
   month — the next boundary lands on the same drifting 30-day grid regardless.

This was surfaced when the maintainer asked to reset budget windows to start on
the 1st of the month, with a plan to disable every model, delete the
`BackendTrafficPolicy` objects, and wipe the Redis + LGTM (Mimir/Loki/Tempo/
Grafana) PVCs in the Hetzner cluster overnight, then restore everything a few
hours later. Investigation (four parallel research passes) found that plan
would not have achieved calendar alignment beyond the first month, and carried
two further costs for no benefit: `redis-ha` is shared with LibreChat's live
chat sessions (a full flush would have force-logged out every active
conversation), and LGTM has no read or write relationship to rate-limit
enforcement at all — it only observes the same Redis keys after the fact for
dashboards, so wiping it risked re-triggering the already-documented Mimir
memberlist ring-wedge (see `docs/migrations/2026-06-07-observability-datasource-
audit.md`) for zero benefit.

## Decision

**Fold a calendar "YYYY-MM" marker into the rate-limit key itself**, as a new
header `x-billing-period`, so a brand-new Redis key is naturally used starting
every 1st of the month — the old key just ages out on its existing 30-day TTL.
No more manual resets, ever, and no data migration at cutover.

The marker is computed by a small **Lua `EnvoyExtensionPolicy`**
(`charts/core-gateway/templates/envoyextensionpolicy-billing-period.yaml`),
targeting the `core-gateway` Gateway, unconditionally rendered (no values.yaml
flag):

```lua
function envoy_on_request(request_handle)
  request_handle:headers():replace("x-billing-period", os.date("!%Y-%m"))
end
```

`os.date("!%Y-%m")` — the leading `!` forces UTC regardless of container-local
timezone. UTC is the one billing-period authority: "the 1st of the month" means
00:00 UTC on the 1st, consistently, everywhere this is checked.

Every `unit: Month` rule gets one more `clientSelectors` header entry,
`{name: x-billing-period, type: Distinct}` — alongside the existing
`x-account-id`/`x-billing-plan` (plan budget), `x-project-id`/`x-account-id`/
`x-quota-tier` (tier budget), and `x-project-id`/`x-project-quota` (project
envelope) selectors:

- `charts/core-gateway/templates/backendtrafficpolicy.yaml` — the shared plan
  budget rule (#532).
- `charts/ai-model/templates/backendtrafficpolicy.yaml` — the per-model plan
  budget rule (dormant while `sharedBudget.enabled`), the tier budget rule, and
  the project envelope rule (ADR-0110). Tiers/envelope are currently inert
  (`tiers: []`, `projectEnvelope: {}` defaults — no AuthConfig stamps their
  headers yet), so adding the selector now is zero-risk and closes the gap
  before that wiring lands, rather than leaving a fourth rule family with the
  identical drift bug for someone to rediscover later.

**Why Lua, and why this runs correctly**: Authorino's CEL (google/cel-go) has
no clock/date function by design — it is deliberately deterministic, and
Authorino's AuthJSON injects no live timestamp either, so "what calendar month
is it" cannot be computed inside the AuthConfig's `response`/metadata blocks
(which, since ADR-0056, live out-of-repo in the private `ai-helm-values`
anyway — changing them would need cross-repo coordination for no benefit).
Envoy Gateway's `EnvoyExtensionPolicy` Lua filter is confirmed, from Envoy
Gateway's own fixed filter-order constants
(`internal/xds/translator/httpfilters.go`: `Lua=12`, `RateLimit=303`), to run
**before** the rate-limit filter in the generated HTTP filter chain — so the
header it sets is guaranteed visible when `clientSelectors` are evaluated. This
is verified post-deploy (not just trusted from source) via the live
`config_dump`, per the Verification section below.

`unit: Month` (the 2,592,000s TTL) is **left unchanged** — it now just
over-generously expires the *previous* month's abandoned key, which is
harmless. The actual "when does a fresh bucket start" question is answered
entirely by when `os.date("!%Y-%m")` flips, not by the unit's own epoch math.

Hard cutover, one PR, no feature flag. Self-contained to `ai-helm` — no
`ai-helm-values` companion change, since the Lua script is chart-owned and the
AuthConfig is untouched. `charts/core-gateway` publishes to OCI and floats on
its semver range (ADR-0055 continuous delivery), so merging to `main` is a live
deploy.

**Immediate consequence, expected and desired**: this re-keys every
`unit: Month` counter at deploy time, silently zeroing every account's
accumulated spend for the current cycle — the same class of event as the
2026-07-08 shared-budget cutover (`docs/patterns/shared-cross-model-budget.md`:
"historical per-model spend did not carry over"). If this PR doesn't merge and
deploy before 2026-08-01 00:00 UTC, a one-time manual Redis key deletion
(scoped to only the monthly-budget rule keys, never burst keys or LibreChat
session keys) may be run as a fallback to give August a clean start regardless
— see the runbook in `docs/patterns/shared-cross-model-budget.md`. That manual
step becomes unnecessary for every month from here on once this ships.

## Consequences

**Positive**

- Budget windows are calendar-aligned from here on, permanently, with zero
  manual intervention required ever again.
- Zero downtime, zero data migration — old keys simply age out on their
  existing TTL.
- Closes the identical drift bug on all four `unit: Month` rule families in one
  pass (plan budget × 2 chart paths, tier budget, project envelope), not just
  the one that prompted the investigation.

**Negative**

- The Lua filter runs on 100% of gateway traffic (every route, not just budget-
  metered ones) — cost is one `os.date` call + one header replace per request,
  negligible, but it is new code in the hot path with a non-zero blast radius
  if it were ever wrong (e.g. malformed date format breaking `Distinct`
  matching for every rule at once).
- Couples the correctness of this fix to Envoy Gateway's *internal* filter-
  order constants, which are not a published, versioned public API guarantee —
  re-verify (via `config_dump`, per Verification below) after any future Envoy
  Gateway version bump.
- One more moving part in the rate-limit key composition to reason about when
  debugging a stuck/wrong budget counter.

**Neutral / follow-ups**

- The `ai-helm-values` `prometheus-redis-exporter` key-parsing regex (used for
  the quota dashboard, ADR-0070) needs to include the new `x-billing-period`
  segment — the same class of open follow-up ADR-0084/0070 already left for
  the 2026-07-08 shared-budget cutover. Separate PR, cross-repo.
- Tier/project-envelope rules now carry the marker even though they're
  currently inert (no AuthConfig stamps their other headers yet) — harmless,
  and means that wiring (tracked separately, ADR-0110 §4) inherits calendar
  alignment for free whenever it lands.

## Alternatives considered

- **Authorino HTTP metadata external callout**, returning
  `{"billing_period": "2026-07"}` for CEL to fold into
  `response.success.dynamicMetadata`. Rejected: adds a network hop on every
  authenticated request (a new failure mode on the critical auth path), and
  requires editing the private `ai-helm-values` AuthConfig (cross-repo
  coordination) for no advantage over Lua's in-process, zero-hop, guaranteed-
  ordered alternative.
- **Gateway API's core `HTTPRoute.RequestHeaderModifier`.** Confirmed (spec
  reading) it only accepts literal static header values — no templating or
  expression support — so it structurally cannot produce a rolling "current
  calendar month" string. Not viable without a compute step.
- **Raw `EnvoyPatchPolicy`.** This repo already retired its one use of this
  (ADR-0039, SNI transport-socket injection) in favor of native Gateway API/
  Envoy Gateway CRDs (ADR-0040), after Envoy Gateway's translator didn't
  reliably honor it for that use case. `EnvoyExtensionPolicy` is the native,
  supported mechanism for exactly this kind of request manipulation and avoids
  reopening that class of risk.
- **Periodic manual Redis flush, indefinitely, timed to each month boundary.**
  Rejected as the permanent solution: structurally cannot fix the drift — the
  window boundary is a pure function of wall-clock time, not of when data was
  last cleared — so this would recur forever and drift a little further off-
  calendar every cycle. Retained only as a one-time fallback for the current
  month if this ADR's fix doesn't ship before the boundary (see Decision).
- **The originally proposed disable-models + delete-BackendTrafficPolicies +
  wipe-Redis-and-LGTM-PVCs + multi-hour maintenance window.** Rejected: doesn't
  fix drift beyond the first month (see Context), the Redis wipe would have
  logged out every live LibreChat session (shared store), the LGTM wipe has no
  relationship to rate-limit enforcement and risks the documented Mimir ring-
  wedge for no benefit, and the model-disable window is unnecessary once the
  actual fix is a near-instant, scoped Redis key operation rather than a data
  migration.

## Related

- Builds on: ADR-0021 (burst/budget descriptors), ADR-0035 (per-person
  budget), ADR-0070 (ratelimit quota observability — first documented the
  2,592,000s fact), ADR-0084 (append-only plan-list contract), ADR-0110
  (project quota tiers + project envelope).
- Charts/files touched:
  `charts/core-gateway/templates/envoyextensionpolicy-billing-period.yaml`
  (new), `charts/core-gateway/templates/backendtrafficpolicy.yaml`,
  `charts/ai-model/templates/backendtrafficpolicy.yaml`,
  `docs/patterns/shared-cross-model-budget.md`,
  `docs/architecture/03-gateway-components.md`.
- Follow-up (cross-repo, `ai-helm-values`): update the
  `prometheus-redis-exporter` key-parsing regex to include the new
  `x-billing-period` segment.
