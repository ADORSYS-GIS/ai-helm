"""Envoy AI Gateway — chats by user (GENERATED SOURCE).

Pick a person (from the Keycloak directory) and see THEIR chat requests. The
`$user` picker is a raw-SQL query variable against the read-only Keycloak
Postgres datasource (ADR-0063) — so the dropdown lists real people by name,
independent of who happens to have recent traffic, and doesn't depend on a
token having carried the email claim.

Two views of the selected person's activity:
  1. **This user's chats (content)** — a Tempo trace feed filtered by
     `span.user.email = "$user"`. Each trace is one real chat; open it to read
     the full prompt/response (llm.input_messages.* / llm.output_messages.*).
     This works because the ext-proc now stamps the Keycloak identity onto its
     OpenInference spans (`spanRequestHeaderAttributes`, ADR-0078 — which
     supersedes ADR-0077's decision to skip it). Confirmed there is no other
     way: a live span carries full content but no identity and no key to join
     to the user-bearing Loki logs, so tagging the span is the only mechanism.
  2. **Per-request log** (Loki, newest first) — one line per chat with model /
     status / tokens / cost / latency, filtered to the person's `email` label.
     The itemised "what did they run, and when" — distinct from the per_user /
     actor-consumption rollup charts.

⚠️ The trace feed shows **"No data" until the ai-helm-values
`spanRequestHeaderAttributes` change deploys and new ext-proc pods roll**
(ADR-0078); the Loki log + stats work immediately.

The JSON file is regenerated from this module — do **not** hand-edit it::

    uv run dashboards build

ADR: docs/adr/0078-per-user-span-attribution-for-chat-content.md (+ ADR-0063, ADR-0008).
"""

from __future__ import annotations

import json

from grafana_foundation_sdk.builders import common as cb
from grafana_foundation_sdk.builders import dashboard as db
from grafana_foundation_sdk.builders import logs, loki, stat, tempo
from grafana_foundation_sdk.cog.encoder import JSONEncoder
from grafana_foundation_sdk.models import common as cm
from grafana_foundation_sdk.models import dashboard as dm

from dashboards._common import (
    CAMER_DIGITAL_REALM_ID,
    EMBEDDING_MODEL_KEYS,
    GATEWAY_SERVICE_NAME,
    KEYCLOAK_UID,
    LABEL_EMAIL,
    LABEL_MODEL,
    LOKI_UID,
    TEMPO_SERVICE_NAME,
    TEMPO_UID,
)
from dashboards.envoy_ai_gateway import _shared as sh

OUTPUT_PATH: str = "charts/observability-dashboards/files/envoy-ai-gateway/chats-by-user.json"

_LOKI_DS = dm.DataSourceRef(type_val="loki", uid=LOKI_UID)
_TEMPO_DS = dm.DataSourceRef(type_val="tempo", uid=TEMPO_UID)
_KEYCLOAK_DS = dm.DataSourceRef(type_val="postgres", uid=KEYCLOAK_UID)

# TraceQL: this user's chat completions (excludes EMBEDDING spans). span.user.email
# is stamped by the ext-proc's spanRequestHeaderAttributes mapping (ADR-0078);
# the $user variable value IS the email (the picker's __value). resource.service.name
# is the gateway's OTel name — TEMPO_SERVICE_NAME (a different string than the Loki
# anchor, see _common.py).
_TRACEQL_USER_CHATS = (
    f'{{ resource.service.name = "{TEMPO_SERVICE_NAME}" '
    f'&& span.openinference.span.kind = "LLM" '
    f'&& span.user.email = "$user" }}'
)

_NOT_EMBEDDING = "|".join(EMBEDDING_MODEL_KEYS)
# Exact match on the selected email (single-select variable, no regex needed).
_LOKI_SEL = (
    f'{{service_name="{GATEWAY_SERVICE_NAME}", {LABEL_EMAIL}="$user", '
    f'{LABEL_MODEL}!~"{_NOT_EMBEDDING}"}}'
)

# Keycloak directory query for the $user picker. `__text`/`__value` are
# Grafana's special column aliases for SQL-backed variable queries: the
# dropdown shows __text, the query filters use __value. No user input is
# interpolated into this SQL (only the constant realm id) — the SELECTED value
# only ever reaches a Loki label matcher below, never another raw SQL string,
# so there's no SQL-injection surface from a manipulated `?var-user=` param.
_USER_VAR_SQL = (
    "SELECT DISTINCT email AS __value, "
    "COALESCE(NULLIF(TRIM(COALESCE(first_name, '') || ' ' || COALESCE(last_name, '')), ''), username)"
    " || ' (' || email || ')' AS __text "
    "FROM user_entity "
    f"WHERE realm_id = '{CAMER_DIGITAL_REALM_ID}' AND email IS NOT NULL "
    "ORDER BY __text"
)

_JSON_TOKENS = 'tokens=`["gen_ai.usage.total_tokens"]`'
_JSON_COST = 'cost=`["gen_ai.usage.custom_total_cost"]`'


def _user_var() -> db.QueryVariable:
    # ⚠️ For a Postgres (SQL) datasource, the variable's query model MUST carry
    # `rawSql` — the generic `{query: "..."}` shape leaves the datasource with
    # no SQL to run ("error when executing the sql query"). Mirror the proven
    # panel-target shape from user_directory.py (rawSql / rawQuery / format).
    return (
        db.QueryVariable("user")
        .label("User (Keycloak)")
        .datasource(_KEYCLOAK_DS)
        .query(
            {
                "refId": "KeycloakUsers",
                "rawSql": _USER_VAR_SQL,
                "rawQuery": True,
                "format": "table",
                "editorMode": "code",
            }
        )
        .refresh(dm.VariableRefresh.ON_DASHBOARD_LOAD)
        .sort(dm.VariableSort.ALPHABETICAL_ASC)
        .multi(False)
        .include_all(False)
    )


def _loki_target(expr: str, *, legend: str = "", ref_id: str = "A") -> loki.Dataquery:
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


# --- thin per-user headline row ---------------------------------------------


def _panel_chats() -> stat.Panel:
    return _stat(
        title="Chats (range)",
        expr=f"sum(count_over_time({_LOKI_SEL}[$__range]))",
        unit="short",
        color="blue",
        grid=(4, 8, 0, 1),
    )


def _panel_tokens() -> stat.Panel:
    return _stat(
        title="Tokens (range)",
        expr=f'sum(sum_over_time({_LOKI_SEL} | json {_JSON_TOKENS} | unwrap tokens | __error__="" [$__range]))',
        unit="short",
        color="green",
        grid=(4, 8, 8, 1),
    )


def _panel_cost() -> stat.Panel:
    inner = f'sum(sum_over_time({_LOKI_SEL} | json {_JSON_COST} | unwrap cost | __error__="" [$__range]))'
    return _stat(
        title="Cost (range)",
        expr=f"(({inner}) / 1e6)",
        unit="currencyUSD",
        color="orange",
        grid=(4, 8, 16, 1),
    )


# --- hero 1: this user's actual chats (content, from Tempo) ------------------


def _panel_user_chats() -> db.Panel:
    # Base Panel type="traces" + a raw TraceQL search (no dedicated SDK builder —
    # same gap scoreboard.py/chat_overview.py hit). Filtered to the selected
    # person via span.user.email (stamped by the ext-proc, ADR-0078). Click a
    # trace to read the full prompt/response Grafana's native span view renders.
    query = (
        tempo.TempoQuery().query_type("traceql").query(_TRACEQL_USER_CHATS).limit(50).ref_id("A")
    )
    return (
        db.Panel()
        .type("traces")
        .title("$user's chats — click a trace to read the full prompt & response")
        .description(
            "This person's chat-completion traces (embeddings excluded). Open "
            "one to read the full OpenInference content (llm.input_messages / "
            "output_messages), token counts, model, latency. Filtered via "
            "span.user.email, stamped by the ext-proc (ADR-0078). ⚠️ 'No data' "
            "until the ai-helm-values spanRequestHeaderAttributes change deploys "
            "and new ext-proc pods roll — the request log below works meanwhile."
        )
        .datasource(_TEMPO_DS)
        .grid_pos(dm.GridPos(h=16, w=24, x=0, y=5))
        .with_target(query)
    )


# --- hero 2: this user's individual chat requests (metadata, from Loki) ------


def _panel_request_log() -> logs.Panel:
    # One line per request, newest first — the itemised "what did they run".
    # line_format renders: model · status · tokens · cost($) · latency(ms).
    line_fmt = (
        "{{.gen_ai_request_model}} · rc={{.response_code}} · "
        "{{.gen_ai_usage_total_tokens}}tok · {{.gen_ai_usage_custom_total_cost}}µ$ · "
        "{{.duration}}ms"
    )
    expr = f"{_LOKI_SEL} | json | line_format `{line_fmt}`"
    return (
        logs.Panel()
        .title("$user's requests — metadata log (newest first)")
        .description(
            "One row per chat request for the selected user (Loki access log): "
            "model, status, tokens, cost, latency. Works immediately (doesn't "
            "wait on the span-attribution deploy). For the actual content, use "
            "the trace panel above."
        )
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=14, w=24, x=0, y=21))
        .show_time(True)
        .show_labels(False)
        .wrap_log_message(True)
        .enable_log_details(True)
        .sort_order(cm.LogsSortOrder.DESCENDING)
        .with_target(_loki_target(expr))
    )


_DESCRIPTION = (
    "Per-user chats (embeddings excluded). The $user picker is sourced from a "
    "read-only Postgres datasource onto the Keycloak DB (ADR-0063), so it lists "
    "real people regardless of recent traffic. Two views: a Tempo trace feed "
    "filtered by span.user.email (click a trace to read the full prompt/"
    "response — ADR-0078), and an itemised per-request metadata log from Loki. "
    "⚠️ The trace feed shows 'No data' until the ai-helm-values "
    "spanRequestHeaderAttributes change deploys; the Loki log works immediately. "
    "GENERATED — source: tools/dashboards/envoy_ai_gateway/chats_by_user.py."
)


def _dashboard() -> db.Dashboard:
    return (
        db.Dashboard("AI Gateway — chats by user")
        .uid("envoy-ai-gateway-chats-by-user")
        .tags(["ai-gateway", "chats", "per-user", "keycloak", "tempo"])
        .description(_DESCRIPTION)
        .timezone("browser")
        .editable()
        .tooltip(dm.DashboardCursorSync.CROSSHAIR)
        .refresh("30s")
        .time("now-6h", "now")
        .with_variable(_user_var())
        .with_panel(sh.row("Chats — $user", y=0))
        .with_panel(_panel_chats())
        .with_panel(_panel_tokens())
        .with_panel(_panel_cost())
        .with_panel(_panel_user_chats())
        .with_panel(_panel_request_log())
    )


def build() -> dict:
    return json.loads(json.dumps(_dashboard().build(), cls=JSONEncoder))
