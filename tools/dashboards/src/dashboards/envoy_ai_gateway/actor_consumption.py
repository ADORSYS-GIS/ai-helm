"""Envoy AI Gateway — actor consumption (GENERATED SOURCE).

Pick ONE actor and see their spend per month / per day and across models, from
the precomputed Mimir metrics (ADR-0058) via PromQL — instant at any range. The
actor selector is the `display_name` label = a person's name for humans and the
repository for CI, so "user or actor (e.g. repository)" is one picker. Optional
Client (azp) / Model filters.

The JSON file is regenerated from this module — do **not** hand-edit it.

    uv run dashboards build

ADR: docs/adr/0058-precompute-gateway-usage-metrics-to-mimir.md (+ ADR-0008).
"""

from __future__ import annotations

import json

from grafana_foundation_sdk.builders import dashboard as db
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

OUTPUT_PATH: str = "charts/observability-dashboards/files/envoy-ai-gateway/actor-consumption.json"

_SEL = sh.selector('display_name=~"$actor"', 'azp=~"$azp"', 'model=~"$model"')

_LEGEND_MODEL = "{{" + LABEL_MODEL + "}}"
_LEGEND_AZP = "{{" + LABEL_AZP + "}}"


def _panel_total_cost() -> object:
    return sh.stat_panel(
        title="Cost — selected range (≈ per month)",
        expr=sh.usd(f"sum(increase({METRIC_COST_MICRO_USD}{_SEL}[$__range]))"),
        unit="currencyUSD",
        color="orange",
        grid=(4, 8, 0, 1),
    )


def _panel_total_tokens() -> object:
    return sh.stat_panel(
        title="Tokens — selected range",
        expr=f"sum(increase({METRIC_TOKENS}{_SEL}[$__range]))",
        unit="short",
        color="green",
        grid=(4, 8, 8, 1),
    )


def _panel_total_requests() -> object:
    return sh.stat_panel(
        title="Requests — selected range",
        expr=f"sum(increase({METRIC_REQUESTS}{_SEL}[$__range]))",
        unit="short",
        color="blue",
        grid=(4, 8, 16, 1),
    )


def _panel_cost_per_day_by_model() -> object:
    expr = sh.usd(f"sum by ({LABEL_MODEL}) (increase({METRIC_COST_MICRO_USD}{_SEL}[1d]))")
    return sh.daily_bars_panel(
        title="Cost per day, by model",
        expr=expr,
        legend=_LEGEND_MODEL,
        unit="currencyUSD",
        grid=(11, 24, 0, 5),
    )


def _panel_cost_by_model_pie() -> object:
    expr = sh.usd(f"sum by ({LABEL_MODEL}) (increase({METRIC_COST_MICRO_USD}{_SEL}[$__range]))")
    return sh.pie_panel(
        title="Which models (cost share, selected range)",
        expr=expr,
        legend_label=_LEGEND_MODEL,
        grid=(11, 12, 0, 16),
    )


def _panel_cost_by_channel() -> object:
    inner = f"sum by ({LABEL_AZP}) (increase({METRIC_COST_MICRO_USD}{_SEL}[$__range]))"
    return sh.bargauge_panel(
        title="Cost by channel (azp, selected range)",
        expr=f"topk(20, {sh.usd(inner)})",
        legend=_LEGEND_AZP,
        unit="currencyUSD",
        color="purple",
        grid=(11, 12, 12, 16),
    )


_DESCRIPTION = (
    "Per-actor consumption for the Envoy AI Gateway, from the precomputed Mimir "
    "metrics (ADR-0058, PromQL increase()). The 'Actor' variable is the "
    "display_name label — a person's name for humans, the repository for CI — so "
    "one picker covers 'user or actor (e.g. repository)'. Cost over the selected "
    "range ≈ the actor's monthly spend (default 30d); the daily-bars panel gives "
    "per-day, stacked by model. Cost ÷1e6 for USD (ADR-0028/0051). ⚠️ LibreChat "
    "agent runs + RAG embeddings fall back to azp=internal-key-librechat, not the "
    "human. ⚠️ Forward-only history. "
    "GENERATED — source: tools/dashboards/envoy_ai_gateway/actor_consumption.py."
)


def _dashboard() -> db.Dashboard:
    return (
        db.Dashboard("AI Gateway — actor consumption")
        .uid("envoy-ai-gateway-actor-consumption")
        .tags(["ai-gateway", "cost", "per-user", "mimir"])
        .description(_DESCRIPTION)
        .timezone("browser")
        .editable()
        .tooltip(dm.DashboardCursorSync.CROSSHAIR)
        .refresh("5m")
        .time("now-30d", "now")
        .with_variable(
            sh.actor_var(
                name="actor",
                label="Actor (user / repo)",
                definition=sh.label_values(METRIC_REQUESTS, LABEL_DISPLAY_NAME),
            )
        )
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
        .with_panel(sh.row("Actor consumption", y=0))
        .with_panel(_panel_total_cost())
        .with_panel(_panel_total_tokens())
        .with_panel(_panel_total_requests())
        .with_panel(_panel_cost_per_day_by_model())
        .with_panel(_panel_cost_by_model_pie())
        .with_panel(_panel_cost_by_channel())
    )


def build() -> dict:
    return json.loads(json.dumps(_dashboard().build(), cls=JSONEncoder))
