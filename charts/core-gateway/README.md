# `core-gateway` — the Envoy Gateway control objects for the public + internal AI planes

This chart owns the *gateway itself*, not the workloads behind it: the `GatewayClass`, the
`Gateway`, its `EnvoyProxy` (access log, telemetry, HPA/capacity), the ingress `Certificate`s, the
`BackendTrafficPolicy` rate-limit rules, and the **one** `EnvoyExtensionPolicy` every extension on
this Gateway has to share.

Everything *deployed* — the values, the per-plane `AuthConfig`s, the image tags — lives in the
private `ai-helm-values` repo (ADR-0055/0056). This README documents chart behaviour; the values
repo's `docs/runbooks/` documents operating it.

> **One `EnvoyExtensionPolicy` per targetRef, and this chart already uses it.** A second policy
> aimed at the same Gateway is rejected `Accepted: False, reason: Conflicted` and silently never
> attaches — caught live on 2026-08-03, when a `ghp_` token sailed through an ext_proc filter that
> was never wired in. Every Lua entry and every ext_proc entry goes into
> `templates/envoyextensionpolicy-billing-period.yaml`. Read that file's header before adding one.

The three `lua` entries it carries, in Envoy Gateway's fixed order (`12 + index`, always after
ext_authz at 5):

| # | entry | what it does | ADR |
|---|---|---|---|
| 12 | billing-period | stamps `x-billing-period` (`%Y-%m`) and `x-billing-week` (`%G-W%V`) so the rate-limit keys rotate on a real calendar boundary | [ADR-0111](../../docs/adr/0111-calendar-aligned-billing-period.md), [ADR-0119](../../docs/adr/0119-weekly-sub-budget-anti-front-loading.md) |
| 13 | model-policy | enforces the per-project model allowlist Authorino publishes but does not apply | [ADR-0133](../../docs/adr/0133-enforce-model-allowlist-in-a-gateway-lua-filter.md) |
| 14 | **budget-limiter** | turns a spent ledger balance into a `402` — the section below | [ADR-0137](../../docs/adr/0137-budget-limiter-enforced-in-lua-not-authorino-denial.md) |

---

## The budget limiter

**Status: ENFORCING in prod since 2026-09-04T19:41Z.** This is not a description of an intended
rollout; it is what the public API-key plane does to a spent account right now.

Script: `files/budget-limiter.lua` (its header carries the authoritative decision table).
Decision: [ADR-0137](../../docs/adr/0137-budget-limiter-enforced-in-lua-not-authorino-denial.md).
Design, end to end: **lightbridge-authz ADR-0034**.

### How it got here

| | when (UTC) | change in `ai-helm-values` | outcome |
|---|---|---|---|
| shadow | **2026-09-04 16:21Z** | [#414](https://github.com/ADORSYS-GIS/ai-helm-values/pull/414) — `enabled: true`, `shadowMode: true` | decisions recorded, nothing refused, **0 5xx** |
| enforce | **2026-09-04 19:41Z** | [#417](https://github.com/ADORSYS-GIS/ai-helm-values/pull/417), commit `991268b` — `shadowMode: false` | `402` live, **0 5xx** |

An earlier shadow attempt on 2026-09-03 (ai-helm-values#366) took *every route on the Gateway* to
`directResponse: 500` and was rolled back within the minute (#367, recorded in #368) — Envoy
Gateway's controller runs the script in gopher-lua before the data plane ever sees it, and
`rawget(_G, …)` is nilled there. That is why "0 5xx" is the metric quoted above, and why
`tests/envoy-gateway-lua/run.sh` (EG's own translator, over the rendered chart) is now a CI gate
that runs on every promotion.

### The two flags, and nothing else

```yaml
budgetLimiter:
  enabled: false      # values.yaml:438 — chart default. false renders NOTHING, not even a comment.
  shadowMode: true    # values.yaml:449 — chart default. Compute + record, refuse nothing.
  refillUrl: ""       # values.yaml:453 — goes into the 402 body verbatim; "" keeps the key present.
```

Prod sets `enabled: true` and `shadowMode: false` in `ai-helm-values`. **Both defaults here are the
safe direction on purpose**: a chart promotion must never be able to start refusing paid traffic,
and the shipped `.lua` makes the same choice independently — with the `BUDGET_LIMITER_CONFIG` table
absent entirely it falls back to shadow-on, and `tests/budget-limiter/run.sh` has a listener that
proves it.

**Turning `enabled: true` on without the matching `dynamicMetadata.budget` block in the AuthConfig
503s every model request.** The two halves ship together; `ai-helm-values`
`docs/runbooks/budget-limiter-rollout.md` sequences them.

### What the caller actually gets

The filter reads one thing — dynamic metadata, namespace `envoy.filters.http.ext_authz`, key
`budget` — and compares one number to zero. It computes no balance.

| condition | status | body `error` / `reason` | why this and not something else |
|---|---|---|---|
| metadata absent, **no** `x-ai-eg-model` | *allow* | — | not a metered request: a model-catalog path the AuthConfig's `when` gate skips, or an `/mcp/*` route with its own `SecurityPolicy` |
| metadata absent, `x-ai-eg-model` **present** | **503** | `budget_unavailable` / `budget_metadata_absent` | a metered model request that never passed the AuthConfig which publishes the budget — the chain is misconfigured or misordered. Allowing it would make every half-deployed chain silently unmetered |
| `enforced: false` | *allow* | — | the internal plane (LibreChat, cron, k8s SAs). Published **explicitly**, so "out of scope" stays distinguishable from "misconfigured" |
| `known: false` | **503** | `budget_unavailable` / `budget_unknown` | **our** outage, not the user's spent budget. Different status, different message, different runbook |
| `remaining_micros` unparseable | **503** | `budget_unavailable` / `budget_malformed` | the two sides have drifted; agree with the strict side |
| `remaining_micros > 0` | *allow* | — | |
| `remaining_micros <= 0` | **402** | `budget_exhausted` | the only refusal a top-up fixes |
| the script raises | **503** | `budget_unavailable` / `budget_limiter_error` | the `pcall` guard. Envoy's own default for an uncaught Lua error is to log and **continue** — fail *open* — which an enforcement point must not do |

**402 vs 503 is the distinction the whole design turns on.** A `402` means "this account is spent,
top up or wait for the reset". A `503` means "we could not tell", and no amount of money fixes it.
Anything that blurs the two teaches clients to retry-with-a-credit-card against our own outages.

The `402` body:

```json
{
  "error": "budget_exhausted",
  "account_id": "<the account_id claim, not sub>",
  "remaining_micros": 0,
  "next_reset_at": "<RFC3339>",
  "refill_url": "<budgetLimiter.refillUrl>",
  "message": "This account has no budget left for the current period. Top up, or wait for the next reset."
}
```

Two fields regularly get misread:

- **`remaining_micros` is hard-coded `0`, by design** (`exhaustedBody()`). The real balance is
  signed and can be negative — over-consumption is forgiven deliberately (lightbridge-authz ADR-0034
  §15). The *body* answers "how much is left"; that answer is zero. The overdraft is our accounting,
  and it is still recorded in the dynamic metadata and the access log.
- **`next_reset_at` is the account's effective schedule**, straight from the introspection's
  `budget_next_reset_at`. It is **not** derived from `x-billing-period`/`x-billing-week` — those key
  the cost buckets below, which reset on their own calendar.

`snapshot_age_seconds` is read, recorded, logged — and **never consulted by the decision**. A
stale-but-known balance is still the ledger's answer; letting an age threshold refuse traffic would
invent an undocumented refusal reason inside a filter whose whole principle is that every branch is
explicit. It is absent, never `0`, when the AuthConfig does not publish it.

### Rollback is one value

```yaml
# ai-helm-values environments/prod/values/core-gateway.yaml
budgetLimiter:
  shadowMode: true      # ← flip this. That is the whole rollback.
```

No chart release, no filter removal, no pod restart, no AuthConfig change. The filter stays in the
chain, keeps computing and recording, and refuses nothing. `enabled: false` is the heavier hammer
(it removes the filter and, with it, all the shadow telemetry) and is only right if the filter
itself is suspect rather than its verdicts.

### Where the balance comes from

One metadata call per request, since lightbridge-authz ADR-0034 §15 (chart side landed in
[#1109](https://github.com/ADORSYS-GIS/ai-helm/pull/1109)):

```
ext_authz (filter 5) → lightbridgeintrospect (authz-opa)
                        └─ Index Scan on budget_remaining_snapshots_pkey  (~20 µs, 3 buffer hits)
                     → response.success.dynamicMetadata.budget
                        { enforced, known, remaining_micros,
                          next_reset_at, account_id, snapshot_age_seconds }
budget-limiter.lua (filter 14) → reads exactly that table
```

It used to be a second, serialised `budgetremaining` metadata step into `authz-budget` (p50 10 ms,
614 ms tail). That step is deleted. **Nothing in this chart changed when it moved** — same
namespace, same key, same five fields — which is the dividend of publishing a shaped table instead
of piping an upstream response body through.

`lightbridgeintrospect` runs only for non-Keycloak credentials carrying `api_key_id`. The
GitHub-Actions plane (`repobinding`) and the legacy Keycloak plane have no introspection step, so
their AuthConfigs publish `enforced: false` and the filter allows — a deliberate fail-open narrowing
on two minority planes, taken for the one-call guarantee. The **catch-all AuthConfig is deny-all**,
so no request reaches the Lua on that path at all.

### Observing it

Decisions land in the `lightbridge.budget_limiter` dynamic-metadata namespace and are surfaced in
the access log (rendered only when `budgetLimiter.enabled`, `templates/envoy-proxy.yaml:208-241`):

| field | values |
|---|---|
| `budget.decision` | `allow` / `deny` — in shadow, `deny` means *would have* denied |
| `budget.reason` | the reason column of the table above — **this is the field to group by** |
| `budget.remaining_micros` | the real signed balance, not the body's `0` |
| `budget.shadow` | `true`/`false` — tells a shadow `deny` apart from a real one |
| `budget.snapshot_age_seconds` | observability only; absent, not `0`, when unpublished |

A rising `budget.reason=budget_unknown` count with a flat `budget_exhausted` count is *our* problem
(the 15-second refresher, or the introspection) — not accounts running dry. That is precisely the
pair a 402 count alone cannot separate.

### The cost buckets are still there, until 2026-10-01

The shared cross-model **monthly** and **weekly** `BackendTrafficPolicy` rules
(`templates/backendtrafficpolicy.yaml`, [ADR-0111](../../docs/adr/0111-calendar-aligned-billing-period.md) /
[ADR-0112](../../docs/adr/0112-year-unit-so-the-billing-period-is-the-only-rotation.md) /
[ADR-0119](../../docs/adr/0119-weekly-sub-budget-anti-front-loading.md)) were **not** removed when
the limiter started enforcing. Per the owner's ruling they stay until **2026-10-01**, and until then
the two mechanisms compose:

> **effective cap = `min(plan bucket, ledger)`** — a request is refused if *either* says stop.

They are not redundant while both exist, and they do not answer the same question: the bucket is a
per-plan **pacing** limit keyed on the calendar marker and refuses with **429**; the limiter is the
account's **actual money** and refuses with **402**. A client that treats them as the same thing
will retry the wrong one.

#### The 2026-10-01 commit

When the date arrives, the change is small and entirely local:

1. `charts/core-gateway/templates/backendtrafficpolicy.yaml` — delete the `monthlyBudget` rule loop
   and the `weeklyBudgetUsd` block that renders after it.
2. `charts/core-gateway/values.yaml` — delete the `monthlyBudget` / plan `weeklyBudgetUsd` keys.
3. `ai-helm-values` `environments/prod/values/core-gateway.yaml` — delete the `monthlyBudget.plans`
   list that overrides them.
4. `charts/ai-model` carries the same per-model rate-limit shape — check it in the same commit
   rather than after, since the two lists have historically drifted.

Deleting the rules also retires the rate-limit keys they own; the `x-billing-period` /
`x-billing-week` markers (Lua entry 12) have **other** consumers and are not deleted with them.

### Tests

```bash
./tests/budget-limiter/run.sh     # needs docker, curl, python3, helm
```

Two gates, in this order, and the order is the lesson:

1. **`tests/envoy-gateway-lua/run.sh`** (called first) — Envoy Gateway's *own* translator over the
   rendered chart, for every `lua` entry, in shadow **and** enforcing renders. Fails on a
   non-`Accepted` policy or any route rewritten to a 500.
2. **23 data-plane cases** replaying `files/budget-limiter.lua` byte-for-byte through
   `envoyproxy/envoy:distroless-v1.38.3` — the image the prod data plane runs — across five
   listeners: enforce, shadow, no-config, fault-injected, and fault-injected-with-the-pcall-removed
   (which proves the guard is load-bearing rather than decorative).

On 2026-09-03 all of stage 2 passed against a script that could not be admitted to a cluster at all.
**A test that exercises the data plane cannot validate control-plane admission.** Stage 1 exists
because of that day.
