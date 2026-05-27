# `observability-dashboards`

Owns `grafana-operator` custom resources for the cluster's existing
Grafana instance — `Grafana` (external mode), `GrafanaFolder`, and
`GrafanaDashboard` CRs. Renders NO workloads.

**ADR:** [`0004`](../../docs/adr/0004-grafana-operator-external-mode.md)
**Companion doc:** [`docs/grafana-operator-and-dashboards.md`](../../docs/grafana-operator-and-dashboards.md)

## What it renders

- One `Grafana` CR in external mode pointing at the in-cluster Grafana
  Service. The operator does NOT stand up a second Grafana — it
  authenticates against the existing one using the `grafana-admin`
  Secret.
- N `GrafanaFolder` CRs from `.Values.folders` (AI Gateway, Applications,
  GitOps).
- N `GrafanaDashboard` CRs from `.Values.dashboards`. Each entry sources
  its JSON from one of:
  - `file:` — path under `charts/observability-dashboards/files/` read
    via `.Files.Get` (preferred; lets dashboards live as plain JSON in
    git)
  - `json:` — inline (use only for trivial dashboards)
  - `jsonRef.configMapRef.{name, key}` — existing ConfigMap reference

Every CR binds to the `Grafana` via
`spec.instanceSelector.matchLabels: { dashboards: grafana-external }`.

## Two layouts for dashboard JSON

Per ADR-0004:

- **Layout A (chart-local)** — app-specific dashboards ship with their
  own chart: `charts/<chart>/files/dashboards/<name>.json` + a
  `GrafanaDashboard` template in the chart. Dashboards travel with chart
  upgrades.
- **Layout B (central)** — cross-app dashboards (per-user AI gateway
  view, total cost per user, GitOps overview) ship here:
  `charts/observability-dashboards/files/<area>/<name>.json` + a
  `dashboards[]` entry in this chart's values.

Today's central dashboards:

| File | Folder | Source |
|---|---|---|
| `files/envoy-ai-gateway/per-user.json` | AI Gateway | Generated from `tools/dashboards/src/dashboards/envoy_ai_gateway/per_user.py` (ADR-0008) |

## Values

| Key | What |
|---|---|
| `grafana.{name, url, adminSecret.{name, userKey, passwordKey}, instanceLabel.{key, value}}` | Pointer to the in-cluster grafana |
| `folders[]` | Each `{ name, title }` → one `GrafanaFolder` CR |
| `dashboards[]` | Each `{ name, folderRef, file/json/jsonRef, resyncPeriod }` → one `GrafanaDashboard` CR |
| `datasources[]` | (Not used today; grafana chart still owns datasources) |

## Adding a dashboard

1. Pick a layout. For Layout B (central):
2. Place JSON at `files/<area>/<name>.json` (preferably emit it from
   `tools/dashboards/` — see [ADR-0008](../../docs/adr/0008-python-dashboard-generation.md))
3. Add an entry to `dashboards:` in `values.yaml` referencing the file
4. Co-locate a `README.md` next to the JSON explaining the panels +
   their data path (see `files/envoy-ai-gateway/README.md` as the
   template).

## Verifying

```bash
helm template observability-dashboards . -n observability | grep -E "^kind:|^  name:"
```

Expected: 1 `Grafana`, N `GrafanaFolder`s, N `GrafanaDashboard`s. All
share the `instanceSelector.matchLabels.dashboards: grafana-external`
binding.
