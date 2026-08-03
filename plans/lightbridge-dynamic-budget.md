# Plan: Lightbridge dynamic budget refill + OPA-Wasm policy

> `~/Downloads/lightbridge_dynamic_budget_refill_opa_wasm_plan.md` assessed against the
> budget system actually in production: ADR-0021 (dual-plane authz + per-model rate
> limiting), ADR-0035 (per-person budgets), ADR-0070 (live quota in redis),
> **ADR-0084** (plan order is append-only) and **ADR-0110** (project quota tiers).
>
> Phases 1–5 land in `ADORSYS-GIS/lightbridge-authz` (its own Rust workspace + ADR
> series). Only Phase 6 touches `ai-helm`, and it touches the part that is hardest to
> change.

**Status:** Proposed plan · **Date:** 2026-07-31 · **Maintainer:** @stephane-segning

---

## 0. The finding that decides the shape of this project

**"A refill changes the allowance" is not expressible in the mechanism that enforces
budgets today.**

The monthly budget is a **static Envoy rate-limit rule**, rendered by Helm into a
`BackendTrafficPolicy` (`charts/ai-model/templates/backendtrafficpolicy.yaml`): one rule
per billing plan, the limit value baked in from `.Values.plans[].monthlyBudgetUsd`, with
`cost` charged from `llm_custom_total_cost`. The Lyft ratelimit service then keys each
counter in redis on the rule's **position in the rendered list** — plan names are `Exact`
matches and render as masked constants, so the rule index is the only carrier of plan
identity.

That is not a design detail, it's a live incident: ADR-0084 records that adding an
`enterprise` plan to a Helm **map** sorted it to index 0 mid-window, shifted `free` and
`pro` to new indices, orphaned every account's accumulated spend, and silently handed the
whole fleet a fresh budget. Hence the append-only-list rule, restated in ADR-0110 for
quota tiers.

So there is no per-account allowance to raise. There are N static limits and a counter
per (rule index, account, window). Three ways out:

| | Approach | Verdict |
|---|---|---|
| **A** | **Discrete refill tiers** — refills move an account between pre-defined budget tiers, each an append-only rule, exactly like ADR-0110's quota tiers. Authorino stamps the tier header; the grant ledger records which tier and why. | **Cheapest by far and it fits the machinery that exists.** The product cost is that refills are steps, not arbitrary amounts. If "user requests $5" can become "user requests the next tier up," this is the MVP. |
| **B** | **Grants decrement the counter** — a $5 grant subtracts 5 000 000 µ$ from the redis counter instead of raising the limit. | Mechanically the simplest, and the spec explicitly forbids it (§15) for good reasons. It also makes `gateway_ratelimit_spend_micro_usd` mean *net of grants*, silently changing what the ADR-0070 quota dashboard displays. Only worth it as a stopgap, and only with the dashboard relabelled in the same change. |
| **C** | **Replace Envoy's rate-limit enforcement with the spec's "Dynamic Budget Limiter"** — a component that reads the live allowance from Postgres and does reserve-and-settle against its own redis keys. | What the spec assumes throughout, without saying so. It is the honest end state, and it **retires ADR-0021/0084/0110's enforcement machinery**. It is also a new component in the inference data path — the same insertion-order problem as the [Censgate plan](./censgate-redact-extproc.md), and it should share that spike. Scope it as its own project, not as "Phase 6". |

**Decided (2026-07-31): option A — refills are discrete tiers.** C stays available as a
later successor if arbitrary amounts ever become a product requirement, but it is out of
scope and is no longer sharing an insertion point with the Censgate plan.

### 0.1 What option A actually costs — two consequences of the counter key

Verified against `charts/ai-model/templates/backendtrafficpolicy.yaml`: the monthly-budget
rule matches on `x-account-id` (`Distinct`) **plus** `x-billing-plan` (`Exact`, the plan
id). So exactly one budget rule matches per request, and the redis counter key is a
function of *which rule matched*. Two things follow, and neither is optional.

**(a) A tier change resets the window's counter — the refill grants the full new tier,
not the difference.** Move an account from a $15 rule to a $20 rule and it stops matching
the first and starts matching the second: new descriptor, new key, counter at zero. A user
who had consumed $15 of $15 does not get $5 more, they get $20 more. This is precisely the
ADR-0084 incident mechanism, invoked deliberately this time.

That is a **product decision, not a bug** — but it has to be stated and priced:

- Refill semantics become *"upgrade for the remainder of the period,"* not *"top up by
  £X."* The tier ladder should be defined that way (`b-base`, `b-plus`, `b-max`), with
  each tier's number being a **total** for the period.
- Repeated refills inflate: second refill ⇒ another reset. Cap the number of tier steps
  per period in policy (the grant ledger already counts them — `selfServiceGrantCount` is
  in the spec's policy input).
- The ledger stays truthful regardless: grants are immutable and record which tier and
  why, so audit is unaffected even though the runtime counter resets.
- The alternative — seeding the new counter with the old consumed value — means writing
  into the Lyft ratelimit service's key space. We already *read* those keys (ADR-0070), so
  it's possible, but writing another service's keys is fragile and I would not build it.

**(b) The tier has to reach Authorino as a claim, not a lookup.** The stamped header is
what selects the rule, so the gateway must know the account's *current* tier at request
time. The obvious route — Authorino calls Lightbridge for live budget scope — is exactly
the pattern disabled on 2026-07-02 (§1.2 below). So: **Lightbridge writes the tier to a
Keycloak user attribute when a grant lands, a protocol mapper turns it into a claim, and
Authorino stamps it with a CEL default** — the same shape `billing_plan` already uses.

Consequence to state in the product: **a refill takes effect on the next token refresh**,
not instantly. That is acceptable and honest; a "your refill is active from your next
sign-in / token refresh" message costs nothing.

**The internal plane is out of scope for refills (decided 2026-07-31).** API-key clients
(LibreChat, cron jobs, k8s SAs) authenticate differently and get a different access model;
they keep their plan-level budget with no self-service refill. That removes the only case
where the tier couldn't ride a claim.

### 0.2 The tier ladder — a separate header, not more plans (decided)

Two shapes were possible: extend the plan list (`free` → `free+1` → `free+2`, per plan), or
move the budget dimension onto its **own header**. **Decided: the separate header.**

- `x-budget-tier` is stamped on every request. Your **plan** determines the starting rung;
  a refill moves you up the ladder. The plan header keeps meaning exactly one thing.
- One ladder shared by all plans — no plans × steps combinatorics.
- The budget rules in `charts/ai-model` / `core-gateway` key on `x-account-id` (`Distinct`)
  + `x-budget-tier` (`Exact`), and the existing per-plan budget rules retire.

Starting ladder, anchored on the live values (`free` 15 → `enterprise` 1000; note the
`charts/ai-models` copies are **dormant** since the #532 shared-budget cutover, so the live
numbers are `core-gateway`'s `monthlyBudget.plans`):

```text
b-15     ← free starts here
b-30
b-60
b-120
b-250
b-500
b-1000   ← enterprise starts here
```

Roughly doubling, so a rung is always a meaningful jump. The only *policy* numbers are then
how many rungs a user may climb unaided per period (**2** to start — a free user reaches
$60, then needs a human) and what happens past that (**manual review**, already modelled).
Both live in rule data, so they change without a deploy.

⚠️ **This is a migration, and it must land on a period boundary.** Retiring the per-plan
budget rules and introducing tier rules moves every counter to a new key. Done mid-window
that is the ADR-0084 incident, deliberately, for the entire fleet at once. Done at a period
boundary — when every counter resets anyway — it costs nothing. **This is a hard scheduling
constraint on Phase 6, not a preference.**

### 0.3 ⚠️ AMENDED 2026-08-01 — the period boundary IS now the first of the month

> **This section originally said the opposite, and was correct when written.** Two ADRs
> landed between drafting and scheduling this plan and jointly replaced the window model:
>
> - **[ADR-0111](../docs/adr/0111-calendar-aligned-billing-period.md)** (2026-07-31) folds a
>   calendar `YYYY-MM` marker into the key as an `x-billing-period` descriptor, stamped by a
>   Lua `EnvoyExtensionPolicy`, so a new counter is minted at **00:00 UTC on the 1st**.
> - **[ADR-0112](../docs/adr/0112-year-unit-so-the-billing-period-is-the-only-rotation.md)**
>   (2026-08-01) sets **`unit: Year`** on all four monthly-budget rule families, because
>   ADR-0111 alone left the 30-day epoch segment *also* in the key — so counters were
>   rotating twice, and every account was being handed a spurious extra budget ~12×/year.
>
> Net effect on this plan: **the fixed 30-day epoch grid is gone as a scheduling
> constraint.** The table below is retained as history; do not schedule against it.

~~The budget window is a **fixed 30-day epoch bucket** — `floor(now / 2592000) * 2592000`~~
— superseded. Historical boundaries, for reading old incident notes only:

| Window | Starts (UTC) | Note |
|---|---|---|
| 688 | 2026-07-06 | current when this plan was drafted |
| 689 | 2026-08-05 | ⚠️ **no longer a reset** — ADR-0112 pinned the epoch |
| 690 | 2026-09-04 | ⚠️ no longer a reset |

**The live boundary is now the 1st of each calendar month, 00:00 UTC.** The nearest ones
are **2026-09-01**, 2026-10-01, 2026-11-01. Verify with one `SCAN` of the ratelimit keys
before deploying — the key now carries a `2026-08`-style segment, not a bare epoch integer.

### 0.4 Split Phase 6 — ⚠️ AMENDED 2026-08-01, the 6a rush is off

Phase 6 is two separable things, and coupling them was my mistake:

- **6a — the mechanical re-key.** Retire the per-plan budget rules, introduce the
  `x-budget-tier` ladder, stamp every account with its plan's **base rung**. Behaviour is
  identical to today; only the counter key changes. **Needs nothing from phases 1–5.**
- **6b — refills actually move accounts between rungs.** Needs phases 1–5.

> **Original decision: "6a ships 2026-08-01, four days before the window-689 boundary, and
> the boundary cleans up after us." That reasoning is void** — ADR-0112 removed the
> 2026-08-05 reset entirely, so nothing would have cleaned up after us. Had 6a shipped on
> its original date under the original rationale, the re-key would have orphaned every
> account's August spend with **no** compensating boundary until 2026-09-01. The plan was
> right about the mechanism and wrong about the calendar.

**Revised: 6a lands on a month boundary, and there is no longer any urgency to rush it.**

- The migration still moves every counter to a new key, so it still wants a boundary — but
  the boundary is now a *calendar* one, and there are twelve a year instead of a drifting
  grid. **Target 2026-09-01 00:00 UTC**, or any later 1st.
- Landing exactly on a boundary is also no longer the fiddly 00:00-UTC deploy it used to
  be: because rotation is driven by the `x-billing-period` header value rather than by
  elapsed time, a deploy in the first hours of the 1st lands in a window whose counters are
  all near-zero anyway. The cost of being a few hours late is a few hours of spend, not a
  fleet-wide orphaning.
- 6a keeps its independence from phases 1–5, so it can still go first — it just no longer
  *has* to.

**After 6a the roadmap is schedule-free.** Moving an account between existing rungs resets
only *that* account's counter — the intended refill semantic (§0.1a), not a migration.
Adding new rungs later is append-only and safe any time.

⚠️ **Co-change required in the same PR: the redis exporter's key patterns.** The ADR-0070
`prometheus-redis-exporter` SCANs `REDIS_EXPORTER_CHECK_KEYS=db0=*rule-2-match-0*,db0=*rule-7-match-0*`
— rule **indices** — and its own values file says to keep it in lockstep with
`monthlyBudget.plans`. Retiring those rules without updating the patterns makes
`gateway_ratelimit_spend_micro_usd` go silent and the `ratelimit-quota` dashboard go blank.
Update the exporter config, the `ServiceMonitor` `metricRelabelings` (they parse
`plan` out of the key) and `tools/dashboards/.../ratelimit_quota.py` together. Keep the
rotation segment as a label — dropping it collides two windows at rollover.

⚠️ **AMENDED 2026-08-01:** that rotation segment is no longer the bare `window` epoch this
plan was written against. Post-ADR-0111/0112 the key carries a calendar `2026-08` segment
(`billing_period`) plus a now-static year epoch. The exporter, the `ServiceMonitor`
relabelings and the dashboard were already migrated to `billing_period` on `main`
(`ea1c81b`, `3b1c69d`, `1d8743e`, `#866`) — so this co-change must be written against
**`billing_period`**, and re-introducing a `window` label would be a regression.

Verify the live key shape with one `SCAN` of the ratelimit keys immediately before
deploying, rather than trusting any table in this document.

⚠️ The ladder is **append-only** like everything else in this area. `b-2000` can be added
later; no rung may ever be reordered or removed.

---

## 1. Three more things the spec walks into

### 1.1 This OPA is not the OPA that was removed — and the ADR must say so

`CLAUDE.md` is blunt: the OPA path is **gone** (2026-06-04), the `lightbridge-validation`
HTTP metadata source and `enforce-valid-key` step were deleted, and nothing OPA-shaped
returns without a new ADR. That history will be the first objection this plan meets, and
it's the wrong objection.

What was removed was an **HTTP call to an external OPA inside the ext_authz hot path**,
whose missing Secret 404'd the entire gateway. What this spec proposes is an **embedded
Wasm evaluator inside a control-plane API** that decides refill requests — off the
inference path entirely, with a last-known-good fallback and a fail-closed default. The
blast radius isn't comparable. Say that explicitly in the ADR rather than letting the
name do the arguing.

### 1.2 §17 puts a database read back into the ext_authz hot path

The spec has Authorino consult Lightbridge introspection for "live identity and budget
scope." This platform tried that shape and **disabled it on 2026-07-02** (#533): the
Keycloak introspection metadata step is commented out in `security-policies.yaml` with a
long note explaining that the ext_authz timeout is shorter than the introspection
latency, so a slow dependency turns into fail-open on every request.

The spec's own instinct is right — "the limiter should retrieve the current allowance
using `budget_account_id`, not depend only on cached Authorino metadata." Keep it that
way: Authorino stamps only **stable** identifiers (`x-budget-account-id`,
`x-budget-period`), which it can do from the credential alone, and the *limiter* does the
allowance lookup. Never add a budget lookup to the Authorino step.

### 1.3 Reserve-and-settle doesn't exist today; requests are charged after the fact

Envoy's rate-limit `cost` is `llm_custom_total_cost`, computed by AIEG's ext_proc **after
the response**. So today a request is allowed and then charged — overshoot past the budget
is possible by design, bounded by one request. §16's reserve-and-settle is a genuine
improvement, but it requires a pre-request cost estimate and a component that runs before
the model call. It is therefore part of option C, not something that can be added to the
current path.

### 1.4 OPA's Wasm target has real built-in gaps — but the spec already dodges them

Not every Rego built-in compiles to Wasm. The spec passes `now` in as input rather than
calling `time.now_ns()`, which suggests the author knew. Verify the specific built-ins the
production policy needs during Phase 2, and keep the rule-data interpreter free of
anything exotic.

---

## 2. The simplification worth taking

§5 defines two authoring levels: **rule data as JSON** (for ordinary admins, the primary
path) and **advanced Rego** (for a restricted `policy-admin` role).

The §5.1 rule data is just ordered predicates over numeric fields — `consumptionRatioGte`,
`requestedAmountMicrosLte`, `selfServiceTotalMicrosLte` — with a priority and an effect.
**A plain Rust evaluator covers 100% of that with none of the Wasm machinery**: no
`opa build`, no bundle signing, no hot-swap, no last-known-good, no Wasm runtime.

Rego/Wasm earns its keep only for §5.2 — cross-entity queries ("approve only if no other
project member refilled this period"), set and aggregate logic, computed relationships
("approve up to 20% of last period's consumption"). **Decided 2026-07-31: those are wanted,
so OPA-Wasm is in scope** — but the two engines still land in order, because the spec's own
design has both:

- **Phase 2:** typed input/decision schemas + a Rust **rule-data evaluator** + the §6
  decision contract + decision logging. This is §5.1, the path ordinary administrators use,
  and it is needed regardless of whether Rego exists.
- **Phase 2b:** the **OPA-Wasm engine** behind the same §6 contract, for the `policy-admin`
  role. Bundle build/sign/verify, atomic hot-swap, last-known-good fallback, evaluation
  timeout, revision in the health endpoint.

Sequencing them this way is not deferral — it puts the entire policy *lifecycle* (§18–§21:
versioning, staging, activation, rollback, simulation, decision logs) on the cheap engine
first, where it's testable in isolation, and adds the second engine to a lifecycle that
already works. Every §19 lifecycle state applies to versioned rule data just as well as to
signed bundles.

⚠️ Verify during Phase 2b which Rego built-ins the production policy needs actually compile
to Wasm — the target does not support all of them. The spec already dodges the obvious one
by passing `now` in as input rather than calling `time.now_ns()`.

---

### 2.1 Permissions: claim → internal permission list, via config (decided)

No Keycloak roles are hardcoded. The token carries a claim (roles/groups); Lightbridge maps
claim values onto the internal `budget:*` permission set of §22 through a `config.yaml`.
That keeps the permission model ours, keeps Keycloak free to reorganise, and makes
`policy-admin` just another entry rather than a special case.

```yaml
# illustrative shape
permissionMapping:
  claim: realm_access.roles          # or a dedicated claim
  map:
    ai-user:          [budget:read, budget:self-refill]
    budget-approver:  [budget:read, budget:review]
    budget-admin:     [budget:read, budget:grant, budget:revoke, budget:audit-read]
    policy-author:    [budget:policy-read, budget:policy-write, budget:policy-simulate]
    policy-operator:  [budget:policy-read, budget:policy-activate]
  default: [budget:read]
```

Four things this has to get right:

- ⚠️ **Fail closed.** A `config.yaml` that is missing or unparseable grants **no**
  permissions and the service refuses to start — never "no mapping ⇒ allow."
- ⚠️ **Unknown claim values map to `default`, not to everything.** The mirror of the
  `FalseyValueParser` trap: an unrecognised value in a security switch must not be guessed.
- **Keep §22's write/activate split real.** `policy-author` and `policy-operator` above are
  deliberately different entries — with arbitrary Rego in scope (§2), `budget:policy-write`
  means "ship executable code into the decision path," and it should not be the same person
  who activates it.
- **Where it lives + how it reloads.** Deployed config ⇒ `ai-helm-values`
  (`environments/prod/values/lightbridge-app.yaml`), values-repo-first. Mount the ConfigMap
  as a **directory, not `subPath`** (subPath mounts never update in place), and roll pods via
  a checksum annotation — `kubectl rollout restart` is reverted by ArgoCD selfHeal. Same
  mechanism the redaction policy config needs in the [Censgate plan](./censgate-redact-extproc.md).

---

## 3. What's genuinely good here and should be kept intact

- **Immutable grant ledger + materialized balance, rebuildable by replay** (§12–§13).
  Correct, and the reconciliation test is the one that matters.
- **Integer micro-units** (§12). Already the house rule and the unit the existing
  `gateway_ratelimit_spend_micro_usd` series uses — so budget, Foundry cost and gateway
  spend stay commensurable.
- **Deterministic trigger keys with a unique constraint** (§10). This is the right answer
  to "don't grant repeatedly while the budget stays above the threshold," and the
  `auto:{revision}:{period}:{account}:{rule}:{threshold}` shape is well judged.
- **Re-evaluate under lock before applying** (§11, §25.8). Right.
- **Separating `budget:policy-write` from `budget:policy-activate`** (§22). Right.
- **The failure-mode table** (§23) is the best part of the document. Keep it as the test
  matrix.
- **Stable runtime counter identity** (§15). Right in principle — note that today's keys
  are the Lyft service's, which embed the rule index, so "stable identity" is exactly what
  option C would fix and what options A and B live without.

---

## 4. Sequencing

| Phase | Where | Notes |
|---|---|---|
| 1 — Grant/request domain | `lightbridge-authz` | Unchanged from the spec. Ledger, balances, idempotency, replay tests. |
| 2 — Rule-data evaluator | `lightbridge-authz` | §2 above. Decision contract §6 is the seam. |
| 3 — Policy management | `lightbridge-authz` | §18–§20 lifecycle over versioned rule data. Simulation endpoint. |
| **2b — OPA-Wasm engine** | `lightbridge-authz` | Second engine behind the §6 contract, for `policy-admin`. Bundle build/sign/verify, atomic hot-swap, last-known-good, eval timeout, revision in `/health`. Lands onto the lifecycle Phase 3 already built. |
| 4 — Refill workflows | `lightbridge-authz` | User request, admin grant, review queue, expiry. **OIDC users only** — the internal/API-key plane is excluded (§0.1). |
| 5 — Automatic augmentation | `lightbridge-authz` | Trigger keys, worker, scheduled reconciliation. |
| **6a — Re-key to the tier ladder** | **`ai-helm`** + Keycloak | ⚠️ **AMENDED — targets a month boundary (2026-09-01 or later), not 2026-08-01** (§0.4; ADR-0112 removed the boundary the original date was racing). May still go ahead of phases 1–5; no longer has to. Tier rules replace the per-plan budget rules; every account lands on its plan's base rung; behaviour unchanged. + Keycloak attribute → protocol mapper → claim → Authorino CEL stamp. ⚠️ Same PR must update the redis-exporter key patterns, the ServiceMonitor relabelings and the `ratelimit_quota` dashboard (now keyed on `billing_period`), or the quota board goes blank. No rung may ever be reordered or removed (ADR-0084). |
| **6b — Refills move rungs** | `lightbridge-authz` + Keycloak | Grants write the tier attribute. No schedule constraint — a rung change resets one account's counter, which is the intended semantic (§0.1a). |
| 7 — Hardening | both | Metrics per §21, alerts, load tests. Include a test that a tier change produces the expected new counter key and that the old one is left orphaned by design (§0.1a). |

ADRs: one in `lightbridge-authz` for the grant/ledger domain model; one in `ai-helm` for
the Phase-6 enforcement decision (this is the one that touches ADR-0021/0084/0110 and
must say which of A/B/C it chose and why); one more if OPA-Wasm lands later.

## 5. Open questions

1. ~~**Can refills be discrete tiers?**~~ — **answered 2026-07-31: yes.** Option A. See
   §0.1 for the two consequences that now need decisions (below).
2. ~~**Do API-key clients get refills?**~~ — **answered: no.** Internal/API-key clients get
   a different access model and keep plan-level budgets. Refill is OIDC-only.
3. ~~**Define the tier ladder**~~ — **answered:** separate `x-budget-tier` header, ladder in
   §0.2, 2 unaided rungs per period to start.
4. ~~**Confirm the reset semantics**~~ — **answered: correct as described.**
5. ~~**Does anyone need arbitrary Rego?**~~ — **answered: yes**, so OPA-Wasm is in scope as
   Phase 2b (§2).
6. ~~**Keycloak role mapping**~~ — **answered:** roles ride a **claim**, and Lightbridge maps
   claim values → the internal `budget:*` permission list via a `config.yaml`. See §2.1.
7. ~~**Which period boundary?**~~ — **answered: the next achievable one.** ⚠️ **AMENDED
   2026-08-01:** boundaries are now **calendar month starts** (00:00 UTC on the 1st), not
   30-day epoch buckets — ADR-0111 + ADR-0112, see §0.3. So the target is **2026-09-01**,
   with 2026-10-01 as fallback. Phases 1–5 no longer have to land before it: 6a is
   independent of them, and 6b carries no boundary constraint at all.
8. **Who actually reviews** in the manual-review flow — which claim value maps to
   `budget:review`? A mapping mechanism doesn't pick the people.
