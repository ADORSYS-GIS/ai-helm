"""Envoy AI Gateway — the gamified "App Scoreboard" (GENERATED SOURCE, ADR-0060).

Phase 3 of the cost-observability work (ADR-0058 captured the intent). A single
multi-panel "scoreboard for our apps" built on the SAME precomputed Mimir
metrics (ADR-0058 `loki_process_custom_gen_ai_*` counters) plus Tempo traces and
unified alerting — using Grafana visualizations the cost dashboards don't:
gauge, heatmap, histogram, alert-list, traces, news, text + a dashboard-list hub.

Design notes / deliberate omissions (see ADR-0060):
  - candlestick + flame-graph are DEFERRED: candlestick needs intra-day OHLC tick
    data and flame-graph needs Pyroscope-format profile frames; we only have
    daily counter aggregates in Mimir, so both would be synthetic. Not built.
  - the budget gauge measures against an editable `$budget` textbox variable
    (default DEFAULT_MONTHLY_BUDGET) so the "% of budget" framing is tunable live.
  - the news panel reads the AI-governance repo's GitHub commits Atom feed (the
    MkDocs site has no RSS); Grafana fetches it server-side → the Grafana pod
    needs github.com egress (added to the prod CiliumNetworkPolicy).

The JSON file is regenerated from this module — do **not** hand-edit it.

    uv run dashboards build

ADR: docs/adr/0060-gamified-app-scoreboard.md (+ ADR-0058, ADR-0008).
"""

from __future__ import annotations

import json

from grafana_foundation_sdk.builders import common as cb
from grafana_foundation_sdk.builders import (
    dashboard as db,
)
from grafana_foundation_sdk.builders import (
    dashboardlist,
    gauge,
    heatmap,
    histogram,
    news,
    tempo,
    text,
)
from grafana_foundation_sdk.cog.encoder import JSONEncoder
from grafana_foundation_sdk.models import common as cm
from grafana_foundation_sdk.models import dashboard as dm
from grafana_foundation_sdk.models import heatmap as hm
from grafana_foundation_sdk.models import text as tm

from dashboards._common import (
    DEFAULT_MONTHLY_BUDGET,
    GOVERNANCE_NEWS_FEED,
    GOVERNANCE_URL,
    LABEL_AZP,
    LABEL_BILLING_PLAN,
    LABEL_DISPLAY_NAME,
    LABEL_MODEL,
    METRIC_COST_MICRO_USD,
    METRIC_REQUESTS,
    METRIC_TOKENS,
    TEMPO_UID,
)
from dashboards.envoy_ai_gateway import _shared as sh

OUTPUT_PATH: str = "charts/observability-dashboards/files/envoy-ai-gateway/scoreboard.json"

TEMPO_DS = dm.DataSourceRef(type_val="tempo", uid=TEMPO_UID)

# Filters apply to every metric panel; the budget burn uses a fixed 30d window
# (monthly budget) regardless of the dashboard range.
_SEL = sh.selector('azp=~"$azp"', 'model=~"$model"')

_LEGEND_USER = "{{" + LABEL_DISPLAY_NAME + "}}"
_LEGEND_MODEL = "{{" + LABEL_MODEL + "}}"
_LEGEND_PLAN = "{{" + LABEL_BILLING_PLAN + "}}"
_LEGEND_AZP = "{{" + LABEL_AZP + "}}"


# ---------------------------------------------------------------------------
# Panel helpers for the visualization types not covered by _shared.py
# ---------------------------------------------------------------------------


def _budget_thresholds() -> db.ThresholdsConfig:
    """green < 70% < yellow < 90% < red — for the budget-burn gauge (percent)."""
    return (
        db.ThresholdsConfig()
        .mode(dm.ThresholdsMode.ABSOLUTE)
        .steps(
            [
                dm.Threshold(color="green"),
                dm.Threshold(value=70.0, color="yellow"),
                dm.Threshold(value=90.0, color="red"),
            ]
        )
    )


def _gauge_budget() -> gauge.Panel:
    # Percent of the editable monthly budget spent in the last 30 days. PromQL
    # substitutes $budget as a literal number, so dividing by it is valid.
    expr = f"100 * (sum(increase({METRIC_COST_MICRO_USD}{_SEL}[30d])) / 1e6) / $budget"
    return (
        gauge.Panel()
        .title("Monthly budget burn (last 30d)")
        .description(
            "Spend over the last 30 days as a % of the $budget variable (default $3000/mo)."
        )
        .datasource(sh.MIMIR_DS)
        .grid_pos(dm.GridPos(h=8, w=8, x=0, y=4))
        .unit("percent")
        .min(0.0)
        .max(120.0)
        .thresholds(_budget_thresholds())
        .show_threshold_markers(True)
        .reduce_options(cb.ReduceDataOptions().calcs(["lastNotNull"]).fields("").values(False))
        .with_target(sh.prom_target(expr, instant=True))
    )


def _heatmap_activity() -> heatmap.Panel:
    # Token-usage intensity over time, one Y-row per client (azp). calculate=False
    # → Grafana renders labeled series as heatmap rows ("rows from series"),
    # color = tokens in each hourly cell. The "intensity by hour/day" view.
    expr = f"sum by ({LABEL_AZP}) (increase({METRIC_TOKENS}{_SEL}[1h]))"
    return (
        heatmap.Panel()
        .title("Token-usage intensity by client (hourly)")
        .description("Tokens per hour per client (azp). Brighter = busier.")
        .datasource(sh.MIMIR_DS)
        .grid_pos(dm.GridPos(h=8, w=24, x=0, y=31))
        .calculate(False)
        .color(
            heatmap.HeatmapColorOptions()
            .mode(hm.HeatmapColorMode.SCHEME)
            .scheme("Oranges")
            .scale(hm.HeatmapColorScale.EXPONENTIAL)
            .steps(64)
        )
        .cell_values(heatmap.CellValues().unit("short"))
        .y_axis(heatmap.YAxisConfig().unit("short"))
        .mode(cm.TooltipDisplayMode.SINGLE)
        .show_legend()
        .with_target(sh.prom_target(expr, legend=_LEGEND_AZP, instant=False, interval="1h"))
    )


def _histogram_actor_cost() -> histogram.Panel:
    # Distribution of per-actor spend over the range: how many actors fall in each
    # cost bucket (the "where do you rank" gamified view). Instant per-actor totals.
    expr = sh.usd(
        f"sum by ({LABEL_DISPLAY_NAME}) (increase({METRIC_COST_MICRO_USD}{_SEL}[$__range]))"
    )
    return (
        histogram.Panel()
        .title("Per-actor spend distribution (range)")
        .description("Histogram of per-actor cost over the selected range.")
        .datasource(sh.MIMIR_DS)
        .grid_pos(dm.GridPos(h=8, w=12, x=0, y=23))
        .unit("currencyUSD")
        .fill_opacity(60)
        .legend(cb.VizLegendOptions().display_mode(cm.LegendDisplayMode.HIDDEN))
        .with_target(sh.prom_target(expr, instant=True))
    )


def _alertlist() -> db.Panel:
    # No dedicated SDK builder → base Panel with type=alertlist + options dict.
    # Surfaces firing/pending alerts from unified alerting (ADR-0059). No
    # datasource (alertlist reads Grafana's own alert state).
    options = {
        "showOptions": "current",
        "maxItems": 20,
        "sortOrder": 3,  # Importance
        "dashboardAlerts": False,
        "alertName": "",
        "dashboardTitle": "",
        "tags": [],
        "stateFilter": {
            "firing": True,
            "pending": True,
            "noData": False,
            "normal": False,
            "error": True,
        },
        "alertInstanceLabelFilter": "",
        "viewMode": "list",
        "groupMode": "default",
    }
    return (
        db.Panel()
        .type("alertlist")
        .title("Firing & pending alerts")
        .description("Live unified-alerting state (ADR-0059) — what's on fire right now.")
        .grid_pos(dm.GridPos(h=10, w=12, x=12, y=49))
        .options(options)
    )


def _traces() -> db.Panel:
    # No dedicated SDK builder → base Panel type=traces + a Tempo TraceQL search.
    # Shows recent gateway traces; click one to see the request data-flow
    # (LibreChat → Envoy → Authorino → model). Depends on traces flowing
    # (Alloy OTLP → Tempo, ADR-0046/observability audit §6) — empty if none.
    query = tempo.TempoQuery().query_type("traceql").query("{}").limit(20).ref_id("A")
    return (
        db.Panel()
        .type("traces")
        .title("Recent request traces (click → LibreChat→Envoy→Authorino→model flow)")
        .description("Recent traces from Tempo. Open one to inspect the per-request span flow.")
        .datasource(TEMPO_DS)
        .grid_pos(dm.GridPos(h=10, w=12, x=0, y=49))
        .with_target(query)
    )


def _dashboardlist_hub() -> dashboardlist.Panel:
    # The entry-point hub: links every AI-gateway-tagged dashboard.
    return (
        dashboardlist.Panel()
        .title("AI Gateway dashboards")
        .description("Jump to the cost / per-user / model dashboards.")
        .grid_pos(dm.GridPos(h=10, w=8, x=0, y=60))
        .tags(["ai-gateway"])
        .show_search(False)
        .show_starred(False)
        .show_headings(True)
        .show_recently_viewed(False)
        .max_items(20)
    )


def _news_governance() -> news.Panel:
    return (
        news.Panel()
        .title("AI governance — latest")
        .description("Recent commits to the AI-governance doctrine repo.")
        .grid_pos(dm.GridPos(h=10, w=8, x=8, y=60))
        .feed_url(GOVERNANCE_NEWS_FEED)
        .show_image(False)
    )


_GOVERNANCE_MD = (
    "### 🤝 AI Governance\n\n"
    "AI may accelerate the work, but **humans own intent, verification, and "
    "consequences**. AI output is not truth — review AI-generated code as "
    "untrusted, and never submit work you cannot explain.\n\n"
    f"📖 **Doctrine:** [{GOVERNANCE_URL}]({GOVERNANCE_URL})\n\n"
    "Every cost on this scoreboard is a real request someone made on our behalf. "
    "Spend it like it's yours. 🎯"
)


def _text_governance() -> text.Panel:
    return (
        text.Panel()
        .title("Play fair")
        .grid_pos(dm.GridPos(h=10, w=8, x=16, y=60))
        .mode(tm.TextMode.MARKDOWN)
        .content(_GOVERNANCE_MD)
    )


_HERO_MD = (
    "# 🏆 AI Gateway Scoreboard\n"
    "Who's using the platform, how much it costs, and how close we are to budget — "
    "live from the precomputed Mimir metrics (ADR-0058). "
    "Default window is **30 days**; pick a calendar month in the time picker for "
    "monthly totals. Filter by client & model up top. ⚡"
)


def _hero() -> text.Panel:
    return (
        text.Panel()
        .title("")
        .transparent(True)
        .grid_pos(dm.GridPos(h=4, w=24, x=0, y=0))
        .mode(tm.TextMode.MARKDOWN)
        .content(_HERO_MD)
    )


# ---------------------------------------------------------------------------
# Metric panels reusing the _shared cost helpers
# ---------------------------------------------------------------------------


def _stat_spend_30d() -> object:
    return sh.stat_panel(
        title="Spend (last 30d)",
        expr=sh.usd(f"sum(increase({METRIC_COST_MICRO_USD}{_SEL}[30d]))"),
        unit="currencyUSD",
        color="orange",
        grid=(4, 8, 8, 4),
    )


def _stat_budget_remaining() -> object:
    expr = f"$budget - (sum(increase({METRIC_COST_MICRO_USD}{_SEL}[30d])) / 1e6)"
    return sh.stat_panel(
        title="Budget remaining (of $budget)",
        expr=expr,
        unit="currencyUSD",
        color="green",
        grid=(4, 8, 16, 4),
    )


def _stat_requests_range() -> object:
    return sh.stat_panel(
        title="Requests (range)",
        expr=f"sum(increase({METRIC_REQUESTS}{_SEL}[$__range]))",
        unit="short",
        color="blue",
        grid=(4, 8, 8, 8),
    )


def _stat_active_actors() -> object:
    return sh.stat_panel(
        title="Active actors (range)",
        expr=f"count(sum by ({LABEL_DISPLAY_NAME}) (increase({METRIC_REQUESTS}{_SEL}[$__range])))",
        unit="short",
        color="purple",
        grid=(4, 8, 16, 8),
    )


def _bargauge_top_actors() -> object:
    inner = sh.usd(
        f"sum by ({LABEL_DISPLAY_NAME}) (increase({METRIC_COST_MICRO_USD}{_SEL}[$__range]))"
    )
    return sh.bargauge_panel(
        title="🥇 Top actors by spend (range)",
        expr=f"topk(15, {inner})",
        legend=_LEGEND_USER,
        unit="currencyUSD",
        color="orange",
        grid=(9, 12, 0, 13),
    )


def _bargauge_top_models() -> object:
    inner = sh.usd(f"sum by ({LABEL_MODEL}) (increase({METRIC_COST_MICRO_USD}{_SEL}[$__range]))")
    return sh.bargauge_panel(
        title="🤖 Top models by spend (range)",
        expr=f"topk(15, {inner})",
        legend=_LEGEND_MODEL,
        unit="currencyUSD",
        color="blue",
        grid=(9, 12, 12, 13),
    )


def _pie_plan_share() -> object:
    expr = sh.usd(
        f"sum by ({LABEL_BILLING_PLAN}) (increase({METRIC_COST_MICRO_USD}{_SEL}[$__range]))"
    )
    return sh.pie_panel(
        title="Spend share by billing plan (range)",
        expr=expr,
        legend_label=_LEGEND_PLAN,
        grid=(8, 12, 12, 23),
    )


def _bars_daily_cost() -> object:
    expr = sh.usd(f"sum(increase({METRIC_COST_MICRO_USD}{_SEL}[1d]))")
    return sh.daily_bars_panel(
        title="💓 Daily spend heartbeat (total)",
        expr=expr,
        legend="total",
        unit="currencyUSD",
        grid=(8, 24, 0, 40),
        legend_calcs=["mean", "max", "sum"],
    )


def _budget_var() -> db.TextBoxVariable:
    return (
        db.TextBoxVariable("budget")
        .label("Monthly budget ($)")
        .default_value(str(DEFAULT_MONTHLY_BUDGET))
        .current(
            dm.VariableOption(
                selected=True, text=str(DEFAULT_MONTHLY_BUDGET), value=str(DEFAULT_MONTHLY_BUDGET)
            )
        )
    )


_DESCRIPTION = (
    "The gamified 'App Scoreboard' for the Envoy AI Gateway (ADR-0060, Phase 3): "
    "budget-burn gauge, leaderboards, token-intensity heatmap, per-actor spend "
    "histogram, daily-spend heartbeat, plan-share pie, firing-alerts list, Tempo "
    "request traces, a dashboard-list hub, and AI-governance news/narration — all "
    "on the precomputed Mimir metrics (ADR-0058) + Tempo + unified alerting. "
    "Budget is the editable $budget variable (default $3000/mo). candlestick + "
    "flame-graph are deferred (need OHLC tick / profile-frame data we don't have). "
    "GENERATED — source: tools/dashboards/envoy_ai_gateway/scoreboard.py."
)


def _dashboard() -> db.Dashboard:
    return (
        db.Dashboard("AI Gateway — App Scoreboard")
        .uid("envoy-ai-gateway-scoreboard")
        .tags(["ai-gateway", "scoreboard", "cost", "mimir", "gamified"])
        .description(_DESCRIPTION)
        .timezone("browser")
        .editable()
        .tooltip(dm.DashboardCursorSync.CROSSHAIR)
        .refresh("5m")
        .time("now-30d", "now")
        .with_variable(_budget_var())
        .with_variable(
            sh.multi_var(
                name="azp",
                label="Client (azp)",
                definition=sh.label_values(METRIC_REQUESTS, LABEL_AZP),
            )
        )
        .with_variable(
            sh.multi_var(
                name="model",
                label="Model",
                definition=sh.label_values(METRIC_REQUESTS, LABEL_MODEL),
            )
        )
        # Hero banner + headline tiles
        .with_panel(_hero())
        .with_panel(sh.row("Headline", y=3))
        .with_panel(_gauge_budget())
        .with_panel(_stat_spend_30d())
        .with_panel(_stat_budget_remaining())
        .with_panel(_stat_requests_range())
        .with_panel(_stat_active_actors())
        # Leaderboards
        .with_panel(sh.row("Leaderboards", y=12))
        .with_panel(_bargauge_top_actors())
        .with_panel(_bargauge_top_models())
        # Distributions
        .with_panel(sh.row("Distributions", y=22))
        .with_panel(_histogram_actor_cost())
        .with_panel(_pie_plan_share())
        .with_panel(_heatmap_activity())
        # Daily heartbeat
        .with_panel(sh.row("Daily heartbeat", y=39))
        .with_panel(_bars_daily_cost())
        # Health & flow
        .with_panel(sh.row("Health & data-flow", y=48))
        .with_panel(_traces())
        .with_panel(_alertlist())
        # Hub & governance
        .with_panel(sh.row("Hub & governance", y=59))
        .with_panel(_dashboardlist_hub())
        .with_panel(_news_governance())
        .with_panel(_text_governance())
    )


def build() -> dict:
    return json.loads(json.dumps(_dashboard().build(), cls=JSONEncoder))
