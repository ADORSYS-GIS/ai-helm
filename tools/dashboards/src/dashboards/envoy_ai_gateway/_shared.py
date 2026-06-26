"""Shared SDK panel/query helpers for the Envoy AI Gateway COST dashboards.

These dashboards read the **precomputed Mimir metrics** (ADR-0058) — Alloy
`stage.metrics` counters (`loki_process_custom_gen_ai_*`) scraped to Mimir — via
**PromQL**, NOT Loki log-scans. That's what makes a 30-day view instant on a
rate-limited object store. Counters → `increase(metric[window])`; cost is
micro-USD (÷1e6 via `usd()`).

`_common.py` stays SDK-free (pure data); this is its SDK-aware sibling.
`per_user.py` is a separate, Loki-backed dashboard and keeps its own helpers.
"""

from __future__ import annotations

from grafana_foundation_sdk.builders import bargauge, piechart, prometheus, stat, timeseries
from grafana_foundation_sdk.builders import common as cb
from grafana_foundation_sdk.builders import dashboard as db
from grafana_foundation_sdk.models import common as cm
from grafana_foundation_sdk.models import dashboard as dm
from grafana_foundation_sdk.models import piechart as pm

from dashboards._common import GATEWAY_SERVICE_NAME, MIMIR_UID

# Mimir is a Prometheus-compatible datasource.
MIMIR_DS = dm.DataSourceRef(type_val="prometheus", uid=MIMIR_UID)


def usd(expr: str) -> str:
    """Convert a micro-USD PromQL expression to USD (the cost counter is µ$)."""
    return f"(({expr}) / 1e6)"


def selector(*matchers: str) -> str:
    """`{service_name="envoy-ai-gateway", <extra PromQL label matchers...>}`."""
    parts = [f'service_name="{GATEWAY_SERVICE_NAME}"', *matchers]
    return "{" + ", ".join(parts) + "}"


def prom_target(
    expr: str,
    *,
    legend: str = "",
    ref_id: str = "A",
    instant: bool = True,
    fmt: str = "time_series",
    interval: str = "",
) -> prometheus.Dataquery:
    """A Mimir/PromQL query target.

    Totals/leaderboards/pies use `instant=True` (one value per series at the
    range end — `$__range` substitutes in Prometheus instant queries, unlike
    Loki). Daily-bar timeseries pass `instant=False` + `interval="1d"` so each
    bar is one day. `fmt="table"` is used for the per-actor table.
    """
    q = prometheus.Dataquery().expr(expr).ref_id(ref_id).datasource(MIMIR_DS)
    q = q.instant() if instant else q.range()
    if fmt:
        q = q.format(fmt)
    if legend:
        q = q.legend_format(legend)
    if interval:
        q = q.interval(interval)
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
) -> stat.Panel:
    """Single-value stat. `grid` is (h, w, x, y). Instant `sum(increase(...[$__range]))`."""
    h, w, x, y = grid
    return (
        stat.Panel()
        .title(title)
        .datasource(MIMIR_DS)
        .grid_pos(dm.GridPos(h=h, w=w, x=x, y=y))
        .unit(unit)
        .thresholds(single_color_thresholds(color))
        .reduce_options(cb.ReduceDataOptions().calcs(["lastNotNull"]).fields("").values(False))
        .orientation(cm.VizOrientation.HORIZONTAL)
        .text_mode(cm.BigValueTextMode.AUTO)
        .color_mode(cm.BigValueColorMode.VALUE)
        .graph_mode(cm.BigValueGraphMode.AREA)
        .justify_mode(cm.BigValueJustifyMode.AUTO)
        .with_target(prom_target(expr, instant=True))
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
    """Stacked daily BARS — pass an `increase(metric[1d])` expr; this pins the
    step to 1d (`interval`) so each bar is one day.

    Legend calcs default to mean/max, NOT sum: `increase` over a relative range
    evaluates a leading partial/lookback bucket at the range start, so a legend
    `sum` would mislead. Authoritative totals live in the stat/table/bargauge
    panels (instant `increase[$__range]`).
    """
    h, w, x, y = grid
    return (
        timeseries.Panel()
        .title(title)
        .datasource(MIMIR_DS)
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
            .calcs(legend_calcs if legend_calcs is not None else ["mean", "max"])
        )
        .tooltip(
            cb.VizTooltipOptions().mode(cm.TooltipDisplayMode.MULTI).sort(cm.SortOrder.DESCENDING)
        )
        .with_target(prom_target(expr, legend=legend, instant=False, interval="1d"))
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
        .datasource(MIMIR_DS)
        .grid_pos(dm.GridPos(h=h, w=w, x=x, y=y))
        .pie_type(pm.PieChartType.DONUT)
        .legend(
            piechart.PieChartLegendOptions()
            .display_mode(cm.LegendDisplayMode.TABLE)
            .placement(cm.LegendPlacement.RIGHT)
            .values([pm.PieChartLegendValues.VALUE, pm.PieChartLegendValues.PERCENT])
        )
        .tooltip(cb.VizTooltipOptions().mode(cm.TooltipDisplayMode.SINGLE))
        .with_target(prom_target(expr, legend=legend_label, instant=True))
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
    """Horizontal bargauge — ranked totals (one bar per series), instant query."""
    h, w, x, y = grid
    return (
        bargauge.Panel()
        .title(title)
        .datasource(MIMIR_DS)
        .grid_pos(dm.GridPos(h=h, w=w, x=x, y=y))
        .unit(unit)
        .orientation(cm.VizOrientation.HORIZONTAL)
        .reduce_options(cb.ReduceDataOptions().calcs(["lastNotNull"]).fields("").values(False))
        .display_mode(cm.BarGaugeDisplayMode.BASIC)
        .thresholds(single_color_thresholds(color))
        .with_target(prom_target(expr, legend=legend, instant=True))
    )


class _RowBuilder:
    """Tiny adapter so a RowPanel can be passed to Dashboard.with_panel."""

    def __init__(self, row: dm.RowPanel) -> None:
        self._row = row

    def build(self) -> dm.RowPanel:
        return self._row


def row(title: str, *, y: int) -> _RowBuilder:
    return _RowBuilder(dm.RowPanel(title=title, grid_pos=dm.GridPos(h=1, w=24, x=0, y=y)))


def actor_var(*, name: str, label: str, definition: str) -> db.QueryVariable:
    """Single-select query variable (the actor picker — one user/repo at a time)."""
    return (
        db.QueryVariable(name)
        .label(label)
        .datasource(MIMIR_DS)
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
        .datasource(MIMIR_DS)
        .query(definition)
        .refresh(dm.VariableRefresh.ON_TIME_RANGE_CHANGED)
        .sort(dm.VariableSort.ALPHABETICAL_ASC)
        .multi(True)
        .include_all(True)
        .all_value(".+")
        .current(dm.VariableOption(selected=True, text=["All"], value=["$__all"]))
    )


def label_values(metric: str, label: str) -> str:
    """PromQL template-variable query: distinct values of `label` on `metric`."""
    return f"label_values({metric}, {label})"
