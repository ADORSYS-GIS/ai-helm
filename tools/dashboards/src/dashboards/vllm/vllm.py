"""vLLM inference engine — comprehensive performance dashboard (GENERATED SOURCE).

End-to-end view of a vLLM inference server: request success/error rates,
generation/prompt token throughput, end-to-end latency + TTFT + inter-token +
prefill latency (p50/p90/p95/p99), request queue depth, KV-cache usage,
prefix-cache hit rate, and preemption counts. All metrics come from vLLM's
built-in Prometheus exporter (vllm:engine); the dashboard reads them via
Mimir (Prometheus-compatible).

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

OUTPUT_PATH: str = "charts/observability-dashboards/files/vllm/vllm-dashboard.json"

MIMIR_DS = dm.DataSourceRef(type_val="prometheus", uid=MIMIR_UID)

# vLLM Prometheus exporter metric names (vllm:engine).
M_REQUEST_SUCCESS = "vllm:request_success_total"
M_GENERATION_TOKENS = "vllm:generation_tokens_total"
M_PROMPT_TOKENS = "vllm:prompt_tokens_total"
M_E2E_LATENCY_SUM = "vllm:e2e_request_latency_seconds_sum"
M_E2E_LATENCY_COUNT = "vllm:e2e_request_latency_seconds_count"
M_E2E_LATENCY_BUCKET = "vllm:e2e_request_latency_seconds_bucket"
M_TTFT_SUM = "vllm:time_to_first_token_seconds_sum"
M_TTFT_COUNT = "vllm:time_to_first_token_seconds_count"
M_TTFT_BUCKET = "vllm:time_to_first_token_seconds_bucket"
M_INTER_TOKEN_BUCKET = "vllm:inter_token_latency_seconds_bucket"
M_PREFILL_BUCKET = "vllm:request_prefill_time_seconds_bucket"
M_NUM_RUNNING = "vllm:num_requests_running"
M_NUM_WAITING = "vllm:num_requests_waiting"
M_KV_CACHE_USAGE = "vllm:kv_cache_usage_perc"
M_PREFIX_CACHE_HITS = "vllm:prefix_cache_hits_total"
M_PREFIX_CACHE_QUERIES = "vllm:prefix_cache_queries_total"
M_NUM_PREEMPTIONS = "vllm:num_preemptions_total"

_SEL = '{model_name=~"$model_name"}'


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


def _percentile_targets(bucket_metric):
    return [
        _prom_target(
            f"histogram_quantile({q}, sum by (le, model_name) (rate({bucket_metric}{_SEL}[5m])))",
            legend=legend,
            ref_id=ref_id,
        )
        for ref_id, q, legend in [("A", 0.5, "p50"), ("B", 0.9, "p90"), ("C", 0.95, "p95"), ("D", 0.99, "p99")]
    ]


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
        db.Dashboard("vLLM Inference - Comprehensive")
        .uid("vllm-perf-dashboard")
        .tags(["vllm", "llm", "inference", "gpu"])
        .description(
            "Comprehensive vLLM inference engine performance dashboard. "
            "Reads vLLM's built-in Prometheus exporter metrics (vllm:engine) "
            "via Mimir. Covers request success/error rates, generation/prompt "
            "token throughput, end-to-end latency + TTFT + inter-token + "
            "prefill latency (p50/p90/p95/p99), request queue depth, "
            "KV-cache usage, prefix-cache hit rate, and preemption counts. "
            "The model_name template variable filters every panel. "
            "GENERATED — source: tools/dashboards/src/dashboards/vllm/vllm.py."
        )
        .timezone("browser")
        .editable()
        .tooltip(dm.DashboardCursorSync.CROSSHAIR)
        .refresh("30s")
        .time("now-1h", "now")
        .with_variable(
            db.QueryVariable("model_name")
            .label("Model")
            .datasource(MIMIR_DS)
            .query(f"label_values({M_REQUEST_SUCCESS}, model_name)")
            .refresh(dm.VariableRefresh.ON_TIME_RANGE_CHANGED)
            .sort(dm.VariableSort.ALPHABETICAL_ASC)
            .multi(True)
            .include_all(True)
            .all_value(".+")
            .current(dm.VariableOption(selected=True, text=["All"], value=["$__all"]))
        )
        .with_panel(_stat_panel(title="Successful Requests", expr=f"{M_REQUEST_SUCCESS}{_SEL}", unit="short", thresholds=_thresholds(("green", None)), grid=(4, 4, 0, 0)))
        .with_panel(_stat_panel(title="Requests (Error)", expr=f'{M_REQUEST_SUCCESS}{{finished_reason="error",model_name=~"$model_name"}}', unit="short", thresholds=_thresholds(("green", None), ("red", 1)), grid=(4, 4, 4, 0)))
        .with_panel(_stat_panel(title="Generation Tokens/s", expr=f"rate({M_GENERATION_TOKENS}{_SEL}[5m])", unit="tokens/s", thresholds=_thresholds(("green", None)), grid=(4, 4, 8, 0)))
        .with_panel(_stat_panel(title="Prompt Tokens/s", expr=f"rate({M_PROMPT_TOKENS}{_SEL}[5m])", unit="tokens/s", thresholds=_thresholds(("green", None)), grid=(4, 4, 12, 0)))
        .with_panel(_stat_panel(title="Avg E2E Latency", expr=f"rate({M_E2E_LATENCY_SUM}{_SEL}[5m]) / rate({M_E2E_LATENCY_COUNT}{_SEL}[5m])", unit="s", thresholds=_thresholds(("green", None), ("yellow", 1)), grid=(4, 4, 16, 0)))
        .with_panel(_stat_panel(title="Avg TTFT", expr=f"rate({M_TTFT_SUM}{_SEL}[5m]) / rate({M_TTFT_COUNT}{_SEL}[5m])", unit="s", thresholds=_thresholds(("green", None), ("yellow", 0.1)), grid=(4, 4, 20, 0)))
        .with_panel(_row("Latency", y=4))
        .with_panel(_timeseries_panel(title="End-to-End Request Latency", unit="s", grid=(8, 12, 0, 5), targets=_percentile_targets(M_E2E_LATENCY_BUCKET)))
        .with_panel(_timeseries_panel(title="Time to First Token", unit="s", grid=(8, 12, 12, 5), targets=_percentile_targets(M_TTFT_BUCKET)))
        .with_panel(_timeseries_panel(title="Per-Token Latency (Inter-Token)", unit="s", grid=(8, 12, 0, 13), targets=_percentile_targets(M_INTER_TOKEN_BUCKET)))
        .with_panel(_timeseries_panel(title="Prompt Processing Latency", unit="s", grid=(8, 12, 12, 13), targets=_percentile_targets(M_PREFILL_BUCKET)))
        .with_panel(_row("Throughput", y=21))
        .with_panel(_timeseries_panel(title="Generation Tokens/s", unit="tokens/s", grid=(8, 12, 0, 22), targets=[_prom_target(f"rate({M_GENERATION_TOKENS}{_SEL}[5m])", legend="{{model_name}}")]))
        .with_panel(_timeseries_panel(title="Prompt Tokens/s", unit="tokens/s", grid=(8, 12, 12, 22), targets=[_prom_target(f"rate({M_PROMPT_TOKENS}{_SEL}[5m])", legend="{{model_name}}")]))
        .with_panel(_timeseries_panel(title="Requests/s", unit="reqps", grid=(8, 12, 0, 30), targets=[_prom_target(f"rate({M_REQUEST_SUCCESS}{_SEL}[5m])", legend="Success"), _prom_target(f'{M_REQUEST_SUCCESS}{{finished_reason="error",model_name=~"$model_name"}}', legend="Failed")]))
        .with_panel(_timeseries_panel(title="Request Queue", unit="short", grid=(8, 12, 12, 30), targets=[_prom_target(f"{M_NUM_RUNNING}{_SEL}", legend="Running"), _prom_target(f"{M_NUM_WAITING}{_SEL}", legend="Waiting"), _prom_target(f"{M_NUM_WAITING}{_SEL}", legend="Swapped")]))
        .with_panel(_row("Engine Internals", y=38))
        .with_panel(_timeseries_panel(title="GPU Cache Usage", unit="percent", grid=(8, 12, 0, 39), thresholds=_thresholds(("green", None), ("yellow", 70)), targets=[_prom_target(f"{M_KV_CACHE_USAGE}{_SEL}", legend="{{model_name}}")]))
        .with_panel(_timeseries_panel(title="Prefix Cache Hits/s", unit="short", grid=(8, 12, 12, 39), targets=[_prom_target(f"rate({M_PREFIX_CACHE_HITS}{_SEL}[5m])", legend="{{model_name}}")]))
        .with_panel(_timeseries_panel(title="Prefix Cache Hit Ratio", unit="percent", grid=(8, 12, 0, 47), thresholds=_thresholds(("green", None), ("yellow", 50)), targets=[_prom_target(f"rate({M_PREFIX_CACHE_HITS}{_SEL}[5m]) / (rate({M_PREFIX_CACHE_HITS}{_SEL}[5m]) + rate({M_PREFIX_CACHE_QUERIES}{_SEL}[5m]))", legend="{{model_name}}")]))
        .with_panel(_timeseries_panel(title="KV Cache & Preemptions", unit="short", grid=(8, 12, 12, 47), targets=[_prom_target(f"{M_KV_CACHE_USAGE}{_SEL}", legend="Usage %"), _prom_target(f"{M_NUM_PREEMPTIONS}{_SEL}", legend="Preemptions")]))
        .with_panel(_row("System Health (DCGM exporter not running - GPU metrics unavailable)", y=55))
    )


def build():
    return json.loads(json.dumps(_dashboard().build(), cls=JSONEncoder))