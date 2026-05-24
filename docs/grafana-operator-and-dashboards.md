# Grafana Operator + dashboards-as-code

**Chart introduced:** `charts/observability-dashboards`
**Operator chart:** `oci://ghcr.io/grafana/helm-charts/grafana-operator`
**Operator version:** `v5.18.0` (pinned; verify before bumping)
**Operator API:** `grafana.integreatly.org/v1beta1`

## Why a separate operator (and not Grafana's sidecar)

Three options were on the table for shipping dashboards into the cluster:

| Option | Pros | Cons |
|---|---|---|
| Helm-chart `dashboards:` (file provider — what we use today) | Simple, no operator | Baked into the grafana Deployment; reload requires pod restart; provider folders per-source; no per-app ownership |
| `grafana_dashboard: "1"` ConfigMap + sidecar | Per-app ownership via ConfigMaps | Sidecar polls disk; race on large ConfigMaps; same-namespace constraints |
| **grafana-operator + `GrafanaDashboard` CRs** (chosen) | ArgoCD-native (CR is a real K8s object with reconciliation); separates ownership cleanly; supports folders, datasources, contact points, alert rules as CRs; cross-namespace import; per-resource resync intervals | Adds an operator pod |

Per-app ownership is the load-bearing reason: each chart can ship its own dashboards as part of its release without ever touching the central grafana app.

## How the pieces fit

```
┌────────────────────────────┐ sync-wave -1
│ grafana-operator (Helm)    │   installs CRDs + controller
└──────────────┬─────────────┘
               │
┌──────────────┴─────────────┐ sync-wave 0
│ grafana (Helm, unchanged)  │   the actual Grafana pod, datasources, OIDC
└──────────────┬─────────────┘
               │
┌──────────────┴─────────────┐ sync-wave 1
│ observability-dashboards   │   Grafana CR (external mode) + GrafanaFolders
│   (chart in this repo)     │   GrafanaDashboards land here OR in each app
└────────────────────────────┘
```

**External mode** is the key: the operator does NOT stand up a second Grafana. The `Grafana` CR points at the existing in-cluster Grafana Service and authenticates with the existing `grafana-admin` Secret. We keep the rich grafana config (OIDC, datasources, alerting) where it is.

## The CRs we use

| CR | What it is | Where it ships |
|---|---|---|
| `Grafana` | Pointer at the in-cluster grafana, in `external` mode | `charts/observability-dashboards/templates/grafana-external.yaml` (one instance, `name: grafana-external`) |
| `GrafanaFolder` | A folder in the Grafana UI | `charts/observability-dashboards/templates/folders.yaml` — driven by the `folders:` list in values |
| `GrafanaDashboard` | A dashboard | Either central via `charts/observability-dashboards/templates/dashboards.yaml` OR co-located in each app chart |
| `GrafanaDatasource` | A datasource (not used yet; today's datasources still ship from the grafana helm chart) | TBD |
| `GrafanaContactPoint` / `GrafanaAlertRuleGroup` | Alert routing & rules | TBD |

Every dashboard/folder selects the Grafana instance via:

```yaml
spec:
  instanceSelector:
    matchLabels:
      dashboards: grafana-external
```

(The label key/value pair is parameterized via `.Values.grafana.instanceLabel` in the chart — change it once, every CR follows.)

## Dashboard location

Two acceptable layouts; pick per dashboard:

### Layout A — co-located with the app chart

For app-specific dashboards that travel with chart upgrades. The chart adds a `GrafanaDashboard` CR template under its own `templates/`, e.g.:

```
charts/librechart/templates/dashboard-librechat-overview.yaml
```

This is the bjw-s app-template extension pattern — dashboards are "Source C" in the multi-source ArgoCD design.

### Layout B — central (this chart)

For cross-app dashboards (per-user AI Gateway view, total cost per user, GitOps overview). They ship via `charts/observability-dashboards`, with the dashboard JSON committed under `dashboards/<area>/<name>.json` and referenced from `values.yaml`:

```yaml
# charts/observability-dashboards/values.yaml
dashboards:
  - name: envoy-ai-gateway-per-user
    folderRef: ai-gateway
    json: |
      { ... full dashboard JSON ... }
```

The JSON should live as a file checked into git (e.g. `dashboards/envoy-ai-gateway/per-user.json`) and be `include`'d into values via a Helm helper, or kept inline if short. (Today the chart accepts inline `json:` or a ConfigMap ref via `jsonRef.configMapRef`.)

> **Convention:** dashboard JSON files live under `dashboards/<area>/<name>.json`, NOT inside chart `templates/`. Templates contain the CR wrapper only.

## Authoring a new dashboard

1. Build it in Grafana (or copy an upstream JSON).
2. Export → "View JSON". Save under `dashboards/<area>/<name>.json`.
3. **Strip these** before committing:
   - `id` (Grafana will assign one)
   - `uid` (set it explicitly to a stable string in the file, not the auto-generated one)
   - any `__inputs` and `__elements` blocks from a fresh import
4. Replace datasource references with **uid** references that match the in-cluster datasources (`mimir`, `loki`, `tempo`, `alertmanager`).
5. Add a `GrafanaDashboard` entry — choose Layout A or B.
6. Open a PR with `helm template` output in the description so reviewers can diff the CR.

## Adding a folder

Add an entry to `folders:` in `charts/observability-dashboards/values.yaml`:

```yaml
folders:
  - name: my-area          # kebab-case CR name
    title: "My Area"       # display name in Grafana
```

Reference it from a dashboard via `folderRef: my-area`.

## Cutover from existing chart-loaded dashboards

The grafana app today ships dashboards via the chart's `dashboards:` map (file-provider, baked into the Deployment). Those keep working — the operator doesn't touch them. Migrate one at a time:

1. Find the dashboard in the grafana app's `dashboards:` block.
2. Either:
   - **Recreate as a CR** under the matching folder. Delete the entry from the grafana app values.
   - Or **leave it where it is** if it's an unmodified upstream gnetId import that's easier to keep as a file provider.
3. After the dashboard list shrinks materially, consider whether the `dashboardProviders:` block in the grafana app values is still needed.

There is no hard deadline. The two systems coexist indefinitely.

## Why external mode (and not letting the operator own grafana)

The vanilla grafana chart already encodes a lot of non-trivial config: OIDC integration with Keycloak (`auth.generic_oauth`), datasources with trace→log derived fields, the `unified_alerting` block pointing at the apprise-adapter, admin secret wiring. Reproducing all of that in a `Grafana` CR (`spec.config`, `spec.deployment`, `spec.service`) would be a large rewrite for no functional gain. External mode lets us migrate the **content** plane (dashboards/folders) to operator-managed CRs while leaving the **platform** plane (the grafana pod and its config) on the well-trodden helm path.

If a future change wants the operator to fully own grafana, the migration would be: replace the grafana app with a Grafana CR carrying `spec.config` ≈ today's `grafana.ini`, `spec.deployment.spec.template.spec.containers[].envFrom` ≈ today's `envFromSecrets`, and so on. Not planned.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Dashboard not appearing | `instanceSelector` doesn't match the `Grafana` CR labels | The chart's `_helpers.tpl` uses the same selector everywhere; the operator picks up changes within `resyncPeriod` (default 5m). Force-reconcile: `kubectl delete grafanadashboard <name>` (the CR will be re-created by ArgoCD). |
| `Grafana` CR shows `NoMatchingInstances` | Admin secret missing or wrong keys | Confirm `grafana-admin` Secret has `admin-user` / `admin-password`. Operator pod logs will say so. |
| Operator pod CrashLoop on first install | CRDs not yet present | Operator chart installs its own CRDs in the same release; if the chart was deployed with `installCRDs: false`, install the CRDs out-of-band. We use the chart default (install). |
| Dashboard JSON renders blank | Datasource uid in the JSON doesn't match what the grafana app declares | Open the JSON; replace `${DS_PROMETHEUS}` / `${DS_LOKI}` style placeholders with concrete `uid: mimir` / `uid: loki` / `uid: tempo`. |
| Dashboard imports correctly but panels say "Datasource not found" | Same as above OR the datasource hasn't fully synced after a grafana restart | `kubectl rollout restart deployment/grafana -n observability` and wait. |

## File map

```
charts/observability-dashboards/
  Chart.yaml
  values.yaml                          # grafana pointer + folders + dashboards lists
  templates/
    _helpers.tpl                       # standard labels + instanceSelector helpers
    grafana-external.yaml              # Grafana CR (external mode)
    folders.yaml                       # GrafanaFolder CRs (range over values.folders)
    dashboards.yaml                    # GrafanaDashboard CRs (range over values.dashboards)

dashboards/                            # JSON sources (one file per dashboard)
  envoy-ai-gateway/
    per-user.json                      # populated in task #7

docs/grafana-operator-and-dashboards.md  # this file
```

## Related

- `docs/observability-stack.md` — Mimir/Loki/Tempo/Alloy topology
- `docs/observability-dashboards.md` — per-subsystem dashboard inventory
- `docs/observability-fix-no-data-dashboards.md` — fixes for the gap in the existing dashboard data
- `charts/apps/values.yaml` — the `grafana-operator` and `observability-dashboards` Applications
