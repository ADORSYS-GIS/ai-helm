# Provider Billing Reconciliation Runbook

How the platform shows **provider-billed** cost (the invoice source of truth) in
Grafana and reconciles it against the Envoy AI Gateway's **estimated** cost and
the Redis limiter spend. Covers the `provider-billing-exporter` chart, the
`AI Gateway — provider billing & reconciliation` dashboard, and the
`ai-gateway-billing-reconcile` alert.

## Overview

| Source | Metric | Meaning |
|---|---|---|
| Provider (DeepInfra) | `provider_billing_cost_micro_usd` / `provider_billing_total_cost_micro_usd` | **Invoice truth** — cumulative per UTC billing period, polled from `GET /payment/usage/tokens`. |
| Gateway estimate | `loki_process_custom_gen_ai_usage_cost_micro_usd` | Per-request **estimate** from AIEG completion metadata (ADR-0058). |
| Redis limiter | `gateway_ratelimit_spend_micro_usd` | Live per-account budget counters (ADR-0070). |

Provider billing is the source of truth for the invoice; gateway estimates remain
useful for per-request / per-actor attribution and enforcement.

### How the poller works

The `provider-billing-exporter` Deployment runs a Python poller
(`charts/provider-billing-exporter/files/poller.py`) that:

- Polls DeepInfra `GET /payment/usage/tokens` **hourly** (billing data is
  low-frequency), one range request per poll covering the previous + current UTC
  calendar month (`from=current(-1)&to=current`).
- Emits **cumulative gauges** (micro-USD, ÷1e6 → USD) with bounded labels
  `provider`, `provider_model`, `pricing_type`, `billing_period`, `task`.
- Is **idempotent by construction**: each poll overwrites the absolute value, so
  restarts / re-polls can never double count.
- Exposes `provider_billing_invoice_final` (1 = final Stripe invoice, 0 =
  `NOT_FINAL`/`EMPTY` still accruing) and `provider_billing_up` (poll health).

The token comes from an ESO-managed Secret (`ssegning-aws` store) and is **never**
a metric label.

## Credential rotation

The DeepInfra API token is stored in AWS Secrets Manager under the
`ssegning-aws` store (property `deepinfra_api_token`, key
`ai/camer/digital/prod/env`) and materialised into the `deepinfra-billing-token`
Secret by the in-chart ExternalSecret.

To rotate:

1. Create a new token in the DeepInfra dashboard (Account → API tokens).
2. Update the `deepinfra_api_token` property in Secrets Manager.
3. The ExternalSecret refreshes within its `refreshInterval` (default `1h`); the
   pod picks up the new token on its next restart (env vars from `secretKeyRef`
   bind at pod start and never refresh — `optional: false` means the pod waits
   for ESO rather than starting tokenless).
4. Verify: `provider_billing_up{provider="deepinfra"}=1` and
   `provider_billing_last_success_timestamp_seconds` is recent.

> The token is read-only (billing usage only). Never grant write/inference
> scopes to the token used by this exporter.

## API failures / rate limiting

DeepInfra's documented rate limit is 200 concurrent requests per model
(inference-focused); the billing endpoint is a low-traffic admin endpoint, so a
1-call/hour poll is trivially within limits. Still:

- **429 / 5xx**: the poller retries with exponential backoff + jitter (30s →
  15m cap) and sets `provider_billing_up=0` for the affected period.
- **Symptoms**: `provider_billing_up=0`, `provider_billing_last_success_*` stale,
  dashboard panels showing "No data" for provider metrics.
- **Action**: check the poller logs (`kubectl logs -n observability
  deploy/provider-billing-exporter`), confirm the token is valid, and confirm
  egress to `api.deepinfra.com:443` (the in-chart CiliumNetworkPolicy opens it).
- The dashboard's **Provider poll health** row — `provider_billing_up`,
  seconds-since-last-success, and last poll duration — makes a silent poller
  failure visible at a glance.

## Delayed invoices

DeepInfra marks a month's `invoice_id` as `NOT_FINAL` (or `EMPTY`) until the
invoice is finalised. The poller exposes this as
`provider_billing_invoice_final{provider, billing_period}`:

- `1` = final Stripe invoice id present (the number is stable).
- `0` = still accruing / not final (the number may still change).

The dashboard shows an "Invoice final" stat. Treat a `0` as "may still move" —
do not treat a non-final month's total as a hard invoice figure. The
reconciliation alert compares provider vs gateway regardless of finality, so a
non-final month can legitimately fire it; check `invoice_final` before acting.

## Backfill behavior

The poller defaults to the previous + current UTC calendar month. To backfill an
older month (e.g. after a pricing correction or a missed window), set the
`BILLING_PERIOD` env to a comma-separated list of `YYYY-MM` periods in
`ai-helm-values` (per-env values for the chart) and let it poll. Because the
metrics are absolute cumulative gauges keyed by `billing_period`, backfilling an
older month simply adds/overwrites that month's series — it cannot double count
and does not disturb other months.

Provider **corrections** (a corrected invoice value) are picked up automatically:
the next poll overwrites the gauge with the corrected value.

## Reconciliation alert response

The `ai-gateway-billing-reconcile` alert fires when
`provider_billed_total / gateway_estimate > 1.5` (threshold configurable in
`charts/observability-dashboards/values.yaml`).

1. Open the **AI Gateway — provider billing & reconciliation** dashboard.
2. Confirm `provider_billing_invoice_final=1` for the period (a non-final month
   can fire spuriously).
3. Compare provider vs gateway by model — the mismatch is usually one model with
   an unverified pricing (e.g. the 2026-08-04 claude-sonnet-5 cache-read case:
   gateway estimated $0.30/M cache reads, DeepInfra billed $2/M).
4. Fix the gateway pricing in `charts/ai-models/values.yaml` (the AIEG cost
   inputs) — see commit `cf65269` for the pattern.
5. If the provider figure itself is wrong, correct it in DeepInfra; the next poll
   overwrites the gauge.

## Metrics reference

| Metric | Type | Labels |
|---|---|---|
| `provider_billing_cost_micro_usd` | gauge | provider, provider_model, pricing_type, billing_period, task |
| `provider_billing_units` | gauge | provider, provider_model, pricing_type, billing_period, task |
| `provider_billing_total_cost_micro_usd` | gauge | provider, billing_period |
| `provider_billing_invoice_final` | gauge | provider, billing_period |
| `provider_billing_up` | gauge | provider, billing_period |
| `provider_billing_last_success_timestamp_seconds` | gauge | — |
| `provider_billing_scrape_duration_seconds` | gauge | — |

## Fireworks gap

Fireworks' API does not currently expose an itemized per-model / per-pricing-type
usage endpoint equivalent to DeepInfra's `GET /payment/usage/tokens`, so the
provider source is **DeepInfra-only** for now. If Fireworks adds an itemized
billing endpoint, add it as a second poller source behind the same gauge schema
(`provider` label distinguishes them); otherwise the gap remains documented here.
