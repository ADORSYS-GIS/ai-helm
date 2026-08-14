"""Envoy AI Gateway — per-user activity dashboard (GENERATED SOURCE).

This module is the *source of truth* for the dashboard JSON shipped at
``charts/observability-dashboards/files/envoy-ai-gateway/per-user.json``.
The JSON file is regenerated from this module — do **not** hand-edit it.

Regenerate with::

    make build
    # or
    uv run dashboards build

Architecture decision: see ``docs/adr/0008-python-dashboard-generation.md``.
Data path the dashboard consumes: ``docs/patterns/per-user-observability.md``.

Repointed to Mimir (ADR-0058): the cost/token/request/model/azp/display_name
panels and the email/azp/model variables read the precomputed
``loki_process_custom_gen_ai_*`` counters via PromQL ``increase()`` — instant
at any range on the rate-limited object store. The latency panels read the
``gen_ai_usage_duration`` histogram (same ADR-0058 stage). Only the two
status-code panels stay on Loki (response_code is deliberately not a Mimir
metric label — bounded ~15 values but multiplying it onto every stream is what
the per-user-observability doc avoided; see the panel docstrings).
"""

from __future__ import annotations

import json

from grafana_foundation_sdk.builders import bargauge, loki, piechart, timeseries
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
    METRIC_COST_MICRO_USD,
    METRIC_DURATION,
    METRIC_REQUESTS,
    METRIC_TOKENS,
)
from dashboards.envoy_ai_gateway import _shared as sh

# ---------------------------------------------------------------------------
# Module contract for the orchestrator (tools/dashboards/main.py)
# ---------------------------------------------------------------------------

OUTPUT_PATH: str = "charts/observability-dashboards/files/envoy-ai-gateway/per-user.json"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOKI_DS = dm.DataSourceRef(type_val="loki", uid=LOKI_UID)
_MIMIR_DS = dm.DataSourceRef(type_val="prometheus", uid=sh.MIMIR_DS.uid)

# Mimir metric selector filtered by all dashboard variables (per-user scope).
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
_SEL = sh.selector(
    f'{LABEL_AZP}=~"$azp"',
    f'{LABEL_EMAIL}=~"$email"',
    f'{LABEL_EMAIL}!~"(missing|unstamped):.*"',
    f'{LABEL_MODEL}=~"$model"',
)

# Metric selector that always spans ALL attributed users regardless of $email.
# user_id=~".+" (not email) so SA traffic is included in overall aggregates.
_OVERALL_SEL = sh.selector(
    f'{LABEL_AZP}=~"$azp"',
    f'{LABEL_USER_ID}=~".+"',
    f'{LABEL_MODEL}=~"$model"',
)

# Selector for the email variable — scoped to the selected azp (like the old
# Loki label_values), but against the Mimir metric (instant, no log scan).
_EMAIL_VAR_SEL = f'{{service_name="{GATEWAY_SERVICE_NAME}", {LABEL_AZP}=~"$azp"}}'


def _usd(expr: str) -> str:
    """Convert a raw micro-USD PromQL aggregation to USD for display.

    The pricing CEL (ai-model.costExpression, ADR-0028/ADR-0051) emits
    gen_ai_usage_custom_total_cost in micro-USD. Every cost panel must
    divide by 1e6 before applying the currencyUSD unit, or values display
    1,000,000x too large.
    """
    return sh.usd(expr)


def _latency_quantile(q: float, *, by: str = "") -> str:
    """`histogram_quantile(q, sum by (le[, by]) (rate(<dur>_bucket{sel}[5m])))`.

    Reads the ADR-0058 latency histogram from Mimir. `by` is an optional extra
    grouping label (e.g. email for the per-user latency panel). [5m] gives
    "current p95 latency" — same window the old Loki panel used.
    """
    group = f" by ({by}, le)" if by else " by (le)"
    return f"histogram_quantile({q}, sum{group} (rate({METRIC_DURATION}_bucket{_SEL}[5m])))"


# ---------------------------------------------------------------------------
# Loki helpers (status-code panels only)
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


def _loki_pie_panel(
    *,
    title: str,
    expr: str,
    legend_label: str,
    grid: tuple[int, int, int, int],
) -> piechart.Panel:
    # Range query (not instant): the Loki Grafana plugin does not substitute
    # $__range in instant queries, causing them to silently return no data.
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


# ---------------------------------------------------------------------------
# Overview stats  (y=0)
# ---------------------------------------------------------------------------


def _panel_requests_range() -> object:
    return sh.stat_panel(
        title="Requests (range)",
        expr=f"sum(increase({METRIC_REQUESTS}{_SEL}[$__range]))",
        unit="short",
        color="blue",
        grid=(4, 6, 0, 1),
    )


def _panel_unique_users() -> object:
    return sh.stat_panel(
        title="Unique users (range)",
        expr=f"count(sum by ({LABEL_EMAIL}) (increase({METRIC_REQUESTS}{_SEL}[$__range])))",
        unit="short",
        color="purple",
        grid=(4, 6, 6, 1),
    )


def _panel_total_tokens() -> object:
    return sh.stat_panel(
        title="Total tokens (range)",
        expr=f"sum(increase({METRIC_TOKENS}{_SEL}[$__range]))",
        unit="short",
        color="green",
        grid=(4, 6, 12, 1),
    )


def _panel_p95_latency() -> object:
    # [5m] window — "current p95 latency", same as the old Loki panel. Reads the
    # ADR-0058 latency histogram from Mimir (instant, no log scan).
    return sh.stat_panel(
        title="p95 latency (5m)",
        expr=_latency_quantile(0.95),
        unit="ms",
        color="green",
        grid=(4, 6, 18, 1),
    )


# ---------------------------------------------------------------------------
# Requests per user / minute  (y=4)
# ---------------------------------------------------------------------------


def _panel_requests_per_user() -> timeseries.Panel:
    return (
        timeseries.Panel()
        .title("Requests per user / minute")
        .datasource(_MIMIR_DS)
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
            sh.prom_target(
                # rate()[5m]*60 = requests per minute. NOT increase()[1m]: the
                # Mimir metrics are scraped every 60s, so a [1m] window holds
                # only 1 sample and increase() needs ≥2 → silent "no data"
                # (same trap as the cost-observability daily-bars note).
                f"sum by ({LABEL_EMAIL}) (rate({METRIC_REQUESTS}{_SEL}[5m]) * 60)",
                legend="{{email}}",
                instant=False,
            )
        )
    )


# ---------------------------------------------------------------------------
# Top 15 users by cost  (y=12)
# ---------------------------------------------------------------------------


def _panel_top_users_bar() -> bargauge.Panel:
    # label_replace extracts the first whitespace-delimited token from
    # display_name ("Kunga Derick" -> "Kunga") so 15 bars fit comfortably.
    # Uses _OVERALL_SEL so the ranking always reflects all users regardless of
    # the $email filter variable.
    _cost_sum = (
        f"sum by ({LABEL_DISPLAY_NAME}) (increase({METRIC_COST_MICRO_USD}{_OVERALL_SEL}[$__range]))"
    )
    expr = (
        f"label_replace("
        f"topk(15, {_usd(_cost_sum)}),"
        f'"given_name", "$1", "{LABEL_DISPLAY_NAME}", "^(\\\\S+).*"'
        f")"
    )
    return sh.bargauge_panel(
        title="Top 15 users — cost (selected range)",
        expr=expr,
        legend="{{given_name}}",
        unit="currencyUSD",
        color="blue",
        grid=(10, 24, 0, 13),
    )


# ---------------------------------------------------------------------------
# Per-user section  (y=22)
# ---------------------------------------------------------------------------


def _panel_user_total_cost() -> object:
    return sh.stat_panel(
        title="User — total cost",
        expr=_usd(f"sum(increase({METRIC_COST_MICRO_USD}{_SEL}[$__range]))"),
        unit="currencyUSD",
        color="orange",
        grid=(8, 12, 0, 24),
    )


def _panel_latency_per_user() -> timeseries.Panel:
    return (
        timeseries.Panel()
        .title("Latency per user — p50 / p95")
        .datasource(_MIMIR_DS)
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
            sh.prom_target(
                _latency_quantile(0.50, by=LABEL_EMAIL),
                legend="p50 {{email}}",
                ref_id="A",
                instant=False,
            )
        )
        .with_target(
            sh.prom_target(
                _latency_quantile(0.95, by=LABEL_EMAIL),
                legend="p95 {{email}}",
                ref_id="B",
                instant=False,
            )
        )
    )


def _panel_user_model_by_requests() -> object:
    return sh.pie_panel(
        title="User — model distribution (requests)",
        expr=f"sum by ({LABEL_MODEL}) (increase({METRIC_REQUESTS}{_SEL}[$__range]))",
        legend_label=f"{{{{{LABEL_MODEL}}}}}",
        grid=(8, 6, 0, 32),
    )


def _panel_user_model_by_cost() -> object:
    return sh.pie_panel(
        title="User — model distribution (cost $)",
        expr=_usd(f"sum by ({LABEL_MODEL}) (increase({METRIC_COST_MICRO_USD}{_SEL}[$__range]))"),
        legend_label=f"{{{{{LABEL_MODEL}}}}}",
        grid=(8, 6, 6, 32),
    )


def _panel_user_model_by_tokens() -> object:
    return sh.pie_panel(
        title="User — model distribution (tokens)",
        expr=f"sum by ({LABEL_MODEL}) (increase({METRIC_TOKENS}{_SEL}[$__range]))",
        legend_label=f"{{{{{LABEL_MODEL}}}}}",
        grid=(8, 6, 12, 32),
    )


def _panel_user_status_codes() -> piechart.Panel:
    # response_code is deliberately NOT a Mimir metric label (bounded ~15 values
    # but multiplying it onto every stream is what the per-user-observability
    # doc avoided). So this panel stays on Loki — it's a small part of the board.
    return _loki_pie_panel(
        title="User — status codes",
        expr=(
            f"sum by (response_code) ("
            f'count_over_time({{service_name="{GATEWAY_SERVICE_NAME}", {LABEL_AZP}=~"$azp",'
            f' {LABEL_EMAIL}=~"$email", {LABEL_EMAIL}!~"(missing|unstamped):.*",'
            f' {LABEL_MODEL}=~"$model"}} | json | response_code !~ "^(-|)$" [$__range])'
            f")"
        ),
        legend_label="{{response_code}}",
        grid=(8, 6, 18, 32),
    )


# ---------------------------------------------------------------------------
# Overall section  (y=38)
# ---------------------------------------------------------------------------


def _panel_overall_model_by_requests() -> object:
    return sh.pie_panel(
        title="Overall — model distribution (requests)",
        expr=f"sum by ({LABEL_MODEL}) (increase({METRIC_REQUESTS}{_OVERALL_SEL}[$__range]))",
        legend_label=f"{{{{{LABEL_MODEL}}}}}",
        grid=(8, 6, 0, 41),
    )


def _panel_overall_model_by_cost() -> object:
    return sh.pie_panel(
        title="Overall — model distribution (cost $)",
        expr=_usd(
            f"sum by ({LABEL_MODEL}) (increase({METRIC_COST_MICRO_USD}{_OVERALL_SEL}[$__range]))"
        ),
        legend_label=f"{{{{{LABEL_MODEL}}}}}",
        grid=(8, 6, 6, 41),
    )


def _panel_overall_model_by_tokens() -> object:
    return sh.pie_panel(
        title="Overall — model distribution (tokens)",
        expr=f"sum by ({LABEL_MODEL}) (increase({METRIC_TOKENS}{_OVERALL_SEL}[$__range]))",
        legend_label=f"{{{{{LABEL_MODEL}}}}}",
        grid=(8, 6, 12, 41),
    )


def _panel_overall_status_codes() -> piechart.Panel:
    # Same Loki-only rationale as _panel_user_status_codes.
    return _loki_pie_panel(
        title="Overall — status codes",
        expr=(
            f"sum by (response_code) ("
            f'count_over_time({{service_name="{GATEWAY_SERVICE_NAME}", {LABEL_AZP}=~"$azp",'
            f' {LABEL_USER_ID}=~".+", {LABEL_MODEL}=~"$model"}}'
            f' | json | response_code !~ "^(-|)$" [$__range])'
            f")"
        ),
        legend_label="{{response_code}}",
        grid=(8, 6, 18, 41),
    )


def _panel_overall_total_cost() -> object:
    return sh.stat_panel(
        title="Overall — total cost",
        expr=_usd(f"sum(increase({METRIC_COST_MICRO_USD}{_OVERALL_SEL}[$__range]))"),
        unit="currencyUSD",
        color="orange",
        grid=(4, 8, 0, 49),
    )


def _panel_overall_total_tokens() -> object:
    return sh.stat_panel(
        title="Overall — total tokens",
        expr=f"sum(increase({METRIC_TOKENS}{_OVERALL_SEL}[$__range]))",
        unit="short",
        color="green",
        grid=(4, 8, 8, 49),
    )


def _panel_overall_total_requests() -> object:
    return sh.stat_panel(
        title="Overall — total requests",
        expr=f"sum(increase({METRIC_REQUESTS}{_OVERALL_SEL}[$__range]))",
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
# gives the per-person / per-repo split the maintainer asked for.
# Uses _OVERALL_SEL so SERVICE traffic (azp != a human) is included.
# ---------------------------------------------------------------------------


def _panel_cost_by_channel_pie() -> object:
    return sh.pie_panel(
        title="Cost by channel (azp)",
        expr=_usd(
            f"sum by ({LABEL_AZP}) (increase({METRIC_COST_MICRO_USD}{_OVERALL_SEL}[$__range]))"
        ),
        legend_label=f"{{{{{LABEL_AZP}}}}}",
        grid=(10, 8, 0, 54),
    )


def _panel_cost_user_by_channel_bar() -> bargauge.Panel:
    # topk over (display_name, azp) pairs → one bar per account-per-channel.
    _cost_sum = f"sum by ({LABEL_DISPLAY_NAME}, {LABEL_AZP}) (increase({METRIC_COST_MICRO_USD}{_OVERALL_SEL}[$__range]))"
    expr = f"topk(20, {_usd(_cost_sum)})"
    return sh.bargauge_panel(
        title="Top 20 — cost by user per channel (selected range)",
        expr=expr,
        legend=f"{{{{{LABEL_DISPLAY_NAME}}}}} · {{{{{LABEL_AZP}}}}}",
        unit="currencyUSD",
        color="green",
        grid=(10, 16, 8, 54),
    )


def _panel_cost_per_channel_ts() -> timeseries.Panel:
    return (
        timeseries.Panel()
        .title("Cost per channel over time")
        .datasource(_MIMIR_DS)
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
            sh.prom_target(
                # rate()[5m]*60 = USD per minute. NOT increase()[1m] — same
                # 60s-scrape / ≥2-samples trap as the requests-per-user panel.
                _usd(
                    f"sum by ({LABEL_AZP}) (rate({METRIC_COST_MICRO_USD}{_OVERALL_SEL}[5m]) * 60)"
                ),
                legend=f"{{{{{LABEL_AZP}}}}}",
                instant=False,
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
    "pins service_name=envoy-ai-gateway; ADR-0046) -> Mimir (ADR-0058). "
    "Cost/token/request/model/azp/latency panels read the precomputed Mimir "
    "metrics (instant at any range); only the status-code panels stay on Loki. "
    "Shows ATTRIBUTED traffic only — unauthenticated requests carry no identity labels. "
    "See docs/patterns/per-user-observability.md. "
    "GENERATED — source: tools/dashboards/envoy_ai_gateway/per_user.py."
)


def _dashboard() -> db.Dashboard:
    return (
        db.Dashboard("AI Gateway — per-user activity")
        .uid("envoy-ai-gateway-per-user")
        .tags(["ai-gateway", "per-user", "mimir"])
        .description(_DESCRIPTION)
        .timezone("browser")
        .editable()
        .tooltip(dm.DashboardCursorSync.CROSSHAIR)
        .refresh("30s")
        .time("now-1h", "now")
        .with_variable(
            sh.multi_var(
                name="azp",
                label="Client (azp)",
                definition=sh.label_values(METRIC_REQUESTS, LABEL_AZP),
            )
        )
        .with_variable(
            sh.multi_var(
                name="email",
                label="User (email)",
                definition=sh.label_values(_EMAIL_VAR_SEL, LABEL_EMAIL),
            )
        )
        .with_variable(
            sh.multi_var(
                name="model",
                label="Model",
                definition=sh.label_values(METRIC_REQUESTS, LABEL_MODEL),
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
