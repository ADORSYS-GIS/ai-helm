"""Envoy AI Gateway — personal usage dashboard (GENERATED SOURCE).

This module is the *source of truth* for the dashboard JSON shipped at
``charts/observability-dashboards/files/envoy-ai-gateway/my-usage.json``.
The JSON file is regenerated from this module — do **not** hand-edit it.

Regenerate with::

    make build
    # or
    uv run dashboards build

Isolation: uses the Grafana built-in ``${__user.email}`` variable,
which maps to the authenticated user's OIDC email claim. The Mimir
``email`` label (inherited from the ADR-0058 precomputed metrics, which
carry the ADR-0046 attribution labels) is 1:1 with ``user_id`` for human
users. Unlike a URL variable, this cannot be tampered with by the viewer.
See ADR-0077.

Repointed to Mimir (ADR-0058): reads the precomputed
``loki_process_custom_gen_ai_*`` counters via PromQL ``increase()`` instead
of scanning Loki logs — instant at any range on the rate-limited object
store. The ``email``/``azp``/``model``/``display_name``/``billing_plan``
axes are all Mimir labels, so every panel maps cleanly.
"""

from __future__ import annotations

import json

from grafana_foundation_sdk.builders import common as cb
from grafana_foundation_sdk.builders import dashboard as db
from grafana_foundation_sdk.builders import gauge, stat
from grafana_foundation_sdk.cog.encoder import JSONEncoder
from grafana_foundation_sdk.models import common as cm
from grafana_foundation_sdk.models import dashboard as dm

from dashboards._common import (
    GATEWAY_SERVICE_NAME,
    LABEL_AZP,
    LABEL_BILLING_PLAN,
    LABEL_DISPLAY_NAME,
    LABEL_EMAIL,
    LABEL_MODEL,
    METRIC_COST_MICRO_USD,
    METRIC_REQUESTS,
    METRIC_TOKENS,
    MIMIR_UID,
)
from dashboards.envoy_ai_gateway import _shared as sh

# ---------------------------------------------------------------------------
# Module contract for the orchestrator (tools/dashboards/main.py)
# ---------------------------------------------------------------------------

OUTPUT_PATH: str = "charts/observability-dashboards/files/envoy-ai-gateway/my-usage.json"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MIMIR_DS = dm.DataSourceRef(type_val="prometheus", uid=MIMIR_UID)

# Metric selector — MUST include email="${__user.email}" to enforce isolation.
# ${__user.email} is a Grafana built-in user variable (server-controlled).
_SEL = sh.selector(
    f'{LABEL_EMAIL}="${{__user.email}}"', f'{LABEL_AZP}=~"$azp"', f'{LABEL_MODEL}=~"$model"'
)

# Scoped selector for the azp/model filter variables (only this user's values).
_USER_SEL = f'{{service_name="{GATEWAY_SERVICE_NAME}", {LABEL_EMAIL}="${{__user.email}}"}}'


def _budget_thresholds() -> db.ThresholdsConfig:
    """green < 70% < yellow < 90% < red — for the budget-burn gauge (percent)."""
    return (
        db.ThresholdsConfig()
        .mode(dm.ThresholdsMode.ABSOLUTE)
        .steps(
            [
                dm.Threshold(color="green"),
                dm.Threshold(value=70.0, color="yellow"),
                dm.Threshold(value=90.0, color="red"),
            ]
        )
    )


# ---------------------------------------------------------------------------
# Overview stats  (y=0)
# ---------------------------------------------------------------------------


def _panel_total_cost() -> object:
    return sh.stat_panel(
        title="Total cost",
        expr=sh.usd(f"sum(increase({METRIC_COST_MICRO_USD}{_SEL}[$__range]))"),
        unit="currencyUSD",
        color="orange",
        grid=(8, 8, 0, 0),
    )


def _panel_total_requests() -> object:
    return sh.stat_panel(
        title="Total requests",
        expr=f"sum(increase({METRIC_REQUESTS}{_SEL}[$__range]))",
        unit="short",
        color="blue",
        grid=(8, 8, 8, 0),
    )


def _panel_total_tokens() -> object:
    return sh.stat_panel(
        title="Total tokens",
        expr=f"sum(increase({METRIC_TOKENS}{_SEL}[$__range]))",
        unit="short",
        color="green",
        grid=(8, 8, 16, 0),
    )


# ---------------------------------------------------------------------------
# Budget gauge  (y=8)
# ---------------------------------------------------------------------------


def _panel_budget_gauge() -> gauge.Panel:
    # Percent of the editable monthly budget spent in the selected range.
    # Same Mimir cost query as _panel_total_cost, divided by the $budget
    # textbox variable (default $15 — the free-plan monthly budget).
    expr = f"100 * (sum(increase({METRIC_COST_MICRO_USD}{_SEL}[$__range])) / 1e6) / $budget"
    return (
        gauge.Panel()
        .title("Budget burn (selected range)")
        .description(
            "Total cost over the selected range as a % of the $budget variable "
            "(default $15/mo — edit in the dashboard toolbar)."
        )
        .datasource(_MIMIR_DS)
        .grid_pos(dm.GridPos(h=8, w=12, x=12, y=8))
        .unit("percent")
        .min(0.0)
        .max(120.0)
        .thresholds(_budget_thresholds())
        .show_threshold_markers(True)
        .reduce_options(cb.ReduceDataOptions().calcs(["lastNotNull"]).fields("").values(False))
        .with_target(sh.prom_target(expr))
    )


# ---------------------------------------------------------------------------
# Breakdown by model  (y=16)
# ---------------------------------------------------------------------------


def _panel_cost_by_model() -> object:
    return sh.pie_panel(
        title="Cost by model",
        expr=sh.usd(f"sum by ({LABEL_MODEL}) (increase({METRIC_COST_MICRO_USD}{_SEL}[$__range]))"),
        legend_label=f"{{{{{LABEL_MODEL}}}}}",
        grid=(8, 6, 0, 16),
    )


def _panel_tokens_by_model() -> object:
    return sh.pie_panel(
        title="Tokens by model",
        expr=f"sum by ({LABEL_MODEL}) (increase({METRIC_TOKENS}{_SEL}[$__range]))",
        legend_label=f"{{{{{LABEL_MODEL}}}}}",
        grid=(8, 6, 6, 16),
    )


def _panel_requests_by_model() -> object:
    return sh.pie_panel(
        title="Requests by model",
        expr=f"sum by ({LABEL_MODEL}) (increase({METRIC_REQUESTS}{_SEL}[$__range]))",
        legend_label=f"{{{{{LABEL_MODEL}}}}}",
        grid=(8, 6, 12, 16),
    )


def _panel_azp() -> object:
    return sh.pie_panel(
        title="Usage by channel (azp)",
        expr=f"sum by ({LABEL_AZP}) (increase({METRIC_REQUESTS}{_SEL}[$__range]))",
        legend_label=f"{{{{{LABEL_AZP}}}}}",
        grid=(8, 6, 18, 16),
    )


def _panel_user_info() -> stat.Panel:
    """Show the authenticated user display name and billing plan from Mimir labels."""
    return (
        stat.Panel()
        .title("User Info")
        .datasource(_MIMIR_DS)
        .grid_pos(dm.GridPos(h=8, w=12, x=0, y=8))
        .thresholds(sh.single_color_thresholds("blue"))
        .reduce_options(cb.ReduceDataOptions().calcs(["lastNotNull"]).fields("").values(False))
        .orientation(cm.VizOrientation.HORIZONTAL)
        .text_mode(cm.BigValueTextMode.NAME)
        .color_mode(cm.BigValueColorMode.NONE)
        .graph_mode(cm.BigValueGraphMode.NONE)
        .justify_mode(cm.BigValueJustifyMode.AUTO)
        .with_target(
            sh.prom_target(
                f"sum by ({LABEL_DISPLAY_NAME}) (increase({METRIC_REQUESTS}{_SEL}[$__range]))",
                legend=f"{{{{{LABEL_DISPLAY_NAME}}}}}",
                ref_id="A",
            )
        )
        .with_target(
            sh.prom_target(
                f"sum by ({LABEL_BILLING_PLAN}) (increase({METRIC_REQUESTS}{_SEL}[$__range]))",
                legend=f"{{{{{LABEL_BILLING_PLAN}}}}}",
                ref_id="B",
            )
        )
    )


# ---------------------------------------------------------------------------
# Top-level builder
# ---------------------------------------------------------------------------

_DESCRIPTION = (
    "Personal AI usage for the authenticated user. "
    "Isolated by ${__user.email} (Grafana built-in user variable, ADR-0077). "
    "Default range starts at the 1st of the current month. "
    "Budget gauge measures total cost against the editable $budget variable "
    "(default $15/mo — the free-plan monthly budget). "
    "Reads the precomputed Mimir metrics (ADR-0058) via PromQL increase() — "
    "instant at any range, no Loki log-scan. "
    "Data path: JWT -> Authorino -> Envoy access log -> Alloy -> Mimir. "
    "See docs/patterns/per-user-observability.md. "
    "GENERATED — source: tools/dashboards/envoy_ai_gateway/my_usage.py."
)


def _budget_var() -> db.TextBoxVariable:
    # Editable textbox — the user sets their own monthly budget in the toolbar.
    # Default $50 = the free-plan monthly budget (charts/ai-models rateLimitBudgeting.plans).
    return (
        db.TextBoxVariable("budget")
        .label("Monthly budget ($)")
        .default_value("15")
        .current(dm.VariableOption(selected=True, text="15", value="15"))
    )


def _dashboard() -> db.Dashboard:
    return (
        db.Dashboard("AI Gateway — my usage")
        .uid("my-usage")
        .tags(["ai-gateway", "my-usage", "mimir"])
        .description(_DESCRIPTION)
        .timezone("browser")
        .editable()
        .tooltip(dm.DashboardCursorSync.CROSSHAIR)
        .refresh("30s")
        .time("now/M", "now")
        .with_variable(
            sh.multi_var(
                name="azp",
                label="Channel (azp)",
                definition=sh.label_values(_USER_SEL, LABEL_AZP),
            )
        )
        .with_variable(
            sh.multi_var(
                name="model",
                label="Model",
                definition=sh.label_values(_USER_SEL, LABEL_MODEL),
            )
        )
        .with_variable(_budget_var())
        .with_panel(_panel_total_cost())
        .with_panel(_panel_total_requests())
        .with_panel(_panel_total_tokens())
        .with_panel(_panel_budget_gauge())
        .with_panel(_panel_cost_by_model())
        .with_panel(_panel_tokens_by_model())
        .with_panel(_panel_requests_by_model())
        .with_panel(_panel_azp())
        .with_panel(_panel_user_info())
    )


def build() -> dict:
    """Return the dashboard as a JSON-compatible dict."""
    return json.loads(json.dumps(_dashboard().build(), cls=JSONEncoder))


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, ensure_ascii=False))
