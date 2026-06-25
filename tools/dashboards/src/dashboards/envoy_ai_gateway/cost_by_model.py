"""Envoy AI Gateway — cost by model, monthly (GENERATED SOURCE).

Answers "what did each model cost this month?" with a minimum granularity of
days: the headline panel is a stacked daily-bars timeseries, one series per
model, defaulting to a 30-day window. Optional Client (azp) / Model filters.

The JSON file is regenerated from this module — do **not** hand-edit it.

    uv run dashboards build

Architecture decision: docs/adr/0008-python-dashboard-generation.md.
Data path the dashboard consumes: docs/per-user-observability.md.
"""

from __future__ import annotations

import json

from grafana_foundation_sdk.builders import dashboard as db
from grafana_foundation_sdk.cog.encoder import JSONEncoder
from grafana_foundation_sdk.models import dashboard as dm

from dashboards._common import GATEWAY_SERVICE_NAME, LABEL_AZP, LABEL_MODEL
from dashboards.envoy_ai_gateway import _shared as sh

OUTPUT_PATH: str = "charts/observability-dashboards/files/envoy-ai-gateway/cost-by-model.json"

# Spans ALL attributed traffic (humans + service accounts) regardless of the
# filter variables' defaults — every gateway stream carries a user_id label
# (a real sub or an "unstamped:*"/"missing:*" sentinel), so `user_id=~".+"`
# matches everything while staying a valid selector.
_SELECTOR = sh.selector('azp=~"$azp"', 'user_id=~".+"', 'model=~"$model"')

_COST = "gen_ai_usage_custom_total_cost"
_TOKENS = "gen_ai_usage_total_tokens"

_LEGEND_MODEL = "{{" + LABEL_MODEL + "}}"


def _panel_total_cost() -> object:
    return sh.stat_panel(
        title="Total cost (selected range)",
        expr=sh.usd(f"sum(sum_over_time({_SELECTOR} {sh.unwrap(_COST)} [$__range]))"),
        unit="currencyUSD",
        color="orange",
        grid=(4, 8, 0, 1),
    )


def _panel_total_tokens() -> object:
    return sh.stat_panel(
        title="Total tokens (selected range)",
        expr=f"sum(sum_over_time({_SELECTOR} {sh.unwrap(_TOKENS)} [$__range]))",
        unit="short",
        color="green",
        grid=(4, 8, 8, 1),
    )


def _panel_total_requests() -> object:
    return sh.stat_panel(
        title="Total requests (selected range)",
        expr=f"sum(count_over_time({_SELECTOR} [$__range]))",
        unit="short",
        color="blue",
        grid=(4, 8, 16, 1),
    )


def _panel_cost_per_day_by_model() -> object:
    # [1d] window + step="1d" (set by daily_bars_panel) → one non-overlapping
    # bar per calendar day, stacked by model. This is the "min granularity of
    # days" contract: the resolution is pinned to a day and can't go finer.
    expr = sh.usd(f"sum by ({LABEL_MODEL}) (sum_over_time({_SELECTOR} {sh.unwrap(_COST)} [1d]))")
    return sh.daily_bars_panel(
        title="Cost per day, by model",
        expr=expr,
        legend=_LEGEND_MODEL,
        unit="currencyUSD",
        grid=(11, 24, 0, 5),
    )


def _panel_cost_by_model_totals() -> object:
    # sum_over_time can't take an inline by() (Loki) — group via the outer
    # sum by; unwrap extracts only the cost field so cardinality stays bounded.
    cost_sum = f"sum_over_time({_SELECTOR} {sh.unwrap(_COST)} [$__range])"
    expr = f"sort_desc(sum by ({LABEL_MODEL}) ({sh.usd(cost_sum)}))"
    return sh.bargauge_panel(
        title="Cost by model — total (selected range)",
        expr=expr,
        legend=_LEGEND_MODEL,
        unit="currencyUSD",
        color="orange",
        grid=(11, 12, 0, 16),
    )


def _panel_cost_by_model_pie() -> object:
    expr = sh.usd(
        f"sum by ({LABEL_MODEL}) (sum_over_time({_SELECTOR} {sh.unwrap(_COST)} [$__range]))"
    )
    return sh.pie_panel(
        title="Cost share by model (selected range)",
        expr=expr,
        legend_label=_LEGEND_MODEL,
        grid=(11, 12, 12, 16),
    )


_DESCRIPTION = (
    "Cost per model for the Envoy AI Gateway, daily granularity. The headline "
    "panel stacks one bar per day per model (resolution pinned to 1d). Default "
    "window is 30 days — set the range to a calendar month for monthly totals. "
    "Cost = gen_ai.usage.custom_total_cost (micro-USD ÷ 1e6; ADR-0028/0051). "
    "Spans all attributed traffic incl. service accounts. "
    "See docs/per-user-observability.md. "
    "GENERATED — source: tools/dashboards/envoy_ai_gateway/cost_by_model.py."
)


def _dashboard() -> db.Dashboard:
    return (
        db.Dashboard("AI Gateway — cost by model (monthly)")
        .uid("envoy-ai-gateway-cost-by-model")
        .tags(["ai-gateway", "cost", "model", "loki"])
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
        .with_panel(sh.row("Cost by model", y=0))
        .with_panel(_panel_total_cost())
        .with_panel(_panel_total_tokens())
        .with_panel(_panel_total_requests())
        .with_panel(_panel_cost_per_day_by_model())
        .with_panel(_panel_cost_by_model_totals())
        .with_panel(_panel_cost_by_model_pie())
    )


def build() -> dict:
    return json.loads(json.dumps(_dashboard().build(), cls=JSONEncoder))
