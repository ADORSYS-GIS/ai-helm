"""Envoy AI Gateway — cost by model, monthly (GENERATED SOURCE).

Cost x model with a minimum granularity of days. Reads the precomputed Mimir
metrics (ADR-0058) via PromQL — NOT Loki log-scans — so a 30-day view is instant
on the rate-limited object store. The headline panel stacks one bar per day per
model. Optional Client (azp) / Model filters.

⚠️ Metrics are forward-only (they began when ADR-0058 part A deployed); the 30d
view fills in over ~30 days.

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
    LABEL_MODEL,
    METRIC_COST_MICRO_USD,
    METRIC_REQUESTS,
    METRIC_TOKENS,
)
from dashboards.envoy_ai_gateway import _shared as sh

OUTPUT_PATH: str = "charts/observability-dashboards/files/envoy-ai-gateway/cost-by-model.json"

# Spans all attributed gateway traffic (the metrics exist only for gateway
# requests); azp/model filters refine it.
_SEL = sh.selector('azp=~"$azp"', 'model=~"$model"')

_LEGEND_MODEL = "{{" + LABEL_MODEL + "}}"


def _panel_total_cost() -> object:
    return sh.stat_panel(
        title="Total cost (selected range)",
        expr=sh.usd(f"sum(increase({METRIC_COST_MICRO_USD}{_SEL}[$__range]))"),
        unit="currencyUSD",
        color="orange",
        grid=(4, 8, 0, 1),
    )


def _panel_total_tokens() -> object:
    return sh.stat_panel(
        title="Total tokens (selected range)",
        expr=f"sum(increase({METRIC_TOKENS}{_SEL}[$__range]))",
        unit="short",
        color="green",
        grid=(4, 8, 8, 1),
    )


def _panel_total_requests() -> object:
    return sh.stat_panel(
        title="Total requests (selected range)",
        expr=f"sum(increase({METRIC_REQUESTS}{_SEL}[$__range]))",
        unit="short",
        color="blue",
        grid=(4, 8, 16, 1),
    )


def _panel_cost_per_day_by_model() -> object:
    # increase(...[1d]) at step 1d (set by daily_bars_panel) → one bar per day,
    # stacked by model. The "minimum granularity of days" contract.
    expr = sh.usd(f"sum by ({LABEL_MODEL}) (increase({METRIC_COST_MICRO_USD}{_SEL}[1d]))")
    return sh.daily_bars_panel(
        title="Cost per day, by model",
        expr=expr,
        legend=_LEGEND_MODEL,
        unit="currencyUSD",
        grid=(11, 24, 0, 5),
    )


def _panel_cost_by_model_totals() -> object:
    inner = f"sum by ({LABEL_MODEL}) (increase({METRIC_COST_MICRO_USD}{_SEL}[$__range]))"
    return sh.bargauge_panel(
        title="Cost by model — total (selected range)",
        expr=f"topk(30, {sh.usd(inner)})",
        legend=_LEGEND_MODEL,
        unit="currencyUSD",
        color="orange",
        grid=(11, 12, 0, 16),
    )


def _panel_cost_by_model_pie() -> object:
    expr = sh.usd(f"sum by ({LABEL_MODEL}) (increase({METRIC_COST_MICRO_USD}{_SEL}[$__range]))")
    return sh.pie_panel(
        title="Cost share by model (selected range)",
        expr=expr,
        legend_label=_LEGEND_MODEL,
        grid=(11, 12, 12, 16),
    )


_DESCRIPTION = (
    "Cost per model for the Envoy AI Gateway, daily granularity, from the "
    "precomputed Mimir metrics (ADR-0058) — PromQL increase() over the "
    "loki_process_custom_gen_ai_usage_cost_micro_usd counter (÷1e6 for USD; "
    "ADR-0028/0051), NOT a Loki log-scan. Default 30 days; set the range to a "
    "calendar month for monthly totals. Spans all attributed traffic incl. "
    "service accounts. ⚠️ Forward-only history (began at ADR-0058 part A). "
    "GENERATED — source: tools/dashboards/envoy_ai_gateway/cost_by_model.py."
)


def _dashboard() -> db.Dashboard:
    return (
        db.Dashboard("AI Gateway — cost by model (monthly)")
        .uid("envoy-ai-gateway-cost-by-model")
        .tags(["ai-gateway", "cost", "model", "mimir"])
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
