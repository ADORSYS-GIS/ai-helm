"""AISIX — the Responses→Chat bridge behind Envoy AI Gateway (GENERATED SOURCE).

Reads the `aisix_*` Prometheus families that `api7/aisix` 1.0.0 serves on :9090,
scraped by the `converse/aisix` PodMonitor (`charts/aisix`) and remote-written to
Mimir by Alloy. Source of truth for the board:
[ai-helm-values#398](https://github.com/ADORSYS-GIS/ai-helm-values/issues/398).

Three things about these metrics decide the queries below, and each one was
checked against the live `:9090` surface and against Mimir on 2026-09-04 before
a panel was written.

1. **`endpoint` is the request PATH, and it only reaches Mimir because the
   PodMonitor renames the scrape's own label.** AISIX exports
   `endpoint="/v1/responses"` / `endpoint="/v1/chat/completions"`; the Prometheus
   operator sets a target label of the same name holding the port name
   (`metrics`), which wins by default. `charts/aisix`'s `metricRelabelings` move
   the port name to `scrape_endpoint` and give `endpoint` back to AISIX
   (ai-helm-values#389). **Every "by operation" panel here depends on that** —
   against a cluster running charts/aisix without it, they collapse to a single
   `metrics` series.

2. **The `*_duration_seconds` SUMMARIES are useless in 1.0.0 — do not use them.**
   `aisix_request_duration_seconds`, `aisix_llm_request_duration_seconds`,
   `aisix_proxy_request_duration_seconds` and
   `aisix_llm_time_to_first_token_seconds` all publish `quantile="0.5|0.9|0.95|
   0.99|0.999|1"` as literal **0** on a pod that has served real traffic (their
   `_sum`/`_count` are populated, so it is the quantile estimator that is dead,
   not the instrumentation). Latency here therefore comes from the two real
   HISTOGRAMS — `aisix_request_e2e_latency_seconds_bucket` and
   `aisix_request_ttft_seconds_bucket` — via `histogram_quantile`.

3. **The histograms use a different label vocabulary than the counters.** They
   carry `status_class` (`2xx`/`4xx`/`5xx`) and `streaming`, where the counters
   carry `status` (the numeric code) and `stream`. Mixing them up yields empty
   panels, not an error.

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

OUTPUT_PATH: str = "charts/observability-dashboards/files/aisix/aisix.json"

MIMIR_DS = dm.DataSourceRef(type_val="prometheus", uid=MIMIR_UID)

# The scrape job the PodMonitor produces: "<namespace>/<PodMonitor name>".
# Confirmed live: `up{job="converse/aisix"}` == 1.
JOB = "converse/aisix"

# Counters (path/status/stream vocabulary).
M_LLM_REQUESTS = "aisix_llm_requests_total"
M_LLM_TOTAL_TOKENS = "aisix_llm_total_tokens_total"
M_LLM_INPUT_TOKENS = "aisix_llm_input_tokens_total"
M_LLM_OUTPUT_TOKENS = "aisix_llm_output_tokens_total"
M_LLM_CACHED_INPUT_TOKENS = "aisix_llm_cached_input_tokens_total"
M_TOKENS_BY_CLIENT = "aisix_llm_tokens_by_client_total"
# Histograms (status_class/streaming vocabulary).
M_E2E_BUCKET = "aisix_request_e2e_latency_seconds_bucket"
M_TTFT_BUCKET = "aisix_request_ttft_seconds_bucket"
# Gauges.
M_IN_FLIGHT = "aisix_proxy_in_flight_requests"

# `model` is a template variable; `job` is pinned — this board is about ONE
# deployment, and a second AISIX would want its own row of stat panels anyway.
_SEL = f'{{job="{JOB}", model=~"$model"}}'
# Latency histograms carry `model` too, so the same selector applies.
_SEL_5XX = f'{{job="{JOB}", model=~"$model", status=~"5.."}}'


def _prom_target(expr, *, legend="", ref_id="A", instant=False):
    q = prometheus.Dataquery().expr(expr).ref_id(ref_id).datasource(MIMIR_DS)
    q = q.instant() if instant else q.range()
    if legend:
        q = q.legend_format(legend)
    return q


def _thresholds(*colors):
    steps = [dm.Threshold(color=c, value=v) for c, v in colors]
    return db.ThresholdsConfig().mode(dm.ThresholdsMode.ABSOLUTE).steps(steps)


def _stat_panel(*, title, expr, unit, thresholds, grid, description="", decimals=None):
    h, w, x, y = grid
    panel = (
        stat.Panel()
        .title(title)
        .description(description)
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
    if decimals is not None:
        panel = panel.decimals(decimals)
    return panel


def _timeseries_panel(*, title, unit, grid, targets, description="", thresholds=None):
    h, w, x, y = grid
    panel = (
        timeseries.Panel()
        .title(title)
        .description(description)
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
    # refIds assigned positionally — Grafana renders NOTHING for a panel whose
    # targets share a refId, and it does so silently. Same guard as the vLLM /
    # llama.cpp boards.
    for i, t in enumerate(targets):
        panel = panel.with_target(t.ref_id(chr(ord("A") + i)))
    return panel


class _RowBuilder:
    """Adapter so a RowPanel can be passed to Dashboard.with_panel."""

    def __init__(self, row: dm.RowPanel) -> None:
        self._row = row

    def build(self) -> dm.RowPanel:
        return self._row


def _row(title, *, y):
    return _RowBuilder(dm.RowPanel(title=title, grid_pos=dm.GridPos(h=1, w=24, x=0, y=y)))


# 5xx as a percentage of all AISIX requests. `or vector(0)` on the numerator so
# the panel reads a flat 0 while there are no 5xx series at all, instead of
# going blank and looking like the scrape broke; the denominator is left bare so
# that NO traffic reads as no data rather than as a fabricated 0 %.
_ERROR_RATIO = (
    f"100 * (sum(rate({M_LLM_REQUESTS}{_SEL_5XX}[$__rate_interval])) or vector(0))"
    f" / sum(rate({M_LLM_REQUESTS}{_SEL}[$__rate_interval]))"
)


def _dashboard():
    return (
        db.Dashboard("AISIX — Responses→Chat bridge")
        .uid("aisix-bridge")
        .tags(["aisix", "ai-gateway", "responses-api", "llm"])
        .description(
            "AISIX (api7/aisix 1.0.0), the /v1/responses → /v1/chat/completions "
            "bridge deployed behind Envoy AI Gateway. Everything here reads the "
            "aisix_* Prometheus families on :9090 via the converse/aisix "
            "PodMonitor. "
            "`endpoint` is the REQUEST PATH and reaches Mimir only because that "
            "PodMonitor renames the scrape's own port-derived label to "
            "`scrape_endpoint` (ai-helm-values#389) — without that chart change "
            "every 'by operation' panel collapses to one `metrics` series. "
            "Latency comes from the aisix_request_e2e_latency_seconds / "
            "aisix_request_ttft_seconds HISTOGRAMS: the *_duration_seconds "
            "SUMMARIES publish every quantile as 0 in 1.0.0 and must not be "
            "used. Traces for the same component are in Tempo under "
            '`{resource.service.name="aisix-dp"}` — the -dp suffix is '
            "hardcoded upstream and cannot be configured. "
            "Token bill: the bridge is stateless, so a Responses conversation "
            "bills exactly the same tokens as the equivalent chat-completions "
            "conversation; /v1/responses buys API compatibility, not a cheaper "
            "bill. "
            "GENERATED — source: tools/dashboards/src/dashboards/aisix/aisix.py."
        )
        .timezone("browser")
        .editable()
        .tooltip(dm.DashboardCursorSync.CROSSHAIR)
        .refresh("30s")
        .time("now-6h", "now")
        .with_variable(
            db.QueryVariable("model")
            .label("Model")
            .datasource(MIMIR_DS)
            .query(f'label_values({M_LLM_REQUESTS}{{job="{JOB}"}}, model)')
            .refresh(dm.VariableRefresh.ON_TIME_RANGE_CHANGED)
            .sort(dm.VariableSort.ALPHABETICAL_ASC)
            .multi(True)
            .include_all(True)
            .all_value(".+")
            .current(dm.VariableOption(selected=True, text=["All"], value=["$__all"]))
        )
        # ── Health ──────────────────────────────────────────────────────────
        .with_panel(_row("Health", y=0))
        # `up` is deliberately unfiltered by $model: it is the scrape's own
        # report sample and carries no model label. It is also the series the
        # `aisix-down` alert selects on.
        .with_panel(
            _stat_panel(
                title="Replicas up",
                expr=f'sum(up{{job="{JOB}"}}) or vector(0)',
                unit="short",
                thresholds=_thresholds(("red", None), ("orange", 1), ("green", 2)),
                grid=(4, 4, 0, 1),
                description=(
                    "Scraped, answering pods. Red at 0 = the `aisix-down` alert's "
                    "condition. Orange at 1 = running, but with no redundancy."
                ),
            )
        )
        .with_panel(
            _stat_panel(
                title="Requests / min",
                expr=f"sum(rate({M_LLM_REQUESTS}{_SEL}[$__rate_interval])) * 60",
                unit="reqpm",
                thresholds=_thresholds(("green", None)),
                grid=(4, 4, 4, 1),
                decimals=1,
            )
        )
        .with_panel(
            _stat_panel(
                title="5xx ratio",
                expr=_ERROR_RATIO,
                unit="percent",
                thresholds=_thresholds(("green", None), ("orange", 1), ("red", 5)),
                grid=(4, 4, 8, 1),
                decimals=2,
                description=(
                    "Share of AISIX's own responses that were 5xx. Orange at 1 % "
                    "is the `aisix-5xx-ratio` alert's threshold. Blank means no "
                    "traffic in the window, not zero errors."
                ),
            )
        )
        .with_panel(
            _stat_panel(
                title="p95 end-to-end latency",
                expr=(
                    f"histogram_quantile(0.95, sum by (le) "
                    f"(rate({M_E2E_BUCKET}{_SEL}[$__rate_interval])))"
                ),
                unit="s",
                thresholds=_thresholds(("green", None), ("orange", 10), ("red", 30)),
                grid=(4, 4, 12, 1),
                decimals=2,
                description=(
                    "Whole request as AISIX sees it, INCLUDING the upstream "
                    "provider's own generation time — this is not the bridge's "
                    "added latency."
                ),
            )
        )
        .with_panel(
            _stat_panel(
                title="Tokens / min",
                expr=f"sum(rate({M_LLM_TOTAL_TOKENS}{_SEL}[$__rate_interval])) * 60",
                unit="short",
                thresholds=_thresholds(("green", None)),
                grid=(4, 4, 16, 1),
                decimals=0,
            )
        )
        .with_panel(
            _stat_panel(
                title="In-flight requests",
                expr=f'sum(({M_IN_FLIGHT}{{job="{JOB}"}}) or vector(0))',
                unit="short",
                thresholds=_thresholds(("green", None)),
                grid=(4, 4, 20, 1),
                description=(
                    "Gauge, per listener path — carries no `model` label, so the "
                    "$model picker does not apply to it."
                ),
            )
        )
        # ── Traffic by operation ────────────────────────────────────────────
        .with_panel(_row("Traffic — Responses vs chat", y=5))
        .with_panel(
            _timeseries_panel(
                title="Requests / min by operation",
                unit="reqpm",
                grid=(8, 12, 0, 6),
                description=(
                    "`endpoint` is the request path. `/v1/responses` is the "
                    "BRIDGED traffic (codex-style clients); `/v1/chat/completions` "
                    "is a client that came in on the chat shape and was passed "
                    "through. One flat `metrics` series here means the PodMonitor "
                    "relabelling from ai-helm-values#389 is not deployed."
                ),
                targets=[
                    _prom_target(
                        f"sum by (endpoint) (rate({M_LLM_REQUESTS}{_SEL}[$__rate_interval])) * 60",
                        legend="{{endpoint}}",
                    )
                ],
            )
        )
        .with_panel(
            _timeseries_panel(
                title="Requests / min by operation and status",
                unit="reqpm",
                grid=(8, 12, 12, 6),
                targets=[
                    _prom_target(
                        f"sum by (endpoint, status) "
                        f"(rate({M_LLM_REQUESTS}{_SEL}[$__rate_interval])) * 60",
                        legend="{{endpoint}} · {{status}}",
                    )
                ],
            )
        )
        .with_panel(
            _timeseries_panel(
                title="Streaming vs non-streaming, by operation",
                unit="reqpm",
                grid=(8, 24, 0, 14),
                description=(
                    "`stream` is the COUNTER vocabulary. The latency histograms "
                    "spell the same idea `streaming` — they are different label "
                    "names on the same deployment."
                ),
                targets=[
                    _prom_target(
                        f"sum by (endpoint, stream) "
                        f"(rate({M_LLM_REQUESTS}{_SEL}[$__rate_interval])) * 60",
                        legend="{{endpoint}} · stream={{stream}}",
                    )
                ],
            )
        )
        # ── Errors ──────────────────────────────────────────────────────────
        .with_panel(_row("Errors", y=22))
        .with_panel(
            _timeseries_panel(
                title="5xx / min by operation",
                unit="reqpm",
                grid=(8, 12, 0, 23),
                description=(
                    "AISIX's OWN 5xx. A provider-side failure that AISIX reports "
                    "faithfully lands here too — join to the Envoy access log in "
                    'Loki (`{job="envoy-ai-gateway"}`) to tell them apart.'
                ),
                targets=[
                    _prom_target(
                        f"sum by (endpoint) "
                        f"(rate({M_LLM_REQUESTS}{_SEL_5XX}[$__rate_interval])) * 60",
                        legend="{{endpoint}}",
                    )
                ],
            )
        )
        .with_panel(
            _timeseries_panel(
                title="5xx ratio (%)",
                unit="percent",
                grid=(8, 12, 12, 23),
                description="The `aisix-5xx-ratio` alert fires above 1 % for 5 m.",
                targets=[_prom_target(_ERROR_RATIO, legend="5xx %")],
            )
        )
        # ── Latency ─────────────────────────────────────────────────────────
        .with_panel(_row("Latency (histograms — the summaries are broken in 1.0.0)", y=31))
        .with_panel(
            _timeseries_panel(
                title="End-to-end latency p50 / p95 by operation",
                unit="s",
                grid=(8, 12, 0, 32),
                description=(
                    "From `aisix_request_e2e_latency_seconds_bucket`. Includes the "
                    "upstream provider's generation time. Do NOT substitute "
                    "`aisix_request_duration_seconds{quantile=...}`: 1.0.0 "
                    "publishes every one of those quantiles as 0."
                ),
                targets=[
                    _prom_target(
                        f"histogram_quantile(0.50, sum by (le, endpoint) "
                        f"(rate({M_E2E_BUCKET}{_SEL}[$__rate_interval])))",
                        legend="p50 · {{endpoint}}",
                    ),
                    _prom_target(
                        f"histogram_quantile(0.95, sum by (le, endpoint) "
                        f"(rate({M_E2E_BUCKET}{_SEL}[$__rate_interval])))",
                        legend="p95 · {{endpoint}}",
                    ),
                ],
            )
        )
        .with_panel(
            _timeseries_panel(
                title="Time to first token p50 / p95 by operation",
                unit="s",
                grid=(8, 12, 12, 32),
                description=(
                    "Streaming requests only — a non-streaming call has no first "
                    "token to time, so it contributes no observation."
                ),
                targets=[
                    _prom_target(
                        f"histogram_quantile(0.50, sum by (le, endpoint) "
                        f"(rate({M_TTFT_BUCKET}{_SEL}[$__rate_interval])))",
                        legend="p50 · {{endpoint}}",
                    ),
                    _prom_target(
                        f"histogram_quantile(0.95, sum by (le, endpoint) "
                        f"(rate({M_TTFT_BUCKET}{_SEL}[$__rate_interval])))",
                        legend="p95 · {{endpoint}}",
                    ),
                ],
            )
        )
        .with_panel(
            _timeseries_panel(
                title="End-to-end latency p95 by status class",
                unit="s",
                grid=(8, 24, 0, 40),
                description=(
                    "`status_class` (2xx/4xx/5xx) is the histogram's vocabulary; "
                    "the counters use the numeric `status` instead."
                ),
                targets=[
                    _prom_target(
                        f"histogram_quantile(0.95, sum by (le, status_class) "
                        f"(rate({M_E2E_BUCKET}{_SEL}[$__rate_interval])))",
                        legend="p95 · {{status_class}}",
                    )
                ],
            )
        )
        # ── Tokens ──────────────────────────────────────────────────────────
        .with_panel(_row("Tokens", y=48))
        .with_panel(
            _timeseries_panel(
                title="Tokens / min by model",
                unit="short",
                grid=(8, 12, 0, 49),
                description=(
                    "Total tokens (input + output) as AISIX counted them. The "
                    "billed figure is EAIG's, metered from the same response — "
                    "these should agree, and a persistent gap is a bug worth "
                    "filing, not a rounding artefact."
                ),
                targets=[
                    _prom_target(
                        f"sum by (model) (rate({M_LLM_TOTAL_TOKENS}{_SEL}[$__rate_interval])) * 60",
                        legend="{{model}}",
                    )
                ],
            )
        )
        .with_panel(
            _timeseries_panel(
                title="Input / output / cached tokens per minute by model",
                unit="short",
                grid=(8, 12, 12, 49),
                description=(
                    "`cached` is what the PROVIDER reported as a prompt-cache hit. "
                    "On DeepInfra it is 0 on every call today — which is exactly "
                    "why moving to /v1/responses does not make the bill cheaper."
                ),
                targets=[
                    _prom_target(
                        f"sum by (model) (rate({M_LLM_INPUT_TOKENS}{_SEL}[$__rate_interval])) * 60",
                        legend="input · {{model}}",
                    ),
                    _prom_target(
                        f"sum by (model) "
                        f"(rate({M_LLM_OUTPUT_TOKENS}{_SEL}[$__rate_interval])) * 60",
                        legend="output · {{model}}",
                    ),
                    _prom_target(
                        f"sum by (model) "
                        f"(rate({M_LLM_CACHED_INPUT_TOKENS}{_SEL}[$__rate_interval])) * 60",
                        legend="cached input · {{model}}",
                    ),
                ],
            )
        )
        .with_panel(
            _timeseries_panel(
                title="Tokens / min by client",
                unit="short",
                grid=(8, 24, 0, 57),
                description=(
                    "`client_type` is AISIX's own User-Agent classification "
                    "(codex, opencode, curl, other, …) — it is NOT the OAuth "
                    "`azp` the gateway attributes cost by, and the two will "
                    "disagree."
                ),
                targets=[
                    _prom_target(
                        f"sum by (client_type) (rate({M_TOKENS_BY_CLIENT}"
                        f'{{job="{JOB}", model=~"$model", token_type="total"}}'
                        f"[$__rate_interval])) * 60",
                        legend="{{client_type}}",
                    )
                ],
            )
        )
    )


def build() -> dict:
    return json.loads(JSONEncoder(sort_keys=True, indent=2).encode(_dashboard().build()))
