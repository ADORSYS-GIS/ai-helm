# ADR-0130: Add `billing_period` label to gateway usage metrics for calendar-month alerts

**Status:** Proposed
**Date:** 2026-08-17
**Deciders:** @stephane-segning

## Context

Grafana alerts for per-actor budget consumption (`charts/observability-dashboards/values.yaml`, rules `cost-actor-budget-free-warn`, `cost-actor-budget-free`, `cost-actor-budget-pro`) currently use a rolling 30-day window:

```promql
sum by (email, display_name)
  (increase(loki_process_custom_gen_ai_usage_cost_micro_usd{billing_plan="free"}[30d])) / 1e6
```

This is misaligned with the billing cycle. Billing is monthly (calendar month), and the rate limiter already enforces against calendar-aligned budgets via the `x-billing-period` header (ADR-0111/0112). Users receive alerts about "last 30 days" when they should receive alerts about "this month so far".

The `gateway_ratelimit_spend_micro_usd` metric (from the Redis limiter, ADR-0070) already carries a `billing_period` label and is calendar-aligned, but it lacks the `email`/`display_name` labels needed for human-readable alert messages. The `loki_process_custom_gen_ai_usage_cost_micro_usd` metric (from Alloy `stage.metrics`, ADR-0058) has `email`/`display_name` but lacks `billing_period`.

## Decision

**Add `billing_period` as a label to the `loki_process_custom_gen_ai_usage_cost_micro_usd` metric** by extracting the `x-billing-period` header in Alloy's `ai_gateway_user_attribution` stage.

### Implementation

In the Alloy configuration (external `ai-helm-values` repo, `charts/observability/values.yaml` alloy child `extraConfig`):

1. Extract the `x-billing-period` header from the flattened access log (it's stamped by the Lua `EnvoyExtensionPolicy` in `charts/core-gateway/templates/envoyextensionpolicy-billing-period.yaml`)
2. Promote it as a Loki label in the `stage.labels` block of the `ai_gateway_user_attribution` stage
3. The `stage.metrics` counters will automatically inherit this label (confirmed in ADR-0058: "generated counters inherit the entry's promoted label set")

The label promotion should be added alongside the existing label promotions:
- `user_id`
- `azp`
- `model`
- `email`
- `display_name`
- `billing_plan`
- **`billing_period`** (new)

### Alert query update

Once the label is available, update the Grafana alert queries in `charts/observability-dashboards/values.yaml` to filter by the current billing period instead of using a rolling 30-day window:

```promql
# Current (rolling 30d)
sum by (email, display_name)
  (increase(loki_process_custom_gen_ai_usage_cost_micro_usd{billing_plan="free"}[30d])) / 1e6

# New (calendar month-to-date)
sum by (email, display_name)
  (increase(loki_process_custom_gen_ai_usage_cost_micro_usd{billing_plan="free", billing_period="$current_billing_period"})) / 1e6
```

The `$current_billing_period` variable can be set as a Grafana dashboard variable or hardcoded in the alert rule (e.g., using a PromQL subquery to get the current period from `gateway_ratelimit_spend_micro_usd`).

Alternatively, use a simpler approach with a time range that covers the current month:

```promql
sum by (email, display_name)
  (increase(loki_process_custom_gen_ai_usage_cost_micro_usd{billing_plan="free", billing_period=~".+"}[30d])) / 1e6
```

Since the metric is now labeled by `billing_period`, the `increase()` function will naturally respect the calendar boundary when combined with the label selector.

## Consequences

**Positive**

- Alerts now align with the actual billing cycle (calendar month-to-date)
- Users receive accurate notifications about their current month's consumption
- Consistent with the rate limiter's enforcement window (ADR-0111/0112)

**Negative**

- Requires cross-repo change to `ai-helm-values` (Alloy configuration)
- Forward-only: historical data before the label addition won't have `billing_period`
- Slightly increased cardinality (one more label on the metric)

**Neutral**

- The `x-billing-period` header is already stamped on every request (ADR-0111), so this is just extracting existing data
- No new components or dependencies

## Alternatives considered

- **Use `gateway_ratelimit_spend_micro_usd` for alerts.** Rejected: lacks `email`/`display_name` labels, so alert messages would show UUIDs instead of human-readable names. Would require joining with Keycloak datasource in Grafana, which adds complexity and may not work reliably in alert annotations.

- **Use PromQL time-range tricks without new label.** Rejected: PromQL has no native "calendar month" function. Workarounds like `increase(metric[$__range])` with a dashboard time range set to "month to date" are fragile and don't work for alert rules (which have fixed evaluation windows).

- **Keep rolling 30-day windows.** Rejected: misaligned with billing, confusing for users, and inconsistent with the rate limiter's calendar-aligned enforcement.

## Related

- Builds on: ADR-0058 (gateway usage metrics), ADR-0111 (calendar billing period), ADR-0112 (unit: Year), ADR-0070 (rate-limit quota observability)
- Files touched (cross-repo): `ai-helm-values/charts/observability/values.yaml` (Alloy extraConfig)
- Files touched (this repo): `charts/observability-dashboards/values.yaml` (alert queries)
