"""Envoy AI Gateway — actor consumption (GENERATED SOURCE).

Pick ONE actor and see their spend per month / per day and across models. The
actor selector is the `display_name` label, which is the unifying identity for
both humans (e.g. "Ariel Kouebou") and CI repositories (e.g.
"ADORSYS-GIS/keycloak-oid4vp-plugin", "vymalo/flutter-tools") — so "user or
actor (e.g. repository)" is one picker. Optional Client (azp) / Model filters
refine it further.

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

from dashboards._common import (
    GATEWAY_SERVICE_NAME,
    LABEL_AZP,
    LABEL_DISPLAY_NAME,
    LABEL_MODEL,
)
from dashboards.envoy_ai_gateway import _shared as sh

OUTPUT_PATH: str = "charts/observability-dashboards/files/envoy-ai-gateway/actor-consumption.json"

# Scoped to the picked actor; azp/model further refine. display_name=~"$actor"
# with $actor defaulting to ".+" (All) so the dashboard renders before a pick.
_SELECTOR = sh.selector('display_name=~"$actor"', 'azp=~"$azp"', 'model=~"$model"')

_COST = "gen_ai_usage_custom_total_cost"
_TOKENS = "gen_ai_usage_total_tokens"

_LEGEND_MODEL = "{{" + LABEL_MODEL + "}}"
_LEGEND_AZP = "{{" + LABEL_AZP + "}}"


def _panel_total_cost() -> object:
    # With the default 30-day range this stat IS the actor's monthly cost.
    return sh.stat_panel(
        title="Cost — selected range (≈ per month)",
        expr=sh.usd(f"sum(sum_over_time({_SELECTOR} {sh.unwrap(_COST)} [$__range]))"),
        unit="currencyUSD",
        color="orange",
        grid=(4, 8, 0, 1),
    )


def _panel_total_tokens() -> object:
    return sh.stat_panel(
        title="Tokens — selected range",
        expr=f"sum(sum_over_time({_SELECTOR} {sh.unwrap(_TOKENS)} [$__range]))",
        unit="short",
        color="green",
        grid=(4, 8, 8, 1),
    )


def _panel_total_requests() -> object:
    return sh.stat_panel(
        title="Requests — selected range",
        expr=f"sum(count_over_time({_SELECTOR} [$__range]))",
        unit="short",
        color="blue",
        grid=(4, 8, 16, 1),
    )


def _panel_cost_per_day_by_model() -> object:
    # Per-day AND which-models in one panel: daily bars stacked by model.
    expr = sh.usd(f"sum by ({LABEL_MODEL}) (sum_over_time({_SELECTOR} {sh.unwrap(_COST)} [1d]))")
    return sh.daily_bars_panel(
        title="Cost per day, by model",
        expr=expr,
        legend=_LEGEND_MODEL,
        unit="currencyUSD",
        grid=(11, 24, 0, 5),
        legend_calcs=["sum", "max"],
    )


def _panel_cost_by_model_pie() -> object:
    expr = sh.usd(
        f"sum by ({LABEL_MODEL}) (sum_over_time({_SELECTOR} {sh.unwrap(_COST)} [$__range]))"
    )
    return sh.pie_panel(
        title="Which models (cost share, selected range)",
        expr=expr,
        legend_label=_LEGEND_MODEL,
        grid=(11, 12, 0, 16),
    )


def _panel_cost_by_channel() -> object:
    # An actor can spend across several channels (a human via opencode-cli AND
    # lightbridge-api-key); break the actor's cost down by azp.
    cost_sum = f"sum_over_time({_SELECTOR} {sh.unwrap(_COST)} [$__range])"
    expr = f"sort_desc(sum by ({LABEL_AZP}) ({sh.usd(cost_sum)}))"
    return sh.bargauge_panel(
        title="Cost by channel (azp, selected range)",
        expr=expr,
        legend=_LEGEND_AZP,
        unit="currencyUSD",
        color="purple",
        grid=(11, 12, 12, 16),
    )


_DESCRIPTION = (
    "Per-actor consumption for the Envoy AI Gateway. The 'Actor' variable is the "
    "display_name label — a person's name for humans, the repository for CI "
    "(github-actions / lightbridge-code-intelligence) — so one picker covers "
    "'user or actor (e.g. repository)'. Cost stat over the selected range ≈ the "
    "actor's monthly spend (default 30-day window); the daily-bars panel gives "
    "per-day, stacked by model. Cost = gen_ai.usage.custom_total_cost "
    "(micro-USD ÷ 1e6; ADR-0028/0051). "
    "⚠️ LibreChat agent runs + RAG embeddings don't forward the end-user, so they "
    "land under azp=internal-key-librechat, not the human (docs/per-user-observability.md). "
    "GENERATED — source: tools/dashboards/envoy_ai_gateway/actor_consumption.py."
)


def _dashboard() -> db.Dashboard:
    return (
        db.Dashboard("AI Gateway — actor consumption")
        .uid("envoy-ai-gateway-actor-consumption")
        .tags(["ai-gateway", "cost", "per-user", "loki"])
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
                definition=(
                    f'label_values({{service_name="{GATEWAY_SERVICE_NAME}"}}, {LABEL_DISPLAY_NAME})'
                ),
            )
        )
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
