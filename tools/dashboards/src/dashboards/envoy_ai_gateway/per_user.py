"""Envoy AI Gateway — per-user activity dashboard (GENERATED SOURCE).

This module is the *source of truth* for the dashboard JSON shipped at
``charts/observability-dashboards/files/envoy-ai-gateway/per-user.json``.
The JSON file is regenerated from this module — do **not** hand-edit it.

Regenerate with::

    make build
    # or
    uv run dashboards build

Architecture decision: see ``docs/adr/0008-python-dashboard-generation.md``.
Data path the dashboard consumes: ``docs/per-user-observability.md``.
"""

from __future__ import annotations

import json

from grafana_foundation_sdk.builders import bargauge, loki, piechart, stat, timeseries
from grafana_foundation_sdk.builders import common as cb
from grafana_foundation_sdk.builders import dashboard as db
from grafana_foundation_sdk.cog.encoder import JSONEncoder
from grafana_foundation_sdk.models import common as cm
from grafana_foundation_sdk.models import dashboard as dm
from grafana_foundation_sdk.models import piechart as pm

from dashboards._common import (
    GATEWAY_SERVICE_NAME,
    LABEL_AZP,
    LABEL_DISPLAY_NAME,
    LABEL_EMAIL,
    LABEL_MODEL,
    LABEL_USER_ID,
    LOKI_UID,
)

# ---------------------------------------------------------------------------
# Module contract for the orchestrator (tools/dashboards/main.py)
# ---------------------------------------------------------------------------

OUTPUT_PATH: str = "charts/observability-dashboards/files/envoy-ai-gateway/per-user.json"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOKI_DS = dm.DataSourceRef(type_val="loki", uid=LOKI_UID)

# Stream selector filtered by all dashboard variables (per-user scope).
# Filters on email (not user_id UUID) so the User picker is human-readable.
#
# `email!~"(missing|unstamped):.*"` keeps the per-user (human) panels clean.
# Absent identity now resolves to a descriptive SENTINEL instead of an empty
# value — "missing:<claim>" when the token lacked the claim (Authorino,
# charts/apps/values.yaml) and "unstamped:<field>" when no header was stamped at
# all (Alloy, charts/observability/values.yaml). Empty used to be dropped by Loki
# and so auto-excluded SA/no-email traffic here; non-empty sentinels would
# otherwise leak into the per-user aggregates, so we exclude both namespaces
# explicitly. That traffic stays VISIBLE in the Overall section (via
# _OVERALL_SELECTOR) and as a "missing:*"/"unstamped:*" row in the Top-15 — the
# whole point of the sentinels is that the gap is named, not hidden.
_SELECTOR = (
    f'{{service_name="{GATEWAY_SERVICE_NAME}", {LABEL_AZP}=~"$azp",'
    f' {LABEL_EMAIL}=~"$email", {LABEL_EMAIL}!~"(missing|unstamped):.*",'
    f' {LABEL_MODEL}=~"$model"}}'
)

# Stream selector that always spans ALL attributed users regardless of $email.
# user_id=~".+" (not email) so SA traffic is included in overall aggregates.
_OVERALL_SELECTOR = (
    f'{{service_name="{GATEWAY_SERVICE_NAME}", {LABEL_AZP}=~"$azp",'
    f' {LABEL_USER_ID}=~".+", {LABEL_MODEL}=~"$model"}}'
)


_JSON_PATHS = {
    "gen_ai_usage_total_tokens": "gen_ai.usage.total_tokens",
    "gen_ai_usage_custom_total_cost": "gen_ai.usage.custom_total_cost",
}


def _unwrap(field: str) -> str:
    """`| json <field> | unwrap <field>` with the error guard ADR-0046 requires.

    Numeric access-log fields arrive as strings and absent ones as "-";
    `__error__=""` drops samples that fail conversion instead of failing
    the whole query.

    Extracts ONLY `field` -- a bare `| json` (no field list) pulls every
    field on the line (trace_id, jti, ...) into the per-line label set, and
    sum_over_time/quantile_over_time default-group by that whole set when no
    explicit grouping is given, blowing past Loki's 500-series cap under real
    traffic. Restricting extraction to the one field we unwrap keeps the
    per-line label set down to just the genuine stream labels.

    Envoy's access-log format.json (charts/core-gateway/templates/envoy-proxy.yaml)
    declares the GenAI usage fields with LITERAL DOTS in the key name
    (`gen_ai.usage.total_tokens`, not a nested object) -- a bare `| json` auto-
    flattens that into the underscored label we use here, but the explicit
    `| json <name>` form treats `<name>` as a path lookup, which does NOT
    match a literal dotted key by bare name. Loki's json-field grammar isn't
    full JMESPath -- a literal/quoted key isn't a valid expression on its
    own, it must be wrapped in brackets: `["dotted.key"]` (confirmed via the
    parser's own error: "unexpected STRING, expecting LSB or FIELD"). Flat
    keys like `duration` have no dot and extract by bare name as before.
    """
    path = _JSON_PATHS.get(field)
    extract = f'{field}=`["{path}"]`' if path else field
    return f'| json {extract} | unwrap {field} | __error__=""'


def _usd(expr: str) -> str:
    """Convert a raw micro-USD LogQL aggregation to USD for display.

    The pricing CEL (ai-model.costExpression, ADR-0028/ADR-0051) emits
    gen_ai_usage_custom_total_cost in micro-USD. Every cost panel must
    divide by 1e6 before applying the currencyUSD unit, or values display
    1,000,000x too large.
    """
    return f"(({expr}) / 1e6)"


# ---------------------------------------------------------------------------
# Small builder helpers
# ---------------------------------------------------------------------------


def _loki_target(
    expr: str,
    *,
    legend: str = "",
    ref_id: str = "A",
    instant: bool = False,
) -> loki.Dataquery:
    q = (
        loki.Dataquery()
        .expr(expr)
        .ref_id(ref_id)
        .query_type("instant" if instant else "range")
        .datasource(_LOKI_DS)
    )
    if legend:
        q = q.legend_format(legend)
    return q


def _single_color_thresholds(color: str) -> db.ThresholdsConfig:
    return db.ThresholdsConfig().mode(dm.ThresholdsMode.ABSOLUTE).steps([dm.Threshold(color=color)])


def _stat_panel(
    *,
    title: str,
    expr: str,
    unit: str,
    color: str,
    grid: tuple[int, int, int, int],
    calcs: list[str] | None = None,
) -> stat.Panel:
    """Single-value stat panel with sparkline. `grid` is (h, w, x, y)."""
    h, w, x, y = grid
    return (
        stat.Panel()
        .title(title)
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=h, w=w, x=x, y=y))
        .unit(unit)
        .thresholds(_single_color_thresholds(color))
        .reduce_options(
            cb.ReduceDataOptions()
            .calcs(calcs if calcs is not None else ["lastNotNull"])
            .fields("")
            .values(False)
        )
        .orientation(cm.VizOrientation.HORIZONTAL)
        .text_mode(cm.BigValueTextMode.AUTO)
        .color_mode(cm.BigValueColorMode.VALUE)
        .graph_mode(cm.BigValueGraphMode.AREA)
        .justify_mode(cm.BigValueJustifyMode.AUTO)
        .with_target(_loki_target(expr))
    )


def _pie_panel(
    *,
    title: str,
    expr: str,
    legend_label: str,
    grid: tuple[int, int, int, int],
) -> piechart.Panel:
    # Range query (not instant): the Loki Grafana plugin does not substitute
    # $__range in instant queries, causing them to silently return no data.
    # Range mode returns a time series per slice; the pie uses the last value.
    h, w, x, y = grid
    return (
        piechart.Panel()
        .title(title)
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=h, w=w, x=x, y=y))
        .pie_type(pm.PieChartType.DONUT)
        .legend(
            piechart.PieChartLegendOptions()
            .display_mode(cm.LegendDisplayMode.TABLE)
            .placement(cm.LegendPlacement.RIGHT)
            .values([pm.PieChartLegendValues.VALUE, pm.PieChartLegendValues.PERCENT])
        )
        .tooltip(cb.VizTooltipOptions().mode(cm.TooltipDisplayMode.SINGLE))
        .with_target(_loki_target(expr, legend=legend_label, instant=False))
    )


class _RowBuilder:
    """Minimal `cogbuilder.Builder[dashboard.RowPanel]` adapter.

    The SDK ships a `RowPanel` model but no dedicated row *builder* module
    (unlike stat/piechart/timeseries) -- `Dashboard.with_panel`/`with_row`
    only need a `.build()` method, so this tiny wrapper is enough to reuse
    `with_panel`'s existing grid_pos handling for row headers.
    """

    def __init__(self, row: dm.RowPanel) -> None:
        self._row = row

    def build(self) -> dm.RowPanel:
        return self._row


def _row(title: str, *, y: int) -> _RowBuilder:
    return _RowBuilder(dm.RowPanel(title=title, grid_pos=dm.GridPos(h=1, w=24, x=0, y=y)))


def _query_var(
    *,
    name: str,
    label: str,
    definition: str,
) -> db.QueryVariable:
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


# ---------------------------------------------------------------------------
# Overview stats  (y=0)
# ---------------------------------------------------------------------------


def _panel_requests_range() -> stat.Panel:
    return _stat_panel(
        title="Requests (range)",
        expr=f"sum(count_over_time({_SELECTOR} [$__range]))",
        unit="short",
        color="blue",
        grid=(4, 6, 0, 1),
    )


def _panel_unique_users() -> stat.Panel:
    return _stat_panel(
        title="Unique users (range)",
        expr=f"count(sum by ({LABEL_EMAIL}) (count_over_time({_SELECTOR} [$__range])))",
        unit="short",
        color="purple",
        grid=(4, 6, 6, 1),
    )


def _panel_total_tokens() -> stat.Panel:
    return _stat_panel(
        title="Total tokens (range)",
        expr=f"sum(sum_over_time({_SELECTOR} {_unwrap('gen_ai_usage_total_tokens')} [$__range]))",
        unit="short",
        color="green",
        grid=(4, 6, 12, 1),
    )


def _panel_p95_latency() -> stat.Panel:
    # Use [5m] instead of [$__range] — quantile_over_time with a 1h window
    # scans too much data per step and times out in Loki for this panel size.
    # [5m] gives "current p95 latency" which is more actionable anyway.
    # `by ()` collapses to ONE overall series — without a grouping clause,
    # quantile_over_time keys its output by each underlying stream's full
    # label set (not just the dashboard variables), which blows past Loki's
    # 500-series-per-query cap and surfaces as a silent "No data" stat panel.
    panel = _stat_panel(
        title="p95 latency (5m)",
        expr=f"quantile_over_time(0.95, {_SELECTOR} {_unwrap('duration')} [5m]) by ()",
        unit="ms",
        color="green",
        grid=(4, 6, 18, 1),
    )
    return panel.thresholds(
        db.ThresholdsConfig()
        .mode(dm.ThresholdsMode.ABSOLUTE)
        .steps(
            [
                dm.Threshold(color="green"),
                dm.Threshold(color="orange", value=1000.0),
                dm.Threshold(color="red", value=5000.0),
            ]
        )
    )


# ---------------------------------------------------------------------------
# Requests per user / minute  (y=4)
# ---------------------------------------------------------------------------


def _panel_requests_per_user() -> timeseries.Panel:
    return (
        timeseries.Panel()
        .title("Requests per user / minute")
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=8, w=24, x=0, y=5))
        .unit("short")
        .draw_style(cm.GraphDrawStyle.LINE)
        .line_interpolation(cm.LineInterpolation.SMOOTH)
        .fill_opacity(10.0)
        .show_points(cm.VisibilityMode.NEVER)
        .stacking(cb.StackingConfig().mode(cm.StackingMode.NORMAL))
        .legend(
            cb.VizLegendOptions()
            .display_mode(cm.LegendDisplayMode.TABLE)
            .placement(cm.LegendPlacement.RIGHT)
            .calcs(["mean", "max"])
        )
        .tooltip(cb.VizTooltipOptions().mode(cm.TooltipDisplayMode.MULTI))
        .with_target(
            _loki_target(
                f"sum by ({LABEL_EMAIL}) (count_over_time({_SELECTOR} [1m]))",
                legend="{{email}}",
            )
        )
    )


# ---------------------------------------------------------------------------
# Top 15 users by cost  (y=12)
# ---------------------------------------------------------------------------


def _panel_top_users_bar() -> bargauge.Panel:
    # label_replace extracts the first whitespace-delimited token from
    # display_name ("Kunga Derick" -> "Kunga") so 15 bars fit comfortably.
    # Uses _OVERALL_SELECTOR so the ranking always reflects all users
    # regardless of the $user_id filter variable.
    # sum_over_time doesn't accept an inline `by (...)` clause in this Loki
    # version ("grouping not allowed for sum_over_time aggregation") -- only
    # quantile_over_time does. Grouping happens via the outer `sum by (...)`;
    # cardinality stays bounded because _unwrap now extracts only the cost
    # field, so the inner result is already keyed by stream labels only.
    _cost_sum = (
        f"sum_over_time({_OVERALL_SELECTOR} {_unwrap('gen_ai_usage_custom_total_cost')} [$__range])"
    )
    expr = (
        f"label_replace("
        f"topk(15, sum by ({LABEL_DISPLAY_NAME}) ({_usd(_cost_sum)})),"
        f'"given_name", "$1", "{LABEL_DISPLAY_NAME}", "^(\\\\S+).*"'
        f")"
    )
    return (
        bargauge.Panel()
        .title("Top 15 users — cost (selected range)")
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=10, w=24, x=0, y=13))
        .unit("currencyUSD")
        .orientation(cm.VizOrientation.HORIZONTAL)
        .reduce_options(cb.ReduceDataOptions().calcs(["lastNotNull"]).fields("").values(False))
        .display_mode(cm.BarGaugeDisplayMode.BASIC)
        .thresholds(_single_color_thresholds("blue"))
        # Range query (not instant): same $__range-not-substituted bug as the
        # pie charts above — instant queries silently return no data here too.
        .with_target(_loki_target(expr, legend="{{given_name}}", instant=False))
    )


# ---------------------------------------------------------------------------
# Per-user section  (y=22)
# ---------------------------------------------------------------------------


def _panel_user_total_cost() -> stat.Panel:
    # [$__range] + the default lastNotNull calc, same trick as the top-row
    # "Requests (range)" stat: at the LAST evaluated point, the window
    # stretches back exactly to the start of the dashboard's selected range,
    # so that one point already IS the total -- lastNotNull just reads it.
    # (The previous [1m]-bucket + calcs=["sum"] version double/triple-counted:
    # Grafana's auto step for a range query is normally well under 60s, so a
    # 1-minute window evaluated every ~10-15s overlaps itself 4-6x, and
    # summing those overlapping buckets inflated the total by that same
    # factor -- this is why "User"/"Overall" totals looked implausibly large
    # relative to e.g. the Top-15 cost breakdown.)
    return _stat_panel(
        title="User — total cost",
        expr=_usd(
            f"sum(sum_over_time({_SELECTOR} {_unwrap('gen_ai_usage_custom_total_cost')} [$__range]))"
        ),
        unit="currencyUSD",
        color="orange",
        grid=(8, 12, 0, 24),
    )


def _panel_latency_per_user() -> timeseries.Panel:
    return (
        timeseries.Panel()
        .title("Latency per user — p50 / p95")
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=8, w=12, x=12, y=24))
        .unit("ms")
        .draw_style(cm.GraphDrawStyle.LINE)
        .line_interpolation(cm.LineInterpolation.LINEAR)
        .fill_opacity(0.0)
        .show_points(cm.VisibilityMode.NEVER)
        .legend(
            cb.VizLegendOptions()
            .display_mode(cm.LegendDisplayMode.TABLE)
            .placement(cm.LegendPlacement.RIGHT)
            .calcs(["mean", "max"])
        )
        .tooltip(cb.VizTooltipOptions().mode(cm.TooltipDisplayMode.MULTI))
        .with_target(
            _loki_target(
                f"quantile_over_time(0.50, {_SELECTOR} {_unwrap('duration')} [5m]) by ({LABEL_EMAIL})",
                legend="p50 {{email}}",
                ref_id="A",
            )
        )
        .with_target(
            _loki_target(
                f"quantile_over_time(0.95, {_SELECTOR} {_unwrap('duration')} [5m]) by ({LABEL_EMAIL})",
                legend="p95 {{email}}",
                ref_id="B",
            )
        )
    )


def _panel_user_model_by_requests() -> piechart.Panel:
    return _pie_panel(
        title="User — model distribution (requests)",
        expr=f"sum by ({LABEL_MODEL}) (count_over_time({_SELECTOR} [$__range]))",
        legend_label=f"{{{{{LABEL_MODEL}}}}}",
        grid=(8, 6, 0, 32),
    )


def _panel_user_model_by_cost() -> piechart.Panel:
    return _pie_panel(
        title="User — model distribution (cost $)",
        expr=_usd(
            f"sum by ({LABEL_MODEL}) (sum_over_time({_SELECTOR} {_unwrap('gen_ai_usage_custom_total_cost')} [$__range]))"
        ),
        legend_label=f"{{{{{LABEL_MODEL}}}}}",
        grid=(8, 6, 6, 32),
    )


def _panel_user_model_by_tokens() -> piechart.Panel:
    return _pie_panel(
        title="User — model distribution (tokens)",
        expr=f"sum by ({LABEL_MODEL}) (sum_over_time({_SELECTOR} {_unwrap('gen_ai_usage_total_tokens')} [$__range]))",
        legend_label=f"{{{{{LABEL_MODEL}}}}}",
        grid=(8, 6, 12, 32),
    )


def _panel_user_status_codes() -> piechart.Panel:
    # response_code is in the log body (not a label); | json extracts it.
    # The ^(-|)$ filter drops absent/placeholder values before grouping.
    return _pie_panel(
        title="User — status codes",
        expr=(
            f"sum by (response_code) ("
            f'count_over_time({_SELECTOR} | json | response_code !~ "^(-|)$" [$__range])'
            f")"
        ),
        legend_label="{{response_code}}",
        grid=(8, 6, 18, 32),
    )


# ---------------------------------------------------------------------------
# Overall section  (y=38)
# ---------------------------------------------------------------------------


def _panel_overall_model_by_requests() -> piechart.Panel:
    return _pie_panel(
        title="Overall — model distribution (requests)",
        expr=f"sum by ({LABEL_MODEL}) (count_over_time({_OVERALL_SELECTOR} [$__range]))",
        legend_label=f"{{{{{LABEL_MODEL}}}}}",
        grid=(8, 6, 0, 41),
    )


def _panel_overall_model_by_cost() -> piechart.Panel:
    return _pie_panel(
        title="Overall — model distribution (cost $)",
        expr=_usd(
            f"sum by ({LABEL_MODEL}) (sum_over_time({_OVERALL_SELECTOR} {_unwrap('gen_ai_usage_custom_total_cost')} [$__range]))"
        ),
        legend_label=f"{{{{{LABEL_MODEL}}}}}",
        grid=(8, 6, 6, 41),
    )


def _panel_overall_model_by_tokens() -> piechart.Panel:
    return _pie_panel(
        title="Overall — model distribution (tokens)",
        expr=f"sum by ({LABEL_MODEL}) (sum_over_time({_OVERALL_SELECTOR} {_unwrap('gen_ai_usage_total_tokens')} [$__range]))",
        legend_label=f"{{{{{LABEL_MODEL}}}}}",
        grid=(8, 6, 12, 41),
    )


def _panel_overall_status_codes() -> piechart.Panel:
    return _pie_panel(
        title="Overall — status codes",
        expr=(
            f"sum by (response_code) ("
            f'count_over_time({_OVERALL_SELECTOR} | json | response_code !~ "^(-|)$" [$__range])'
            f")"
        ),
        legend_label="{{response_code}}",
        grid=(8, 6, 18, 41),
    )


def _panel_overall_total_cost() -> stat.Panel:
    # See _panel_user_total_cost -- same [$__range]+lastNotNull fix, same
    # reason (the prior [1m]+sum form double/triple-counted via overlapping
    # auto-step windows).
    return _stat_panel(
        title="Overall — total cost",
        expr=_usd(
            f"sum(sum_over_time({_OVERALL_SELECTOR} {_unwrap('gen_ai_usage_custom_total_cost')} [$__range]))"
        ),
        unit="currencyUSD",
        color="orange",
        grid=(4, 8, 0, 49),
    )


def _panel_overall_total_tokens() -> stat.Panel:
    return _stat_panel(
        title="Overall — total tokens",
        expr=f"sum(sum_over_time({_OVERALL_SELECTOR} {_unwrap('gen_ai_usage_total_tokens')} [$__range]))",
        unit="short",
        color="green",
        grid=(4, 8, 8, 49),
    )


def _panel_overall_total_requests() -> stat.Panel:
    return _stat_panel(
        title="Overall — total requests",
        expr=f"sum(count_over_time({_OVERALL_SELECTOR} [$__range]))",
        unit="short",
        color="blue",
        grid=(4, 8, 16, 49),
    )


# ---------------------------------------------------------------------------
# Cost by channel  (y=53)
#
# "How is each account consuming its spend across CONSUMPTION CHANNELS?" The
# channel is the `azp` label = the authenticated client/service that made the
# call (ADR-0011/0021): e.g. opencode-cli / lightbridge-api-key / converse-frontend
# = direct API, internal-key-librechat = LibreChat, lightbridge-code-intelligence
# = code-intel, github-actions = CI runners. Grouping cost by (display_name, azp)
# gives the per-person / per-repo split the maintainer asked for, e.g.
#   "stephane · lightbridge-api-key = $20  /  stephane · internal-key-librechat = $10"
#   "adorsys-gis/ai-helm · github-actions = $30 / · lightbridge-code-intelligence = $10"
# Uses _OVERALL_SELECTOR so SERVICE traffic (azp != a human) is included — the
# whole point is to see every channel, not just human-attributed rows.
# ⚠️ KNOWN GAP: LibreChat AGENT runs + RAG embeddings don't forward the end-user
# (they fall back to azp=internal-key-librechat with user_id=internal-key-librechat),
# so LibreChat's per-USER split is currently only its DIRECT chats. See
# docs/per-user-observability.md / the librechat-app header-forwarding note.
# ---------------------------------------------------------------------------


def _panel_cost_by_channel_pie() -> piechart.Panel:
    return _pie_panel(
        title="Cost by channel (azp)",
        expr=_usd(
            f"sum by ({LABEL_AZP}) (sum_over_time({_OVERALL_SELECTOR} "
            f"{_unwrap('gen_ai_usage_custom_total_cost')} [$__range]))"
        ),
        legend_label=f"{{{{{LABEL_AZP}}}}}",
        grid=(10, 8, 0, 54),
    )


def _panel_cost_user_by_channel_bar() -> bargauge.Panel:
    # topk over (display_name, azp) pairs → one bar per account-per-channel.
    # Legend "<user> · <channel>" is the literal answer to the breakdown ask.
    # sum_over_time can't take an inline by() (Loki limitation) — group via the
    # outer sum by; _unwrap extracts only the cost field so cardinality stays
    # bounded (same pattern as _panel_top_users_bar).
    _cost_sum = (
        f"sum_over_time({_OVERALL_SELECTOR} {_unwrap('gen_ai_usage_custom_total_cost')} [$__range])"
    )
    expr = f"topk(20, sum by ({LABEL_DISPLAY_NAME}, {LABEL_AZP}) ({_usd(_cost_sum)}))"
    return (
        bargauge.Panel()
        .title("Top 20 — cost by user per channel (selected range)")
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=10, w=16, x=8, y=54))
        .unit("currencyUSD")
        .orientation(cm.VizOrientation.HORIZONTAL)
        .reduce_options(cb.ReduceDataOptions().calcs(["lastNotNull"]).fields("").values(False))
        .display_mode(cm.BarGaugeDisplayMode.BASIC)
        .thresholds(_single_color_thresholds("green"))
        .with_target(
            _loki_target(
                expr,
                legend=f"{{{{{LABEL_DISPLAY_NAME}}}}} · {{{{{LABEL_AZP}}}}}",
                instant=False,
            )
        )
    )


def _panel_cost_per_channel_ts() -> timeseries.Panel:
    return (
        timeseries.Panel()
        .title("Cost per channel over time")
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=8, w=24, x=0, y=64))
        .unit("currencyUSD")
        .draw_style(cm.GraphDrawStyle.LINE)
        .line_interpolation(cm.LineInterpolation.SMOOTH)
        .fill_opacity(10.0)
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
            _loki_target(
                _usd(
                    f"sum by ({LABEL_AZP}) (sum_over_time({_OVERALL_SELECTOR} "
                    f"{_unwrap('gen_ai_usage_custom_total_cost')} [1m]))"
                ),
                legend=f"{{{{{LABEL_AZP}}}}}",
            )
        )
    )


# ---------------------------------------------------------------------------
# Top-level builder
# ---------------------------------------------------------------------------

_DESCRIPTION = (
    "Per-user activity for the Envoy AI Gateway. "
    "Data flows: JWT -> Authorino response headers (x-oidc-user-id, x-oidc-azp, "
    "x-oidc-email, x-oidc-name; full x-oidc-* contract in ADR-0011) -> "
    "Envoy access log JSON (OTLP attributes) -> "
    "Alloy loki.process 'ai_gateway_user_attribution' (flattens the envelope, "
    "promotes user_id/azp/model/email/display_name/billing_plan labels, "
    "pins service_name=envoy-ai-gateway; ADR-0046) -> Loki. "
    "Shows ATTRIBUTED traffic only — unauthenticated requests carry no identity labels. "
    "See docs/per-user-observability.md. "
    "GENERATED — source: tools/dashboards/envoy_ai_gateway/per_user.py."
)


def _dashboard() -> db.Dashboard:
    return (
        db.Dashboard("AI Gateway — per-user activity")
        .uid("envoy-ai-gateway-per-user")
        .tags(["ai-gateway", "per-user", "loki"])
        .description(_DESCRIPTION)
        .timezone("browser")
        .editable()
        .tooltip(dm.DashboardCursorSync.CROSSHAIR)
        .refresh("30s")
        .time("now-1h", "now")
        .with_variable(
            _query_var(
                name="azp",
                label="Client (azp)",
                definition=(f'label_values({{service_name="{GATEWAY_SERVICE_NAME}"}}, azp)'),
            )
        )
        .with_variable(
            _query_var(
                name="email",
                label="User (email)",
                definition=(
                    f'label_values({{service_name="{GATEWAY_SERVICE_NAME}", azp=~"$azp"}}, email)'
                ),
            )
        )
        .with_variable(
            _query_var(
                name="model",
                label="Model",
                definition=(f'label_values({{service_name="{GATEWAY_SERVICE_NAME}"}}, model)'),
            )
        )
        # Overview row
        .with_panel(_row("Overview", y=0))
        .with_panel(_panel_requests_range())
        .with_panel(_panel_unique_users())
        .with_panel(_panel_total_tokens())
        .with_panel(_panel_p95_latency())
        # Requests per user / minute
        .with_panel(_panel_requests_per_user())
        # Top 15 users by cost
        .with_panel(_panel_top_users_bar())
        # Per-user row
        .with_panel(_row("Per-User", y=23))
        .with_panel(_panel_user_total_cost())
        .with_panel(_panel_latency_per_user())
        .with_panel(_panel_user_model_by_requests())
        .with_panel(_panel_user_model_by_cost())
        .with_panel(_panel_user_model_by_tokens())
        .with_panel(_panel_user_status_codes())
        # Overall row
        .with_panel(_row("Overall", y=40))
        .with_panel(_panel_overall_model_by_requests())
        .with_panel(_panel_overall_model_by_cost())
        .with_panel(_panel_overall_model_by_tokens())
        .with_panel(_panel_overall_status_codes())
        .with_panel(_panel_overall_total_cost())
        .with_panel(_panel_overall_total_tokens())
        .with_panel(_panel_overall_total_requests())
        # Cost by channel row
        .with_panel(_row("Cost by Channel", y=53))
        .with_panel(_panel_cost_by_channel_pie())
        .with_panel(_panel_cost_user_by_channel_bar())
        .with_panel(_panel_cost_per_channel_ts())
    )


def build() -> dict:
    """Return the dashboard as a JSON-compatible dict."""
    return json.loads(json.dumps(_dashboard().build(), cls=JSONEncoder))
