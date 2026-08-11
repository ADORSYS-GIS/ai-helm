"""Envoy AI Gateway — usage by CLIENT (GENERATED SOURCE).

Which AI coding tool is talking to the gateway, through which credential, and
how reliably. Every other gateway dashboard slices by user, model or cost;
none of them slice by the client TOOL, because `user-agent` is the one useful
field Alloy does not promote to a Loki label (ADR-0046 promotes user_id / azp
/ model / email / display_name / billing_plan, not user-agent).

That makes this the only view that answers "is anyone actually using the
governed CLI path?" — `azp = governance-auth-cli` is the credential
`governance-auth` issues (lightbridge-governance ADR-0010), so
client x azp is the adoption metric for it. A single client appearing under
two azp values means part of its traffic bypasses governance-auth.

⚠️ LOKI LOG-SCAN, not the precomputed Mimir metrics the cost dashboards use
(ADR-0058). Those counters carry only the promoted labels, so they cannot
answer a user-agent question at all. Keep the default range modest for that
reason — this pays the object-store scan the metric-backed dashboards avoid.

⚠️ `user-agent` is HYPHENATED in the access log, so it needs the bracket form
(`| json user_agent=`["user-agent"]``). A bare `| json user_agent` extracts
nothing, silently, and ships an empty panel with no error anywhere.

⚠️ Every panel is a RANGE query, including the stat/table ones. The Loki
Grafana plugin does not substitute `$__range` in INSTANT queries — they
silently return no data (same trap per_user.py documents).

The JSON file is regenerated from this module — do **not** hand-edit it.

    uv run dashboards build

ADR: docs/adr/0008-python-dashboard-generation.md, docs/adr/0046-*.
"""

from __future__ import annotations

import json

from grafana_foundation_sdk.builders import bargauge, loki, stat, timeseries
from grafana_foundation_sdk.builders import common as cb
from grafana_foundation_sdk.builders import dashboard as db
from grafana_foundation_sdk.cog.encoder import JSONEncoder
from grafana_foundation_sdk.models import common as cm
from grafana_foundation_sdk.models import dashboard as dm

from dashboards._common import (
    COLOR_BLUE,
    COLOR_GREEN,
    COLOR_ORANGE,
    COLOR_PURPLE,
    COLOR_RED,
    GATEWAY_SERVICE_NAME,
    LABEL_AZP,
    LABEL_MODEL,
    LOKI_UID,
)
from dashboards.envoy_ai_gateway import _shared as sh

OUTPUT_PATH: str = "charts/observability-dashboards/files/envoy-ai-gateway/by-client.json"

_LOKI_DS = dm.DataSourceRef(type_val="loki", uid=LOKI_UID)

# Stream anchor + the promoted-label filters the template variables drive.
# `user-agent` is NOT a label, so it can only be filtered after `| json`.
_STREAM = f'{{service_name="{GATEWAY_SERVICE_NAME}", {LABEL_AZP}=~"$azp", {LABEL_MODEL}=~"$model"}}'

# Extracts the client string. Bracket form is load-bearing — see module docstring.
_UA = '| json user_agent=`["user-agent"]`'
# Response code is a plain top-level field, so a bare extraction is correct here.
_CODE = "| json code=`response_code`"

_LEGEND_UA = "{{user_agent}}"
_LEGEND_AZP = "{{" + LABEL_AZP + "}}"


def _loki_target(
    expr: str,
    *,
    legend: str = "",
    ref_id: str = "A",
) -> loki.Dataquery:
    """Always a RANGE query — see the `$__range` trap in the module docstring."""
    q = loki.Dataquery().expr(expr).ref_id(ref_id).query_type("range").datasource(_LOKI_DS)
    if legend:
        q = q.legend_format(legend)
    return q


def _thresholds(color: str) -> db.ThresholdsConfig:
    return db.ThresholdsConfig().mode(dm.ThresholdsMode.ABSOLUTE).steps([dm.Threshold(color=color)])


def _stat(
    *,
    title: str,
    expr: str,
    color: str,
    grid: tuple[int, int, int, int],
    unit: str = "short",
    description: str = "",
) -> stat.Panel:
    h, w, x, y = grid
    return (
        stat.Panel()
        .title(title)
        .description(description)
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


def _timeseries(
    *,
    title: str,
    expr: str,
    legend: str,
    grid: tuple[int, int, int, int],
    unit: str = "short",
    stacked: bool = False,
    description: str = "",
) -> timeseries.Panel:
    h, w, x, y = grid
    panel = (
        timeseries.Panel()
        .title(title)
        .description(description)
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=h, w=w, x=x, y=y))
        .unit(unit)
        .fill_opacity(15)
        .line_width(1)
        .legend(
            cb.VizLegendOptions()
            .display_mode(cm.LegendDisplayMode.TABLE)
            .placement(cm.LegendPlacement.RIGHT)
            .calcs(["sum"])
        )
        .tooltip(cb.VizTooltipOptions().mode(cm.TooltipDisplayMode.MULTI))
        .with_target(_loki_target(expr, legend=legend))
    )
    if stacked:
        panel = panel.stacking(cb.StackingConfig().mode(cm.StackingMode.NORMAL))
    return panel


def _bargauge(
    *,
    title: str,
    expr: str,
    legend: str,
    grid: tuple[int, int, int, int],
    color: str = COLOR_BLUE,
    unit: str = "short",
    description: str = "",
) -> bargauge.Panel:
    """Ranked horizontal bars.

    Deliberately NOT a `table.Panel`: every table in this package is
    Prometheus- or SQL-backed, because a Loki table needs an INSTANT query to
    render one row per series -- and instant queries silently drop `$__range`
    (see the module docstring). Bargauge takes a range query and reduces to the
    last value, which is the same trap per_user.py documents and works around.
    """
    h, w, x, y = grid
    return (
        bargauge.Panel()
        .title(title)
        .description(description)
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=h, w=w, x=x, y=y))
        .unit(unit)
        .orientation(cm.VizOrientation.HORIZONTAL)
        .reduce_options(cb.ReduceDataOptions().calcs(["lastNotNull"]).fields("").values(False))
        .display_mode(cm.BarGaugeDisplayMode.BASIC)
        .thresholds(_thresholds(color))
        .with_target(_loki_target(expr, legend=legend))
    )


# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------


def _panel_requests() -> stat.Panel:
    return _stat(
        title="Requests",
        expr=f"sum(count_over_time({_STREAM} [$__range]))",
        color=COLOR_BLUE,
        grid=(4, 6, 0, 1),
        description="Every request the gateway served in range, all clients.",
    )


def _panel_distinct_clients() -> stat.Panel:
    return _stat(
        title="Distinct clients",
        expr=f"count(sum by (user_agent) (count_over_time({_STREAM} {_UA} [$__range])))",
        color=COLOR_PURPLE,
        grid=(4, 6, 6, 1),
        description=(
            "Distinct user-agent strings. Each CLI VERSION counts separately "
            "(opencode ships many), so this reads higher than 'distinct tools'."
        ),
    )


def _panel_tokens() -> stat.Panel:
    return _stat(
        title="Tokens",
        expr=(
            f"sum(sum_over_time({_STREAM} "
            '| json tot=`["gen_ai.usage.total_tokens"]` '
            '| unwrap tot | __error__="" [$__range]))'
        ),
        color=COLOR_GREEN,
        grid=(4, 6, 12, 1),
        description="Total tokens across all clients in range.",
    )


def _panel_error_requests() -> stat.Panel:
    return _stat(
        title="Non-2xx responses",
        expr=f'sum(count_over_time({_STREAM} {_CODE} | code!~"2.." [$__range]))',
        color=COLOR_RED,
        grid=(4, 6, 18, 1),
        description=(
            "Client-visible failures. A 404 here is usually a model the gateway "
            "does not serve — a CLI's built-in default model that does not exist "
            "upstream produces exactly this."
        ),
    )


def _panel_requests_by_client() -> timeseries.Panel:
    return _timeseries(
        title="Requests by client",
        expr=f"sum by (user_agent) (count_over_time({_STREAM} {_UA} [$__interval]))",
        legend=_LEGEND_UA,
        grid=(9, 24, 0, 5),
        stacked=True,
        description=(
            "Adoption over time per client — the panel that shows a newly "
            "onboarded CLI appearing against the established ones."
        ),
    )


def _panel_clients_table() -> bargauge.Panel:
    return _bargauge(
        title="Top clients by request count",
        expr=f"topk(15, sum by (user_agent) (count_over_time({_STREAM} {_UA} [$__range])))",
        legend=_LEGEND_UA,
        color=COLOR_BLUE,
        grid=(9, 12, 0, 14),
        description="Ranked client list for the selected range.",
    )


def _panel_tokens_by_client() -> bargauge.Panel:
    return _bargauge(
        title="Top clients by tokens",
        expr=(
            "topk(15, sum by (user_agent) (sum_over_time("
            f'{_STREAM} {_UA}, tot=`["gen_ai.usage.total_tokens"]` '
            '| unwrap tot | __error__="" [$__range])))'
        ),
        legend=_LEGEND_UA,
        color=COLOR_GREEN,
        grid=(9, 12, 12, 14),
        description=(
            "Consumption, not call count — a client with few calls can still dominate spend."
        ),
    )


def _panel_requests_by_azp() -> timeseries.Panel:
    return _timeseries(
        title="Requests by credential (azp)",
        expr=f"sum by ({LABEL_AZP}) (count_over_time({_STREAM} [$__interval]))",
        legend=_LEGEND_AZP,
        grid=(8, 24, 0, 23),
        stacked=True,
        description=(
            "`azp` identifies WHICH credential was used, not who used it. "
            "`governance-auth-cli` is the governed path issued by "
            "governance-auth (lightbridge-governance ADR-0010); anything else "
            "is a long-lived API key or a client's own registration. This "
            "ratio is the adoption metric for governance-auth itself."
        ),
    )


def _panel_client_x_credential() -> bargauge.Panel:
    return _bargauge(
        title="Client x credential",
        expr=(
            f"topk(20, sum by (user_agent, {LABEL_AZP}) "
            f"(count_over_time({_STREAM} {_UA} [$__range])))"
        ),
        legend="{{user_agent}} via {{" + LABEL_AZP + "}}",
        color=COLOR_PURPLE,
        grid=(9, 12, 0, 31),
        description=(
            "The join that answers 'is this tool going through the governed "
            "path?'. One client under two azp values means part of its traffic "
            "bypasses governance-auth."
        ),
    )


def _panel_models_by_client() -> bargauge.Panel:
    return _bargauge(
        title="Models by client",
        expr=(
            f"topk(20, sum by (user_agent, {LABEL_MODEL}) "
            f"(count_over_time({_STREAM} {_UA} [$__range])))"
        ),
        legend="{{user_agent}} -> {{" + LABEL_MODEL + "}}",
        color=COLOR_ORANGE,
        grid=(9, 12, 12, 31),
        description="Which models each client actually asks for.",
    )


def _panel_errors_by_client() -> timeseries.Panel:
    return _timeseries(
        title="Non-2xx by client",
        expr=(
            f"sum by (user_agent, code) (count_over_time({_STREAM} {_UA}, "
            f'code=`response_code` | code!~"2.." [$__interval]))'
        ),
        legend="{{user_agent}} {{code}}",
        grid=(8, 12, 0, 40),
        description="Failures attributed to the client that caused them.",
    )


def _panel_latency_by_client() -> timeseries.Panel:
    return _timeseries(
        title="p95 latency by client",
        expr=(
            f"quantile_over_time(0.95, {_STREAM} {_UA}, duration "
            '| unwrap duration | __error__="" [5m]) by (user_agent)'
        ),
        legend=_LEGEND_UA,
        grid=(8, 12, 12, 40),
        unit="ms",
        description="Gateway-observed p95, per client.",
    )


def _panel_codes_table() -> bargauge.Panel:
    return _bargauge(
        title="Response codes by client",
        expr=(
            "topk(20, sum by (user_agent, code) (count_over_time("
            f"{_STREAM} {_UA}, code=`response_code` [$__range])))"
        ),
        legend="{{user_agent}} {{code}}",
        color=COLOR_RED,
        grid=(9, 24, 0, 48),
        description=(
            "Full breakdown including 2xx, so a client's success RATE is "
            "readable rather than inferred from the error panel alone."
        ),
    )


_DESCRIPTION = (
    "Which AI coding client talks to the Envoy AI Gateway, through which "
    "credential (azp), and how reliably. The only gateway dashboard keyed on "
    "`user-agent` — Alloy does not promote it to a Loki label (ADR-0046), so "
    "this is a Loki log-scan rather than a precomputed-metric read (ADR-0058); "
    "keep the range modest. `azp=governance-auth-cli` is the governed CLI path "
    "(lightbridge-governance ADR-0010), so client x credential is its adoption "
    "metric. GENERATED — source: tools/dashboards/envoy_ai_gateway/by_client.py."
)


def _var(name: str, label: str, definition: str) -> db.QueryVariable:
    """Loki query variable — same shape per_user.py uses (plain string query,
    `.+` all-value so the `=~"$azp"` selector matches everything by default)."""
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


def _dashboard() -> db.Dashboard:
    return (
        db.Dashboard("AI Gateway — by client")
        .uid("envoy-ai-gateway-by-client")
        .tags(["ai-gateway", "client", "adoption", "loki"])
        .description(_DESCRIPTION)
        .timezone("browser")
        .editable()
        .tooltip(dm.DashboardCursorSync.CROSSHAIR)
        .refresh("5m")
        .time("now-24h", "now")
        .with_variable(
            _var(
                "azp",
                "Client (azp)",
                f'label_values({{service_name="{GATEWAY_SERVICE_NAME}"}}, {LABEL_AZP})',
            )
        )
        .with_variable(
            _var(
                "model",
                "Model",
                f'label_values({{service_name="{GATEWAY_SERVICE_NAME}"}}, {LABEL_MODEL})',
            )
        )
        .with_panel(sh.row("Which AI clients are being used", y=0))
        .with_panel(_panel_requests())
        .with_panel(_panel_distinct_clients())
        .with_panel(_panel_tokens())
        .with_panel(_panel_error_requests())
        .with_panel(_panel_requests_by_client())
        .with_panel(_panel_clients_table())
        .with_panel(_panel_tokens_by_client())
        .with_panel(sh.row("Which credential path (governed vs not)", y=22))
        .with_panel(_panel_requests_by_azp())
        .with_panel(_panel_client_x_credential())
        .with_panel(_panel_models_by_client())
        .with_panel(sh.row("Reliability", y=39))
        .with_panel(_panel_errors_by_client())
        .with_panel(_panel_latency_by_client())
        .with_panel(_panel_codes_table())
    )


def build() -> dict:
    return json.loads(json.dumps(_dashboard().build(), cls=JSONEncoder))
