"""Envoy AI Gateway — chats by user, Phoenix-style (GENERATED SOURCE).

Same idea as chat_overview.py, scoped to one person. The `$user` picker is
sourced directly from a **read-only Postgres datasource onto the Keycloak DB**
(ADR-0063) — not from Loki `label_values(email)` like per_user.py/jwt_tokens.py
— so the dropdown shows real names, not just whatever already has gateway
traffic in the current time window, and doesn't depend on a token having
carried the email claim.

Per-user volume/cost/token/error aggregates — Loki access-log body +
precomputed Mimir metrics (ADR-0046/0058), filtered on the `email` label.

⚠️ **No per-user Tempo trace panel here, by design (amended in ADR-0077).**
An earlier version of this dashboard planned one, gated on a new
`user.id`/`user.email` span attribute that would have required tagging the AI
Gateway ext-proc's spans with identity (a real privacy step-up: making
already-full-content traces directly person-attributable). That plan was
dropped after confirming LIVE that per-request content was already fully
readable without it — Tempo/Phoenix never needed user attribution to show
content, only to let TraceQL FILTER by person, which nobody actually needed.
For reading actual chat content, use chat_overview.py's global (unattributed)
trace feed instead.

The JSON file is regenerated from this module — do **not** hand-edit it::

    uv run dashboards build

ADR: docs/adr/0077-phoenix-style-chat-dashboards.md (+ ADR-0063, ADR-0008).
"""

from __future__ import annotations

import json

from grafana_foundation_sdk.builders import common as cb
from grafana_foundation_sdk.builders import dashboard as db
from grafana_foundation_sdk.builders import loki, piechart, stat, timeseries
from grafana_foundation_sdk.cog.encoder import JSONEncoder
from grafana_foundation_sdk.models import common as cm
from grafana_foundation_sdk.models import dashboard as dm
from grafana_foundation_sdk.models import piechart as pm

from dashboards._common import (
    CAMER_DIGITAL_REALM_ID,
    EMBEDDING_MODEL_KEYS,
    GATEWAY_SERVICE_NAME,
    KEYCLOAK_UID,
    LABEL_EMAIL,
    LABEL_MODEL,
    LOKI_UID,
)
from dashboards.envoy_ai_gateway import _shared as sh

OUTPUT_PATH: str = "charts/observability-dashboards/files/envoy-ai-gateway/chats-by-user.json"

_LOKI_DS = dm.DataSourceRef(type_val="loki", uid=LOKI_UID)
_KEYCLOAK_DS = dm.DataSourceRef(type_val="postgres", uid=KEYCLOAK_UID)

_NOT_EMBEDDING = "|".join(EMBEDDING_MODEL_KEYS)
# Exact match on the selected email (single-select variable, no regex needed).
_LOKI_SEL = (
    f'{{service_name="{GATEWAY_SERVICE_NAME}", {LABEL_EMAIL}="$user", '
    f'{LABEL_MODEL}!~"{_NOT_EMBEDDING}"}}'
)

# Keycloak directory query for the $user picker. `__text`/`__value` are
# Grafana's special column aliases for SQL-backed variable queries: the
# dropdown shows __text, the query filters use __value. No user input is
# interpolated into this SQL (only the constant realm id) — the SELECTED
# value only ever reaches a Loki label matcher below, never another raw SQL
# string, so there's no SQL-injection surface from a manipulated
# `?var-user=` URL param.
_USER_VAR_SQL = (
    "SELECT DISTINCT email AS __value, "
    "COALESCE(NULLIF(TRIM(COALESCE(first_name, '') || ' ' || COALESCE(last_name, '')), ''), username)"
    " || ' (' || email || ')' AS __text "
    "FROM user_entity "
    f"WHERE realm_id = '{CAMER_DIGITAL_REALM_ID}' AND email IS NOT NULL "
    "ORDER BY __text"
)


def _user_var() -> db.QueryVariable:
    return (
        db.QueryVariable("user")
        .label("User (Keycloak)")
        .datasource(_KEYCLOAK_DS)
        .query({"query": _USER_VAR_SQL, "refId": "KeycloakUsers"})
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


_JSON_TOKENS = 'tokens=`["gen_ai.usage.total_tokens"]`'
_JSON_COST = 'cost=`["gen_ai.usage.custom_total_cost"]`'


def _sum_tokens(*, window: str = "$__range") -> str:
    return f'sum(sum_over_time({_LOKI_SEL} | json {_JSON_TOKENS} | unwrap tokens | __error__="" [{window}]))'


def _sum_cost_usd(*, window: str = "$__range") -> str:
    inner = f'sum(sum_over_time({_LOKI_SEL} | json {_JSON_COST} | unwrap cost | __error__="" [{window}]))'
    return f"(({inner}) / 1e6)"


# --- stats -----------------------------------------------------------------


def _panel_requests() -> stat.Panel:
    return _stat(
        title="Chat requests (range)",
        expr=f"sum(count_over_time({_LOKI_SEL}[$__range]))",
        unit="short",
        color="blue",
        grid=(4, 6, 0, 1),
    )


def _panel_tokens() -> stat.Panel:
    return _stat(
        title="Total tokens (range)",
        expr=_sum_tokens(),
        unit="short",
        color="green",
        grid=(4, 6, 6, 1),
    )


def _panel_cost() -> stat.Panel:
    return _stat(
        title="Total cost (range)",
        expr=_sum_cost_usd(),
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


# --- trends ------------------------------------------------------------


def _panel_cost_over_time() -> timeseries.Panel:
    return (
        timeseries.Panel()
        .title("Cost over time")
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=9, w=12, x=0, y=6))
        .unit("currencyUSD")
        .draw_style(cm.GraphDrawStyle.BARS)
        .fill_opacity(70.0)
        .show_points(cm.VisibilityMode.NEVER)
        .legend(cb.VizLegendOptions().display_mode(cm.LegendDisplayMode.LIST).calcs(["sum", "max"]))
        .tooltip(cb.VizTooltipOptions().mode(cm.TooltipDisplayMode.MULTI))
        .with_target(_loki_target(_sum_cost_usd(window="$__auto"), legend="Cost"))
    )


def _panel_tokens_over_time() -> timeseries.Panel:
    return (
        timeseries.Panel()
        .title("Tokens over time")
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=9, w=12, x=12, y=6))
        .unit("short")
        .draw_style(cm.GraphDrawStyle.BARS)
        .fill_opacity(70.0)
        .show_points(cm.VisibilityMode.NEVER)
        .legend(cb.VizLegendOptions().display_mode(cm.LegendDisplayMode.LIST).calcs(["sum", "max"]))
        .tooltip(cb.VizTooltipOptions().mode(cm.TooltipDisplayMode.MULTI))
        .with_target(_loki_target(_sum_tokens(window="$__auto"), legend="Tokens"))
    )


def _panel_model_pie() -> piechart.Panel:
    expr = f"sum by ({LABEL_MODEL}) (count_over_time({_LOKI_SEL}[$__range]))"
    return (
        piechart.Panel()
        .title("Requests by model (range)")
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=9, w=24, x=0, y=15))
        .pie_type(pm.PieChartType.DONUT)
        .legend(
            piechart.PieChartLegendOptions()
            .display_mode(cm.LegendDisplayMode.TABLE)
            .placement(cm.LegendPlacement.RIGHT)
            .values([pm.PieChartLegendValues.VALUE, pm.PieChartLegendValues.PERCENT])
        )
        .tooltip(cb.VizTooltipOptions().mode(cm.TooltipDisplayMode.SINGLE))
        .with_target(_loki_target(expr, legend=f"{{{{{LABEL_MODEL}}}}}"))
    )


_DESCRIPTION = (
    "Per-user chat-completion view (embeddings excluded) — the Phoenix-style "
    "'what is this person doing' cut. The $user picker is sourced directly "
    "from a read-only Postgres datasource onto the Keycloak DB (ADR-0063), so "
    "it lists real people regardless of recent gateway traffic. Volume/cost/"
    "token/error aggregates come from Loki, filtered on the `email` label "
    "(ADR-0046). No per-user trace/content panel here by design (ADR-0077) — "
    "content was already fully visible without per-user span attribution, so "
    "adding it wasn't worth the privacy cost; use 'AI Gateway — chat overview' "
    "to read actual chat content. "
    "GENERATED — source: tools/dashboards/envoy_ai_gateway/chats_by_user.py."
)


def _dashboard() -> db.Dashboard:
    return (
        db.Dashboard("AI Gateway — chats by user")
        .uid("envoy-ai-gateway-chats-by-user")
        .tags(["ai-gateway", "chats", "per-user", "keycloak", "phoenix"])
        .description(_DESCRIPTION)
        .timezone("browser")
        .editable()
        .tooltip(dm.DashboardCursorSync.CROSSHAIR)
        .refresh("30s")
        .time("now-6h", "now")
        .with_variable(_user_var())
        .with_panel(sh.row("Chats — $user", y=0))
        .with_panel(_panel_requests())
        .with_panel(_panel_tokens())
        .with_panel(_panel_cost())
        .with_panel(_panel_error_rate())
        .with_panel(sh.row("Trends", y=5))
        .with_panel(_panel_cost_over_time())
        .with_panel(_panel_tokens_over_time())
        .with_panel(_panel_model_pie())
    )


def build() -> dict:
    return json.loads(json.dumps(_dashboard().build(), cls=JSONEncoder))
