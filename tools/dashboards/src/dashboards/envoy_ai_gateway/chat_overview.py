"""Envoy AI Gateway — chat overview, Phoenix-style (GENERATED SOURCE).

A global, no-input "what's going on with chats right now" view — the LLM
completions half of the gateway's traffic, embeddings deliberately excluded
(see EMBEDDING_MODEL_KEYS). Two data sources:

  1. Aggregate volume/cost/token/error/latency panels, same Loki access-log
     body + precomputed Mimir metrics (ADR-0046/0058) every other
     envoy_ai_gateway dashboard reads.
  2. A live Tempo "recent traces" panel — the actual Phoenix-like piece. The
     AI Gateway ext-proc has been emitting full-content OpenInference spans
     (`openinference.span.kind`, `llm.input_messages.*`, `llm.output_messages.*`,
     `llm.token_count.*`) to Tempo all along via `OTEL_EXPORTER_OTLP_ENDPOINT`
     (gateway-config.yaml) — nobody built this deliberately, it's a side effect
     of that env var, and it was undocumented until ADR-0077. Click a trace to
     see the full request/response content Grafana's native trace view already
     renders; no custom table/column-selection needed (same `type="traces"`
     panel scoreboard.py already uses, just scoped to span.kind=LLM instead of
     match-all).

⚠️ No `user.id`/`session.id` span attributes exist yet (as of ADR-0077) — the
trace panel here shows every chat, unattributed. See chats_by_user.py for the
per-user cut, which depends on the ai-helm-values span-attribution wiring.

The JSON file is regenerated from this module — do **not** hand-edit it::

    uv run dashboards build

ADR: docs/adr/0077-phoenix-style-chat-dashboards.md (+ ADR-0008, ADR-0002).
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
    METRIC_REQUESTS,
    METRIC_TOKENS,
    TEMPO_SERVICE_NAME,
    TEMPO_UID,
)
from dashboards.envoy_ai_gateway import _shared as sh

OUTPUT_PATH: str = "charts/observability-dashboards/files/envoy-ai-gateway/chat-overview.json"

_LOKI_DS = dm.DataSourceRef(type_val="loki", uid=LOKI_UID)
_TEMPO_DS = dm.DataSourceRef(type_val="tempo", uid=TEMPO_UID)

# Excludes embedding-model traffic on the Loki/Mimir side (no span-kind concept
# there — see EMBEDDING_MODEL_KEYS docstring in _common.py).
_NOT_EMBEDDING = "|".join(EMBEDDING_MODEL_KEYS)
_MIMIR_SEL = sh.selector(f'{LABEL_MODEL}!~"{_NOT_EMBEDDING}"')
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


# --- stats (Loki/Mimir aggregates) -------------------------------------------


def _panel_requests() -> stat.Panel:
    return sh.stat_panel(
        title="Chat requests (range)",
        expr=f"sum(increase({METRIC_REQUESTS}{_MIMIR_SEL}[$__range]))",
        unit="short",
        color="blue",
        grid=(4, 6, 0, 1),
    )


def _panel_tokens() -> stat.Panel:
    return sh.stat_panel(
        title="Total tokens (range)",
        expr=f"sum(increase({METRIC_TOKENS}{_MIMIR_SEL}[$__range]))",
        unit="short",
        color="green",
        grid=(4, 6, 6, 1),
    )


def _panel_cost() -> stat.Panel:
    return sh.stat_panel(
        title="Total cost (range)",
        expr=sh.usd(f"sum(increase({METRIC_COST_MICRO_USD}{_MIMIR_SEL}[$__range]))"),
        unit="currencyUSD",
        color="orange",
        grid=(4, 6, 12, 1),
    )


def _panel_error_rate() -> stat.Panel:
    total = f"sum(count_over_time({_LOKI_SEL}[$__range]))"
    errors = f'sum(count_over_time({_LOKI_SEL} | json | response_code=~"5.."[$__range]))'
    return (
        stat.Panel()
        .title("Error rate — 5xx (range)")
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


# --- trends --------------------------------------------------------------


def _panel_requests_by_model() -> timeseries.Panel:
    return sh.daily_bars_panel(
        title="Requests/day by model",
        expr=f"sum by ({LABEL_MODEL}) (increase({METRIC_REQUESTS}{_MIMIR_SEL}[1d]))",
        legend=f"{{{{{LABEL_MODEL}}}}}",
        unit="short",
        grid=(9, 12, 0, 6),
    )


def _panel_cost_by_model() -> timeseries.Panel:
    return sh.daily_bars_panel(
        title="Cost/day by model",
        expr=sh.usd(f"sum by ({LABEL_MODEL}) (increase({METRIC_COST_MICRO_USD}{_MIMIR_SEL}[1d]))"),
        legend=f"{{{{{LABEL_MODEL}}}}}",
        unit="currencyUSD",
        grid=(9, 12, 12, 6),
    )


def _panel_requests_pie():
    return sh.pie_panel(
        title="Requests by model (range)",
        expr=f"topk(10, sum by ({LABEL_MODEL}) (increase({METRIC_REQUESTS}{_MIMIR_SEL}[$__range])))",
        legend_label=f"{{{{{LABEL_MODEL}}}}}",
        grid=(9, 8, 0, 15),
    )


def _panel_cost_bargauge():
    return sh.bargauge_panel(
        title="Cost by model (range)",
        expr=sh.usd(
            f"topk(10, sum by ({LABEL_MODEL}) (increase({METRIC_COST_MICRO_USD}{_MIMIR_SEL}[$__range])))"
        ),
        legend=f"{{{{{LABEL_MODEL}}}}}",
        unit="currencyUSD",
        color="orange",
        grid=(9, 8, 8, 15),
    )


def _panel_p95_latency() -> timeseries.Panel:
    expr = f'quantile_over_time(0.95, {_LOKI_SEL} | json | unwrap duration | __error__="" [$__auto]) by ()'
    return (
        timeseries.Panel()
        .title("P95 gateway latency")
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=9, w=8, x=16, y=15))
        .unit("ms")
        .draw_style(cm.GraphDrawStyle.LINE)
        .line_interpolation(cm.LineInterpolation.SMOOTH)
        .fill_opacity(15.0)
        .show_points(cm.VisibilityMode.NEVER)
        .legend(
            cb.VizLegendOptions().display_mode(cm.LegendDisplayMode.LIST).calcs(["mean", "max"])
        )
        .tooltip(cb.VizTooltipOptions().mode(cm.TooltipDisplayMode.MULTI))
        .with_target(_loki_target(expr, legend="P95"))
    )


# --- live trace feed -----------------------------------------------------


def _panel_recent_chats() -> db.Panel:
    # No dedicated SDK builder for the Tempo trace-list panel (same gap
    # scoreboard.py hit) — base Panel type="traces" + a raw TraceQL search.
    # Click a trace to see the full request/response content Grafana's native
    # span-detail view already renders (llm.input_messages.*/output_messages.*,
    # token counts, model, latency) — no custom table/select() needed.
    query = tempo.TempoQuery().query_type("traceql").query(_TRACEQL_CHATS).limit(40).ref_id("A")
    return (
        db.Panel()
        .type("traces")
        .title("Recent chats (click a trace for the full prompt/response)")
        .description(
            "Live chat-completion spans from Tempo (embeddings excluded). Each "
            "trace is one gateway request — open it to see the full "
            "OpenInference content (llm.input_messages/output_messages), token "
            "counts, model, and latency breakdown. Unattributed to a user until "
            "the span-attribution wiring lands (ADR-0077) — see chats_by_user.py."
        )
        .datasource(_TEMPO_DS)
        .grid_pos(dm.GridPos(h=16, w=24, x=0, y=24))
        .with_target(query)
    )


_DESCRIPTION = (
    "Global chat-completion overview (embeddings excluded) — the Phoenix-style "
    "'what's going on' view. Volume/cost/token/error/latency aggregates come "
    "from the same Loki access-log body + precomputed Mimir metrics as the "
    "other envoy_ai_gateway dashboards (ADR-0046/0058); the live trace feed "
    "reads the AI Gateway ext-proc's OpenInference spans straight from Tempo "
    "(full request/response content per trace — click to open). No input "
    "variables by design; see chats_by_user.py for a per-user cut. "
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
        .with_panel(sh.row("Chat overview", y=0))
        .with_panel(_panel_requests())
        .with_panel(_panel_tokens())
        .with_panel(_panel_cost())
        .with_panel(_panel_error_rate())
        .with_panel(sh.row("Trends", y=5))
        .with_panel(_panel_requests_by_model())
        .with_panel(_panel_cost_by_model())
        .with_panel(_panel_requests_pie())
        .with_panel(_panel_cost_bargauge())
        .with_panel(_panel_p95_latency())
        .with_panel(sh.row("Recent chats (live)", y=23))
        .with_panel(_panel_recent_chats())
    )


def build() -> dict:
    return json.loads(json.dumps(_dashboard().build(), cls=JSONEncoder))
