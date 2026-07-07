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
    TEMPO_SERVICE_NAME,
    TEMPO_UID,
)
from dashboards.envoy_ai_gateway import _shared as sh

OUTPUT_PATH: str = "charts/observability-dashboards/files/envoy-ai-gateway/chat-overview.json"

_LOKI_DS = dm.DataSourceRef(type_val="loki", uid=LOKI_UID)
_TEMPO_DS = dm.DataSourceRef(type_val="tempo", uid=TEMPO_UID)

# Excludes embedding-model traffic on the Loki side (Loki has no span-kind
# concept — that's Tempo/OpenInference-only; see EMBEDDING_MODEL_KEYS docstring).
_NOT_EMBEDDING = "|".join(EMBEDDING_MODEL_KEYS)
_LOKI_SEL = f'{{service_name="{GATEWAY_SERVICE_NAME}", {LABEL_MODEL}!~"{_NOT_EMBEDDING}"}}'

# TraceQL: chat completions only (excludes EMBEDDING-kind spans). Scoped to the
# gateway's own OTel resource name — a DIFFERENT string than the Loki anchor
# above (TEMPO_SERVICE_NAME docstring, _common.py).
_TRACEQL_CHATS = (
    f'{{ resource.service.name = "{TEMPO_SERVICE_NAME}" && span.openinference.span.kind = "LLM" }}'
)

_JSON_TOKENS = 'tokens=`["gen_ai.usage.total_tokens"]`'
_JSON_COST = 'cost=`["gen_ai.usage.custom_total_cost"]`'


def _loki_target(expr: str, *, legend: str = "", ref_id: str = "A") -> loki.Dataquery:
    # Range query (never instant) — the Loki plugin doesn't substitute $__range
    # in instant queries (jwt_tokens.py / per_user.py learned this the hard way).
    q = loki.Dataquery().expr(expr).ref_id(ref_id).query_type("range").datasource(_LOKI_DS)
    return q.legend_format(legend) if legend else q


def _thresholds(color: str) -> db.ThresholdsConfig:
    return db.ThresholdsConfig().mode(dm.ThresholdsMode.ABSOLUTE).steps([dm.Threshold(color=color)])


def _stat(
    *, title: str, expr: str, unit: str, color: str, grid: tuple[int, int, int, int]
) -> stat.Panel:
    h, w, x, y = grid
    return (
        stat.Panel()
        .title(title)
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=h, w=w, x=x, y=y))
        .unit(unit)
        .thresholds(_thresholds(color))
        .reduce_options(cb.ReduceDataOptions().calcs(["lastNotNull"]).fields("").values(False))
        .text_mode(cm.BigValueTextMode.AUTO)
        .color_mode(cm.BigValueColorMode.VALUE)
        .graph_mode(cm.BigValueGraphMode.AREA)
        .with_target(_loki_target(expr))
    )


# --- thin headline row (context only, not per-model breakdowns) --------------


def _panel_chats() -> stat.Panel:
    return _stat(
        title="Chats (range)",
        expr=f"sum(count_over_time({_LOKI_SEL}[$__range]))",
        unit="short",
        color="blue",
        grid=(4, 6, 0, 1),
    )


def _panel_tokens() -> stat.Panel:
    return _stat(
        title="Tokens (range)",
        expr=f'sum(sum_over_time({_LOKI_SEL} | json {_JSON_TOKENS} | unwrap tokens | __error__="" [$__range]))',
        unit="short",
        color="green",
        grid=(4, 6, 6, 1),
    )


def _panel_cost() -> stat.Panel:
    inner = f'sum(sum_over_time({_LOKI_SEL} | json {_JSON_COST} | unwrap cost | __error__="" [$__range]))'
    return _stat(
        title="Cost (range)",
        expr=f"(({inner}) / 1e6)",
        unit="currencyUSD",
        color="orange",
        grid=(4, 6, 12, 1),
    )


def _panel_error_rate() -> stat.Panel:
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


def _panel_latency() -> timeseries.Panel:
    unwrap = f'{_LOKI_SEL} | json | unwrap duration | __error__=""'
    p50 = f"quantile_over_time(0.50, {unwrap} [$__auto]) by ()"
    p95 = f"quantile_over_time(0.95, {unwrap} [$__auto]) by ()"
    return (
        timeseries.Panel()
        .title("Chat latency (p50 / p95)")
        .datasource(_LOKI_DS)
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
        .with_target(_loki_target(p50, legend="p50", ref_id="A"))
        .with_target(_loki_target(p95, legend="p95", ref_id="B"))
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
    "headline stats + latency are thin context; per-model request/cost "
    "breakdowns deliberately live in the cost-by-model / actor-consumption "
    "dashboards, not here. No input variables by design; see chats-by-user for "
    "a per-user cut. "
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
