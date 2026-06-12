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

from grafana_foundation_sdk.builders import common as cb
from grafana_foundation_sdk.builders import (
    dashboard as db,
)
from grafana_foundation_sdk.builders import (
    loki,
    piechart,
    stat,
    table,
    timeseries,
)
from grafana_foundation_sdk.cog.encoder import JSONEncoder
from grafana_foundation_sdk.models import common as cm
from grafana_foundation_sdk.models import dashboard as dm
from grafana_foundation_sdk.models import piechart as pm

from dashboards._common import (
    GATEWAY_SERVICE_NAME,
    LABEL_AZP,
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

# Common stream selector used by every panel: labels only (ADR-0046) —
# anchored on the service_name pinned by Alloy's attribution stage, so no
# panel pays for a full-body `| json` parse just to scope its streams.
# All three variables are label-backed; "All" (.+) requires the label to
# exist, so the dashboard intentionally shows ATTRIBUTED traffic only
# (unauthenticated requests carry no identity labels).
_SELECTOR = (
    f'{{service_name="{GATEWAY_SERVICE_NAME}", {LABEL_AZP}=~"$azp",'
    f' {LABEL_USER_ID}=~"$user_id", {LABEL_MODEL}=~"$model"}}'
)


def _unwrap(field: str) -> str:
    """`| json | unwrap <field>` with the error guard ADR-0046 requires.

    Numeric access-log fields arrive as strings and absent ones as "-";
    the `__error__=""` filter drops the samples that fail conversion
    instead of failing the whole query.
    """
    return f'| json | unwrap {field} | __error__=""'


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
    """Build a Loki Dataquery with sane defaults."""
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
) -> stat.Panel:
    """Single-value stat panel. `grid` is (h, w, x, y)."""
    h, w, x, y = grid
    return (
        stat.Panel()
        .title(title)
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=h, w=w, x=x, y=y))
        .unit(unit)
        .thresholds(_single_color_thresholds(color))
        .reduce_options(cb.ReduceDataOptions().calcs(["lastNotNull"]).fields("").values(False))
        .orientation(cm.VizOrientation.HORIZONTAL)
        .text_mode(cm.BigValueTextMode.AUTO)
        .color_mode(cm.BigValueColorMode.VALUE)
        .graph_mode(cm.BigValueGraphMode.AREA)
        .justify_mode(cm.BigValueJustifyMode.AUTO)
        .with_target(_loki_target(expr))
    )


def _query_var(
    *,
    name: str,
    label: str,
    definition: str,
) -> db.QueryVariable:
    """Loki `label_values(...)` query variable.

    The SDK exposes `query()` only — Grafana parses the `label_values(...)`
    LogQL form server-side and reconstructs the typed `{label, type}` form
    when the dashboard opens in the editor.
    """
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
# Panel factories
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
        expr=(f"count(sum by (user_id) (count_over_time({_SELECTOR} [$__range])))"),
        unit="short",
        color="purple",
        grid=(4, 6, 6, 0),
    )


def _panel_total_tokens() -> stat.Panel:
    return _stat_panel(
        title="Total tokens (range)",
        expr=(f"sum(sum_over_time({_SELECTOR} {_unwrap('gen_ai_usage_total_tokens')} [$__range]))"),
        unit="short",
        color="green",
        grid=(4, 6, 12, 0),
    )


def _panel_p95_latency() -> stat.Panel:
    panel = _stat_panel(
        title="p95 latency (range)",
        expr=(f"quantile_over_time(0.95, {_SELECTOR} {_unwrap('duration')} [$__range])"),
        unit="ms",
        color="green",
        grid=(4, 6, 18, 0),
    )
    # Multi-stop thresholds override the single-color default from the helper.
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


def _panel_requests_per_user() -> timeseries.Panel:
    return (
        timeseries.Panel()
        .title("Requests per user / minute")
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=9, w=24, x=0, y=4))
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
                f"sum by (user_id) (count_over_time({_SELECTOR} [1m]))",
                legend="{{user_id}}",
            )
        )
    )


def _panel_top_users() -> table.Panel:
    return (
        table.Panel()
        .title("Top users by requests")
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=9, w=12, x=0, y=13))
        .show_header(True)
        .sort_by([cb.TableSortByFieldState().display_name("Value").desc(True)])
        .with_target(
            _loki_target(
                (f"topk(20, sum by (user_id, azp) (count_over_time({_SELECTOR} [$__range])))"),
                ref_id="A",
                instant=True,
            )
        )
        .with_transformation(
            dm.DataTransformerConfig(
                id_val="labelsToFields",
                options={"valueLabel": "Requests"},
            )
        )
        .with_transformation(
            dm.DataTransformerConfig(
                id_val="organize",
                options={"excludeByName": {"Time": True}},
            )
        )
    )


def _panel_model_distribution() -> piechart.Panel:
    return (
        piechart.Panel()
        .title("Model distribution (selected scope)")
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=9, w=12, x=12, y=13))
        .pie_type(pm.PieChartType.DONUT)
        .legend(
            piechart.PieChartLegendOptions()
            .display_mode(cm.LegendDisplayMode.TABLE)
            .placement(cm.LegendPlacement.RIGHT)
            .values([pm.PieChartLegendValues.VALUE, pm.PieChartLegendValues.PERCENT])
        )
        .tooltip(cb.VizTooltipOptions().mode(cm.TooltipDisplayMode.SINGLE))
        .with_target(
            _loki_target(
                (f"sum by ({LABEL_MODEL}) (count_over_time({_SELECTOR} [$__range]))"),
                legend=f"{{{{{LABEL_MODEL}}}}}",
                instant=True,
            )
        )
    )


def _panel_latency_per_user() -> timeseries.Panel:
    return (
        timeseries.Panel()
        .title("Latency per user — p50 / p95")
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=9, w=24, x=0, y=22))
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
                (f"quantile_over_time(0.50, {_SELECTOR} {_unwrap('duration')} [5m]) by (user_id)"),
                legend="p50 {{user_id}}",
                ref_id="A",
            )
        )
        .with_target(
            _loki_target(
                (f"quantile_over_time(0.95, {_SELECTOR} {_unwrap('duration')} [5m]) by (user_id)"),
                legend="p95 {{user_id}}",
                ref_id="B",
            )
        )
    )


def _panel_failed_requests() -> timeseries.Panel:
    return (
        timeseries.Panel()
        .title("Failed requests per user (5xx)")
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=9, w=12, x=0, y=31))
        .unit("short")
        .draw_style(cm.GraphDrawStyle.BARS)
        .fill_opacity(70.0)
        .line_width(0.0)
        .stacking(cb.StackingConfig().mode(cm.StackingMode.NORMAL))
        .legend(
            cb.VizLegendOptions()
            .display_mode(cm.LegendDisplayMode.TABLE)
            .placement(cm.LegendPlacement.RIGHT)
            .calcs(["sum"])
        )
        .with_target(
            _loki_target(
                (
                    f"sum by (user_id) (count_over_time({_SELECTOR}"
                    " | json | response_code >= 500 [1m]))"
                ),
                legend="{{user_id}}",
            )
        )
    )


def _panel_token_usage() -> timeseries.Panel:
    return (
        timeseries.Panel()
        .title("Token usage per user (total)")
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=9, w=12, x=12, y=31))
        .unit("short")
        .draw_style(cm.GraphDrawStyle.LINE)
        .line_interpolation(cm.LineInterpolation.SMOOTH)
        .fill_opacity(5.0)
        .show_points(cm.VisibilityMode.NEVER)
        .legend(
            cb.VizLegendOptions()
            .display_mode(cm.LegendDisplayMode.TABLE)
            .placement(cm.LegendPlacement.RIGHT)
            .calcs(["sum", "mean"])
        )
        .with_target(
            _loki_target(
                (
                    "sum by (user_id) (sum_over_time("
                    f"{_SELECTOR} {_unwrap('gen_ai_usage_total_tokens')} [1m]))"
                ),
                legend="{{user_id}}",
            )
        )
    )


# ---------------------------------------------------------------------------
# Top-level builder
# ---------------------------------------------------------------------------

_DESCRIPTION = (
    "Per-user activity for the Envoy AI Gateway. "
    "Data flows: JWT -> Authorino response headers (x-oidc-user-id, x-oidc-azp; "
    "full x-oidc-* contract in ADR-0011) -> Envoy access log JSON (OTLP attributes) -> "
    "Alloy loki.process 'ai_gateway_user_attribution' (flattens the envelope, "
    "pins service_name=envoy-ai-gateway; ADR-0046) -> Loki labels (user_id, azp, model). "
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
                name="user_id",
                label="User",
                definition=(
                    f'label_values({{service_name="{GATEWAY_SERVICE_NAME}", azp=~"$azp"}}, user_id)'
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
        .with_panel(_panel_requests_range())
        .with_panel(_panel_unique_users())
        .with_panel(_panel_total_tokens())
        .with_panel(_panel_p95_latency())
        .with_panel(_panel_requests_per_user())
        .with_panel(_panel_top_users())
        .with_panel(_panel_model_distribution())
        .with_panel(_panel_latency_per_user())
        .with_panel(_panel_failed_requests())
        .with_panel(_panel_token_usage())
    )


def build() -> dict:
    """Return the dashboard as a JSON-compatible dict.

    Round-tripped through ``JSONEncoder`` so the dict contains only
    JSON-native types — no SDK model instances leak through nested fields.
    """
    return json.loads(json.dumps(_dashboard().build(), cls=JSONEncoder))
