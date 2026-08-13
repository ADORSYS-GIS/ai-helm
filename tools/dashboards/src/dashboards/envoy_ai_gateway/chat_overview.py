"""Envoy AI Gateway — chat overview, Phoenix-style (GENERATED SOURCE).

The "what are people chatting about right now" board — the LLM completions
half of the gateway's traffic (embeddings excluded). Its POINT is the live
**Tempo trace feed**: the AI Gateway ext-proc has been emitting full-content
OpenInference spans to Tempo all along (`OTEL_EXPORTER_OTLP_ENDPOINT`,
gateway-config.yaml — see ADR-0077), so each trace here is one real chat you
can click open to read the full prompt/response (llm.input_messages.* /
llm.output_messages.*), token counts, model, and latency. That's the thing no
other dashboard shows.

Deliberately does NOT re-plot per-model request/cost breakdowns — those already
live in `cost-by-model` and `actor-consumption`. This board keeps only a thin
headline row + a latency view (chat-experience signal, not a cost signal) as
context above the trace feed, to avoid duplicating the cost dashboards.

Repointed to Mimir (ADR-0058): the chats/tokens/cost headline stats and the
latency view read the precomputed ``loki_process_custom_gen_ai_*`` counters +
the ``gen_ai_usage_duration`` histogram via PromQL — instant at any range on
the rate-limited object store. Only the 5xx error-rate panel stays on Loki
(response_code is deliberately not a Mimir metric label). The trace feed stays
on Tempo (it's trace data, not metrics).

The JSON file is regenerated from this module — do **not** hand-edit it::

    uv run dashboards build

ADR: docs/adr/0077-phoenix-style-chat-dashboards.md (+ ADR-0002, ADR-0008).
"""

from __future__ import annotations

import json

from grafana_foundation_sdk.builders import common as cb
from grafana_foundation_sdk.builders import dashboard as db
from grafana_foundation_sdk.builders import loki, stat, tempo, timeseries
from grafana_foundation_sdk.cog.encoder import JSONEncoder
from grafana_foundation_sdk.models import common as cm
from grafana_foundation_sdk.models import dashboard as dm

from dashboards._common import (
    EMBEDDING_MODEL_KEYS,
    GATEWAY_SERVICE_NAME,
    LABEL_MODEL,
    LOKI_UID,
    METRIC_COST_MICRO_USD,
    METRIC_DURATION,
    METRIC_REQUESTS,
    METRIC_TOKENS,
    TEMPO_SERVICE_NAME,
    TEMPO_UID,
)
from dashboards.envoy_ai_gateway import _shared as sh

OUTPUT_PATH: str = "charts/observability-dashboards/files/envoy-ai-gateway/chat-overview.json"

_LOKI_DS = dm.DataSourceRef(type_val="loki", uid=LOKI_UID)
_TEMPO_DS = dm.DataSourceRef(type_val="tempo", uid=TEMPO_UID)
_MIMIR_DS = dm.DataSourceRef(type_val="prometheus", uid=sh.MIMIR_DS.uid)

# Excludes embedding-model traffic on the Mimir side (Loki has no span-kind
# concept — that's Tempo/OpenInference-only; see EMBEDDING_MODEL_KEYS docstring).
_NOT_EMBEDDING = "|".join(EMBEDDING_MODEL_KEYS)
_MIMIR_SEL = sh.selector(f'{LABEL_MODEL}!~"{_NOT_EMBEDDING}"')

# Loki selector for the 5xx error-rate panel (response_code is body-only).
_LOKI_SEL = f'{{service_name="{GATEWAY_SERVICE_NAME}", {LABEL_MODEL}!~"{_NOT_EMBEDDING}"}}'

# TraceQL: chat completions only (excludes EMBEDDING-kind spans). Scoped to the
# gateway's own OTel resource name — a DIFFERENT string than the Loki anchor
# above (TEMPO_SERVICE_NAME docstring, _common.py).
_TRACEQL_CHATS = (
    f'{{ resource.service.name = "{TEMPO_SERVICE_NAME}" && span.openinference.span.kind = "LLM" }}'
)


def _loki_target(expr: str, *, legend: str = "", ref_id: str = "A") -> loki.Dataquery:
    # Range query (never instant) — the Loki plugin doesn't substitute $__range
    # in instant queries (jwt_tokens.py / per_user.py learned this the hard way).
    q = loki.Dataquery().expr(expr).ref_id(ref_id).query_type("range").datasource(_LOKI_DS)
    return q.legend_format(legend) if legend else q


def _thresholds(color: str) -> db.ThresholdsConfig:
    return db.ThresholdsConfig().mode(dm.ThresholdsMode.ABSOLUTE).steps([dm.Threshold(color=color)])


# --- thin headline row (context only, not per-model breakdowns) -------------


def _panel_chats() -> object:
    return sh.stat_panel(
        title="Chats (range)",
        expr=f"sum(increase({METRIC_REQUESTS}{_MIMIR_SEL}[$__range]))",
        unit="short",
        color="blue",
        grid=(4, 6, 0, 1),
    )


def _panel_tokens() -> object:
    return sh.stat_panel(
        title="Tokens (range)",
        expr=f"sum(increase({METRIC_TOKENS}{_MIMIR_SEL}[$__range]))",
        unit="short",
        color="green",
        grid=(4, 6, 6, 1),
    )


def _panel_cost() -> object:
    return sh.stat_panel(
        title="Cost (range)",
        expr=sh.usd(f"sum(increase({METRIC_COST_MICRO_USD}{_MIMIR_SEL}[$__range]))"),
        unit="currencyUSD",
        color="orange",
        grid=(4, 6, 12, 1),
    )


def _panel_error_rate() -> stat.Panel:
    # response_code is deliberately NOT a Mimir metric label (bounded ~15 values
    # but multiplying it onto every stream is what the per-user-observability
    # doc avoided). So the 5xx error-rate stays on Loki — a single small panel.
    total = f"sum(count_over_time({_LOKI_SEL}[$__range]))"
    errors = f'sum(count_over_time({_LOKI_SEL} | json | response_code=~"5.."[$__range]))'
    return (
        stat.Panel()
        .title("Errors — 5xx (range)")
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=4, w=6, x=18, y=1))
        .unit("percent")
        .thresholds(
            db.ThresholdsConfig()
            .mode(dm.ThresholdsMode.ABSOLUTE)
            .steps(
                [
                    dm.Threshold(color="green", value=None),
                    dm.Threshold(color="orange", value=1),
                    dm.Threshold(color="red", value=5),
                ]
            )
        )
        .reduce_options(cb.ReduceDataOptions().calcs(["lastNotNull"]).fields("").values(False))
        .text_mode(cm.BigValueTextMode.AUTO)
        .color_mode(cm.BigValueColorMode.VALUE)
        .graph_mode(cm.BigValueGraphMode.AREA)
        .with_target(_loki_target(f"100 * ({errors}) / ({total})"))
    )


# --- latency (chat-experience signal, distinct from the cost dashboards) -----


def _latency_quantile(q: float) -> str:
    # Reads the ADR-0058 latency histogram from Mimir. Fixed [5m] window — NOT
    # [$__auto]: the auto step for a 6h range is ~21s, which is < the 60s
    # scrape interval, so rate()[<60s] has <2 samples → silent "no data" (same
    # trap as the per-user requests panel). [5m] holds ~5 samples.
    return (
        f"histogram_quantile({q}, sum by (le) "
        f"(rate({METRIC_DURATION}_bucket{_MIMIR_SEL}[5m])))"
    )


def _panel_latency() -> timeseries.Panel:
    return (
        timeseries.Panel()
        .title("Chat latency (p50 / p95)")
        .datasource(_MIMIR_DS)
        .grid_pos(dm.GridPos(h=8, w=24, x=0, y=6))
        .unit("ms")
        .draw_style(cm.GraphDrawStyle.LINE)
        .line_interpolation(cm.LineInterpolation.SMOOTH)
        .fill_opacity(10.0)
        .show_points(cm.VisibilityMode.NEVER)
        .legend(
            cb.VizLegendOptions().display_mode(cm.LegendDisplayMode.LIST).calcs(["mean", "max"])
        )
        .tooltip(cb.VizTooltipOptions().mode(cm.TooltipDisplayMode.MULTI))
        .with_target(
            sh.prom_target(_latency_quantile(0.50), legend="p50", ref_id="A", instant=False)
        )
        .with_target(
            sh.prom_target(_latency_quantile(0.95), legend="p95", ref_id="B", instant=False)
        )
    )


# --- the point of this board: live chat traces -------------------------------


def _panel_recent_chats() -> db.Panel:
    # No dedicated SDK builder for the Tempo trace-list panel (same gap
    # scoreboard.py hit) — base Panel type="traces" + a raw TraceQL search.
    # Click a trace to see the full request/response content Grafana's native
    # span-detail view already renders (llm.input_messages.*/output_messages.*,
    # token counts, model, latency) — no custom table/select() needed.
    query = tempo.TempoQuery().query_type("traceql").query(_TRACEQL_CHATS).limit(50).ref_id("A")
    return (
        db.Panel()
        .type("traces")
        .title("Recent chats — click a trace to read the full prompt & response")
        .description(
            "Live chat-completion spans from Tempo (embeddings excluded). Each "
            "trace is one chat request — open it to see the full OpenInference "
            "content (llm.input_messages/output_messages), token counts, model, "
            "and latency. This is the Phoenix-style piece; unattributed to a "
            "user by design (ADR-0077)."
        )
        .datasource(_TEMPO_DS)
        .grid_pos(dm.GridPos(h=20, w=24, x=0, y=14))
        .with_target(query)
    )


_DESCRIPTION = (
    "Global chat-completion overview (embeddings excluded). The point is the "
    "live Tempo trace feed — click any trace to read the full prompt/response "
    "content the AI Gateway ext-proc already sends to Tempo (ADR-0077). The "
    "headline stats + latency read the precomputed Mimir metrics (ADR-0058) — "
    "instant at any range; only the 5xx error-rate stays on Loki. Per-model "
    "request/cost breakdowns deliberately live in the cost-by-model / "
    "actor-consumption dashboards, not here. No input variables by design; see "
    "chats-by-user for a per-user cut. "
    "GENERATED — source: tools/dashboards/envoy_ai_gateway/chat_overview.py."
)


def _dashboard() -> db.Dashboard:
    return (
        db.Dashboard("AI Gateway — chat overview")
        .uid("envoy-ai-gateway-chat-overview")
        .tags(["ai-gateway", "chats", "tempo", "phoenix"])
        .description(_DESCRIPTION)
        .timezone("browser")
        .editable()
        .tooltip(dm.DashboardCursorSync.CROSSHAIR)
        .refresh("30s")
        .time("now-6h", "now")
        .with_panel(sh.row("Overview", y=0))
        .with_panel(_panel_chats())
        .with_panel(_panel_tokens())
        .with_panel(_panel_cost())
        .with_panel(_panel_error_rate())
        .with_panel(sh.row("Latency", y=5))
        .with_panel(_panel_latency())
        .with_panel(sh.row("Recent chats (live)", y=13))
        .with_panel(_panel_recent_chats())
    )


def build() -> dict:
    return json.loads(json.dumps(_dashboard().build(), cls=JSONEncoder))
