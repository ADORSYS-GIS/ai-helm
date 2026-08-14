"""Envoy AI Gateway — chats by user (GENERATED SOURCE).

Pick a person (from the Keycloak directory) and see THEIR chat requests. The
`$user` picker is a raw-SQL query variable against the read-only Keycloak
Postgres datasource (ADR-0063) — so the dropdown lists real people by name,
independent of who happens to have recent traffic, and doesn't depend on a
token having carried the email claim.

The hero is a **per-request log** (Loki, newest first): one line per chat
request with model / status / tokens / cost / latency, filtered to the
selected person's `email` label. No existing dashboard shows this — per_user
and actor-consumption are rollup charts; this is the itemised "what did Sarah
actually run, and when" list.

Repointed to Mimir (ADR-0058): the chats/tokens/cost headline stats read the
precomputed ``loki_process_custom_gen_ai_*`` counters via PromQL — instant at
any range. The per-request log panel stays on Loki (it's a log listing; Mimir
stores metrics, not individual log lines).

⚠️ **This shows request METADATA, not the prompt/response CONTENT** — and that
is now a *confirmed structural* limit, not a choice (ADR-0079, superseding
ADR-0078). The chat content lives in Tempo (OpenInference spans), but those
spans carry no user identity and no key to join to the user-bearing Loki logs.
Stamping identity onto the span needs the AI Gateway ext-proc to see
Authorino's `x-oidc-*` headers — but the live filter chain proved the AIEG
ext-proc runs as HTTP filter #1, *before* Authorino's ext_authz, so those
headers don't exist yet when it builds the span. The `spanRequestHeaderAttributes`
mapping was tried end-to-end and produced nothing; it was reverted. To read
actual chat content, use the global `chat-overview` trace feed.

The JSON file is regenerated from this module — do **not** hand-edit it::

    uv run dashboards build

ADR: docs/adr/0079-per-user-span-attribution-not-viable.md (+ ADR-0063, ADR-0008).
"""

from __future__ import annotations

import json

from grafana_foundation_sdk.builders import dashboard as db
from grafana_foundation_sdk.builders import logs, loki
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
    METRIC_COST_MICRO_USD,
    METRIC_REQUESTS,
    METRIC_TOKENS,
)
from dashboards.envoy_ai_gateway import _shared as sh

OUTPUT_PATH: str = "charts/observability-dashboards/files/envoy-ai-gateway/chats-by-user.json"

_LOKI_DS = dm.DataSourceRef(type_val="loki", uid=LOKI_UID)
_KEYCLOAK_DS = dm.DataSourceRef(type_val="postgres", uid=KEYCLOAK_UID)

_NOT_EMBEDDING = "|".join(EMBEDDING_MODEL_KEYS)
# Exact match on the selected email (single-select variable, no regex needed).
_MIMIR_SEL = sh.selector(f'{LABEL_EMAIL}="$user"', f'{LABEL_MODEL}!~"{_NOT_EMBEDDING}"')

# Loki selector for the per-request log panel (same email/model scope).
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


def _user_var() -> db.QueryVariable:
    # ⚠️ For a Postgres (SQL) datasource, the template variable's `query` MUST be
    # a **plain SQL string**, NOT the `{rawSql, format: table, …}` object a panel
    # target uses. Grafana's *variable* resolver only honors `format: table` when
    # the query is a string (it routes through metricFindQuery, which forces
    # table); given an object it ignores the stored format and runs the query as
    # `time_series`, which fails on a SQL with no time column → the UI shows
    # "error when executing the sql query". Verified live in Grafana 12.3 (a
    # string-form variable resolved __text/__value correctly; both object forms
    # errored). So this is the OPPOSITE of a panel target — don't "fix" it into
    # an object. The SQL returns `__text`/`__value` (legacy alias form).
    return (
        db.QueryVariable("user")
        .label("User (Keycloak)")
        .datasource(_KEYCLOAK_DS)
        .query(_USER_VAR_SQL)
        .refresh(dm.VariableRefresh.ON_DASHBOARD_LOAD)
        .sort(dm.VariableSort.ALPHABETICAL_ASC)
        .multi(False)
        .include_all(False)
    )


def _loki_target(expr: str, *, legend: str = "", ref_id: str = "A") -> loki.Dataquery:
    q = loki.Dataquery().expr(expr).ref_id(ref_id).query_type("range").datasource(_LOKI_DS)
    return q.legend_format(legend) if legend else q


# --- thin per-user headline row ---------------------------------------------


def _panel_chats() -> object:
    return sh.stat_panel(
        title="Chats (range)",
        expr=f"sum(increase({METRIC_REQUESTS}{_MIMIR_SEL}[$__range]))",
        unit="short",
        color="blue",
        grid=(4, 8, 0, 1),
    )


def _panel_tokens() -> object:
    return sh.stat_panel(
        title="Tokens (range)",
        expr=f"sum(increase({METRIC_TOKENS}{_MIMIR_SEL}[$__range]))",
        unit="short",
        color="green",
        grid=(4, 8, 8, 1),
    )


def _panel_cost() -> object:
    return sh.stat_panel(
        title="Cost (range)",
        expr=sh.usd(f"sum(increase({METRIC_COST_MICRO_USD}{_MIMIR_SEL}[$__range]))"),
        unit="currencyUSD",
        color="orange",
        grid=(4, 8, 16, 1),
    )


# --- hero: this user's individual chat requests (metadata, from Loki) --------


def _panel_request_log() -> logs.Panel:
    # One line per request, newest first — the itemised "what did they run".
    # line_format renders: model · status · tokens · cost($) · latency(ms).
    # Stays on Loki: it's a per-request LOG listing; Mimir stores metrics, not
    # individual log lines.
    line_fmt = (
        "{{.gen_ai_request_model}} · rc={{.response_code}} · "
        "{{.gen_ai_usage_total_tokens}}tok · {{.gen_ai_usage_custom_total_cost}}µ$ · "
        "{{.duration}}ms"
    )
    expr = f"{_LOKI_SEL} | json | line_format `{line_fmt}`"
    return (
        logs.Panel()
        .title("$user's chats — recent requests (newest first)")
        .description(
            "One row per chat request for the selected user (Loki access log): "
            "model, status, tokens, cost, latency. Metadata only — the actual "
            "prompt/response content can't be filtered per user (the AIEG "
            "ext-proc runs before Authorino, so its spans carry no identity; "
            "ADR-0079). Read content in the global chat-overview board."
        )
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=22, w=24, x=0, y=5))
        .show_time(True)
        .show_labels(False)
        .wrap_log_message(True)
        .enable_log_details(True)
        .sort_order(cm.LogsSortOrder.DESCENDING)
        .with_target(_loki_target(expr))
    )


_DESCRIPTION = (
    "Per-user chat requests (embeddings excluded). The $user picker is sourced "
    "from a read-only Postgres datasource onto the Keycloak DB (ADR-0063), so "
    "it lists real people regardless of recent traffic. The headline stats read "
    "the precomputed Mimir metrics (ADR-0058); the hero is an itemised "
    "per-request log (model/status/tokens/cost/latency) filtered on the `email` "
    "label — distinct from the per_user / actor-consumption rollup charts. "
    "⚠️ Metadata only: prompt/response CONTENT can't be filtered per user — the "
    "AIEG ext-proc runs before Authorino so its Tempo spans carry no identity "
    "(ADR-0079, confirmed live); read content in the global chat-overview board. "
    "GENERATED — source: tools/dashboards/envoy_ai_gateway/chats_by_user.py."
)


def _dashboard() -> db.Dashboard:
    return (
        db.Dashboard("AI Gateway — chats by user")
        .uid("envoy-ai-gateway-chats-by-user")
        .tags(["ai-gateway", "chats", "per-user", "keycloak"])
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
        .with_panel(_panel_request_log())
    )


def build() -> dict:
    return json.loads(json.dumps(_dashboard().build(), cls=JSONEncoder))
