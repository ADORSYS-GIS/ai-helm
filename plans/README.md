# Plans — the four directions and one roadmap

Four specs arrived on 2026-07-31. This is the consolidated view: what each one really is,
what they share, what order to build them in, and what I'd cut.

**Status:** Proposed · **Date:** 2026-07-31 · **Maintainer:** @stephane-segning

## Decisions taken (2026-07-31)

| # | Question | Decision |
|---|---|---|
| 1 | Refill counter-reset semantics | **Correct as described** — a refill is an upgrade for the remainder of the period, not a top-up |
| 2 | Multi-customer? | **No.** Us and repos we manage. Selling it means the customer runs their own install → *single-tenant, deployable*, not SaaS |
| 3 | LGTM multi-tenancy | **Do not turn it on.** Single tenant for us; a customer decides for their own install |
| 4 | What is the product | **The Grafana dashboards.** Per-tenant redaction policy is a "keep the door open," not a requirement |
| 5 | Tier ladder | **A separate `x-budget-tier` header**, not more plans. Ladder `b-15 … b-1000`, 2 unaided rungs per period. ⚠️ Ships on a **period boundary** — which since ADR-0111/0112 means the **1st of a calendar month**, not a 30-day epoch bucket |
| 6 | Who gets refills | **OIDC users only**, via self-service in `lightbridge-ss` (converse-ui). Internal/API-key clients get a different access model — no refill |
| 7 | Arbitrary Rego | **Wanted** → OPA-Wasm is in scope as Phase 2b, behind the same §6 decision contract as the rule-data evaluator |
| 8 | Loki retention | Keep **90 d**, document it as configurable |
| 9 | Redacted-token billing | Document the consequence; no change |
| 10 | `failOpen: false` in production | **Yes** |
| 11 | Repo name | **`ADORSYS-GIS/lightbridge-governance`** |
| 12 | Hostnames | `governance.ai.camer.digital`, `otel.ai.camer.digital` |
| 13 | Keycloak roles | **Not hardcoded.** Roles ride a claim; Lightbridge maps claim values → the internal `budget:*` permission list via `config.yaml`. Fail-closed, unknown values → `default` |
| — | Phase 6 cutover date | **Split.** ⚠️ **AMENDED 2026-08-01** — the original "6a ships 2026-08-01, ahead of the window-689 boundary" is **void**: ADR-0112 removed that boundary. 6a now targets **2026-09-01 or any later 1st**; 6b still has **no date constraint**. The window *is* a calendar month now |
| 14 | Redaction engine | ~~[`censgate/redact`](https://github.com/censgate/redact) — it already ships `redact-gateway`; no rewrite needed~~ ⚠️ **REVERSED 2026-08-02 (ADR-0115).** Its only published image cannot execute — builder glibc newer than its distroless runtime, so every container exits with `GLIBC_2.38 not found` on any host ([censgate/redact#114](https://github.com/censgate/redact/issues/114)). Now **first-party**, in `lightbridge-governance`, wrapping the [`pii`](https://crates.io/crates/pii) crate as a library. The front-proxy-over-`ext_proc` decision (ADR-0113) is unaffected and stands |

Consequences: plan 2 loses its whole tenancy problem (§3 option C by default, B never
needed for us); plan 1 loses the public-App/installation-webhook path; plan 4 gets the
`x-budget-tier` ladder plus OPA-Wasm; plan 3 leads with the off-the-shelf `redact-gateway`
front proxy.

**Repos.** `lightbridge-authz` (exists) hosts `lightbridge-api` → budget-service.
`lightbridge-ss` / converse-frontends (exists) is the self-service UI — **no new Vite app
needed**. `lightbridge-governance` (new, Rust) holds the registry + both connectors.
`censgate/redact` is upstream. Governance views are Grafana, so the only homeless surface
is Foundry's integration-setup page — one server-rendered page on the governance API, or a
screen in `lightbridge-ss`.

---

| # | Plan | Source spec | What it really is | Touches the inference data path? |
|---|---|---|---|---|
| 1 | [github-copilot-governance.md](./github-copilot-governance.md) | GitHub Copilot Governance MVP | A **pull** connector: poll GitHub's daily Copilot reports, store, report on them | No |
| 2 | [microsoft-foundry-governance.md](./microsoft-foundry-governance.md) | Microsoft Foundry Governance MVP | A **push** connector: authenticated OTLP ingestion of *customer* agent telemetry | No |
| 3 | [censgate-redact-extproc.md](./censgate-redact-extproc.md) | Envoy AI Gateway + Censgate Redact `ext_proc` | PII redaction/blocking **inside the gateway filter chain** | **Yes** |
| 4 | [lightbridge-dynamic-budget.md](./lightbridge-dynamic-budget.md) | Lightbridge Dynamic Budget Refill + OPA-Wasm | Self-service budget refills, policy-driven, with an immutable grant ledger | **Yes**, at Phase 6 |

Also here: [openai-alternative-plan.md](./openai-alternative-plan.md) (2026-06-04, prior work).

---

## 1. Sequencing insight — and how the 2026-07-31 decision changed it

**As originally written, plans 3 and 4 were the same problem wearing different clothes.**
Censgate needs a processor running *before* Envoy AI Gateway's ext_proc; plan 4's
"Dynamic Budget Limiter" (option C) needed a component in the request path reading a live
allowance. Both hinged on one question: can we insert a component at a chosen position in
the filter chain on EG v1.8.2 + AIEG v1.0.0 without forking the AI Gateway?

**That merged only if plan 4 went with option C. It didn't** — refills are discrete tiers
(option A, decided 2026-07-31), which is expressible in the existing append-only
rate-limit rule machinery with **no new data-path component at all**.

Consequences:

- **Plan 4 leaves the red-risk tier.** Its runtime phase becomes an append-only tier rule
  set in `charts/ai-model` plus a Keycloak claim — the same shape as ADR-0110's quota
  tiers. It can move much earlier in the roadmap.
- **The ordering spike now has one consumer, not two.** It's still needed for plan 3, but
  it can no longer be amortised across two projects — which weakens the case for
  maintaining an AI Gateway fork, since a fork would now serve exactly one feature.
- **Plan 3 becomes the only data-path project**, and can be deferred or dropped on its own
  merits without holding anything else up.

Plan 4 carries two consequences of option A that need product answers, not engineering
ones — a tier change **resets the window's counter** (so a refill grants the full new
tier, not the difference) and the tier must arrive as a **Keycloak claim**, so refills take
effect at the next token refresh. Both are written up in plan 4 §0.1.

---

## 2. What plans 1 and 2 share

They are **one product with two connectors**, which plan 1's amendment note already
records. Shared foundations, built once:

- **Tenant → Application → Environment → Integration registry** with credential issuance
  and revocation. Both connectors need it, and retrofitting `tenant_id` underneath
  existing tables means rewriting every primary key. **Build it first.**
- **One `governance` role/database** on the existing `lightbridge-main-db` CNPG cluster —
  a ~30-line addition alongside the six roles already there, not a new database.
- **The Grafana-reads-Postgres pattern** (ADR-0063 precedent, `uid: keycloak`). It's what
  lets both plans drop most of their Mimir metric-publishing and their low-cardinality
  label constraints: usernames, repos, teams and applications become *columns*.
- **Integer micro-USD everywhere.** Already the house unit and what
  `gateway_ratelimit_spend_micro_usd` uses — so Copilot spend, Foundry estimated cost,
  Lightbridge grants and existing gateway spend all stay commensurable in one view.

---

## 3. Risk, honestly ranked

| Risk | Why |
|---|---|
| 🟢 **Plan 1 (Copilot)** | Nothing in production changes. Worst case is a CronJob that doesn't run. |
| 🟡 **Plan 2 (Foundry)** | New namespace, contained blast radius — **except** the Authorino AuthConfig edit. A `sharedSecretRef` to a missing Secret fails AuthConfig readiness and 404s the **entire gateway**. That is the OPA-removal outage, and it is one YAML mistake away. |
| 🟡 **Plan 4, phases 1–5** | Control-plane only, in its own repo, behind its own API. Safe to build. |
| 🟡 **Plan 4, phase 6 (option A)** | No new data-path component — but it edits the append-only rate-limit rule list, and ADR-0084 exists because a *Helm map key sort* silently rebudgeted the entire fleet. Mechanically small, unforgiving of carelessness. |
| 🔴 **Plan 3 (Censgate)** | New mandatory hop in the path of every AI request, `failOpen: false`, and possibly a maintained fork of the AI Gateway controller. |

With option A chosen, **plan 3 is the only red row** — the only project that mutates the
inference data path. It goes last and gets its own ADR.

---

## 4. The single roadmap

Sizes are relative, not calendar commitments.

### ~~Wave −1 — The budget re-key (2026-08-01, ahead of everything)~~ → folded into Wave 4

> ⚠️ **AMENDED 2026-08-01.** This wave existed *only* because the budget window was a
> drifting 30-day epoch bucket with a boundary at 2026-08-05 that would "absorb the reset."
> Two ADRs landed in the meantime and removed that boundary:
> **[ADR-0111](../docs/adr/0111-calendar-aligned-billing-period.md)** put a calendar
> `YYYY-MM` `x-billing-period` marker in the key, and
> **[ADR-0112](../docs/adr/0112-year-unit-so-the-billing-period-is-the-only-rotation.md)**
> set `unit: Year` so that marker is the *only* rotation.
>
> **Consequence: shipping 6a today would have been the worst option, not the best.** The
> 2026-08-05 reset it was counting on no longer happens, so the re-key would have orphaned
> every account's August spend with no compensating boundary until 2026-09-01.
>
> **Phase 6a moves to Wave 4** and targets a **calendar month boundary (2026-09-01 or any
> later 1st)**. It keeps its independence from phases 1–5 and may still be pulled forward —
> it simply is no longer date-forced, and there is now no calendar-pinned item anywhere in
> this roadmap. Full reasoning: plan 4 §0.3–§0.4.

### Wave 0 — Answer the blocking questions (~1 week, mostly spikes)

Cheap, and each one can invalidate weeks of downstream work.

| Spike | Plan | Question | If it fails |
|---|---|---|---|
| GitHub App token access | 1 | Do App installation tokens work on `/copilot/metrics/reports/*` with Copilot metrics + seat management + **Members: read**, and the org's "Copilot metrics API access policy" enabled? | Fall back to a fine-grained PAT — structurally cheap |
| **Tenancy decision** | 2 | LGTM is single-tenant (`multitenancy_enabled: false`, `auth_enabled: false`, Tempo `replicas: 1`) — so `X-Scope-OrgID` is a no-op. A, B or C? | Recommendation: C now, B as end state |
| **Filter ordering** | 3 | Can a custom processor be positioned before AIEG's on EG v1.8.2 / AIEG v1.0.0? Four configurations, read `/config_dump` | Fork vs. front-proxy — decide with evidence, not the spec's hedge. Note this now serves **one** feature, so a fork is harder to justify |
| ~~Discrete refill tiers?~~ | 4 | **Answered 2026-07-31: yes** → option A | — |
| Streaming client | 3 | Is there a *non-streaming* production client to canary with? | No ⇒ SSE moves into the MVP, not post-MVP |

**Do not start Wave 1 before these are answered.** Every one of them is an afternoon, and
each one is currently load-bearing for a multi-sprint commitment.

### Wave 1 — Shared foundation

- Governance registry: tenant / application / environment / integration / agent.
- `governance` role + database on `lightbridge-main-db`; credential issuance + revocation;
  `/internal/v1/resolve`.
- Repo: `ADORSYS-GIS/lightbridge-governance` (connectors as crates).
- *In parallel, different repo:* Lightbridge plan 4 **Phase 1** — grant ledger, balances,
  idempotency, replay tests. No dependency on the above.

### Wave 2 — First value, lowest risk

- **Plan 1 complete**: Copilot ingestion → Postgres + S3, ServiceMonitor, four dashboards,
  five alerts. Proves the registry and the Postgres-to-Grafana pattern end to end.
- *Parallel:* Lightbridge **Phases 2–3** — rule-data evaluator (**not** OPA-Wasm; see plan
  4 §2) + policy lifecycle, versioning, simulation.

### Wave 3 — Ingestion and workflows

- **Plan 2**: `otel.` host + AuthConfig #3 + collector + three-signal fan-out + privacy
  modes + normalization. ⚠️ Secret-first on the AuthConfig, or gateway-wide 404.
- *Parallel:* Lightbridge **Phases 4–5** — refill workflows, review queue, automatic
  augmentation with deterministic trigger keys.

### Wave 4 — Governance surface

- Cost engine, five policies, evidence to S3, the four Grafana views, one integration-setup
  page, golden dataset in CI.
- Lightbridge **Phase 6a** — the fleet-wide re-key (moved here from the retired Wave −1).
  Append-only budget-tier rules in `charts/ai-model`, rendered strictly **after** the
  ADR-0110 quota-tier rules so no existing rule index shifts, + the Keycloak attribute →
  protocol mapper → claim → Authorino CEL stamp. ⚠️ **Must land on a calendar month
  boundary (2026-09-01 or a later 1st)** — see plan 4 §0.3–§0.4. Small, but it is the
  ADR-0084 blast zone — one PR, one reviewer, one ADR.
- Lightbridge **Phase 6b** — grants write the tier attribute. **No date constraint**, once
  6a has done the re-key.

### Wave 5 — Data path (gated on the Wave 0 ordering spike)

- **Plan 3** only: redact processor, canary internal gateway, filter-order verification on
  every replica, fail-closed and rollback drills, plus the SSE decision.
- Now separable — nothing else waits on it, so it can be deferred or dropped on its own
  merits.

---

## 5. What I'd cut or change

| Change | From | Why |
|---|---|---|
| **Parquet-on-S3 query layer** → Postgres | Plan 1 | Deletes the Parquet writer, the S3 query engine, the normalizer and the metrics publisher. S3 stays raw archive + replay. |
| **Memcached** → in-process `moka` | Plans 1, 2 | There is no memcached in this cluster and the alternative (redis-ha) is TLS-only with a password — real wiring for a single-replica API over 6-hourly data. |
| **Backfill `Job`** → self-healing CronJob | Plan 1 | A one-shot Job fights ArgoCD selfHeal; reading the DB high-water mark also gives late-report recovery for free. |
| **Manual team mapping** → GitHub's own report | Plan 1 | `user-teams-1-day` exists at org scope; the spec says it's enterprise-only and is out of date. |
| **Next.js console** → four Grafana views + one page | Plan 2 | Only integration-setup genuinely needs bespoke UI. |
| **OPA-Wasm before the rule-data evaluator** → rule-data first, Wasm as Phase 2b | Plan 4 | Both are wanted (decision 7), but §5.1 rule data is the path ordinary admins use and is needed regardless. Building the policy *lifecycle* on the cheap engine first means Wasm lands onto a lifecycle that already works. |
| **Building a redaction proxy** → deploy `redact-gateway` | Plan 3 | It already exists, in Rust, Apache-2.0, with OTel metrics. `redact-core` is the library seam if/when the ext_proc variant is wanted. |
| **AI Gateway fork** → decide after the spike | Plan 3 | The spec's own hedge is "*may* not produce the required order" — and with the front proxy available, the spike may never need running. |
| **SSE as post-MVP item #1** → decided during the MVP | Plan 3 | It's the gate on production use, not a follow-up. |

---

## 6. Process

All four are governed work: the governance PR template (AI Usage Declaration,
source-of-truth link, Verification evidence) on every PR in every repo; Conventional
Commits enforced by hook + CI; values-repo-first for anything reaching `ai-helm-values`.

ADRs — ⚠️ **renumbered 2026-08-01**: 0111 and 0112 were taken by the calendar-billing-period
work while this plan sat unmerged, so these now start at **0113** (next free). Re-check
`docs/adr/` before claiming a number; this repo moves fast.

| ADR | Subject |
|---|---|
| 0113 | Governance registry + the tenancy model (including why LGTM multi-tenancy was rejected for the MVP) |
| 0114 | Copilot connector |
| 0115 | Foundry OTLP ingestion via core-gateway + Authorino |
| 0116 | Redaction placement — ext_proc vs front-proxy, fail-closed, and the billing interaction |
| 0117 | Budget refill as append-only discrete tiers (option A) — the tier ladder, the counter-reset semantics, and the Keycloak-claim propagation path. Builds on ADR-0021/0084/0110/0111/0112 |

Plus one in `lightbridge-authz` for the grant/ledger domain model.
