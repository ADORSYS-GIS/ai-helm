"""Shared constants for dashboard generators.

Everything here is pure data — no SDK imports — so it can be `import`-ed
from any generator module without dragging the SDK along. Keep it that way.

If a constant is referenced by more than one dashboard, it lives here.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Datasource UIDs — must match what `charts/apps/values.yaml` provisions
# under `grafana.datasources.datasources.yaml.datasources[*].uid`.
# Changing them here without changing the grafana app's values is a
# silent breakage.
# ---------------------------------------------------------------------------
MIMIR_UID = "mimir"
LOKI_UID = "loki"
TEMPO_UID = "tempo"
ALERTMANAGER_UID = "alertmanager"


# ---------------------------------------------------------------------------
# Loki label keys promoted by Alloy's `ai_gateway_user_attribution` stage
# (see ADR-0005 + ADR-0046 and docs/per-user-observability.md).
# ---------------------------------------------------------------------------
LABEL_USER_ID = "user_id"
LABEL_AZP = "azp"
LABEL_MODEL = "model"
LABEL_EMAIL = "email"
LABEL_DISPLAY_NAME = "display_name"
LABEL_BILLING_PLAN = "billing_plan"
LABEL_NAMESPACE = "namespace"
LABEL_POD = "pod"
LABEL_CONTAINER = "container"

# Stream anchor pinned by the same Alloy stage (stage.static_labels) on every
# gateway access-log stream — ADR-0046. Every per-user query selects on it.
GATEWAY_SERVICE_NAME = "envoy-ai-gateway"


# ---------------------------------------------------------------------------
# Service-account client IDs — keep in sync with
# `charts/apps/values.yaml` `security-policies.authConfigs.main.serviceAccountClients`.
# Used by dashboards that want to split human vs SA traffic.
# ---------------------------------------------------------------------------
SERVICE_ACCOUNT_CLIENTS: tuple[str, ...] = (
    "adorsys-gis-github-ci",
    "lightbridge-api-key",
)


# ---------------------------------------------------------------------------
# Color palette — used in stat / threshold panels.
# Grafana built-in semantic colors. Stays stable across themes.
# ---------------------------------------------------------------------------
COLOR_BLUE = "blue"
COLOR_PURPLE = "purple"
COLOR_GREEN = "green"
COLOR_ORANGE = "orange"
COLOR_RED = "red"
COLOR_YELLOW = "yellow"


# ---------------------------------------------------------------------------
# Time defaults applied if a dashboard doesn't override.
# ---------------------------------------------------------------------------
DEFAULT_TIME_FROM = "now-1h"
DEFAULT_TIME_TO = "now"
DEFAULT_REFRESH = "30s"
DEFAULT_REFRESH_INTERVALS: tuple[str, ...] = (
    "10s",
    "30s",
    "1m",
    "5m",
    "15m",
    "30m",
    "1h",
    "6h",
)


# ---------------------------------------------------------------------------
# Grafana dashboard schema version. Tracks the cluster's Grafana.
# Today: Grafana 12 → schemaVersion 42 (audit task #15).
# Bump when grafana is bumped; ADR-0008.
# ---------------------------------------------------------------------------
SCHEMA_VERSION = 42


# ---------------------------------------------------------------------------
# Output paths, relative to repo root. Used by the orchestrator.
# Layout B (central) lives under charts/observability-dashboards/files/.
# Layout A (chart-local) targets each chart's own files/dashboards/ — set
# the OUTPUT_PATH constant on the generator module directly in that case.
# ---------------------------------------------------------------------------
CENTRAL_DASHBOARDS_DIR = "charts/observability-dashboards/files"
