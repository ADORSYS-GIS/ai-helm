# Plan: Microsoft Foundry governance connector (OTLP ingestion)

> `~/Downloads/microsoft-foundry-governance-mvp-plan.md` mapped onto this platform.
> Companion to [`github-copilot-governance.md`](./github-copilot-governance.md) — the two
> specs are **one product with two connectors**, and §1 below says what that means for
> both.

**Status:** Proposed plan · **Date:** 2026-07-31 · **Maintainer:** @stephane-segning

---

## 0. The headline finding

**The LGTM stack is single-tenant today, and the spec's entire isolation model rests on
`X-Scope-OrgID`, which currently does nothing.** Verified in `ai-helm-values`:

```yaml
# environments/prod/values/mimir.yaml:16
multitenancy_enabled: false
# environments/prod/values/loki.yaml:21
auth_enabled: false
# environments/prod/values/tempo.yaml:7
replicas: 1                # single-binary, retention: 720h
```

There is even a comment in `mimir.yaml:207` reading "a multi-tenant fleet we don't run."

So Increment 3 ("Tempo uses this header to isolate tenant trace data") and Increment 10's
isolation matrix ("tenant A cannot query tenant B") are **not** configuration tweaks on
top of what's running — they are a migration of the observability stack that currently
monitors our own production. §3 is the decision that follows, and it's the one that
should be settled before any code is written.

The good news, and it's substantial: **Increment 2 is already built.** Not "something
similar" — the exact flow. See §2.

---

## 1. These two specs are one product

The Foundry spec's Increment 1 (Tenant → Application → Environment → Integration → Agent,
plus credential issuance and revocation) is **not Foundry-specific**. The Copilot
connector needs the same `tenant_id`, the same application record, and the same identity
map. The Foundry spec's Increment 5 explicitly frames normalization as provider-agnostic;
the Copilot spec's Phase 5 says the same thing in different words ("normalize all
providers into a generic AI-application model").

That resolves open question #4 in the Copilot plan. Consequences:

| | Copilot plan said | Now |
|---|---|---|
| Repo | `ADORSYS-GIS/copilot-governance` | **`ADORSYS-GIS/lightbridge-governance`** — one workspace, `crates/governance-core` + `crates/connector-copilot` + `crates/connector-foundry` |
| Namespace | `governance` | `governance` (unchanged — it was already the right call) |
| Database | `copilotgov` role on `lightbridge-main-db` | **`governance`** role/DB, shared: registry + both connectors' tables |
| Charts | `copilot-governance{,-app,-secrets,-auth}` | `lightbridge-governance{,-api,-collector,-secrets,-auth}` |
| Sequencing | Copilot Sprint 1 = ingestion | **Registry first.** Increment 1 here is the prerequisite for *both* connectors |

**The sequencing change is the important one.** Building the Copilot connector first and
retrofitting a tenant registry underneath it means rewriting every table's primary key.
Build the registry (~1 sprint), then both connectors land against it.

I'd still ship **Copilot first** as the second milestone — it's pull-based, single-tenant
in practice (our own org), needs no public endpoint, and no LGTM changes. It proves the
registry and the Postgres+Grafana pattern at low risk. Foundry is the harder one and
benefits from going second.

---

## 2. Increment 2 is already in production — don't rebuild it

The spec asks for: public HTTPS :443 → bearer token → authentication service → token
lookup → trusted integration context → collector, with the producer forbidden from
setting `X-Scope-OrgID` or `governance.*` itself.

That is a description of `core-gateway` + Authorino as currently deployed. Concretely,
this is live in `ai-helm-values` `security-policies.yaml` today:

```yaml
    metadata:
      "repobinding":
        http:
          url: http://lightbridge-repo-auth.converse.svc.cluster.local:3000/v1/resolve
          method: POST
          credentials:
            customHeader:
              name: X-Internal-Token
          sharedSecretRef:
            name: lightbridge-repo-auth-internal
            key: internal-token
```

An Authorino AuthConfig calling a first-party Rust service's `/v1/resolve` over a shared
secret, to turn a credential into trusted context, and then stamping the result as
headers via `response.success.headers`. **That is the spec's Increment 2 authentication
design, already running.**

So the Foundry ingestion path is:

```text
Foundry agent
  → https://otel.ai.camer.digital (core-gateway, public LB, ACME HTTP-01)
  → Authorino AuthConfig #3 (host-indexed, alongside main + internal)
        authentication: bearer integration token
        metadata.http → governance-api /internal/v1/resolve  (X-Internal-Token)
        response.success.headers → X-Scope-OrgID, governance.tenant.id,
                                   governance.application.id, governance.integration.id
  → BackendTrafficPolicy (per-token rate limit + quota, redis-backed — ADR-0021)
  → OpenTelemetryCollector/foundry-gateway  (OTLP/HTTP :4318)
        memory_limiter → redaction → transform → batch
  → fan-out
```

What this buys you, free: TLS termination + ACME, a stable public endpoint, 401 on bad
tokens, server-side revocation (the resolve call is authoritative every request), per-token
rate limiting and monthly quotas with live counters in redis, and the existing
gateway dashboards.

**Three traps carried over from how this is already wired:**

- ⚠️ A `sharedSecretRef` pointing at a Secret that doesn't exist makes the AuthConfig fail
  readiness → **gateway-wide 404**. This is the OPA-removal outage, documented in
  `docs/migrations/2026-hetzner-cutover.md`. Create the `ssegning-aws` property and confirm
  `SecretSynced=True` *before* the AuthConfig references it.
- ⚠️ Authorino attaches per-**listener** via the SecurityPolicy's `sectionNames` (today
  `api-https` + `api-internal`). A new `otel-https` listener must be added there or it is
  silently unauthenticated.
- ⚠️ The resolve endpoint must be ClusterIP-only and trust the posted body **only** with
  the internal token — repo-auth's own comment says exactly this.

**Not free, and worth stating plainly:** Authorino evaluates the AuthConfig on every
request, so `/internal/v1/resolve` is in the hot path of customer telemetry. Cache the
token→tenant resolution in-process (`moka`, 60 s TTL) inside the governance API, and
accept that revocation takes up to one TTL to propagate. The spec's acceptance test
"revoked tokens stop working" then means "within 60 s" — say so in the docs rather than
implying instant.

---

## 3. The tenancy decision (blocking, settle before code)

Three options. I recommend **C for the MVP, B as the stated end state.**

### A — Turn on multi-tenancy in the existing LGTM stack

Flip `multitenancy_enabled` / `auth_enabled` to `true`, tenant our own data, tenant the
customers'. **Reject.** It means: every existing writer must start sending
`X-Scope-OrgID` (Alloy's `prometheus.remote_write`, the core-gateway OTel collector,
every log path); every Grafana datasource gains the header; existing Mimir blocks written
under the implicit tenant don't relabel themselves, so there's a cutover with a data
discontinuity in the boards that watch production. And it puts customer telemetry volume
in the same ingesters as the monitoring you need *during* an incident caused by that
volume. Wrong blast radius for an MVP.

### B — A second, multi-tenant LGTM instance for customer telemetry

Own namespace, own S3 prefixes in `ssegning-k8s-state`, multi-tenant from birth, our
production stack untouched. This is the correct end state and satisfies every isolation
test in Increment 10 as written. It is also a whole second observability stack to operate
— and the existing one has cost real incidents (the Mimir memberlist ring wedge, the
Alloy egress trap, the datasource UID substitution). Not a first milestone.

### C — MVP: governance Postgres is the tenant-isolated system of record

Customer telemetry still flows to Tempo/Loki/Mimir, single-tenant, **for operator use
only** — no customer Grafana access at all. Everything the customer sees comes from the
governance API and the governance Postgres, where isolation is a `WHERE tenant_id = $1`
enforced in one place and testable. The normalized execution record keeps `trace_id` /
`span_id` so an *operator* can jump to Tempo.

What this costs you against the spec, stated honestly:

- Increment 3's acceptance test "a tenant-isolated query result in Grafana" is **not
  met**; it becomes "an operator-isolated query result."
- DoD step 7, "Open its Tempo trace," is operator-only. A customer-facing deep link would
  rely on 128-bit trace IDs being unguessable — that's non-enumerability, not
  authorization, and it should not be sold as isolation.
- Increment 10's isolation matrix reduces to three rows (write-as, query-as, S3 path),
  all of which C *does* satisfy, plus two that are deferred with B.

If customer-facing Grafana is non-negotiable for the MVP, that is a legitimate call — it
just means B moves into scope and adds roughly a sprint.

### Loki cardinality (applies to B and C alike)

The spec is right that `trace_id`/`session_id`/`user_id`/`model`/`agent_id` must be
structured metadata, not stream labels. Two platform-specific additions:

- Loki's **native OTLP endpoint** with structured metadata is the right receiver, and
  it is what the spec asks for. Note our Alloy path uses `otelcol.exporter.loki`, which
  is the *older* shape and stores the line as `{"attributes":…,"resources":…}` — ADR-0046
  and a lot of pain. Don't copy the existing Envoy-access-log pipeline for this; go
  native OTLP.
- ⚠️ **"Full prompt content: 7 days maximum" (Increment 10) is not achievable with our
  current Loki config.** `retention_period: 90d` is global. Per-stream retention needs
  `limits_config.retention_stream` matched on a **label** — so content-bearing streams
  must carry a distinguishing stream label (e.g. `content_capture="full"`), which is one
  of the very few places a label is justified. Design it in from the start; retrofitting
  means the 7-day promise silently isn't kept.

---

## 4. What to build, by increment

### Increment 1 — Registry (shared, first)

`governance` role + database on `lightbridge-main-db` (same 30-line addition as the
Copilot plan). Tables: `tenant`, `application`, `environment`, `integration`, `agent`,
`agent_version`, `identity_map`, plus the connector tables.

Credentials: issue an opaque token, store **only** `credential_hash` (argon2id), never
the token. `POST /api/v1/integrations` returns it once. Revocation = a status flip that
`/internal/v1/resolve` reads.

⚠️ Foundry constraint the spec flags and it's load-bearing: **changing the OTLP env vars
requires publishing a new agent version.** So endpoint and token must be *stable* —
rotation is expensive for the customer. Design for long-lived tokens with server-side
revocation (which C gives you), not short-lived tokens with rotation.

### Increment 2 — Ingestion

`charts/lightbridge-governance-collector` renders an `OpenTelemetryCollector` CR. Precedent and
its two hard-won notes are in `charts/core-gateway/templates/otel.yaml`:

- ⚠️ `mode:` is **required** — the v1beta1 webhook rejects an empty mode with a confusing
  message — and **immutable**; changing it means deleting the CR once so ArgoCD recreates it.
- ⚠️ `memory_limiter` **must be first** in every pipeline; it sheds load before OOM, and
  an OOM loses data outright. This regressed once already (ADR-0034).

Three replicas, PDB, anti-affinity, HPA — all standard, all in the chart. Namespace
`governance` (not the spec's `governance-ingestion`; short names, and the collector and
API want to be co-resident anyway).

⚠️ New namespace ⇒ no Cilium default-deny baseline, so ship a `CiliumNetworkPolicy` in
the deps overlay, and **it must include `fromEntities: [host, remote-node, health]`** or
kubelet probes fail and it reads as a crash-loop.

### Increment 3 — Fan-out

Three pipelines as the spec writes them. Exporters: `otlp/tempo`, `otlphttp/loki`
(native), `otlphttp/mimir`, plus `otlphttp/governance` to our own ingestion API.

⚠️ Mimir's native OTLP endpoint — verify against the installed chart version before
relying on it; the fallback is remote-write via the `prometheusremotewrite` exporter.

### Increment 4 — Privacy (release blocker, agreed)

`redaction` + `filter` + `transform` processors, three capture modes, default
`metadata_only`. The mode is resolved from the **integration record**, not the payload —
which means the collector needs it as a trusted header from Authorino, or the governance
API enforces it post-hoc. Prefer the header: redact before the data reaches Tempo/Loki,
not after.

### Increment 5 — Normalization

Execution / model-call / tool-call records as specified, keeping `trace_id`, `span_id`,
`raw_backend`, `raw_schema_version`. One change: **money in integer µ$**, never floats —
house rule, and it makes Foundry cost commensurable with the existing
`gateway_ratelimit_spend_micro_usd` series so one board can show both.

### Increment 6 — Cost + policies

The versioned pricing table is right (Foundry reports Azure OpenAI models, not ours).
Shape it like `charts/ai-models/values.yaml`'s per-model `pricing:` blocks (ADR-0028) so
the two cost models read the same way, but keep it in Postgres — it's customer-editable
data, not chart config.

Five policies, evidence to S3 (`s3://ssegning-k8s-state/lightbridge-governance/evidence/…`),
searchable metadata in Postgres. Exactly as specified.

### Increment 7 — UI: four of the five views are Grafana

**Applications, Application overview, Executions, Policies are all SQL over the
governance Postgres** — the same `GrafanaDatasource` trick as the Copilot plan (ADR-0063
precedent). Only **Integration setup** genuinely needs a bespoke page: create app, mint
token once, show copyable Foundry config, live "receiving telemetry" status.

So build **one small server-rendered page** off the axum API (askama/maud), not a Next.js
console. `lightbridge-code-intelligence` has a Next.js console and it is a lot of surface
to carry for four tables and a form. Revisit when the product earns it.

### Increments 8–10

Dashboards via `tools/dashboards/` Python only (hand-written JSON fails
`dashboards-drift`), folder `lightbridge-governance`, `resyncPeriod` on the folder or the first
Grafana pod roll wipes it. The **platform ingestion health** dashboard is the one the
spec correctly calls essential — "no violations" vs "no telemetry" — and it reads Mimir.

Increment 9's golden-dataset-in-CI is the best idea in either spec. Make it a fixture
replayed through the real collector config in CI on every change to collector config,
normalization, pricing, or policy logic.

Increment 10: rate limiting and quotas are `BackendTrafficPolicy` config (ADR-0021), not
code. Retention: Tempo 30d ✓, Mimir 90d ✓, Loki 90d vs the spec's 14–30d (decide), full
content ≤7d needs the `retention_stream` work from §3.

---

## 5. Sequencing across both specs

```text
M1  Registry + credentials + /internal/v1/resolve + governance DB      (shared)
M2  Copilot connector  → proves registry + Postgres/Grafana, low risk
M3  Foundry ingestion  → otel host + AuthConfig #3 + collector + fan-out
M4  Normalization + cost + 5 policies + evidence                       (shared)
M5  Grafana views + integration-setup page + golden dataset in CI
M6  Hardening: quotas, isolation tests, retention, load test
    (+ option B — second LGTM instance — if customer Grafana access is in scope)
```

## 6. ADRs

Three, not one. `0111` registry + tenancy model (including the §3 decision and why A was
rejected); `0112` Copilot connector; `0113` Foundry OTLP ingestion via core-gateway +
Authorino. Template is `docs/adr/template.md` — three bold metadata lines, no YAML
front-matter, next free number is 0111.

## 7. Open questions

1. **§3 — A, B or C?** Everything else depends on it. My recommendation: C now, B stated
   as the end state, and be explicit in customer-facing docs that MVP Grafana access is
   operator-only.
2. **Is this actually multi-customer, or is "tenant" us + a pilot?** It changes whether
   token issuance needs self-service in M1 or can be `govctl` + a row in Postgres.
3. **Loki retention** — drop to 30d globally to match the spec, or keep 90d and treat the
   spec's table as a floor?
4. **Repo name** — `lightbridge-governance`, or keep the connectors in separate repos
   with a shared core crate published to a private registry? (One repo is simpler; I'd
   only split if the connectors get separate release cadences.)
5. Does the Foundry agent's OTLP client tolerate a **401 with a JSON body** from
   Authorino, or does it need a specific challenge shape? Worth a 30-minute check against
   a real hosted agent before M3.
