# ADR-0120: Provider-billed cost as the invoice source of truth via a billing-exporter

**Status:** Accepted
**Date:** 2026-08-05
**Deciders:** @stephane-segning

## Context

Grafana reported **gateway-estimated** cost from Envoy AI Gateway completion
metadata, not **provider-billed** cost. On 2026-08-04 this produced a material
month-to-date discrepancy: DeepInfra invoiced **$507.08** while Grafana/Mimir
showed **$277.01** (raw Loki gateway estimates $286.06; DeepInfra-backed models
only $230.56). The primary cause was `anthropic/claude-sonnet-5`: DeepInfra
billed $442.66 while the gateway estimated $160.10 — the route had an unverified
cache-read estimate ($0.30/M) while DeepInfra billed cache reads at $2/M.
Commit `cf65269` corrected future gateway estimates, but the provider also bills
cache **writes** at $2.50/M, which the AIEG cost inputs cannot represent
separately.

Two further blind spots: successful streaming disconnects can lack terminal
usage/cost metadata entirely, and the Grafana Mimir `increase()` total ran ~$9
below raw Loki for the same period.

The gateway estimate remains useful for per-request / per-actor attribution and
enforcement, but it is **not** the invoice truth. We need provider billing to be
the source of truth for the invoice, continuously reconciled against the
gateway estimate and the live Redis limiter counters (ADR-0070).

## Decision

**Adopt a `provider-billing-exporter` chart** — a small Python poller that reads
provider read-only billing APIs and exports **cumulative monthly gauges** to
Mimir, which Grafana shows as the invoice source of truth and reconciles against
the gateway estimate and limiter spend.

### Why gauges, not counters

Each poll **overwrites** the absolute cumulative value the provider reports for
a UTC calendar billing period. This makes the exporter **idempotent by
construction**: restarts and re-polls can never double count, provider
corrections are picked up automatically on the next poll, and backfilling an
older month simply adds/overwrites that month's series. A counter + `increase()`
would double-count on restart and cannot represent a corrected invoice value.

### Why polling, not push / webhooks

Billing data is low-frequency (delayed invoices, corrections), so an hourly poll
of DeepInfra's `GET /payment/usage/tokens` is ample. Polling is simpler than a
push pipeline and needs no extra infrastructure; the provider offers no
webhook for billing anyway.

### Metric schema (bounded labels only)

| Metric | Type | Labels |
|---|---|---|
| `provider_billing_cost_micro_usd` | gauge | provider, provider_model, pricing_type, billing_period, task |
| `provider_billing_units` | gauge | provider, provider_model, pricing_type, billing_period, task |
| `provider_billing_total_cost_micro_usd` | gauge | provider, billing_period |
| `provider_billing_invoice_final` | gauge | provider, billing_period |
| `provider_billing_up` | gauge | provider, billing_period |
| `provider_billing_last_success_timestamp_seconds` | gauge | — |
| `provider_billing_scrape_duration_seconds` | gauge | — |

Labels are deliberately bounded to `provider`, `provider_model`,
`pricing_type`, `billing_period`, `task`. The API token and account identifiers
are **never** metric labels (FR-002/FR-006). `pricing_type` carries the
provider's own `cache_read` / `cache_write` / `input` / `output` line items, so
the claude-sonnet-5 cache-read/write discrepancy is visible as separate
provider-billed items.

### Credentials

The DeepInfra API token is a **read-only** billing token, stored in AWS Secrets
Manager (`ssegning-aws`, property `deepinfra_api_token`) and materialised by an
in-chart `ExternalSecret` into a Secret consumed via `secretKeyRef`
(`optional: false` so the pod waits for ESO rather than starting tokenless). It
is never exposed as a metric label.

### Dashboard + alert

A generated **`AI Gateway — provider billing & reconciliation`** dashboard
(ADR-0008 source) shows provider-billed total by model/pricing type, gateway
estimate vs provider bill, absolute and percentage reconciliation delta, cache
read/write costs, invoice finality, and missing-cost/disconnected gateway
requests (from Loki). A `ai-gateway-billing-reconcile` alert fires when the
provider total exceeds the gateway estimate by a configurable ratio (default
1.5x), with `clamp_min` guarding the divide-by-zero.

## Consequences

**Positive**

- Provider billing becomes the invoice source of truth in Grafana, reconciled
  against the gateway estimate and the Redis limiter spend (ADR-0070).
- Idempotent by construction — restarts / re-polls / backfills cannot double
  count; provider corrections are picked up automatically.
- Cache reads and writes appear as separate provider-billed line items, closing
  the claude-sonnet-5 blind spot.
- Bounded cardinality (a handful of providers × models × pricing types ×
  periods) and no secret material in metric labels.
- Follows existing patterns: off-the-shelf Python image (ADR-0040), CI
  lint-values fixture, values-repo-first (ADR-0056/0057), in-chart
  CiliumNetworkPolicy for the default-deny egress baseline.

**Negative**

- **Forward-only + poll-lag.** Provider metrics begin when the exporter deploys
  and update at the poll interval (hourly); a non-final month's total may still
  move. Pre-cutover months are not backfilled automatically.
- **New moving part** — a poller with a credential, egress, and a scrape path to
  keep healthy; a silent poller failure would hide provider data (mitigated by
  `provider_billing_up` / `provider_billing_last_success_timestamp_seconds`).
- **DeepInfra-only for now.** Fireworks' API does not expose an itemized
  per-model / per-pricing-type usage endpoint equivalent to DeepInfra's, so the
  provider source is DeepInfra-only; the gap is documented in the runbook and
  the schema is provider-agnostic (`provider` label) so a second source can be
  added later.

**Neutral / follow-ups**

- The reconciliation alert compares provider vs gateway regardless of invoice
  finality, so a non-final month can legitimately fire it — check
  `provider_billing_invoice_final` before acting.
- The gateway estimate and provider bill are different window semantics (trailing
  30d counter vs calendar billing period gauge); the reconciliation delta is
  approximate and intended as a drift signal, not an exact audit.

## Alternatives considered

- **Counters + `increase()`.** Rejected: double-counts on restart and cannot
  represent a corrected invoice value; gauges with overwrite are idempotent.
- **Loki recording rules (ruler).** Rejected for the same reason as ADR-0058 —
  the ruler re-queries Loki/S3 on a timer, re-creating the object-store throttle.
- **A custom image / CronJob pushing clean metrics.** Rejected in favour of the
  off-the-shelf Python image + ConfigMap pattern (ADR-0040); the poller is
  stdlib-only plus `prometheus_client`, installed at container start.
- **Webhooks / push from the provider.** Not available for billing; polling is
  simpler and sufficient for low-frequency data.

## Related

- Builds on: ADR-0058 (precomputed gateway usage metrics to Mimir), ADR-0070
  (Redis limiter spend), ADR-0008 (Python dashboard generation), ADR-0040
  (off-the-shelf images), ADR-0056/0057 (values-repo-first), ADR-0028/0051
  (micro-USD cost convention).
- Docs: `docs/playbooks/provider-billing-reconciliation.md` (the *how*; this ADR
  is the *why*).
- Charts/files touched: `charts/provider-billing-exporter/`,
  `charts/observability-dashboards/` (dashboard + alert),
  `tools/dashboards/src/dashboards/envoy_ai_gateway/provider_billing.py`,
  `tools/dashboards/tests/test_provider_billing_poller.py`.
- Pricing correction: commit `cf65269`.
