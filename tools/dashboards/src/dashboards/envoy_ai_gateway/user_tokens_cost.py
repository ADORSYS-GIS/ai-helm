"""Envoy AI Gateway — users: tokens & cost (GENERATED SOURCE).

The user x tokens x cost cross: one table row per actor (display_name) with
requests / tokens / cost side by side, plus per-day stacked breakdowns and
ranked leaderboards. Reads the precomputed Mimir metrics (ADR-0058) via PromQL.
display_name is a person for humans and the repository for CI, so "user/actor"
is one axis.

The JSON file is regenerated from this module — do **not** hand-edit it.

    uv run dashboards build

ADR: docs/adr/0058-precompute-gateway-usage-metrics-to-mimir.md (+ ADR-0008).
"""

from __future__ import annotations

import json

from grafana_foundation_sdk.builders import dashboard as db
from grafana_foundation_sdk.builders import table
from grafana_foundation_sdk.cog.encoder import JSONEncoder
from grafana_foundation_sdk.models import dashboard as dm

from dashboards._common import (
    LABEL_AZP,
    LABEL_DISPLAY_NAME,
    LABEL_MODEL,
    METRIC_COST_MICRO_USD,
    METRIC_REQUESTS,
    METRIC_TOKENS,
)
from dashboards.envoy_ai_gateway import _shared as sh

OUTPUT_PATH: str = "charts/observability-dashboards/files/envoy-ai-gateway/user-tokens-cost.json"

_SEL = sh.selector('azp=~"$azp"', 'model=~"$model"')

_LEGEND_USER = "{{" + LABEL_DISPLAY_NAME + "}}"

# Per-actor range totals (instant PromQL — one value per display_name).
_COST_BY_USER = sh.usd(
    f"sum by ({LABEL_DISPLAY_NAME}) (increase({METRIC_COST_MICRO_USD}{_SEL}[$__range]))"
)
_TOKENS_BY_USER = f"sum by ({LABEL_DISPLAY_NAME}) (increase({METRIC_TOKENS}{_SEL}[$__range]))"
_REQS_BY_USER = f"sum by ({LABEL_DISPLAY_NAME}) (increase({METRIC_REQUESTS}{_SEL}[$__range]))"


# ---------------------------------------------------------------------------
# Stats row
# ---------------------------------------------------------------------------


def _panel_total_cost() -> object:
    return sh.stat_panel(
        title="Total cost (range)",
        expr=sh.usd(f"sum(increase({METRIC_COST_MICRO_USD}{_SEL}[$__range]))"),
        unit="currencyUSD",
        color="orange",
        grid=(4, 6, 0, 1),
    )


def _panel_total_tokens() -> object:
    return sh.stat_panel(
        title="Total tokens (range)",
        expr=f"sum(increase({METRIC_TOKENS}{_SEL}[$__range]))",
        unit="short",
        color="green",
        grid=(4, 6, 6, 1),
    )


def _panel_unique_users() -> object:
    return sh.stat_panel(
        title="Unique actors (range)",
        expr=f"count(sum by ({LABEL_DISPLAY_NAME}) (increase({METRIC_REQUESTS}{_SEL}[$__range])))",
        unit="short",
        color="purple",
        grid=(4, 6, 12, 1),
    )


def _panel_cost_per_1k_tokens() -> object:
    cost = f"sum(increase({METRIC_COST_MICRO_USD}{_SEL}[$__range])) / 1e6"
    ktok = f"(sum(increase({METRIC_TOKENS}{_SEL}[$__range])) / 1000)"
    return sh.stat_panel(
        title="Blended cost / 1k tokens (range)",
        expr=f"({cost}) / ({ktok})",
        unit="currencyUSD",
        color="blue",
        grid=(4, 6, 18, 1),
    )


# ---------------------------------------------------------------------------
# The user x tokens x cost table
# ---------------------------------------------------------------------------


def _panel_user_table() -> table.Panel:
    # Three instant table-format PromQL queries (A=cost, B=tokens, C=requests),
    # each `sum by (display_name)`. Prometheus instant+table returns one row per
    # series with a "Value #<refId>" column; `merge` collapses the three frames
    # into one row per display_name, `organize` renames + drops Time, `sortBy`
    # ranks by cost. Far simpler than the Loki timeSeriesTable path.
    panel = (
        table.Panel()
        .title("Per actor — requests · tokens · cost (selected range)")
        .datasource(sh.MIMIR_DS)
        .grid_pos(dm.GridPos(h=12, w=24, x=0, y=5))
        .filterable(True)
        .with_target(sh.prom_target(_COST_BY_USER, ref_id="A", instant=True, fmt="table"))
        .with_target(sh.prom_target(_TOKENS_BY_USER, ref_id="B", instant=True, fmt="table"))
        .with_target(sh.prom_target(_REQS_BY_USER, ref_id="C", instant=True, fmt="table"))
        .with_transformation(dm.DataTransformerConfig(id_val="merge", options={}))
        .with_transformation(
            dm.DataTransformerConfig(
                id_val="organize",
                options={
                    "renameByName": {
                        LABEL_DISPLAY_NAME: "Actor",
                        "Value #A": "Cost ($)",
                        "Value #B": "Tokens",
                        "Value #C": "Requests",
                    },
                    "excludeByName": {"Time": True},
                    "indexByName": {},
                },
            )
        )
        .with_transformation(
            dm.DataTransformerConfig(
                id_val="sortBy",
                options={"fields": {}, "sort": [{"field": "Cost ($)", "desc": True}]},
            )
        )
    )
    return panel.override_by_name(
        "Cost ($)",
        [
            dm.DynamicConfigValue(id_val="unit", value="currencyUSD"),
            dm.DynamicConfigValue(id_val="decimals", value=2),
        ],
    )


# ---------------------------------------------------------------------------
# Per-day breakdowns + leaderboards
# ---------------------------------------------------------------------------


def _panel_cost_per_day_by_user() -> object:
    expr = sh.usd(f"sum by ({LABEL_DISPLAY_NAME}) (increase({METRIC_COST_MICRO_USD}{_SEL}[1d]))")
    return sh.daily_bars_panel(
        title="Cost per day, by actor",
        expr=expr,
        legend=_LEGEND_USER,
        unit="currencyUSD",
        grid=(10, 12, 0, 17),
    )


def _panel_tokens_per_day_by_user() -> object:
    expr = f"sum by ({LABEL_DISPLAY_NAME}) (increase({METRIC_TOKENS}{_SEL}[1d]))"
    return sh.daily_bars_panel(
        title="Tokens per day, by actor",
        expr=expr,
        legend=_LEGEND_USER,
        unit="short",
        grid=(10, 12, 12, 17),
    )


def _panel_top_users_cost() -> object:
    return sh.bargauge_panel(
        title="Top actors by cost (selected range)",
        expr=f"topk(20, {_COST_BY_USER})",
        legend=_LEGEND_USER,
        unit="currencyUSD",
        color="orange",
        grid=(10, 12, 0, 27),
    )


def _panel_top_users_tokens() -> object:
    return sh.bargauge_panel(
        title="Top actors by tokens (selected range)",
        expr=f"topk(20, {_TOKENS_BY_USER})",
        legend=_LEGEND_USER,
        unit="short",
        color="green",
        grid=(10, 12, 12, 27),
    )


_DESCRIPTION = (
    "Users x tokens x cost for the Envoy AI Gateway, from the precomputed Mimir "
    "metrics (ADR-0058, PromQL increase()). The table gives one row per actor "
    "(display_name = a person for humans, the repository for CI) with requests / "
    "tokens / cost side by side over the selected range (default 30d ≈ monthly); "
    "per-day stacked panels add daily granularity, leaderboards rank by cost and "
    "tokens. Cost ÷1e6 for USD (ADR-0028/0051). Filters: azp, model. "
    "⚠️ Forward-only history; LibreChat agents/embeddings fall back to "
    "azp=internal-key-librechat. "
    "GENERATED — source: tools/dashboards/envoy_ai_gateway/user_tokens_cost.py."
)


def _dashboard() -> db.Dashboard:
    return (
        db.Dashboard("AI Gateway — users: tokens & cost")
        .uid("envoy-ai-gateway-user-tokens-cost")
        .tags(["ai-gateway", "cost", "tokens", "per-user", "mimir"])
        .description(_DESCRIPTION)
        .timezone("browser")
        .editable()
        .tooltip(dm.DashboardCursorSync.CROSSHAIR)
        .refresh("5m")
        .time("now-30d", "now")
        .with_variable(
            sh.multi_var(
                name="azp",
                label="Client (azp)",
                definition=sh.label_values(METRIC_REQUESTS, LABEL_AZP),
            )
        )
        .with_variable(
            sh.multi_var(
                name="model",
                label="Model",
                definition=sh.label_values(METRIC_REQUESTS, LABEL_MODEL),
            )
        )
        .with_panel(sh.row("Users — tokens & cost", y=0))
        .with_panel(_panel_total_cost())
        .with_panel(_panel_total_tokens())
        .with_panel(_panel_unique_users())
        .with_panel(_panel_cost_per_1k_tokens())
        .with_panel(_panel_user_table())
        .with_panel(_panel_cost_per_day_by_user())
        .with_panel(_panel_tokens_per_day_by_user())
        .with_panel(_panel_top_users_cost())
        .with_panel(_panel_top_users_tokens())
    )


def build() -> dict:
    return json.loads(json.dumps(_dashboard().build(), cls=JSONEncoder))
