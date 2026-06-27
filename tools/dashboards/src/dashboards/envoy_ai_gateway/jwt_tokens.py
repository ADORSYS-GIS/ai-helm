"""Envoy AI Gateway — JWT tokens x consumption (GENERATED SOURCE).

Per **JWT** (the `oidc_jti` access-token id) consumption — cost / tokens /
requests — and last usages, alongside the **email from the JWT claim only**
(the Loki `email` label Alloy promotes from `oidc_email`), NOT the Keycloak
directory. Thin tokens with no email claim show their `missing:*` / `unstamped:*`
sentinel — that's the honest "from the JWT only" view.

Why Loki (not Mimir): the JWT id `oidc_jti` is an access-log **body** field —
it is deliberately NOT promoted to a Mimir metric label (per-token cardinality;
ADR-0064). It lives only in the Loki access-log line, so per-`jti` aggregation
must come from Loki. The `email`/`model` axes are stream labels (ADR-0046).

⚠️ LogQL contract: `oidc_jti` (and any unwrap field) must be **extracted in the
same `| json`** that the outer `sum by (oidc_jti, email)` groups on — extracting
only the unwrap field collapses `oidc_jti` to `-`. Numeric usage fields have
LITERAL DOTTED keys (`gen_ai.usage.total_tokens`) → backtick-quoted bracket form
`field=["dotted.key"]`; every `unwrap` needs `| __error__=""` (string / "-"
values). Cost is micro-USD → `/1e6`.

The JSON file is regenerated from this module — do **not** hand-edit it::

    uv run dashboards build

ADR: docs/adr/0008-python-dashboard-generation.md.
"""

from __future__ import annotations

import json

from grafana_foundation_sdk.builders import bargauge, logs, loki, stat, timeseries
from grafana_foundation_sdk.builders import common as cb
from grafana_foundation_sdk.builders import dashboard as db
from grafana_foundation_sdk.cog.encoder import JSONEncoder
from grafana_foundation_sdk.models import common as cm
from grafana_foundation_sdk.models import dashboard as dm

from dashboards._common import GATEWAY_SERVICE_NAME, LABEL_EMAIL, LABEL_MODEL, LOKI_UID

OUTPUT_PATH: str = "charts/observability-dashboards/files/envoy-ai-gateway/jwt-tokens.json"

_LOKI_DS = dm.DataSourceRef(type_val="loki", uid=LOKI_UID)
_JTI = "oidc_jti"

# Stream selector: the gateway anchor + the dashboard's email/model filters.
# oidc_jti is a BODY field (not a label) → filtered after `| json`, not here.
_SEL = (
    f'{{service_name="{GATEWAY_SERVICE_NAME}", {LABEL_EMAIL}=~"$email", {LABEL_MODEL}=~"$model"}}'
)

# Legend "<email> · <jti>" — the literal "JWT token, whose, how much".
_LEGEND = f"{{{{{LABEL_EMAIL}}}}} · {{{{{_JTI}}}}}"

_JSON_DOTTED = {
    "tokens": "gen_ai.usage.total_tokens",
    "cost": "gen_ai.usage.custom_total_cost",
}


def _usd(expr: str) -> str:
    return f"(({expr}) / 1e6)"


def _sum_by_jti(field: str, *, window: str = "$__range") -> str:
    """`sum by (oidc_jti, email) (sum_over_time(<sel> | json oidc_jti, f=… | unwrap f …))`.

    Extracts oidc_jti IN THE SAME json so it survives as a grouping label, plus
    the unwrap field only (bounded cardinality). sum_over_time takes no inline
    by() (Loki) — grouping is the outer sum by. `window` is the range vector
    (default `$__range` for totals/leaderboards; `$__auto` for the timeseries).
    """
    dotted = _JSON_DOTTED[field]
    inner = (
        f'sum_over_time({_SEL} | json {_JTI}, {field}=`["{dotted}"]`'
        f' | {_JTI}!="" | unwrap {field} | __error__="" [{window}])'
    )
    return f"sum by ({_JTI}, {LABEL_EMAIL}) ({inner})"


def _count_by_jti() -> str:
    return (
        f"sum by ({_JTI}, {LABEL_EMAIL}) "
        f'(count_over_time({_SEL} | json {_JTI} | {_JTI}!="" [$__range]))'
    )


class _RowBuilder:
    """Minimal builder for a `dashboard.RowPanel` (the SDK ships the model but no
    row *builder* — same wrapper per_user.py uses)."""

    def __init__(self, title: str, *, y: int) -> None:
        self._row = dm.RowPanel(title=title, grid_pos=dm.GridPos(h=1, w=24, x=0, y=y))

    def build(self) -> dm.RowPanel:
        return self._row


def _loki_target(expr: str, *, legend: str = "", ref_id: str = "A") -> loki.Dataquery:
    # Range query (never instant): the Loki plugin doesn't substitute $__range in
    # instant queries → silent no-data (per_user.py learned this the hard way).
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


def _bargauge(
    *, title: str, expr: str, unit: str, color: str, grid: tuple[int, int, int, int]
) -> bargauge.Panel:
    h, w, x, y = grid
    return (
        bargauge.Panel()
        .title(title)
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=h, w=w, x=x, y=y))
        .unit(unit)
        .orientation(cm.VizOrientation.HORIZONTAL)
        .reduce_options(cb.ReduceDataOptions().calcs(["lastNotNull"]).fields("").values(False))
        .display_mode(cm.BarGaugeDisplayMode.GRADIENT)
        .thresholds(_thresholds(color))
        .with_target(_loki_target(expr, legend=_LEGEND))
    )


# --- stats -------------------------------------------------------------------


def _panel_distinct_jwts() -> stat.Panel:
    return _stat(
        title="Distinct JWTs (range)",
        expr=f"count({_count_by_jti()})",
        unit="short",
        color="purple",
        grid=(4, 6, 0, 1),
    )


def _panel_total_cost() -> stat.Panel:
    return _stat(
        title="Total cost (range)",
        expr=_usd(f"sum({_sum_by_jti('cost')})"),
        unit="currencyUSD",
        color="orange",
        grid=(4, 6, 6, 1),
    )


def _panel_total_tokens() -> stat.Panel:
    return _stat(
        title="Total tokens (range)",
        expr=f"sum({_sum_by_jti('tokens')})",
        unit="short",
        color="green",
        grid=(4, 6, 12, 1),
    )


def _panel_total_requests() -> stat.Panel:
    return _stat(
        title="Requests (range)",
        expr=f"sum({_count_by_jti()})",
        unit="short",
        color="blue",
        grid=(4, 6, 18, 1),
    )


# --- leaderboards (JWT x consumption) ---------------------------------------


def _panel_top_jwts_cost() -> bargauge.Panel:
    return _bargauge(
        title="Top JWTs by cost (selected range)",
        expr=f"topk(20, {_usd(_sum_by_jti('cost'))})",
        unit="currencyUSD",
        color="orange",
        grid=(11, 12, 0, 5),
    )


def _panel_top_jwts_tokens() -> bargauge.Panel:
    return _bargauge(
        title="Top JWTs by tokens (selected range)",
        expr=f"topk(20, {_sum_by_jti('tokens')})",
        unit="short",
        color="green",
        grid=(11, 12, 12, 5),
    )


def _panel_cost_per_jwt_over_time() -> timeseries.Panel:
    # When each JWT was active = the temporal "usages" view. Per-jti cardinality
    # is low (short-lived access tokens, few concurrent users), so stacking is fine.
    return (
        timeseries.Panel()
        .title("Cost per JWT over time")
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=8, w=24, x=0, y=16))
        .unit("currencyUSD")
        .draw_style(cm.GraphDrawStyle.LINE)
        .line_interpolation(cm.LineInterpolation.SMOOTH)
        .fill_opacity(15.0)
        .show_points(cm.VisibilityMode.NEVER)
        .stacking(cb.StackingConfig().mode(cm.StackingMode.NORMAL))
        .legend(
            cb.VizLegendOptions()
            .display_mode(cm.LegendDisplayMode.TABLE)
            .placement(cm.LegendPlacement.RIGHT)
            .calcs(["sum", "max"])
        )
        .tooltip(cb.VizTooltipOptions().mode(cm.TooltipDisplayMode.MULTI))
        .with_target(
            # Reuse the same helper as the totals/leaderboards, only the range
            # vector differs ($__auto for per-step buckets) — no duplicated LogQL.
            _loki_target(
                _usd(_sum_by_jti("cost", window="$__auto")),
                legend=_LEGEND,
            )
        )
    )


# --- last usages -------------------------------------------------------------


def _panel_last_usages() -> logs.Panel:
    # Raw recent gateway requests, newest first — the literal "last usages".
    # line_format renders a tidy one-liner: email · jti · model · status · tokens · $.
    line_fmt = (
        "{{.email}} · jti={{.oidc_jti}} · {{.gen_ai_request_model}} · "
        "rc={{.response_code}} · {{.gen_ai_usage_total_tokens}}tok · "
        "{{.gen_ai_usage_custom_total_cost}}µ$"
    )
    expr = f'{_SEL} | json | {_JTI}!="" | line_format `{line_fmt}`'
    return (
        logs.Panel()
        .title("Last usages (recent requests, newest first)")
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=12, w=24, x=0, y=25))
        .show_time(True)
        .show_labels(False)
        .wrap_log_message(True)
        .enable_log_details(True)
        .sort_order(cm.LogsSortOrder.DESCENDING)
        .with_target(_loki_target(expr))
    )


# --- variables / dashboard ---------------------------------------------------


def _multi_var(*, name: str, label: str, definition: str) -> db.QueryVariable:
    return (
        db.QueryVariable(name)
        .label(label)
        .datasource(_LOKI_DS)
        .query(definition)
        .refresh(dm.VariableRefresh.ON_TIME_RANGE_CHANGED)
        .sort(dm.VariableSort.ALPHABETICAL_ASC)
        .multi(True)
        .include_all(True)
        .all_value(".+")
        .current(dm.VariableOption(selected=True, text=["All"], value=["$__all"]))
    )


_DESCRIPTION = (
    "Per-JWT (the oidc_jti access-token id) consumption — cost / tokens / requests "
    "— and last usages, with the email taken from the JWT claim ONLY (the Loki "
    "`email` label, not the Keycloak directory). Thin tokens show their "
    "`missing:*`/`unstamped:*` sentinel. Loki-backed because oidc_jti is an "
    "access-log body field, never a Mimir label (per-token cardinality, ADR-0064). "
    "Cost ÷1e6 for USD. Filters: email, model. "
    "GENERATED — source: tools/dashboards/envoy_ai_gateway/jwt_tokens.py."
)


def _dashboard() -> db.Dashboard:
    return (
        db.Dashboard("AI Gateway — JWT tokens x consumption")
        .uid("envoy-ai-gateway-jwt-tokens")
        .tags(["ai-gateway", "per-user", "jwt", "loki"])
        .description(_DESCRIPTION)
        .timezone("browser")
        .editable()
        .tooltip(dm.DashboardCursorSync.CROSSHAIR)
        .refresh("1m")
        .time("now-6h", "now")
        .with_variable(
            _multi_var(
                name="email",
                label="User (email, from JWT)",
                definition=f'label_values({{service_name="{GATEWAY_SERVICE_NAME}"}}, email)',
            )
        )
        .with_variable(
            _multi_var(
                name="model",
                label="Model",
                definition=f'label_values({{service_name="{GATEWAY_SERVICE_NAME}"}}, model)',
            )
        )
        .with_panel(_RowBuilder("JWT tokens x consumption", y=0))
        .with_panel(_panel_distinct_jwts())
        .with_panel(_panel_total_cost())
        .with_panel(_panel_total_tokens())
        .with_panel(_panel_total_requests())
        .with_panel(_panel_top_jwts_cost())
        .with_panel(_panel_top_jwts_tokens())
        .with_panel(_panel_cost_per_jwt_over_time())
        .with_panel(_RowBuilder("Last usages", y=24))
        .with_panel(_panel_last_usages())
    )


def build() -> dict:
    return json.loads(json.dumps(_dashboard().build(), cls=JSONEncoder))
