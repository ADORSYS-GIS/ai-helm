"""Shared SDK panel/query helpers for the Envoy AI Gateway dashboards.

`_common.py` is intentionally SDK-free (pure data). This module is the
SDK-aware sibling: the query-builder gotchas the gateway dashboards all
share (the µ$→USD divide, the `| json ["dotted.key"] | unwrap` form, the
range-not-instant rule, daily-step buckets) live here ONCE so cost/actor
dashboards stay consistent with each other.

NOTE: `per_user.py` predates this module and keeps its own private copies of
these helpers on purpose — refactoring it would change its generated JSON and
trip the `dashboards check` drift guard. New dashboards import from here.
"""

from __future__ import annotations

from grafana_foundation_sdk.builders import bargauge, loki, piechart, stat, timeseries
from grafana_foundation_sdk.builders import common as cb
from grafana_foundation_sdk.builders import dashboard as db
from grafana_foundation_sdk.models import common as cm
from grafana_foundation_sdk.models import dashboard as dm
from grafana_foundation_sdk.models import piechart as pm

from dashboards._common import GATEWAY_SERVICE_NAME, LOKI_UID

LOKI_DS = dm.DataSourceRef(type_val="loki", uid=LOKI_UID)

# Envoy's access-log format.json declares the GenAI usage fields with LITERAL
# dots in the key name (`gen_ai.usage.total_tokens`), so the explicit
# `| json <name>` path-lookup form must bracket+quote the dotted key
# (`["dotted.key"]`) — a bare name doesn't match. See per_user._unwrap for the
# full archaeology (ADR-0046).
_JSON_PATHS = {
    "gen_ai_usage_total_tokens": "gen_ai.usage.total_tokens",
    "gen_ai_usage_custom_total_cost": "gen_ai.usage.custom_total_cost",
}


def unwrap(field: str) -> str:
    """`| json <field> | unwrap <field> | __error__=""` — extract ONLY `field`.

    Extracting one field (not a bare `| json`) keeps the per-line label set
    down to the genuine stream labels, so `sum_over_time`'s implicit grouping
    can't blow past Loki's 500-series cap. `__error__=""` drops samples that
    fail the string→float conversion (absent fields arrive as "-").
    """
    path = _JSON_PATHS.get(field)
    extract = f'{field}=`["{path}"]`' if path else field
    return f'| json {extract} | unwrap {field} | __error__=""'


def usd(expr: str) -> str:
    """Convert a raw micro-USD LogQL aggregation to USD (pricing CEL emits µ$)."""
    return f"(({expr}) / 1e6)"


def selector(*matchers: str) -> str:
    """`{service_name="envoy-ai-gateway", <extra matchers...>}`.

    Pass extra label matchers as raw LogQL fragments, e.g.
    `selector('display_name=~"$actor"', 'model=~"$model"')`.
    """
    parts = [f'service_name="{GATEWAY_SERVICE_NAME}"', *matchers]
    return "{" + ", ".join(parts) + "}"


def loki_target(
    expr: str,
    *,
    legend: str = "",
    ref_id: str = "A",
    instant: bool = False,
    step: str = "",
) -> loki.Dataquery:
    """A Loki query target. Range mode by default — the Loki Grafana plugin does
    NOT substitute `$__range`/`$__interval` in instant queries (silent no-data).

    `step="1d"` pins the query resolution so cost panels can't bucket finer than
    a day (the "minimum granularity of days" contract).
    """
    q = (
        loki.Dataquery()
        .expr(expr)
        .ref_id(ref_id)
        .query_type("instant" if instant else "range")
        .datasource(LOKI_DS)
    )
    if legend:
        q = q.legend_format(legend)
    if step:
        q = q.step(step)
    return q


def single_color_thresholds(color: str) -> db.ThresholdsConfig:
    return db.ThresholdsConfig().mode(dm.ThresholdsMode.ABSOLUTE).steps([dm.Threshold(color=color)])


def stat_panel(
    *,
    title: str,
    expr: str,
    unit: str,
    color: str,
    grid: tuple[int, int, int, int],
    step: str = "",
) -> stat.Panel:
    """Single-value stat with sparkline. `grid` is (h, w, x, y).

    `[$__range]` + the default lastNotNull calc reads the per-range total at the
    last evaluated point (a [1m]+sum form double-counts via overlapping
    auto-step windows — see per_user._panel_user_total_cost).
    """
    h, w, x, y = grid
    return (
        stat.Panel()
        .title(title)
        .datasource(LOKI_DS)
        .grid_pos(dm.GridPos(h=h, w=w, x=x, y=y))
        .unit(unit)
        .thresholds(single_color_thresholds(color))
        .reduce_options(cb.ReduceDataOptions().calcs(["lastNotNull"]).fields("").values(False))
        .orientation(cm.VizOrientation.HORIZONTAL)
        .text_mode(cm.BigValueTextMode.AUTO)
        .color_mode(cm.BigValueColorMode.VALUE)
        .graph_mode(cm.BigValueGraphMode.AREA)
        .justify_mode(cm.BigValueJustifyMode.AUTO)
        .with_target(loki_target(expr, step=step))
    )


def daily_bars_panel(
    *,
    title: str,
    expr: str,
    legend: str,
    unit: str,
    grid: tuple[int, int, int, int],
    legend_calcs: list[str] | None = None,
) -> timeseries.Panel:
    """Stacked daily BARS timeseries — the canonical "X per day, stacked by
    series" cost viz. Pairs with an `expr` that uses a `[1d]` window and a
    `step="1d"` target (set by the caller) so each bar is exactly one day.
    """
    h, w, x, y = grid
    return (
        timeseries.Panel()
        .title(title)
        .datasource(LOKI_DS)
        .grid_pos(dm.GridPos(h=h, w=w, x=x, y=y))
        .unit(unit)
        .draw_style(cm.GraphDrawStyle.BARS)
        .fill_opacity(70.0)
        .line_width(1.0)
        .show_points(cm.VisibilityMode.NEVER)
        .stacking(cb.StackingConfig().mode(cm.StackingMode.NORMAL))
        .legend(
            cb.VizLegendOptions()
            .display_mode(cm.LegendDisplayMode.TABLE)
            .placement(cm.LegendPlacement.RIGHT)
            .calcs(legend_calcs if legend_calcs is not None else ["sum"])
        )
        .tooltip(
            cb.VizTooltipOptions().mode(cm.TooltipDisplayMode.MULTI).sort(cm.SortOrder.DESCENDING)
        )
        .with_target(loki_target(expr, legend=legend, step="1d"))
    )


def pie_panel(
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
        .datasource(LOKI_DS)
        .grid_pos(dm.GridPos(h=h, w=w, x=x, y=y))
        .pie_type(pm.PieChartType.DONUT)
        .legend(
            piechart.PieChartLegendOptions()
            .display_mode(cm.LegendDisplayMode.TABLE)
            .placement(cm.LegendPlacement.RIGHT)
            .values([pm.PieChartLegendValues.VALUE, pm.PieChartLegendValues.PERCENT])
        )
        .tooltip(cb.VizTooltipOptions().mode(cm.TooltipDisplayMode.SINGLE))
        .with_target(loki_target(expr, legend=legend_label, instant=False))
    )


def bargauge_panel(
    *,
    title: str,
    expr: str,
    legend: str,
    unit: str,
    color: str,
    grid: tuple[int, int, int, int],
) -> bargauge.Panel:
    """Horizontal bargauge — ranked totals (one bar per series). Range query so
    `$__range` substitutes; the bar uses the series' last value."""
    h, w, x, y = grid
    return (
        bargauge.Panel()
        .title(title)
        .datasource(LOKI_DS)
        .grid_pos(dm.GridPos(h=h, w=w, x=x, y=y))
        .unit(unit)
        .orientation(cm.VizOrientation.HORIZONTAL)
        .reduce_options(cb.ReduceDataOptions().calcs(["lastNotNull"]).fields("").values(False))
        .display_mode(cm.BarGaugeDisplayMode.BASIC)
        .thresholds(single_color_thresholds(color))
        .with_target(loki_target(expr, legend=legend, instant=False))
    )


class _RowBuilder:
    """Tiny adapter so a RowPanel can be passed to Dashboard.with_panel (the SDK
    ships a RowPanel model but no row *builder*)."""

    def __init__(self, row: dm.RowPanel) -> None:
        self._row = row

    def build(self) -> dm.RowPanel:
        return self._row


def row(title: str, *, y: int) -> _RowBuilder:
    return _RowBuilder(dm.RowPanel(title=title, grid_pos=dm.GridPos(h=1, w=24, x=0, y=y)))


def actor_var(*, name: str, label: str, definition: str) -> db.QueryVariable:
    """Single-select query variable (for the actor picker — one user/repo at a
    time). All-value `.+` so 'All' still renders a valid regex matcher."""
    return (
        db.QueryVariable(name)
        .label(label)
        .datasource(LOKI_DS)
        .query(definition)
        .refresh(dm.VariableRefresh.ON_TIME_RANGE_CHANGED)
        .sort(dm.VariableSort.ALPHABETICAL_ASC)
        .multi(False)
        .include_all(True)
        .all_value(".+")
        .current(dm.VariableOption(selected=True, text="All", value="$__all"))
    )


def multi_var(*, name: str, label: str, definition: str) -> db.QueryVariable:
    """Multi-select query variable (channel/model filters)."""
    return (
        db.QueryVariable(name)
        .label(label)
        .datasource(LOKI_DS)
        .query(definition)
        .refresh(dm.VariableRefresh.ON_TIME_RANGE_CHANGED)
        .sort(dm.VariableSort.ALPHABETICAL_ASC)
        .multi(True)
        .include_all(True)
        .all_value(".+")
        .current(dm.VariableOption(selected=True, text=["All"], value=["$__all"]))
    )
