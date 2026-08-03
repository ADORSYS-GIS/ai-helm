# Grafana PDF Export (dashboard-reporter-app)

**Plugin:** [`mahendrapaipuri/grafana-dashboard-reporter-app`](https://github.com/mahendrapaipuri/grafana-dashboard-reporter-app) (OSS)
**Chart:** `charts/grafana-pdf-reporter` (this repo, published to OCI)
**Values:** `ai-helm-values` `environments/prod/values/{grafana,grafana-pdf-reporter}.yaml` + `environments/prod/deps/grafana/reporter-provisioning.yaml`

## What this does

Adds a **"Report" button** to every Grafana dashboard that exports the current
dashboard as a **PDF**. It is the OSS equivalent of Grafana Enterprise Reports
(the top-right "Export as PDF" menu item is Enterprise-only).

## Architecture

```
┌─────────────────────────────┐
│ Grafana pod (observability) │
│  • dashboard-reporter-app   │  plugin: rasterizes panels → PNG, assembles PDF
│  • image-renderer SIDECAR   │  (already enabled, imageRenderer.enabled: true)
└──────────────┬──────────────┘
               │ remoteChromeUrl: ws://grafana-pdf-reporter:9222
               ▼
┌─────────────────────────────┐
│ grafana-pdf-reporter (new)  │  chromedp/headless-shell — builds the PDF
└─────────────────────────────┘
```

- **image-renderer** is already deployed as a sidecar to the Grafana pod
  (`imageRenderer.enabled: true` in `ai-helm-values` grafana.yaml) — it renders
  each panel to a PNG.
- **grafana-pdf-reporter** is the only NEW deployment: a remote headless-chromium
  (`chromedp/headless-shell`) the reporter plugin uses to assemble the PDF from
  HTML. It is a standard leaf chart, published to OCI and wired as a child of the
  `observability` orchestrator (sync-wave 0).
- The **report button** is a per-dashboard *link* injected into every dashboard
  at generation time (see below) — no per-dashboard hardcoding.

## Changes

### ai-helm (this repo)

1. **New chart `charts/grafana-pdf-reporter`** — chrome Deployment + Service
   (port 9222), `shmSize` emptyDir at `/dev/shm`, non-root. Added to
   `release-please-config.json`.
2. **Observability orchestrator** (`charts/observability/values.yaml`) — new
   child `grafana-pdf-reporter` (OCI chart-float, `valuesFromRepo`, sync-wave 0).
3. **Report link injection** (`tools/dashboards/src/dashboards/_report.py` +
   `main.py::_emit`) — every generated dashboard gets a `links[]` entry:
   `/api/plugins/mahendrapaipuri-dashboardreporter-app/resources/report?dashUid=<uid>`.
   Regenerated all dashboard JSON. The 3 vendored (non-generated) dashboards
   (`alloy-collector`, `tempo-single-binary`, `nvidia-dcgm-12239`) got the link
   added manually.

### ai-helm-values (sibling repo)

1. **`environments/prod/values/grafana.yaml`**:
   - `plugins:` — added the reporter plugin (URL form of `GF_INSTALL_PLUGINS`).
   - `grafana.ini [plugins]` — `allow_loading_unsigned_plugins` (it is UNSIGNED)
     + `forward_host_env_vars`.
   - `grafana.ini [feature_toggles]` — `accessControlOnCall,idForwarding,externalServiceAccounts`.
   - `grafana.ini [auth]` — `managed_service_accounts_enabled: true`.
   - `extraConfigmapMounts` — mounts the reporter provisioning ConfigMap at
     `/etc/grafana/provisioning/plugins/reporter.yml`.
2. **`environments/prod/deps/grafana/reporter-provisioning.yaml`** — ConfigMap
   enabling the app + `remoteChromeUrl: ws://grafana-pdf-reporter:9222` +
   `appUrl` (internal Service).
3. **`environments/prod/values/grafana-pdf-reporter.yaml`** — chrome image tag +
   resources (ADR-0057).

## Using it

- Open any dashboard → top-right **"Report"** button (doc icon) → PDF opens in a
  new tab, carrying the current time range + template variables.
- Direct URL (scriptable):
  `https://grafana.ai.camer.digital/api/plugins/mahendrapaipuri-dashboardreporter-app/resources/report?dashUid=<UID>`
  with optional `from`/`to`/`var-*`, `layout`, `orientation`, `theme`, `dashboardMode`.
- The plugin enforces the requesting user has at least **Viewer** on the dashboard
  (respects folder-level RBAC, ADR-0077).

## Security note

The reporter plugin is **unsigned** (Grafana Labs will not sign it because it
competes with Enterprise Reports). It is whitelisted deliberately. Review the
upstream source before bumping the pinned version (v1.13.0).

## Troubleshooting

- **403 "permission"** → the requesting user lacks View on the dashboard (or is
  anonymous with no token). Use an authenticated session / service account.
- **Plugin not loading** → check `allow_loading_unsigned_plugins` and that the
  plugin installed (pod logs: `Plugin registered`).
- **PDF hangs / empty** → check the `grafana-pdf-reporter` pod is up and the
  `remoteChromeUrl` matches the Service name; check the image-renderer sidecar
  logs for panel-render errors.

## Tested

Validated on a throwaway k3d cluster (see `plans/grafana-pdf-test/`): a test
dashboard exported to a valid 1-page landscape PDF with both panels embedded;
`orientation=portrait&layout=simple` overrides worked.
