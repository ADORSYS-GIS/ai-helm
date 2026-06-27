"""Envoy AI Gateway — rate-limit quota (GENERATED SOURCE).

Shows WHO is consuming the gateway and HOW MUCH of their budget, read straight
from the rate-limit service's LIVE counters in redis-ha — the only place that
state exists (Mimir/Loki hold historical cost, not the limiter's current-window
budget; ADR-0070). Two read paths over the SAME Redis keys:

  1. Mimir leaderboard (the numbers). prometheus-redis-exporter SCANs the
     monthly-budget keys and exports `gateway_ratelimit_spend_micro_usd` with
     parsed account_id / model / plan / plane / window labels. These panels rank
     spend per account and per model for the selected 30-day budget window.
  2. Redis census (the live "who's active right now"). A `redis-datasource`
     tmscan straight against redis-ha — zero scrape-lag, the limiter's own view.

RAW consumption only (no quota/% overlay): the budget LIMITS live in static Helm
config (free $50/mo, pro $200, per-model overrides — charts/ai-models) and a
user's plan isn't on the key, so a precise "% of quota" can't be derived here.
The value shown is micro-USD spent this window (÷1e6 → USD).

`window` is the 30-day budget bucket start (Unix epoch, a multiple of 2592000s).
The $window picker defaults to the newest (current) bucket; the previous bucket
lingers until its TTL, so pick it to see last period.

The JSON file is regenerated from this module — do **not** hand-edit it::

    uv run dashboards build

ADR: docs/adr/0070-ratelimit-quota-observability.md (+ ADR-0008).
"""

from __future__ import annotations

import json
import typing

from grafana_foundation_sdk.builders import dashboard as db
from grafana_foundation_sdk.builders import table
from grafana_foundation_sdk.cog.encoder import JSONEncoder
from grafana_foundation_sdk.models import dashboard as dm

from dashboards._common import (
    METRIC_RATELIMIT_SPEND_MICRO_USD,
    REDIS_RATELIMIT_UID,
    RL_LABEL_ACCOUNT,
    RL_LABEL_MODEL,
    RL_LABEL_PLAN,
    RL_LABEL_PLANE,
    RL_LABEL_WINDOW,
)
from dashboards.envoy_ai_gateway import _shared as sh

OUTPUT_PATH: str = "charts/observability-dashboards/files/envoy-ai-gateway/ratelimit-quota.json"

_M = METRIC_RATELIMIT_SPEND_MICRO_USD
_A = RL_LABEL_ACCOUNT
_MO = RL_LABEL_MODEL
_PL = RL_LABEL_PLAN
_PE = RL_LABEL_PLANE

# All filters refine the same metric. $window is single-select (default newest)
# so totals are for ONE budget period; the rest are multi (default All → .+).
_SEL = f'{{{RL_LABEL_WINDOW}=~"$window", {_PL}=~"$plan", {_MO}=~"$model", {_A}=~"$account"}}'
_MSEL = f"{_M}{_SEL}"

_LEGEND_ACCOUNT = "{{" + _A + "}}"
_LEGEND_MODEL = "{{" + _MO + "}}"

_REDIS_DS = dm.DataSourceRef(type_val="redis-datasource", uid=REDIS_RATELIMIT_UID)


class _RedisTmscanTarget:
    """Minimal builder for a redis-datasource `tmscan` target.

    The SDK ships no redis-datasource query builder, but table.Panel.with_target
    only calls `.build()` and the cog JSONEncoder serialises a plain dict (same
    trick as user_directory's `_SqlTarget`). `command: tmscan` SCANs keys matching
    `match` and returns a frame with `key` / `type` / `memory` columns; the
    account/model are then carved out of `key` by an extractFields transform.
    """

    def __init__(self, *, ref_id: str, match: str, count: int = 2000, size: int = 2000) -> None:
        self._d: dict[str, typing.Any] = {
            "refId": ref_id,
            "datasource": {"type": "redis-datasource", "uid": REDIS_RATELIMIT_UID},
            "type": "command",
            "command": "tmscan",
            "match": match,
            "count": count,
            "size": size,
        }

    def build(self) -> dict[str, typing.Any]:
        return self._d


# ── Mimir leaderboard (the numbers) ────────────────────────────────────────────
def _panel_total_spend() -> object:
    return sh.stat_panel(
        title="Total spend — this window",
        expr=sh.usd(f"sum({_MSEL})"),
        unit="currencyUSD",
        color="orange",
        grid=(4, 6, 0, 1),
    )


def _panel_active_accounts() -> object:
    return sh.stat_panel(
        title="Active accounts",
        expr=f"count(count by ({_A}) ({_MSEL}))",
        unit="short",
        color="blue",
        grid=(4, 6, 6, 1),
    )


def _panel_counters() -> object:
    return sh.stat_panel(
        title="Tracked counters (account x model)",
        expr=f"count({_MSEL})",
        unit="short",
        color="purple",
        grid=(4, 6, 12, 1),
    )


def _panel_models() -> object:
    return sh.stat_panel(
        title="Models in use",
        expr=f"count(count by ({_MO}) ({_MSEL}))",
        unit="short",
        color="green",
        grid=(4, 6, 18, 1),
    )


def _panel_top_accounts() -> object:
    return sh.bargauge_panel(
        title="Top accounts by spend — this window",
        expr=sh.usd(f"topk(20, sum by ({_A}) ({_MSEL}))"),
        legend=_LEGEND_ACCOUNT,
        unit="currencyUSD",
        color="orange",
        grid=(12, 12, 0, 5),
    )


def _panel_spend_by_model() -> object:
    return sh.pie_panel(
        title="Spend share by model — this window",
        expr=sh.usd(f"sum by ({_MO}) ({_MSEL})"),
        legend_label=_LEGEND_MODEL,
        grid=(12, 12, 12, 5),
    )


def _panel_breakdown_table() -> table.Panel:
    # One row per account x model x plan x plane, instant → table, ranked by spend.
    expr = sh.usd(f"sum by ({_A}, {_MO}, {_PL}, {_PE}) ({_MSEL})")
    panel = (
        table.Panel()
        .title("Consumption by account x model — this window")
        .datasource(sh.MIMIR_DS)
        .grid_pos(dm.GridPos(h=12, w=24, x=0, y=17))
        .filterable(True)
        .with_target(sh.prom_target(expr, ref_id="A", instant=True, fmt="table"))
        .with_transformation(
            dm.DataTransformerConfig(
                id_val="organize",
                options={
                    "renameByName": {
                        _A: "Account",
                        _MO: "Model",
                        _PL: "Plan",
                        _PE: "Plane",
                        "Value #A": "Spend ($)",
                    },
                    "excludeByName": {"Time": True, RL_LABEL_WINDOW: True},
                    "indexByName": {
                        _A: 0,
                        _MO: 1,
                        _PL: 2,
                        _PE: 3,
                        "Value #A": 4,
                    },
                },
            )
        )
        .with_transformation(
            dm.DataTransformerConfig(
                id_val="sortBy",
                options={"fields": {}, "sort": [{"field": "Spend ($)", "desc": True}]},
            )
        )
    )
    return panel.override_by_name(
        "Spend ($)",
        [
            dm.DynamicConfigValue(id_val="unit", value="currencyUSD"),
            dm.DynamicConfigValue(id_val="decimals", value=4),
        ],
    )


def _panel_spend_over_time() -> object:
    # The gauge over time — accumulation within the window, per top account.
    expr = sh.usd(f"topk(10, sum by ({_A}) ({_MSEL}))")
    return sh.daily_bars_panel(
        title="Spend over time — top accounts",
        expr=expr,
        legend=_LEGEND_ACCOUNT,
        unit="currencyUSD",
        grid=(10, 24, 0, 30),
        legend_calcs=["last", "max"],
    )


# ── Redis census (the live "who's active now") ─────────────────────────────────
def _panel_live_census() -> table.Panel:
    # Direct redis-datasource tmscan of the per-account counter keys (any
    # *-match-0* = an x-account-id-keyed budget/burst counter). Zero scrape-lag,
    # the limiter's own current view. extractFields carves Account + Model out of
    # the raw key (JS RegExp named groups — this transform runs in the browser).
    return (
        table.Panel()
        .title("Live limiter counters — direct from Redis (zero scrape-lag)")
        .datasource(_REDIS_DS)
        .grid_pos(dm.GridPos(h=12, w=24, x=0, y=41))
        .filterable(True)
        .with_target(_RedisTmscanTarget(ref_id="A", match="*-match-0*"))
        .with_transformation(
            dm.DataTransformerConfig(
                id_val="extractFields",
                options={
                    "source": "key",
                    "format": "regex",
                    "regExp": (
                        r"/converse/(?<Model>[^/]+)/.*"
                        r"_rule-\d+-match-0_(?<Account>.+?)_rule-\d+-match-1"
                    ),
                    "keepFields": True,
                },
            )
        )
        .with_transformation(
            dm.DataTransformerConfig(
                id_val="organize",
                options={
                    "renameByName": {"key": "Redis key"},
                    "excludeByName": {"type": True, "memory": True, "cursor": True, "count": True},
                    "indexByName": {"Account": 0, "Model": 1, "Redis key": 2},
                },
            )
        )
    )


_DESCRIPTION = (
    "WHO is consuming the Envoy AI Gateway and HOW MUCH of their budget, read from "
    "the rate-limit service's LIVE counters in redis-ha (ADR-0070) — the only place "
    "that current-window state exists. Mimir panels rank spend per account/model "
    "for the selected 30-day budget window (prometheus-redis-exporter → "
    "gateway_ratelimit_spend_micro_usd, ÷1e6 → USD); the bottom table is a direct "
    "redis-datasource census (zero scrape-lag). RAW consumption only — budget "
    "limits are static Helm config (ADR-0021/0035), not derivable per-user here. "
    "$window defaults to the current bucket. Filters: plan, model, account. "
    "GENERATED — source: tools/dashboards/envoy_ai_gateway/ratelimit_quota.py."
)


def _window_var() -> db.QueryVariable:
    # Single-select, newest-first (NUMERICAL_DESC) so the current 30-day bucket is
    # the default. No "All" — totals must be for ONE budget period.
    return (
        db.QueryVariable("window")
        .label("Budget window (30-day bucket)")
        .datasource(sh.MIMIR_DS)
        .query(sh.label_values(_M, RL_LABEL_WINDOW))
        .refresh(dm.VariableRefresh.ON_TIME_RANGE_CHANGED)
        .sort(dm.VariableSort.NUMERICAL_DESC)
        .multi(False)
        .include_all(False)
    )


def _dashboard() -> db.Dashboard:
    return (
        db.Dashboard("AI Gateway — rate-limit quota")
        .uid("envoy-ai-gateway-ratelimit-quota")
        .tags(["ai-gateway", "rate-limit", "quota", "redis"])
        .description(_DESCRIPTION)
        .timezone("browser")
        .editable()
        .tooltip(dm.DashboardCursorSync.CROSSHAIR)
        .refresh("1m")
        .time("now-30d", "now")
        .with_variable(_window_var())
        .with_variable(sh.multi_var(name="plan", label="Plan", definition=sh.label_values(_M, _PL)))
        .with_variable(
            sh.multi_var(name="model", label="Model", definition=sh.label_values(_M, _MO))
        )
        .with_variable(
            sh.multi_var(name="account", label="Account", definition=sh.label_values(_M, _A))
        )
        .with_panel(sh.row("Live budget consumption — selected window", y=0))
        .with_panel(_panel_total_spend())
        .with_panel(_panel_active_accounts())
        .with_panel(_panel_counters())
        .with_panel(_panel_models())
        .with_panel(_panel_top_accounts())
        .with_panel(_panel_spend_by_model())
        .with_panel(_panel_breakdown_table())
        .with_panel(sh.row("Spend over time (gauge history)", y=29))
        .with_panel(_panel_spend_over_time())
        .with_panel(sh.row("Live limiter census — direct from Redis", y=40))
        .with_panel(_panel_live_census())
    )


def build() -> dict:
    return json.loads(json.dumps(_dashboard().build(), cls=JSONEncoder))
