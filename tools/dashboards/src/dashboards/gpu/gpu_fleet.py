"""GPU fleet ↔ model attribution — the board no community dashboard can provide.

Deliberately NOT a general DCGM dashboard. Commodity GPU health (temperature,
power, clocks, utilisation per card) is covered by the adopted community board
`nvidia-dcgm-12239`, per ADR-0045 §2. This board answers the one question that
depends on knowing OUR platform: **which model is on which card, and what is it
costing in silicon.**

It joins DCGM's per-GPU samples to the workload using them. That join only exists
because the ServiceMonitor sets `honorLabels: true`, so DCGM's own `pod` /
`namespace` / `container` labels — which describe the WORKLOAD, not the exporter —
survive the scrape. With honorLabels false they land as `exported_pod` and every
series claims to be the dcgm-exporter pod in kube-system, which makes exactly
these panels impossible.

Metric availability was verified against live Mimir before writing this (22 DCGM
families present, all referenced metrics returning data). Cross-check: DCGM's
`DCGM_FI_DEV_FB_USED` agreed with `nvidia-smi` to within a MiB on both cards.

The JSON file is regenerated from this module — do **not** hand-edit it.

    uv run dashboards build

ADR: ADR-0008 (Python dashboard generation), ADR-0045 (dashboard sourcing).
"""

from __future__ import annotations

import json

from grafana_foundation_sdk.builders import common as cb
from grafana_foundation_sdk.builders import dashboard as db
from grafana_foundation_sdk.builders import prometheus, stat, timeseries
from grafana_foundation_sdk.cog.encoder import JSONEncoder
from grafana_foundation_sdk.models import common as cm
from grafana_foundation_sdk.models import dashboard as dm

from dashboards._common import MIMIR_UID

OUTPUT_PATH: str = "charts/observability-dashboards/files/gpu/gpu-fleet.json"

MIMIR_DS = dm.DataSourceRef(type_val="prometheus", uid=MIMIR_UID)

M_FB_USED = "DCGM_FI_DEV_FB_USED"
M_FB_FREE = "DCGM_FI_DEV_FB_FREE"
M_GPU_UTIL = "DCGM_FI_DEV_GPU_UTIL"
M_MEM_COPY_UTIL = "DCGM_FI_DEV_MEM_COPY_UTIL"
M_POWER = "DCGM_FI_DEV_POWER_USAGE"
M_TEMP = "DCGM_FI_DEV_GPU_TEMP"
M_SM_CLOCK = "DCGM_FI_DEV_SM_CLOCK"
M_TENSOR_ACTIVE = "DCGM_FI_PROF_PIPE_TENSOR_ACTIVE"

# `hostname` is the DCGM-provided node label, lowercase in DCGM 4.x (it was
# `Hostname` in the 2.x era — a community dashboard written then renders empty
# legends against this exporter).
_SEL = '{hostname=~"$node"}'

# The card is 20475 MiB. Kept as a constant so the "% of card" panels do not
# depend on a metric DCGM does not export as a ratio.
CARD_TOTAL_MIB = 20475


def _prom_target(expr, *, legend="", ref_id="A", instant=False):
    q = prometheus.Dataquery().expr(expr).ref_id(ref_id).datasource(MIMIR_DS)
    q = q.instant() if instant else q.range()
    if legend:
        q = q.legend_format(legend)
    return q


def _thresholds(*colors):
    steps = [dm.Threshold(color=c, value=v) for c, v in colors]
    return db.ThresholdsConfig().mode(dm.ThresholdsMode.ABSOLUTE).steps(steps)


def _stat_panel(*, title, expr, unit, thresholds, grid, legend=""):
    h, w, x, y = grid
    return (
        stat.Panel()
        .title(title)
        .datasource(MIMIR_DS)
        .grid_pos(dm.GridPos(h=h, w=w, x=x, y=y))
        .unit(unit)
        .thresholds(thresholds)
        .reduce_options(cb.ReduceDataOptions().calcs(["lastNotNull"]).fields("").values(False))
        .orientation(cm.VizOrientation.AUTO)
        .text_mode(cm.BigValueTextMode.AUTO)
        .color_mode(cm.BigValueColorMode.VALUE)
        .graph_mode(cm.BigValueGraphMode.AREA)
        .justify_mode(cm.BigValueJustifyMode.AUTO)
        .with_target(_prom_target(expr, instant=True, legend=legend))
    )


def _timeseries_panel(*, title, unit, grid, targets, thresholds=None, maximum=None):
    h, w, x, y = grid
    panel = (
        timeseries.Panel()
        .title(title)
        .datasource(MIMIR_DS)
        .grid_pos(dm.GridPos(h=h, w=w, x=x, y=y))
        .unit(unit)
        .legend(
            cb.VizLegendOptions()
            .display_mode(cm.LegendDisplayMode.TABLE)
            .placement(cm.LegendPlacement.BOTTOM)
            .calcs(["mean", "max"])
        )
        .tooltip(
            cb.VizTooltipOptions().mode(cm.TooltipDisplayMode.MULTI).sort(cm.SortOrder.DESCENDING)
        )
    )
    if maximum is not None:
        panel = panel.max(maximum)
    if thresholds is not None:
        panel = panel.thresholds(thresholds)
    # Assign refIds positionally (A, B, C, ...) rather than trusting each call
    # site to pass a unique one. Grafana rejects a panel whose targets share a
    # refId with "Multiple queries using the same RefId is not allowed" and
    # renders NOTHING — and since _prom_target defaults to "A", any panel with
    # more than one target silently produced that unless the author remembered.
    # Three panels shipped broken that way; doing it here makes it impossible.
    for i, t in enumerate(targets):
        panel = panel.with_target(t.ref_id(chr(ord("A") + i)))
    return panel


class _RowBuilder:
    def __init__(self, row: dm.RowPanel) -> None:
        self._row = row

    def build(self) -> dm.RowPanel:
        return self._row


def _row(title, *, y):
    return _RowBuilder(dm.RowPanel(title=title, grid_pos=dm.GridPos(h=1, w=24, x=0, y=y)))


# Legend showing node + the attributed workload, e.g.
# "hetzner-k8s-gpu-1 · openmythos-27b-main-...". `pod` is DCGM's own label,
# preserved by honorLabels.
_LEGEND = "{{hostname}} · {{pod}}"


def _dashboard():
    return (
        db.Dashboard("GPU Fleet — cards and the models on them")
        .uid("gpu-fleet-attribution")
        .tags(["gpu", "dcgm", "inference", "model-serving"])
        .description(
            "Which model is on which GPU, and what it costs in silicon. Joins "
            "DCGM per-card telemetry to the workload using the card via DCGM's "
            "own pod/namespace labels (which survive only because the "
            "ServiceMonitor sets honorLabels: true). "
            "For general per-card health — clocks, temperature, power curves — "
            "see the adopted community board 'NVIDIA DCGM Exporter (12239)'. "
            "GENERATED — source: tools/dashboards/src/dashboards/gpu/gpu_fleet.py."
        )
        .timezone("browser")
        .editable()
        .tooltip(dm.DashboardCursorSync.CROSSHAIR)
        .refresh("30s")
        .time("now-6h", "now")
        .with_variable(
            db.QueryVariable("node")
            .label("GPU node")
            .datasource(MIMIR_DS)
            .query(f"label_values({M_FB_USED}, hostname)")
            .refresh(dm.VariableRefresh.ON_TIME_RANGE_CHANGED)
            .sort(dm.VariableSort.ALPHABETICAL_ASC)
            .multi(True)
            .include_all(True)
            .all_value(".+")
            .current(dm.VariableOption(selected=True, text=["All"], value=["$__all"]))
        )
        # ── At a glance ─────────────────────────────────────────────────────
        .with_panel(
            _stat_panel(
                title="VRAM used",
                expr=f"{M_FB_USED}{_SEL}",
                unit="decmbytes",
                thresholds=_thresholds(("green", None), ("yellow", 17000), ("red", 19500)),
                grid=(5, 6, 0, 0),
                legend=_LEGEND,
            )
        )
        .with_panel(
            _stat_panel(
                title="GPU utilisation",
                expr=f"{M_GPU_UTIL}{_SEL}",
                unit="percent",
                thresholds=_thresholds(("green", None)),
                grid=(5, 6, 6, 0),
                legend=_LEGEND,
            )
        )
        .with_panel(
            _stat_panel(
                title="Power draw",
                expr=f"{M_POWER}{_SEL}",
                unit="watt",
                # The card is capped at 70 W; sustained near-cap is the ceiling,
                # not a fault.
                thresholds=_thresholds(("green", None), ("yellow", 60)),
                grid=(5, 6, 12, 0),
                legend=_LEGEND,
            )
        )
        .with_panel(
            _stat_panel(
                title="Temperature",
                expr=f"{M_TEMP}{_SEL}",
                unit="celsius",
                thresholds=_thresholds(("green", None), ("yellow", 75), ("red", 85)),
                grid=(5, 6, 18, 0),
                legend=_LEGEND,
            )
        )
        # ── Attribution ─────────────────────────────────────────────────────
        .with_panel(_row("Which model is on which card", y=5))
        .with_panel(
            _timeseries_panel(
                title="VRAM used per model (MiB)",
                unit="decmbytes",
                grid=(8, 12, 0, 6),
                targets=[_prom_target(f"{M_FB_USED}{_SEL}", legend=_LEGEND)],
            )
        )
        .with_panel(
            _timeseries_panel(
                title="VRAM used as % of the 20475 MiB card",
                unit="percent",
                grid=(8, 12, 12, 6),
                maximum=100,
                thresholds=_thresholds(("green", None), ("yellow", 85), ("red", 95)),
                targets=[
                    _prom_target(
                        f"100 * {M_FB_USED}{_SEL} / {CARD_TOTAL_MIB}",
                        legend=_LEGEND,
                    )
                ],
            )
        )
        # ── Load ────────────────────────────────────────────────────────────
        .with_panel(_row("Load", y=14))
        .with_panel(
            _timeseries_panel(
                title="GPU utilisation (%)",
                unit="percent",
                grid=(8, 12, 0, 15),
                maximum=100,
                targets=[_prom_target(f"{M_GPU_UTIL}{_SEL}", legend=_LEGEND)],
            )
        )
        # Memory-copy utilisation next to SM utilisation is the tell for a
        # bandwidth-bound workload — which every decode-heavy LLM on this card is.
        .with_panel(
            _timeseries_panel(
                title="Memory-copy utilisation (%) — the bandwidth-bound tell",
                unit="percent",
                grid=(8, 12, 12, 15),
                maximum=100,
                targets=[_prom_target(f"{M_MEM_COPY_UTIL}{_SEL}", legend=_LEGEND)],
            )
        )
        .with_panel(
            _timeseries_panel(
                title="Tensor-core pipe active (fraction)",
                unit="percentunit",
                grid=(8, 12, 0, 23),
                targets=[_prom_target(f"{M_TENSOR_ACTIVE}{_SEL}", legend=_LEGEND)],
            )
        )
        .with_panel(
            _timeseries_panel(
                title="SM clock (MHz)",
                unit="rothz",
                grid=(8, 12, 12, 23),
                targets=[_prom_target(f"{M_SM_CLOCK}{_SEL}", legend=_LEGEND)],
            )
        )
        # ── Thermals & power ────────────────────────────────────────────────
        .with_panel(_row("Thermals & power", y=31))
        .with_panel(
            _timeseries_panel(
                title="Temperature (°C)",
                unit="celsius",
                grid=(8, 12, 0, 32),
                thresholds=_thresholds(("green", None), ("yellow", 75), ("red", 85)),
                targets=[_prom_target(f"{M_TEMP}{_SEL}", legend=_LEGEND)],
            )
        )
        .with_panel(
            _timeseries_panel(
                title="Power draw (W) — card is capped at 70 W",
                unit="watt",
                grid=(8, 12, 12, 32),
                thresholds=_thresholds(("green", None), ("yellow", 60)),
                targets=[_prom_target(f"{M_POWER}{_SEL}", legend=_LEGEND)],
            )
        )
    )


def build():
    return json.loads(json.dumps(_dashboard().build(), cls=JSONEncoder))
