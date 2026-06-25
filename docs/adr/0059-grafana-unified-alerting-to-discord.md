# ADR-0059: Grafana unified alerting → Discord, provisioned as grafana-operator CRs

**Status:** Accepted
**Date:** 2026-06-25
**Deciders:** @stephane-segning
**Builds on:** [ADR-0023](./0023-stateless-grafana.md) (stateless Grafana), [ADR-0020](./0020-observability-app-of-apps.md), [ADR-0058](./0058-precompute-gateway-usage-metrics-to-mimir.md) (the gen_ai metrics some alerts use)
**Relates to:** [ADR-0036](./0036-remove-apprise-notification-path.md) (the removed apprise path)

## Context

We had **no alerting**: dashboards showed problems but nothing notified. Grafana
already runs with `unified_alerting.enabled: true` but zero contact points or
rules (the old apprise path was removed in ADR-0036, and the Mimir Alertmanager
is disabled — its orphaned PVC was deleted 2026-06-25). The maintainer wants
alerts delivered to **Discord**.

Two constraints shape the design:
1. **Grafana is stateless** (emptyDir, ADR-0023) — anything configured in the
   Grafana UI is wiped on every pod roll. Alerting config MUST be provisioned as
   code, the same way dashboards/folders already are.
2. The Discord webhook is a **secret** — it must not live in git.

## Decision

Provision Grafana **unified alerting** entirely through **grafana-operator CRs**
(in `charts/observability-dashboards`, which already manages the
`GrafanaDashboard`/`GrafanaFolder` CRs against the same `grafana-external`
instance), so it survives stateless rolls and is reviewable as code:

- **`GrafanaContactPoint` `discord`** — `type: discord`; the webhook `url` is
  injected at reconcile time via `spec.valuesFrom` from a Secret, never inline.
- **ESO `ExternalSecret`** (`grafana-discord-webhook`) — pulls the webhook from
  `ssegning-aws` key `ai/camer/digital/prod/env` property
  `grafana_discord_webhook_url` (consistent with every other app secret here).
  Until the maintainer populates that property, the secret doesn't sync and the
  contact point keeps a placeholder url: **rules still evaluate; delivery is a
  no-op** (and the ExternalSecret/contact-point show a transient not-synced
  condition — expected until the webhook is added).
- **`GrafanaNotificationPolicy`** — default route → the Discord contact point,
  grouped by `grafana_folder`/`alertname` (group-wait 30s, repeat 4h).
- **`GrafanaAlertRuleGroup` × 5** — a *comprehensive first-pass* rule set. Each
  rule is expressed in a **compact values shape** (`datasourceUid`, `expr`,
  `op`, `threshold`, `for`, …) that the template expands into Grafana's standard
  three-node model: **A** = query (Mimir or Loki), **B** = `reduce(last)`,
  **C** = `threshold(op, threshold)`, `condition: C`.

### Rule set (thresholds are first-pass — tune live once firing)

| Group / folder | Rule | Source | Fires when |
|---|---|---|---|
| ai-gateway-health | AI Gateway no traffic | Mimir | `rate(gen_ai_requests[15m]) ≈ 0` for 15m |
| ai-gateway-errors | 5xx surge | Loki | 5xx rate > 0.2/s for 10m |
| ai-gateway-errors | p95 latency high | Loki | p95 `duration` > 5s for 10m |
| ai-gateway-cost | daily spend high | Mimir | `increase(cost[24h])/1e6` > $300 |
| ai-gateway-cost | monthly burn high | Mimir | `increase(cost[30d])/1e6` > $4000 |
| stack-health | component down | Mimir | any `up{ns=observability}==0` for 5m |
| cluster-health | pod crashlooping | Mimir | restarts > 3 in 15m |
| cluster-health | node not ready | Mimir | a node `Ready != true` for 5m |
| cluster-health | node memory pressure | Mimir | node mem > 90% for 10m |

Cost rules reuse the ADR-0058 `loki_process_custom_gen_ai_usage_cost_micro_usd`
metric (µ$ ÷ 1e6).

### Why grafana-operator CRs (not the alternatives)

- **Grafana chart `alerting:` provisioning files** would also survive rolls, but
  split alerting config away from the operator-CR model the rest of Grafana
  content uses here; CRs keep one mechanism + per-object status.
- **Mimir Alertmanager + ruler (Prometheus rules)** was rejected: it's the
  component we just disabled/cleaned up, and Grafana-native alerting can query
  both Mimir AND Loki (the 5xx/latency rules need Loki) in one place.

## Consequences

- Alerts (stack health, gateway errors, cost guardrails, cluster basics) now
  notify Discord, provisioned as code and roll-safe.
- **Action required to deliver:** populate `grafana_discord_webhook_url` in
  `ssegning-aws`. Until then the contact point is a no-op and the app may show a
  transient Degraded (unresolved secret) — self-heals when the property lands.
- Thresholds are first-pass and will need a live tuning pass (especially 5xx,
  p95, and the cost guardrails) once alerts are evaluating against real traffic.
- The compact rule shape keeps the values readable; adding a rule is a few lines.
  The Loki rules (5xx, p95) are heavier queries — watch their eval cost.
- New surface: an ESO secret + the Discord webhook as a dependency.
