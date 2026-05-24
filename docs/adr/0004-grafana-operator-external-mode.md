# ADR-0004: Adopt grafana-operator in external mode for dashboards-as-code

**Status:** Accepted
**Date:** 2026-05-24
**Deciders:** repo maintainers via `claude/magical-bohr-390242`

## Context

Dashboards in this repo currently ship three ways:
- Most live as `dashboards: { gnetId: NNN }` entries in the grafana app's
  values (file-provider, baked into the Deployment).
- A few are imported manually in the UI and survive only because the PVC
  survives.
- None are owned by the chart of the app they describe.

We want per-app dashboard ownership — each chart (LibreChat, Coder, MCPs,
etc.) should ship its own dashboards alongside its workloads — and we want
cross-app dashboards (per-user AI gateway view, total cost per user) to
live in a central, diffable place. The current setup supports neither.

Three packaging options were on the table:
1. Keep using the helm chart's `dashboards:` field (file provider).
2. Use the chart's built-in sidecar discovery via `grafana_dashboard: "1"`-
   labeled ConfigMaps.
3. Install `grafana-operator` and use `GrafanaDashboard` / `GrafanaFolder` /
   `GrafanaDatasource` CRs.

## Decision

Install the grafana-operator at infra sync-wave (-1) and a new
`charts/observability-dashboards` chart at sync-wave 1 that owns
**operator CRs only** — never Deployments, Services, or ConfigMaps.

Use the operator in **external mode**: a `Grafana` CR with
`spec.external.{url, adminUser, adminPassword}` points at the existing
in-cluster Grafana Service. The operator does not stand up a second
Grafana instance.

Dashboards live in two layouts:
- **Layout A (chart-local)** — `charts/<chart>/files/dashboards/<name>.json`
  for app-specific dashboards; the chart ships its own `GrafanaDashboard`
  CR. Dashboards travel with chart upgrades.
- **Layout B (central)** — `charts/observability-dashboards/files/<area>/<name>.json`
  for cross-app dashboards.

Every CR binds to the Grafana instance via
`spec.instanceSelector.matchLabels: { dashboards: grafana-external }`.

## Consequences

**Positive**
- Per-app dashboard ownership without touching the central grafana app.
- ArgoCD-native: CRs are real K8s objects with reconciliation, status, and
  drift detection — no sidecar polling.
- Folders, datasources, contact points, alert rule groups all available as
  CRs when needed.
- Cross-namespace dashboard import supported.
- Existing chart-loaded dashboards keep working — no cutover required.

**Negative**
- One more operator pod to run.
- Two paths exist during the indefinite transition period (chart-loaded
  AND CR-loaded). Documented as a known coexistence, not a problem.

**Neutral / follow-ups**
- A future ADR (0008) decides whether to generate the dashboard JSON from
  Python. The operator path is JSON-agnostic — works for hand-written and
  generated alike.
- If the team ever wants the operator to fully own grafana (replacing the
  helm chart with a `Grafana` CR carrying `spec.config`/`spec.deployment`),
  the existing OIDC / datasource / alerting config would need to be
  ported into the CR. Large change; not planned.

## Alternatives considered

- **Helm chart `dashboards:` field (status quo)** — simple, no operator,
  but baked into the Deployment; reload requires pod restart and there
  is no per-app ownership boundary. Acceptable for upstream gnetId imports;
  insufficient for app-specific or generated dashboards. Kept for the
  unchanged gnetId imports it already serves.
- **Grafana sidecar (`grafana_dashboard: "1"` ConfigMaps)** — per-app
  ownership via ConfigMaps, but sidecar polls disk; race on large
  ConfigMaps; same-namespace constraints unless you wire cross-namespace
  watch carefully. Operator is strictly better for this use case.
- **Let the operator own grafana entirely** — would replace the helm chart.
  Reproducing the existing OIDC/datasource/alerting wiring as `Grafana` CR
  fields is a large rewrite for no functional gain today. Rejected; revisit
  if a strong reason emerges.

## Related

- Commit: `9fb030e` (operator install + dashboards chart),
  `81c4108` (first dashboard)
- Doc: `docs/grafana-operator-and-dashboards.md` (the how — layouts,
  authoring checklist, troubleshooting)
- Charts: `charts/observability-dashboards/`, `charts/apps/values.yaml`
  (grafana-operator + observability-dashboards Application entries)
