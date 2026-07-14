"""Envoy AI Gateway — personal usage dashboard (GENERATED SOURCE).

This module is the *source of truth* for the dashboard JSON shipped at
``charts/observability-dashboards/files/envoy-ai-gateway/my-usage.json``.
The JSON file is regenerated from this module — do **not** hand-edit it.

Regenerate with::

    make build
    # or
    uv run dashboards build

Isolation: uses the Grafana built-in ``${__user.email}`` variable,
which maps to the authenticated user's OIDC email claim. The Loki
``email`` label (promoted by Alloy from the JWT ``email`` field) is 1:1
with ``user_id`` for human users. Unlike a URL variable, this cannot
be tampered with by the viewer. See ADR-0077.
"""

from __future__ import annotations

import json

from grafana_foundation_sdk.builders import common as cb
from grafana_foundation_sdk.builders import dashboard as db
from grafana_foundation_sdk.builders import loki, piechart, stat, timeseries
from grafana_foundation_sdk.cog.encoder import JSONEncoder
from grafana_foundation_sdk.models import common as cm
from grafana_foundation_sdk.models import dashboard as dm
from grafana_foundation_sdk.models import piechart as pm

from dashboards._common import (
    GATEWAY_SERVICE_NAME,
    LABEL_AZP,
    LABEL_DISPLAY_NAME,
    LABEL_MODEL,
    LABEL_EMAIL,
    LABEL_BILLING_PLAN,
    LOKI_UID,
)

# ---------------------------------------------------------------------------
# Module contract for the orchestrator (tools/dashboards/main.py)
# ---------------------------------------------------------------------------

OUTPUT_PATH: str = "charts/observability-dashboards/files/envoy-ai-gateway/my-usage.json"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOKI_DS = dm.DataSourceRef(type_val="loki", uid=LOKI_UID)

# Stream selector — MUST include email="${__user.email}" to enforce isolation.
# ${__user.email} is a Grafana built-in user variable (server-controlled).
_SELECTOR = (
    f'{{service_name="{GATEWAY_SERVICE_NAME}", {LABEL_EMAIL}="${{__user.email}}",'
    f' {LABEL_AZP}=~"$azp", {LABEL_MODEL}=~"$model"}}'
)

_JSON_PATHS = {
    "gen_ai_usage_total_tokens": "gen_ai.usage.total_tokens",
    "gen_ai_usage_custom_total_cost": "gen_ai.usage.custom_total_cost",
}


def _unwrap(field: str) -> str:
    """`| json <field> | unwrap <field>` with the error guard ADR-0046 requires.
    Numeric access-log fields arrive as strings and absent ones as "-";
    `__error__=""` drops samples that fail conversion instead of failing
    the whole query.

    Extracts ONLY `field` -- a bare `| json` (no field list) pulls every
    field on the line (trace_id, jti, ...) into the per-line label set, and
    sum_over_time/quantile_over_time default-group by that whole set when no
    explicit grouping is given, blowing past Loki's 500-series cap under real
    traffic. Restricting extraction to the one field we unwrap keeps the
    per-line label set down to just the genuine stream labels.

    Envoy's access-log format.json (charts/core-gateway/templates/envoy-proxy.yaml)
    declares the GenAI usage fields with LITERAL DOTS in the key name
    (`gen_ai.usage.total_tokens`, not a nested object) -- a bare `| json` auto-
    flattens that into the underscored label we use here, but the explicit
    `| json <name>` form treats `<name>` as a path lookup, which does NOT
    match a literal dotted key by bare name. Loki's json-field grammar isn't
    full JMESPath -- a literal/quoted key isn't a valid expression on its
    own, it must be wrapped in brackets: `["dotted.key"]` (confirmed via the
    parser's own error: "unexpected STRING, expecting LSB or FIELD"). Flat
    keys like `duration` have no dot and extract by bare name as before.
    """
    path = _JSON_PATHS.get(field)
    extract = f'{field}=`["{path}"]`' if path else field
    return f'| json {extract} | unwrap {field} | __error__=""'


def _usd(expr: str) -> str:
    """Convert raw micro-USD LogQL aggregation to USD for display."""
    return f"(({expr}) / 1e6)"


# ---------------------------------------------------------------------------
# Builder helpers
# ---------------------------------------------------------------------------


def _loki_target(
    expr: str,
    *,
    legend: str = "",
    ref_id: str = "A",
    instant: bool = False,
) -> loki.Dataquery:
    q = (
        loki.Dataquery()
        .expr(expr)
        .ref_id(ref_id)
        .query_type("instant" if instant else "range")
        .datasource(_LOKI_DS)
    )
    if legend:
        q = q.legend_format(legend)
    return q
def _single_color_thresholds(color: str) -> db.ThresholdsConfig:


    return db.ThresholdsConfig().mode(dm.ThresholdsMode.ABSOLUTE).steps([dm.Threshold(color=color)])


def _stat_panel(
    *,
    title: str,
    expr: str,
    unit: str,
    color: str,
    grid: tuple[int, int, int, int],
    calcs: list[str] | None = None,
) -> stat.Panel:
    """Single-value stat panel. ``grid`` is (h, w, x, y)."""
    h, w, x, y = grid
    return (
        stat.Panel()
        .title(title)
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=h, w=w, x=x, y=y))
        .unit(unit)
        .thresholds(_single_color_thresholds(color))
        .reduce_options(
            cb.ReduceDataOptions()
            .calcs(calcs if calcs is not None else ["lastNotNull"])
            .fields("")
            .values(False)
        )
        .orientation(cm.VizOrientation.HORIZONTAL)
        .text_mode(cm.BigValueTextMode.AUTO)
        .color_mode(cm.BigValueColorMode.VALUE)
        .graph_mode(cm.BigValueGraphMode.AREA)
        .justify_mode(cm.BigValueJustifyMode.AUTO)
        .with_target(_loki_target(expr))
    )


def _pie_panel(
    *,
    title: str,
    expr: str,
    legend_label: str,
    grid: tuple[int, int, int, int],
) -> piechart.Panel:
    h, w, x, y = grid
    return (
        piechart.Panel()
        .title(title)
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=h, w=w, x=x, y=y))
        .pie_type(pm.PieChartType.DONUT)
        .legend(
            piechart.PieChartLegendOptions()
            .display_mode(cm.LegendDisplayMode.TABLE)
            .placement(cm.LegendPlacement.RIGHT)
            .values([pm.PieChartLegendValues.VALUE, pm.PieChartLegendValues.PERCENT])
        )
        .tooltip(cb.VizTooltipOptions().mode(cm.TooltipDisplayMode.SINGLE))
        .with_target(_loki_target(expr, legend=legend_label, instant=False))
    )


# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# Overview stats  (y=5)
# ---------------------------------------------------------------------------


def _panel_total_cost() -> stat.Panel:
    return _stat_panel(
        title="Total cost",
        expr=_usd(
            f"sum(sum_over_time({_SELECTOR} {_unwrap('gen_ai_usage_custom_total_cost')} [$__range]))"
        ),
        unit="currencyUSD",
        color="orange",
        grid=(8, 8, 0, 0),
    )


def _panel_total_requests() -> stat.Panel:
    return _stat_panel(
        title="Total requests",
        expr=f"sum(count_over_time({_SELECTOR} [$__range]))",
        unit="short",
        color="blue",
        grid=(8, 8, 8, 0),
    )


def _panel_total_tokens() -> stat.Panel:
    return _stat_panel(
        title="Total tokens",
        expr=f"sum(sum_over_time({_SELECTOR} {_unwrap('gen_ai_usage_total_tokens')} [$__range]))",
        unit="short",
        color="green",
        grid=(8, 8, 16, 0),
    )


# ---------------------------------------------------------------------------
# Time series  (y=13)
# ---------------------------------------------------------------------------


def _panel_cost_over_time() -> timeseries.Panel:
    return (
        timeseries.Panel()
        .title("Cost over time")
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=8, w=24, x=0, y=8))
        .unit("currencyUSD")
        .draw_style(cm.GraphDrawStyle.LINE)
        .line_interpolation(cm.LineInterpolation.SMOOTH)
        .fill_opacity(10.0)
        .show_points(cm.VisibilityMode.NEVER)
        .stacking(cb.StackingConfig().mode(cm.StackingMode.NORMAL))
        .legend(
            cb.VizLegendOptions()
            .display_mode(cm.LegendDisplayMode.TABLE)
            .placement(cm.LegendPlacement.RIGHT)
            .calcs(["sum", "mean"])
        )
        .tooltip(cb.VizTooltipOptions().mode(cm.TooltipDisplayMode.MULTI))
        .with_target(
            _loki_target(
                _usd(
                    f"sum by ({LABEL_MODEL}) (sum_over_time({_SELECTOR} {_unwrap('gen_ai_usage_custom_total_cost')} [1m]))"
                ),
                legend=f"{{{{{LABEL_MODEL}}}}}",
            )
        )
    )


# ---------------------------------------------------------------------------
# Breakdown by model  (y=21)
# ---------------------------------------------------------------------------


def _panel_cost_by_model() -> piechart.Panel:
    return _pie_panel(
        title="Cost by model",
        expr=_usd(
            f"sum by ({LABEL_MODEL}) (sum_over_time({_SELECTOR} {_unwrap('gen_ai_usage_custom_total_cost')} [$__range]))"
        ),
        legend_label=f"{{{{{LABEL_MODEL}}}}}",
        grid=(8, 8, 0, 16),
    )


def _panel_tokens_by_model() -> piechart.Panel:
    return _pie_panel(
        title="Tokens by model",
        expr=f"sum by ({LABEL_MODEL}) (sum_over_time({_SELECTOR} {_unwrap('gen_ai_usage_total_tokens')} [$__range]))",
        legend_label=f"{{{{{LABEL_MODEL}}}}}",
        grid=(8, 8, 8, 16),
    )


def _panel_requests_by_model() -> piechart.Panel:
    return _pie_panel(
        title="Requests by model",
        expr=f"sum by ({LABEL_MODEL}) (count_over_time({_SELECTOR} [$__range]))",
        legend_label=f"{{{{{LABEL_MODEL}}}}}",
        grid=(8, 8, 16, 16),
    )


# ---------------------------------------------------------------------------
# Latency  (y=29)
# ---------------------------------------------------------------------------


def _panel_latency() -> timeseries.Panel:
    return (
        timeseries.Panel()
        .title("Latency — p50 / p95")
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=8, w=24, x=0, y=24))
        .unit("ms")
        .draw_style(cm.GraphDrawStyle.LINE)
        .line_interpolation(cm.LineInterpolation.SMOOTH)
        .fill_opacity(0.0)
        .show_points(cm.VisibilityMode.NEVER)
        .legend(
            cb.VizLegendOptions()
            .display_mode(cm.LegendDisplayMode.TABLE)
            .placement(cm.LegendPlacement.RIGHT)
            .calcs(["mean", "max"])
        )
        .tooltip(cb.VizTooltipOptions().mode(cm.TooltipDisplayMode.MULTI))
        .with_target(
            _loki_target(
                f"quantile_over_time(0.50, {_SELECTOR} {_unwrap('duration')} [5m]) by ()",
                legend="p50",
                ref_id="A",
            )
        )
        .with_target(
            _loki_target(
                f"quantile_over_time(0.95, {_SELECTOR} {_unwrap('duration')} [5m]) by ()",
                legend="p95",
                ref_id="B",
            )
        )
    )


# ---------------------------------------------------------------------------
# Usage by channel  (y=37)
# ---------------------------------------------------------------------------


def _panel_azp() -> piechart.Panel:
    return _pie_panel(
        title="Usage by channel (azp)",
        expr=f"sum by ({LABEL_AZP}) (count_over_time({_SELECTOR} [$__range]))",
        legend_label=f"{{{{{LABEL_AZP}}}}}",
        grid=(8, 12, 0, 32),
    )


def _panel_display_name() -> stat.Panel:
    """Show the authenticated user display name from Loki label."""
    return (
        stat.Panel()
        .title("Your name")
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=8, w=6, x=12, y=32))
        .thresholds(_single_color_thresholds("blue"))
        .reduce_options(
            cb.ReduceDataOptions()
            .calcs(["lastNotNull"])
            .fields("")
            .values(False)
        )
        .orientation(cm.VizOrientation.HORIZONTAL)
        .text_mode(cm.BigValueTextMode.NAME)
        .color_mode(cm.BigValueColorMode.NONE)
        .graph_mode(cm.BigValueGraphMode.NONE)
        .justify_mode(cm.BigValueJustifyMode.AUTO)
        .with_target(
            _loki_target(
                f"sum by ({LABEL_DISPLAY_NAME}) (count_over_time({_SELECTOR} [$__range]))",
                legend=f"{{{{{LABEL_DISPLAY_NAME}}}}}",
            )
        )
    )


def _panel_billing_plan() -> stat.Panel:
    """Show the authenticated user billing plan from Loki label."""
    return (
        stat.Panel()
        .title("Billing plan")
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=8, w=6, x=18, y=32))
        .thresholds(_single_color_thresholds("blue"))
        .reduce_options(
            cb.ReduceDataOptions()
            .calcs(["lastNotNull"])
            .fields("")
            .values(False)
        )
        .orientation(cm.VizOrientation.HORIZONTAL)
        .text_mode(cm.BigValueTextMode.NAME)
        .color_mode(cm.BigValueColorMode.NONE)
        .graph_mode(cm.BigValueGraphMode.NONE)
        .justify_mode(cm.BigValueJustifyMode.AUTO)
        .with_target(
            _loki_target(
                f"sum by ({LABEL_BILLING_PLAN}) (count_over_time({_SELECTOR} [$__range]))",
                legend=f"{{{{{LABEL_BILLING_PLAN}}}}}",
            )
        )
    )


# ---------------------------------------------------------------------------
# Top-level builder
# ---------------------------------------------------------------------------

_DESCRIPTION = (
    "Personal AI usage for the authenticated user. "
    "Isolated by ${__user.email} (Grafana built-in user variable, ADR-0077). "
    "Data path: JWT -> Authorino -> Envoy access log -> Alloy -> Loki. "
    "See docs/patterns/per-user-observability.md. "
    "GENERATED — source: tools/dashboards/envoy_ai_gateway/my_usage.py."
)


def _query_var(
    *,
    name: str,
    label: str,
    definition: str,
) -> db.QueryVariable:
    return (
        db.QueryVariable(name)
        .label(label)
        .datasource(_LOKI_DS)
        .query(definition)
        .refresh(dm.VariableRefresh.ON_TIME_RANGE_CHANGED)
        .sort(dm.VariableSort.ALPHABETICAL_ASC)
        .multi(True)
        .include_all(True)
        .all_value(".+")
        .current(dm.VariableOption(selected=True, text=["All"], value=["$__all"]))
    )


def _dashboard() -> db.Dashboard:
    return (
        db.Dashboard("AI Gateway — my usage")
        .uid("my-usage")
        .tags(["ai-gateway", "my-usage", "loki"])
        .description(_DESCRIPTION)
        .timezone("browser")
        .editable()
        .tooltip(dm.DashboardCursorSync.CROSSHAIR)
        .refresh("30s")
        .time("now-30d", "now")
        .with_variable(
            _query_var(
                name="azp",
                label="Channel (azp)",
                definition=f'label_values({{service_name="{GATEWAY_SERVICE_NAME}", email="${{__user.email}}"}}, azp)',
            )
        )
        .with_variable(
            _query_var(
                name="model",
                label="Model",
                definition=f'label_values({{service_name="{GATEWAY_SERVICE_NAME}", email="${{__user.email}}"}}, model)',
            )
        )
        .with_panel(_panel_total_cost())
        .with_panel(_panel_total_requests())
        .with_panel(_panel_total_tokens())
        .with_panel(_panel_cost_over_time())
        .with_panel(_panel_cost_by_model())
        .with_panel(_panel_tokens_by_model())
        .with_panel(_panel_requests_by_model())
        .with_panel(_panel_latency())
        .with_panel(_panel_azp())
        .with_panel(_panel_display_name())
        .with_panel(_panel_billing_plan())
    )


def build() -> dict:
    """Return the dashboard as a JSON-compatible dict."""
    return json.loads(json.dumps(_dashboard().build(), cls=JSONEncoder))


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, ensure_ascii=False))
