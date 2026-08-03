# ADR-0118: Grafana dashboard PDF export via the dashboard-reporter-app plugin

**Status:** Accepted
**Date:** 2026-08-03
**Deciders:** @stephane-segning

## Context

Ticket: *"Install and configure a Grafana plugin that enables exporting
dashboards as PDFs, test it on key dashboards, and document usage for the team."*

Grafana OSS has **no** native PDF export — the top-right "Export as PDF" menu
item is a **Grafana Enterprise** feature. The OSS options are:

| Option | Type | Engine | Status | Verdict |
|---|---|---|---|---|
| `mahendrapaipuri/grafana-dashboard-reporter-app` | Grafana app plugin (Go backend) | headless Chromium → HTML → PDF | actively maintained (v1.13.0) | **chosen** |
| `IzakMarais/reporter` (grafana-reporter) | standalone Go service | LaTeX / pdflatex | effectively unmaintained | rejected |
| `grafana/grafana-image-renderer` | official plugin/service | Chromium → **PNG only** | maintained | prerequisite only (PDF is Enterprise) |

Our Grafana is OSS **12.3.1**, **stateless** (ADR-0023), deployed via the vanilla
`grafana/grafana` chart (10.5.15) as the `grafana` Application in `observability`
(sync-wave 0), with all config in the private `ai-helm-values` repo (ADR-0056).
It already runs **grafana-image-renderer as a sidecar** (`imageRenderer.enabled: true`)
for PNG panel export.

## Decision

1. **Adopt `mahendrapaipuri/grafana-dashboard-reporter-app`** (pinned v1.13.0) as the
   PDF-export mechanism. It rasterizes each panel to a PNG via the existing
   image-renderer sidecar, then assembles the PDF from HTML via a headless chromium.
   Rejected `IzakMarais/reporter` (unmaintained, LaTeX, separate service to operate).

2. **Deploy the chromium as a standard leaf chart `charts/grafana-pdf-reporter`**
   (chromedp/headless-shell Deployment + Service, port 9222), published to OCI and
   wired as a child of the `observability` orchestrator (sync-wave 0, `valuesFromRepo`).
   **Chrome-only, not renderer+chrome**: the image-renderer is already a sidecar, so
   duplicating it would be redundant. The reporter plugin connects via
   `remoteChromeUrl: ws://grafana-pdf-reporter:9222`.

3. **Report button on ALL dashboards, injected at generation time** — no per-dashboard
   hardcoding. `tools/dashboards/src/dashboards/_report.py` + `main.py::_emit()` (the
   single choke point every generated dashboard passes through) append a `Report`
   dashboard link (`/api/plugins/mahendrapaipuri-dashboardreporter-app/resources/report?dashUid=<uid>`)`
   to every generated dashboard. The 3 vendored (non-generated) dashboards
   (`alloy-collector`, `tempo-single-binary`, `nvidia-dcgm-12239`) got the link added
   manually. This is declarative and survives stateless-Grafana rolls.

4. **Grafana config lives in `ai-helm-values`** (ADR-0056): install the plugin, whitelist
   it as unsigned, enable the feature toggles (`accessControlOnCall,idForwarding,
   `externalServiceAccounts`) + `managed_service_accounts_enabled`, and mount a
   provisioning ConfigMap enabling the app with `remoteChromeUrl` + `appUrl`.

## Consequences

**Positive**
- OSS PDF export with a one-click "Report" button on every dashboard.
- Declarative, GitOps-native: the button is part of the dashboard JSON; the chrome is
  a standard chart; the plugin config is in the values repo. Survives pod rolls.
- Reuses the existing image-renderer sidecar — no redundant renderer deployment.
- The plugin enforces the requesting user has at least **Viewer** on the dashboard,
  respecting folder-level RBAC (ADR-0077).

**Negative / trade-offs**
- **The plugin is UNSIGNED** (Grafana Labs will not sign it — it competes with
  Enterprise Reports), so it must be whitelisted. This is a deliberate exception to
  the ADR-0076 precedent of declining unsigned plugins; mitigated by pinning the
  version and reviewing the upstream source. The plugin makes API calls to Grafana
  (via an auto-provisioned service-account token from `externalServiceAccounts`).
- Requires `externalServiceAccounts` + `managed_service_accounts_enabled` (new auth
  surface) and the feature toggles.
- The report button only appears on dashboards shipped through this repo's pipeline
  (generated or vendored here); dashboards loaded purely via the grafana chart's
  `dashboards:` map in `ai-helm-values` would need the link added there too.

## Alternatives considered

- **`IzakMarais/reporter`** — rejected: unmaintained (Gopkg/dep, Travis), LaTeX
  dependency, a separate service to operate.
- **Grafana Enterprise Reports** — rejected: paid, and the whole point is an OSS
  solution.
- **A reconciliation Job/CronJob** adding the link to every dashboard via the Grafana
  API — rejected: a runtime mutation that must re-run after every stateless roll,
  against the repo's dashboards-as-code philosophy.

## References

- Playbook: [`docs/playbooks/grafana-pdf-export.md`](../playbooks/grafana-pdf-export.md)
- Chart: `charts/grafana-pdf-reporter`
- Upstream: https://github.com/mahendrapaipuri/grafana-dashboard-reporter-app
