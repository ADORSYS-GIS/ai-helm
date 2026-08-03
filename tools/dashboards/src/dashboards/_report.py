"""Report-link injection for generated dashboards."""

from __future__ import annotations

# The dashboard-reporter-app plugin's report endpoint. Every generated dashboard
# gets a "Report" dashboard link pointing here so the PDF-export button appears
# on ALL dashboards (no per-dashboard hardcoding). The plugin rasterizes panels
# via Grafana's image-renderer sidecar and assembles the PDF via the
# grafana-pdf-reporter chromium. See docs/playbooks/grafana-pdf-export.md.
REPORT_PLUGIN_PATH = "/api/plugins/mahendrapaipuri-dashboardreporter-app/resources/report"


def inject_report_link(dashboard: dict) -> None:
    """Add a "Report" dashboard link (PDF export) to a generated dashboard.

    Reads the dashboard's own `uid` so the link targets the correct dashboard.
    Idempotent: if a link with the same URL already exists, it is left alone.
    """
    uid = dashboard.get("uid")
    if not uid:
        return
    url = f"{REPORT_PLUGIN_PATH}?dashUid={uid}"
    links = dashboard.get("links") or []
    if any(isinstance(l, dict) and l.get("url") == url for l in links):
        return
    links.append(
        {
            "title": "Report",
            "type": "link",
            "url": url,
            "tooltip": "Create a PDF report",
            "icon": "doc",
            "includeVars": True,
            "keepTime": True,
            "targetBlank": True,
        }
    )
    dashboard["links"] = links
