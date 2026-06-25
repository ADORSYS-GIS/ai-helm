"""Envoy AI Gateway — users: tokens & cost (GENERATED SOURCE).

The user x tokens x cost cross: one table row per actor (display_name) with
requests / tokens / cost side by side, plus per-day stacked breakdowns and
ranked leaderboards. display_name is a person's name for humans and the
repository for CI, so "user/actor" is one axis.

The JSON file is regenerated from this module — do **not** hand-edit it.

    uv run dashboards build

Architecture decision: docs/adr/0008-python-dashboard-generation.md.
Data path the dashboard consumes: docs/per-user-observability.md.
"""

from __future__ import annotations

import json

from grafana_foundation_sdk.builders import dashboard as db
from grafana_foundation_sdk.builders import table
from grafana_foundation_sdk.cog.encoder import JSONEncoder
from grafana_foundation_sdk.models import dashboard as dm

from dashboards._common import (
    GATEWAY_SERVICE_NAME,
    LABEL_AZP,
    LABEL_DISPLAY_NAME,
    LABEL_MODEL,
)
from dashboards.envoy_ai_gateway import _shared as sh

OUTPUT_PATH: str = "charts/observability-dashboards/files/envoy-ai-gateway/user-tokens-cost.json"

# All attributed traffic (humans + service accounts / repos), refined by the
# azp / model filters. user_id=~".+" matches every gateway stream.
_SELECTOR = sh.selector('azp=~"$azp"', 'user_id=~".+"', 'model=~"$model"')

_COST = "gen_ai_usage_custom_total_cost"
_TOKENS = "gen_ai_usage_total_tokens"

_LEGEND_USER = "{{" + LABEL_DISPLAY_NAME + "}}"

# Per-user range aggregations. The [$__range] window means the LAST evaluated
# point of each series IS the per-range total (same trick as the stat panels);
# timeSeriesTable's lastNotNull stat then reads exactly that total.
_COST_BY_USER = sh.usd(
    f"sum by ({LABEL_DISPLAY_NAME}) (sum_over_time({_SELECTOR} {sh.unwrap(_COST)} [$__range]))"
)
_TOKENS_BY_USER = (
    f"sum by ({LABEL_DISPLAY_NAME}) (sum_over_time({_SELECTOR} {sh.unwrap(_TOKENS)} [$__range]))"
)
_REQS_BY_USER = f"sum by ({LABEL_DISPLAY_NAME}) (count_over_time({_SELECTOR} [$__range]))"


# ---------------------------------------------------------------------------
# Stats row
# ---------------------------------------------------------------------------


def _panel_total_cost() -> object:
    return sh.stat_panel(
        title="Total cost (range)",
        expr=sh.usd(f"sum(sum_over_time({_SELECTOR} {sh.unwrap(_COST)} [$__range]))"),
        unit="currencyUSD",
        color="orange",
        grid=(4, 6, 0, 1),
    )


def _panel_total_tokens() -> object:
    return sh.stat_panel(
        title="Total tokens (range)",
        expr=f"sum(sum_over_time({_SELECTOR} {sh.unwrap(_TOKENS)} [$__range]))",
        unit="short",
        color="green",
        grid=(4, 6, 6, 1),
    )


def _panel_unique_users() -> object:
    return sh.stat_panel(
        title="Unique actors (range)",
        expr=f"count(sum by ({LABEL_DISPLAY_NAME}) (count_over_time({_SELECTOR} [$__range])))",
        unit="short",
        color="purple",
        grid=(4, 6, 12, 1),
    )


def _panel_cost_per_1k_tokens() -> object:
    # Blended efficiency: total USD / (total tokens / 1000). Arithmetic between
    # two scalar LogQL aggregations is valid; both collapse via sum().
    cost = f"sum(sum_over_time({_SELECTOR} {sh.unwrap(_COST)} [$__range])) / 1e6"
    ktok = f"(sum(sum_over_time({_SELECTOR} {sh.unwrap(_TOKENS)} [$__range])) / 1000)"
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
    # Three range queries (refIds A/B/C) grouped by display_name. The transform
    # chain is order-critical:
    #   1. timeSeriesTable — reduce each series to its per-range total
    #      (lastNotNull on the [$__range] running sum), one frame per refId with
    #      columns [display_name, "Trend #A"|"#B"|"#C"].
    #   2. merge — collapse the three frames into ONE row per display_name
    #      (Grafana merges rows sharing identical values in shared fields, i.e.
    #      display_name). WITHOUT this, the three frames stay separate and the
    #      table can't show Cost/Tokens/Requests side by side or sort across
    #      them (Grafana "Merge series/tables"; PR #485 review).
    #   3. organize — rename the auto "Trend #X" columns + display_name.
    #   4. sortBy — rank by cost. Cost column carries the USD unit override.
    panel = (
        table.Panel()
        .title("Per actor — requests · tokens · cost (selected range)")
        .datasource(sh.LOKI_DS)
        .grid_pos(dm.GridPos(h=12, w=24, x=0, y=5))
        .filterable(True)
        .with_target(sh.loki_target(_COST_BY_USER, ref_id="A", legend=_LEGEND_USER))
        .with_target(sh.loki_target(_TOKENS_BY_USER, ref_id="B", legend=_LEGEND_USER))
        .with_target(sh.loki_target(_REQS_BY_USER, ref_id="C", legend=_LEGEND_USER))
        .with_transformation(
            dm.DataTransformerConfig(
                id_val="timeSeriesTable",
                options={
                    "A": {"stat": "lastNotNull"},
                    "B": {"stat": "lastNotNull"},
                    "C": {"stat": "lastNotNull"},
                },
            )
        )
        .with_transformation(dm.DataTransformerConfig(id_val="merge", options={}))
        .with_transformation(
            dm.DataTransformerConfig(
                id_val="organize",
                options={
                    "renameByName": {
                        LABEL_DISPLAY_NAME: "Actor",
                        "Trend #A": "Cost ($)",
                        "Trend #B": "Tokens",
                        "Trend #C": "Requests",
                    },
                    "excludeByName": {},
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
    # USD unit + 2 decimals on the cost column (others stay plain counts).
    return panel.override_by_name(
        "Cost ($)",
        [
            dm.DynamicConfigValue(id_val="unit", value="currencyUSD"),
            dm.DynamicConfigValue(id_val="decimals", value=2),
        ],
    )


# ---------------------------------------------------------------------------
# Per-day breakdowns (min granularity = days, like the sibling boards)
# ---------------------------------------------------------------------------


def _panel_cost_per_day_by_user() -> object:
    expr = sh.usd(
        f"sum by ({LABEL_DISPLAY_NAME}) (sum_over_time({_SELECTOR} {sh.unwrap(_COST)} [1d]))"
    )
    return sh.daily_bars_panel(
        title="Cost per day, by actor",
        expr=expr,
        legend=_LEGEND_USER,
        unit="currencyUSD",
        grid=(10, 12, 0, 17),
    )


def _panel_tokens_per_day_by_user() -> object:
    expr = f"sum by ({LABEL_DISPLAY_NAME}) (sum_over_time({_SELECTOR} {sh.unwrap(_TOKENS)} [1d]))"
    return sh.daily_bars_panel(
        title="Tokens per day, by actor",
        expr=expr,
        legend=_LEGEND_USER,
        unit="short",
        grid=(10, 12, 12, 17),
    )


# ---------------------------------------------------------------------------
# Leaderboards (dependable, regardless of the table transform)
# ---------------------------------------------------------------------------


def _panel_top_users_cost() -> object:
    expr = f"topk(20, {_COST_BY_USER})"
    return sh.bargauge_panel(
        title="Top actors by cost (selected range)",
        expr=expr,
        legend=_LEGEND_USER,
        unit="currencyUSD",
        color="orange",
        grid=(10, 12, 0, 27),
    )


def _panel_top_users_tokens() -> object:
    expr = f"topk(20, {_TOKENS_BY_USER})"
    return sh.bargauge_panel(
        title="Top actors by tokens (selected range)",
        expr=expr,
        legend=_LEGEND_USER,
        unit="short",
        color="green",
        grid=(10, 12, 12, 27),
    )


_DESCRIPTION = (
    "Users x tokens x cost for the Envoy AI Gateway. The table gives one row per "
    "actor (display_name = a person for humans, the repository for CI) with "
    "requests / tokens / cost side by side over the selected range (default 30d ≈ "
    "monthly); per-day stacked panels add daily granularity, and the leaderboards "
    "rank by cost and by tokens. Cost = gen_ai.usage.custom_total_cost "
    "(micro-USD ÷ 1e6; ADR-0028/0051). Filters: azp, model. "
    "⚠️ LibreChat agent runs + RAG embeddings fall back to azp=internal-key-librechat "
    "(not the human) — docs/per-user-observability.md. "
    "GENERATED — source: tools/dashboards/envoy_ai_gateway/user_tokens_cost.py."
)


def _dashboard() -> db.Dashboard:
    return (
        db.Dashboard("AI Gateway — users: tokens & cost")
        .uid("envoy-ai-gateway-user-tokens-cost")
        .tags(["ai-gateway", "cost", "tokens", "per-user", "loki"])
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
                definition=f'label_values({{service_name="{GATEWAY_SERVICE_NAME}"}}, {LABEL_AZP})',
            )
        )
        .with_variable(
            sh.multi_var(
                name="model",
                label="Model",
                definition=f'label_values({{service_name="{GATEWAY_SERVICE_NAME}"}}, {LABEL_MODEL})',
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
