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
# Precomputed AI Gateway usage METRICS in Mimir (ADR-0058). Emitted by Alloy
# `loki.process` `stage.metrics` (default `loki_process_custom_` prefix) at
# ingest and scraped to Mimir, so the cost dashboards read cheap PromQL
# time-series instead of unwrap-scanning a month of Loki logs from the
# rate-limited object store. All three carry the ADR-0046 attribution labels
# (model / azp / display_name / user_id / email / billing_plan / service_name).
# Counters → use PromQL `increase(...[window])`. Cost is micro-USD (÷1e6).
# ---------------------------------------------------------------------------
_METRIC_PREFIX = "loki_process_custom_"
METRIC_COST_MICRO_USD = _METRIC_PREFIX + "gen_ai_usage_cost_micro_usd"
METRIC_TOKENS = _METRIC_PREFIX + "gen_ai_usage_tokens"
METRIC_REQUESTS = _METRIC_PREFIX + "gen_ai_requests"


# ---------------------------------------------------------------------------
# Phase-3 "gamified scoreboard" knobs (ADR-0060).
# ---------------------------------------------------------------------------
# Default monthly AI-inference budget the burn gauge measures against. The
# scoreboard exposes this as an editable textbox variable ($budget), so this is
# only the default — change it in the UI without regenerating. Set to $3000
# (real budget ~$2.5k, rounded up for headroom; run-rate ~$5k means the gauge
# will read >100% until usage settles — that's the point of the gamified view).
DEFAULT_MONTHLY_BUDGET = 3000

# AI-governance doctrine (referenced by the scoreboard's text + news panels).
# The site itself (MkDocs) exposes no RSS feed, so the news panel reads the
# GitHub repo's commits Atom feed — real "governance updates" that actually
# render. Grafana fetches it server-side, so the Grafana pod needs egress to
# github.com (added to the prod deps CiliumNetworkPolicy in ai-helm-values).
GOVERNANCE_URL = "https://adorsys-gis.github.io/ai-governance/"
GOVERNANCE_NEWS_FEED = "https://github.com/ADORSYS-GIS/ai-governance/commits.atom"


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
