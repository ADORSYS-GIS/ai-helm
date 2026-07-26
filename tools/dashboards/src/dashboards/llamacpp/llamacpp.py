"""llama.cpp inference engine — performance dashboard (GENERATED SOURCE).

Companion to `dashboards.vllm.vllm`. The GPU fleet runs two engines with
**completely disjoint metric namespaces** — vLLM publishes `vllm:*`, llama.cpp
publishes `llamacpp:*` — so neither dashboard can show the other's tier and both
are needed to see the whole fleet (ai-helm ADR-0094).

Two differences from the vLLM board are structural, not oversights:

1. **Selector is `job`, not `model_name`.** llama.cpp's exporter attaches NO
   `model_name` label; the only per-model identity is the scrape `job` (which
   equals the Service, and therefore the catalog entry name). Reusing the vLLM
   selector here yields empty panels on every query — verified against live
   Mimir before this file was written.

2. **No percentiles.** llama.cpp exports counters and gauges only — no
   histograms — so p50/p90/p99 are not computable. Where the vLLM board shows a
   latency distribution, this one shows an average derived from
   `…_seconds_total / …_total`, and says so in the panel title. Do not add
   `histogram_quantile` here; there are no `_bucket` series to feed it.

Metrics come from `llama-server --metrics`, scraped by the model's ServiceMonitor
— which must authenticate, because the engine requires a Bearer on `/metrics`
(ADR-0097).

The JSON file is regenerated from this module — do **not** hand-edit it.

    uv run dashboards build

ADR: ADR-0008 (Python dashboard generation).
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

OUTPUT_PATH: str = "charts/observability-dashboards/files/llamacpp/llamacpp-dashboard.json"

MIMIR_DS = dm.DataSourceRef(type_val="prometheus", uid=MIMIR_UID)

# llama-server's Prometheus exporter (llamacpp:*). This is the COMPLETE set as of
# build 10133 — eleven families, all counters or gauges.
M_PROMPT_TOKENS = "llamacpp:prompt_tokens_total"
M_PROMPT_SECONDS = "llamacpp:prompt_seconds_total"
M_PREDICTED_TOKENS = "llamacpp:tokens_predicted_total"
M_PREDICTED_SECONDS = "llamacpp:tokens_predicted_seconds_total"
M_DECODE_TOTAL = "llamacpp:n_decode_total"
M_TOKENS_MAX = "llamacpp:n_tokens_max"
M_PROMPT_RATE = "llamacpp:prompt_tokens_seconds"
M_PREDICTED_RATE = "llamacpp:predicted_tokens_seconds"
M_REQUESTS_PROCESSING = "llamacpp:requests_processing"
M_REQUESTS_DEFERRED = "llamacpp:requests_deferred"
M_BUSY_SLOTS = "llamacpp:n_busy_slots_per_decode"

# ⚠️ `job`, NOT `model_name` — see the module docstring.
_SEL = '{job=~"$model"}'


def _prom_target(expr, *, legend="", ref_id="A", instant=False):
    q = prometheus.Dataquery().expr(expr).ref_id(ref_id).datasource(MIMIR_DS)
    q = q.instant() if instant else q.range()
    if legend:
        q = q.legend_format(legend)
    return q


def _thresholds(*colors):
    steps = [dm.Threshold(color=c, value=v) for c, v in colors]
    return db.ThresholdsConfig().mode(dm.ThresholdsMode.ABSOLUTE).steps(steps)


def _stat_panel(*, title, expr, unit, thresholds, grid):
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
        .with_target(_prom_target(expr, instant=True))
    )


def _timeseries_panel(*, title, unit, grid, targets, thresholds=None):
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
    if thresholds is not None:
        panel = panel.thresholds(thresholds)
    for t in targets:
        panel = panel.with_target(t)
    return panel


class _RowBuilder:
    """Adapter so a RowPanel can be passed to Dashboard.with_panel."""

    def __init__(self, row: dm.RowPanel) -> None:
        self._row = row

    def build(self) -> dm.RowPanel:
        return self._row


def _row(title, *, y):
    return _RowBuilder(dm.RowPanel(title=title, grid_pos=dm.GridPos(h=1, w=24, x=0, y=y)))


def _dashboard():
    return (
        db.Dashboard("llama.cpp Inference")
        .uid("llamacpp-perf-dashboard")
        .tags(["llamacpp", "llm", "inference", "gpu"])
        .description(
            "llama.cpp (llama-server) inference performance, read from the "
            "llamacpp:* Prometheus exporter via Mimir. Companion to the vLLM "
            "board — the two engines publish disjoint metric namespaces, so "
            "each tier of the GPU fleet has its own dashboard. "
            "NOTE: llama.cpp exports counters and gauges only, no histograms, "
            "so latency panels are AVERAGES (seconds_total / tokens_total), not "
            "percentiles. The `model` variable filters on the scrape job, "
            "because this exporter emits no model_name label. "
            "GENERATED — source: tools/dashboards/src/dashboards/llamacpp/llamacpp.py."
        )
        .timezone("browser")
        .editable()
        .tooltip(dm.DashboardCursorSync.CROSSHAIR)
        .refresh("30s")
        .time("now-1h", "now")
        .with_variable(
            db.QueryVariable("model")
            .label("Model")
            .datasource(MIMIR_DS)
            .query(f"label_values({M_REQUESTS_PROCESSING}, job)")
            .refresh(dm.VariableRefresh.ON_TIME_RANGE_CHANGED)
            .sort(dm.VariableSort.ALPHABETICAL_ASC)
            .multi(True)
            .include_all(True)
            .all_value(".+")
            .current(dm.VariableOption(selected=True, text=["All"], value=["$__all"]))
        )
        # ── Overview ────────────────────────────────────────────────────────
        # The two rate gauges are llama-server's own instantaneous figures, which
        # are what to compare against a benchmark report; the counter-derived
        # rates further down are what to trust for trends.
        .with_panel(
            _stat_panel(
                title="Decode (tok/s, live)",
                expr=f"{M_PREDICTED_RATE}{_SEL}",
                unit="tokens/s",
                thresholds=_thresholds(("red", None), ("yellow", 5), ("green", 10)),
                grid=(4, 4, 0, 0),
            )
        )
        .with_panel(
            _stat_panel(
                title="Prefill (tok/s, live)",
                expr=f"{M_PROMPT_RATE}{_SEL}",
                unit="tokens/s",
                thresholds=_thresholds(("green", None)),
                grid=(4, 4, 4, 0),
            )
        )
        .with_panel(
            _stat_panel(
                title="Requests Processing",
                expr=f"{M_REQUESTS_PROCESSING}{_SEL}",
                unit="short",
                thresholds=_thresholds(("green", None)),
                grid=(4, 4, 8, 0),
            )
        )
        # Deferred > 0 means every slot is busy and requests are queuing — the
        # signal that this tier is saturated, since there is no autoscaling.
        .with_panel(
            _stat_panel(
                title="Requests Deferred (queued)",
                expr=f"{M_REQUESTS_DEFERRED}{_SEL}",
                unit="short",
                thresholds=_thresholds(("green", None), ("yellow", 1), ("red", 5)),
                grid=(4, 4, 12, 0),
            )
        )
        .with_panel(
            _stat_panel(
                title="Avg Time / Output Token",
                expr=(
                    f"rate({M_PREDICTED_SECONDS}{_SEL}[5m]) / rate({M_PREDICTED_TOKENS}{_SEL}[5m])"
                ),
                unit="s",
                thresholds=_thresholds(("green", None), ("yellow", 0.1)),
                grid=(4, 4, 16, 0),
            )
        )
        .with_panel(
            _stat_panel(
                title="Busy Slots / Decode",
                expr=f"{M_BUSY_SLOTS}{_SEL}",
                unit="short",
                thresholds=_thresholds(("green", None)),
                grid=(4, 4, 20, 0),
            )
        )
        # ── Throughput ──────────────────────────────────────────────────────
        .with_panel(_row("Throughput", y=4))
        .with_panel(
            _timeseries_panel(
                title="Generated Tokens/s",
                unit="tokens/s",
                grid=(8, 12, 0, 5),
                targets=[_prom_target(f"rate({M_PREDICTED_TOKENS}{_SEL}[5m])", legend="{{job}}")],
            )
        )
        .with_panel(
            _timeseries_panel(
                title="Prompt Tokens/s",
                unit="tokens/s",
                grid=(8, 12, 12, 5),
                targets=[_prom_target(f"rate({M_PROMPT_TOKENS}{_SEL}[5m])", legend="{{job}}")],
            )
        )
        # ── Latency (averages — no histograms available) ─────────────────────
        .with_panel(_row("Latency (averages — llama.cpp exports no histograms)", y=13))
        .with_panel(
            _timeseries_panel(
                title="Avg Time per Output Token",
                unit="s",
                grid=(8, 12, 0, 14),
                targets=[
                    _prom_target(
                        f"rate({M_PREDICTED_SECONDS}{_SEL}[5m]) "
                        f"/ rate({M_PREDICTED_TOKENS}{_SEL}[5m])",
                        legend="{{job}}",
                    )
                ],
            )
        )
        .with_panel(
            _timeseries_panel(
                title="Avg Prompt Processing Time per Token",
                unit="s",
                grid=(8, 12, 12, 14),
                targets=[
                    _prom_target(
                        f"rate({M_PROMPT_SECONDS}{_SEL}[5m]) / rate({M_PROMPT_TOKENS}{_SEL}[5m])",
                        legend="{{job}}",
                    )
                ],
            )
        )
        # ── Slots & concurrency ─────────────────────────────────────────────
        .with_panel(_row("Slots & Concurrency", y=22))
        .with_panel(
            _timeseries_panel(
                title="Requests: Processing vs Deferred",
                unit="short",
                grid=(8, 12, 0, 23),
                targets=[
                    _prom_target(f"{M_REQUESTS_PROCESSING}{_SEL}", legend="Processing"),
                    _prom_target(f"{M_REQUESTS_DEFERRED}{_SEL}", legend="Deferred", ref_id="B"),
                ],
            )
        )
        .with_panel(
            _timeseries_panel(
                title="Decode Batches/s & Busy Slots",
                unit="short",
                grid=(8, 12, 12, 23),
                targets=[
                    _prom_target(f"rate({M_DECODE_TOTAL}{_SEL}[5m])", legend="Decode batches/s"),
                    _prom_target(f"{M_BUSY_SLOTS}{_SEL}", legend="Busy slots", ref_id="B"),
                ],
            )
        )
        # `n_tokens_max` is the largest context seen — the practical check on
        # whether the advertised contextLength is anywhere near being used.
        .with_panel(
            _timeseries_panel(
                title="Largest Context Seen (tokens)",
                unit="short",
                grid=(8, 24, 0, 31),
                targets=[_prom_target(f"{M_TOKENS_MAX}{_SEL}", legend="{{job}}")],
            )
        )
    )


def build():
    return json.loads(json.dumps(_dashboard().build(), cls=JSONEncoder))
