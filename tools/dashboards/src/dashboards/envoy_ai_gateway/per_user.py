"""Envoy AI Gateway — per-user activity dashboard (GENERATED SOURCE).

This module is the *source of truth* for the dashboard JSON shipped at
``charts/observability-dashboards/files/envoy-ai-gateway/per-user.json``.
The JSON file is regenerated from this module — do **not** hand-edit it.

Regenerate with::

    make build
    # or
    uv run dashboards build

Architecture decision: see ``docs/adr/0008-python-dashboard-generation.md``.
Data path the dashboard consumes: ``docs/per-user-observability.md``.
"""

from __future__ import annotations

import json

from grafana_foundation_sdk.builders import bargauge, loki, piechart, stat, timeseries
from grafana_foundation_sdk.builders import common as cb
from grafana_foundation_sdk.builders import dashboard as db
from grafana_foundation_sdk.cog.encoder import JSONEncoder
from grafana_foundation_sdk.models import common as cm
from grafana_foundation_sdk.models import dashboard as dm
from grafana_foundation_sdk.models import piechart as pm

from dashboards._common import (
    GATEWAY_SERVICE_NAME,
    LABEL_AZP,
    LABEL_DISPLAY_NAME,
    LABEL_EMAIL,
    LABEL_MODEL,
    LABEL_USER_ID,
    LOKI_UID,
)

# ---------------------------------------------------------------------------
# Module contract for the orchestrator (tools/dashboards/main.py)
# ---------------------------------------------------------------------------

OUTPUT_PATH: str = "charts/observability-dashboards/files/envoy-ai-gateway/per-user.json"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOKI_DS = dm.DataSourceRef(type_val="loki", uid=LOKI_UID)

# Stream selector filtered by all dashboard variables (per-user scope).
# Filters on email (not user_id UUID) so the User picker is human-readable.
# email=~"$email" also naturally excludes service-account traffic, which
# carries no email label — that traffic stays visible in the Overall section
# via _OVERALL_SELECTOR which anchors on user_id=~".+" (present on all
# authenticated requests including SAs).
_SELECTOR = (
    f'{{service_name="{GATEWAY_SERVICE_NAME}", {LABEL_AZP}=~"$azp",'
    f' {LABEL_EMAIL}=~"$email", {LABEL_MODEL}=~"$model"}}'
)

# Stream selector that always spans ALL attributed users regardless of $email.
# user_id=~".+" (not email) so SA traffic is included in overall aggregates.
_OVERALL_SELECTOR = (
    f'{{service_name="{GATEWAY_SERVICE_NAME}", {LABEL_AZP}=~"$azp",'
    f' {LABEL_USER_ID}=~".+", {LABEL_MODEL}=~"$model"}}'
)


def _unwrap(field: str) -> str:
    """`| json | unwrap <field>` with the error guard ADR-0046 requires.

    Numeric access-log fields arrive as strings and absent ones as "-";
    `__error__=""` drops samples that fail conversion instead of failing
    the whole query.
    """
    return f'| json | unwrap {field} | __error__=""'


def _usd(expr: str) -> str:
    """Convert a raw micro-USD LogQL aggregation to USD for display.

    The pricing CEL (ai-model.costExpression, ADR-0028/ADR-0051) emits
    gen_ai_usage_custom_total_cost in micro-USD. Every cost panel must
    divide by 1e6 before applying the currencyUSD unit, or values display
    1,000,000x too large.
    """
    return f"(({expr}) / 1e6)"


# ---------------------------------------------------------------------------
# Small builder helpers
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
    """Single-value stat panel with sparkline. `grid` is (h, w, x, y)."""
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
    # Range query (not instant): the Loki Grafana plugin does not substitute
    # $__range in instant queries, causing them to silently return no data.
    # Range mode returns a time series per slice; the pie uses the last value.
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


# ---------------------------------------------------------------------------
# Overview stats  (y=0)
# ---------------------------------------------------------------------------


def _panel_requests_range() -> stat.Panel:
    return _stat_panel(
        title="Requests (range)",
        expr=f"sum(count_over_time({_SELECTOR} [$__range]))",
        unit="short",
        color="blue",
        grid=(4, 6, 0, 0),
    )


def _panel_unique_users() -> stat.Panel:
    return _stat_panel(
        title="Unique users (range)",
        expr=f"count(sum by ({LABEL_EMAIL}) (count_over_time({_SELECTOR} [$__range])))",
        unit="short",
        color="purple",
        grid=(4, 6, 6, 0),
    )


def _panel_total_tokens() -> stat.Panel:
    return _stat_panel(
        title="Total tokens (range)",
        expr=f"sum(sum_over_time({_SELECTOR} {_unwrap('gen_ai_usage_total_tokens')} [$__range]))",
        unit="short",
        color="green",
        grid=(4, 6, 12, 0),
    )


def _panel_p95_latency() -> stat.Panel:
    # Use [5m] instead of [$__range] — quantile_over_time with a 1h window
    # scans too much data per step and times out in Loki for this panel size.
    # [5m] gives "current p95 latency" which is more actionable anyway.
    # `by ()` collapses to ONE overall series — without a grouping clause,
    # quantile_over_time keys its output by each underlying stream's full
    # label set (not just the dashboard variables), which blows past Loki's
    # 500-series-per-query cap and surfaces as a silent "No data" stat panel.
    panel = _stat_panel(
        title="p95 latency (5m)",
        expr=f"quantile_over_time(0.95, {_SELECTOR} {_unwrap('duration')} [5m]) by ()",
        unit="ms",
        color="green",
        grid=(4, 6, 18, 0),
    )
    return panel.thresholds(
        db.ThresholdsConfig()
        .mode(dm.ThresholdsMode.ABSOLUTE)
        .steps(
            [
                dm.Threshold(color="green"),
                dm.Threshold(color="orange", value=1000.0),
                dm.Threshold(color="red", value=5000.0),
            ]
        )
    )


# ---------------------------------------------------------------------------
# Requests per user / minute  (y=4)
# ---------------------------------------------------------------------------


def _panel_requests_per_user() -> timeseries.Panel:
    return (
        timeseries.Panel()
        .title("Requests per user / minute")
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=8, w=24, x=0, y=4))
        .unit("short")
        .draw_style(cm.GraphDrawStyle.LINE)
        .line_interpolation(cm.LineInterpolation.SMOOTH)
        .fill_opacity(10.0)
        .show_points(cm.VisibilityMode.NEVER)
        .stacking(cb.StackingConfig().mode(cm.StackingMode.NORMAL))
        .legend(
            cb.VizLegendOptions()
            .display_mode(cm.LegendDisplayMode.TABLE)
            .placement(cm.LegendPlacement.RIGHT)
            .calcs(["mean", "max"])
        )
        .tooltip(cb.VizTooltipOptions().mode(cm.TooltipDisplayMode.MULTI))
        .with_target(
            _loki_target(
                f"sum by ({LABEL_EMAIL}) (count_over_time({_SELECTOR} [1m]))",
                legend="{{email}}",
            )
        )
    )


# ---------------------------------------------------------------------------
# Top 15 users by cost  (y=12)
# ---------------------------------------------------------------------------


def _panel_top_users_bar() -> bargauge.Panel:
    # label_replace extracts the first whitespace-delimited token from
    # display_name ("Kunga Derick" -> "Kunga") so 15 bars fit comfortably.
    # Uses _OVERALL_SELECTOR so the ranking always reflects all users
    # regardless of the $user_id filter variable.
    _cost_sum = (
        f"sum_over_time({_OVERALL_SELECTOR} {_unwrap('gen_ai_usage_custom_total_cost')} [$__range])"
    )
    expr = (
        f"label_replace("
        f"topk(15, sum by ({LABEL_DISPLAY_NAME}) ({_usd(_cost_sum)})),"
        f'"given_name", "$1", "{LABEL_DISPLAY_NAME}", "^(\\\\S+).*"'
        f")"
    )
    return (
        bargauge.Panel()
        .title("Top 15 users — cost (selected range)")
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=10, w=24, x=0, y=12))
        .unit("currencyUSD")
        .orientation(cm.VizOrientation.HORIZONTAL)
        .reduce_options(cb.ReduceDataOptions().calcs(["lastNotNull"]).fields("").values(False))
        .display_mode(cm.BarGaugeDisplayMode.BASIC)
        .thresholds(_single_color_thresholds("blue"))
        # Range query (not instant): same $__range-not-substituted bug as the
        # pie charts above — instant queries silently return no data here too.
        .with_target(_loki_target(expr, legend="{{given_name}}", instant=False))
    )


# ---------------------------------------------------------------------------
# Per-user section  (y=22)
# ---------------------------------------------------------------------------


def _panel_user_total_cost() -> stat.Panel:
    # calcs=["sum"] sums 1m-bucket costs across the whole range → total spend.
    # graph_mode=AREA renders the per-minute cost curve as the sparkline.
    return _stat_panel(
        title="User — total cost",
        expr=_usd(
            f"sum(sum_over_time({_SELECTOR} {_unwrap('gen_ai_usage_custom_total_cost')} [1m]))"
        ),
        unit="currencyUSD",
        color="orange",
        grid=(8, 6, 0, 22),
        calcs=["sum"],
    )


def _panel_user_total_requests() -> stat.Panel:
    return _stat_panel(
        title="User — total requests",
        expr=f"sum(count_over_time({_SELECTOR} [1m]))",
        unit="short",
        color="blue",
        grid=(8, 6, 6, 22),
        calcs=["sum"],
    )


def _panel_user_model_by_requests() -> piechart.Panel:
    return _pie_panel(
        title="User — model distribution (requests)",
        expr=f"sum by ({LABEL_MODEL}) (count_over_time({_SELECTOR} [$__range]))",
        legend_label=f"{{{{{LABEL_MODEL}}}}}",
        grid=(8, 6, 12, 22),
    )


def _panel_user_model_by_cost() -> piechart.Panel:
    return _pie_panel(
        title="User — model distribution (cost $)",
        expr=_usd(
            f"sum by ({LABEL_MODEL}) (sum_over_time({_SELECTOR} {_unwrap('gen_ai_usage_custom_total_cost')} [$__range]))"
        ),
        legend_label=f"{{{{{LABEL_MODEL}}}}}",
        grid=(8, 6, 18, 22),
    )


def _panel_user_model_by_tokens() -> piechart.Panel:
    return _pie_panel(
        title="User — model distribution (tokens)",
        expr=f"sum by ({LABEL_MODEL}) (sum_over_time({_SELECTOR} {_unwrap('gen_ai_usage_total_tokens')} [$__range]))",
        legend_label=f"{{{{{LABEL_MODEL}}}}}",
        grid=(8, 6, 0, 30),
    )


def _panel_user_status_codes() -> piechart.Panel:
    # response_code is in the log body (not a label); | json extracts it.
    # The ^(-|)$ filter drops absent/placeholder values before grouping.
    return _pie_panel(
        title="User — status codes",
        expr=(
            f"sum by (response_code) ("
            f'count_over_time({_SELECTOR} | json | response_code !~ "^(-|)$" [$__range])'
            f")"
        ),
        legend_label="{{response_code}}",
        grid=(8, 6, 6, 30),
    )


def _panel_latency_per_user() -> timeseries.Panel:
    return (
        timeseries.Panel()
        .title("Latency per user — p50 / p95")
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=8, w=12, x=12, y=30))
        .unit("ms")
        .draw_style(cm.GraphDrawStyle.LINE)
        .line_interpolation(cm.LineInterpolation.LINEAR)
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
                f"quantile_over_time(0.50, {_SELECTOR} {_unwrap('duration')} [5m]) by ({LABEL_EMAIL})",
                legend="p50 {{email}}",
                ref_id="A",
            )
        )
        .with_target(
            _loki_target(
                f"quantile_over_time(0.95, {_SELECTOR} {_unwrap('duration')} [5m]) by ({LABEL_EMAIL})",
                legend="p95 {{email}}",
                ref_id="B",
            )
        )
    )


# ---------------------------------------------------------------------------
# Overall section  (y=38)
# ---------------------------------------------------------------------------


def _panel_overall_model_by_requests() -> piechart.Panel:
    return _pie_panel(
        title="Overall — model distribution (requests)",
        expr=f"sum by ({LABEL_MODEL}) (count_over_time({_OVERALL_SELECTOR} [$__range]))",
        legend_label=f"{{{{{LABEL_MODEL}}}}}",
        grid=(8, 6, 0, 38),
    )


def _panel_overall_model_by_cost() -> piechart.Panel:
    return _pie_panel(
        title="Overall — model distribution (cost $)",
        expr=_usd(
            f"sum by ({LABEL_MODEL}) (sum_over_time({_OVERALL_SELECTOR} {_unwrap('gen_ai_usage_custom_total_cost')} [$__range]))"
        ),
        legend_label=f"{{{{{LABEL_MODEL}}}}}",
        grid=(8, 6, 6, 38),
    )


def _panel_overall_model_by_tokens() -> piechart.Panel:
    return _pie_panel(
        title="Overall — model distribution (tokens)",
        expr=f"sum by ({LABEL_MODEL}) (sum_over_time({_OVERALL_SELECTOR} {_unwrap('gen_ai_usage_total_tokens')} [$__range]))",
        legend_label=f"{{{{{LABEL_MODEL}}}}}",
        grid=(8, 6, 12, 38),
    )


def _panel_overall_status_codes() -> piechart.Panel:
    return _pie_panel(
        title="Overall — status codes",
        expr=(
            f"sum by (response_code) ("
            f'count_over_time({_OVERALL_SELECTOR} | json | response_code !~ "^(-|)$" [$__range])'
            f")"
        ),
        legend_label="{{response_code}}",
        grid=(8, 6, 18, 38),
    )


def _panel_overall_total_cost() -> stat.Panel:
    return _stat_panel(
        title="Overall — total cost",
        expr=_usd(
            f"sum(sum_over_time({_OVERALL_SELECTOR} {_unwrap('gen_ai_usage_custom_total_cost')} [1m]))"
        ),
        unit="currencyUSD",
        color="orange",
        grid=(4, 8, 0, 46),
        calcs=["sum"],
    )


def _panel_overall_total_tokens() -> stat.Panel:
    return _stat_panel(
        title="Overall — total tokens",
        expr=f"sum(sum_over_time({_OVERALL_SELECTOR} {_unwrap('gen_ai_usage_total_tokens')} [1m]))",
        unit="short",
        color="green",
        grid=(4, 8, 8, 46),
        calcs=["sum"],
    )


def _panel_overall_total_requests() -> stat.Panel:
    return _stat_panel(
        title="Overall — total requests",
        expr=f"sum(count_over_time({_OVERALL_SELECTOR} [1m]))",
        unit="short",
        color="blue",
        grid=(4, 8, 16, 46),
        calcs=["sum"],
    )


# ---------------------------------------------------------------------------
# Top-level builder
# ---------------------------------------------------------------------------

_DESCRIPTION = (
    "Per-user activity for the Envoy AI Gateway. "
    "Data flows: JWT -> Authorino response headers (x-oidc-user-id, x-oidc-azp, "
    "x-oidc-email, x-oidc-name; full x-oidc-* contract in ADR-0011) -> "
    "Envoy access log JSON (OTLP attributes) -> "
    "Alloy loki.process 'ai_gateway_user_attribution' (flattens the envelope, "
    "promotes user_id/azp/model/email/display_name/billing_plan labels, "
    "pins service_name=envoy-ai-gateway; ADR-0046) -> Loki. "
    "Shows ATTRIBUTED traffic only — unauthenticated requests carry no identity labels. "
    "See docs/per-user-observability.md. "
    "GENERATED — source: tools/dashboards/envoy_ai_gateway/per_user.py."
)


def _dashboard() -> db.Dashboard:
    return (
        db.Dashboard("AI Gateway — per-user activity")
        .uid("envoy-ai-gateway-per-user")
        .tags(["ai-gateway", "per-user", "loki"])
        .description(_DESCRIPTION)
        .timezone("browser")
        .editable()
        .tooltip(dm.DashboardCursorSync.CROSSHAIR)
        .refresh("30s")
        .time("now-1h", "now")
        .with_variable(
            _query_var(
                name="azp",
                label="Client (azp)",
                definition=(f'label_values({{service_name="{GATEWAY_SERVICE_NAME}"}}, azp)'),
            )
        )
        .with_variable(
            _query_var(
                name="email",
                label="User (email)",
                definition=(
                    f'label_values({{service_name="{GATEWAY_SERVICE_NAME}", azp=~"$azp"}}, email)'
                ),
            )
        )
        .with_variable(
            _query_var(
                name="model",
                label="Model",
                definition=(f'label_values({{service_name="{GATEWAY_SERVICE_NAME}"}}, model)'),
            )
        )
        # Overview stats
        .with_panel(_panel_requests_range())
        .with_panel(_panel_unique_users())
        .with_panel(_panel_total_tokens())
        .with_panel(_panel_p95_latency())
        # Requests per user / minute
        .with_panel(_panel_requests_per_user())
        # Top 15 users by cost
        .with_panel(_panel_top_users_bar())
        # Per-user section
        .with_panel(_panel_user_total_cost())
        .with_panel(_panel_user_total_requests())
        .with_panel(_panel_user_model_by_requests())
        .with_panel(_panel_user_model_by_cost())
        .with_panel(_panel_user_model_by_tokens())
        .with_panel(_panel_user_status_codes())
        .with_panel(_panel_latency_per_user())
        # Overall section
        .with_panel(_panel_overall_model_by_requests())
        .with_panel(_panel_overall_model_by_cost())
        .with_panel(_panel_overall_model_by_tokens())
        .with_panel(_panel_overall_status_codes())
        .with_panel(_panel_overall_total_cost())
        .with_panel(_panel_overall_total_tokens())
        .with_panel(_panel_overall_total_requests())
    )


def build() -> dict:
    """Return the dashboard as a JSON-compatible dict."""
    return json.loads(json.dumps(_dashboard().build(), cls=JSONEncoder))
