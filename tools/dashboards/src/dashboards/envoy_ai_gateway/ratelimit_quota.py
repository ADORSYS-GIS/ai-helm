"""Envoy AI Gateway — rate-limit quota (GENERATED SOURCE).

Shows WHO is consuming the gateway and HOW MUCH of their budget, read straight
from the rate-limit service's LIVE counters in redis-ha — the only place that
state exists (Mimir/Loki hold historical cost, not the limiter's current-window
budget; ADR-0070). Two read paths over the SAME Redis keys:

  1. Mimir leaderboards (the numbers). prometheus-redis-exporter SCANs the
     monthly AND weekly budget keys (ADR-0021/0119) and exports
     `gateway_ratelimit_spend_micro_usd` with parsed account_id / plan / plane /
     window / billing_period / billing_week labels. Two parallel panel sets rank
     spend per account and per plan — one for the selected calendar month, one
     for the selected ISO week — composing the SAME way the underlying rate
     limit rules do (ADR-0119: weekly is additive to monthly, never a
     replacement).
  2. Redis census (the live "who's active right now", i.e. RAW/unfiltered —
     every row, both monthly and weekly rules, no period selection at all). A
     `redis-datasource` tmscan straight against redis-ha — zero scrape-lag, the
     limiter's own view. Shows "Billing period" and "Billing week" columns
     parsed straight from the raw key (a row has exactly one of the two, never
     both), so you can see which accounts have rotated to the calendar-aligned
     keys, live, without waiting on the exporter's scrape.

RAW consumption only (no quota/% overlay): the budget LIMITS live in static Helm
config + ai-helm-values (free/pro/enterprise, per ADR-0021/0119) and a user's
plan isn't on the key, so a precise "% of quota" can't be derived here. The
value shown is micro-USD spent in the selected period (÷1e6 → USD).

`billing_period` (calendar "YYYY-MM", ADR-0111) and `billing_week` (ISO
"GGGG-Www", Monday-start, ADR-0119) are the primary temporal filters — they
rotate on the real 1st-of-the-month / Monday respectively, unlike the legacy
`window` label (a fixed 30-day Unix-epoch bucket that drifts off the calendar
and is no longer surfaced here). Each picker defaults to the newest (current)
period; pick an older one to see a past period. The Redis census table below
both is the "raw" view — no period picker, every row at once.

The JSON file is regenerated from this module — do **not** hand-edit it::

    uv run dashboards build

ADR: docs/adr/0070-ratelimit-quota-observability.md (+ ADR-0008, ADR-0111, ADR-0119).
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
    RL_LABEL_BILLING_PERIOD,
    RL_LABEL_BILLING_WEEK,
    RL_LABEL_PLAN,
)
from dashboards.envoy_ai_gateway import _shared as sh

OUTPUT_PATH: str = "charts/observability-dashboards/files/envoy-ai-gateway/ratelimit-quota.json"

_M = METRIC_RATELIMIT_SPEND_MICRO_USD
_A = RL_LABEL_ACCOUNT
_PL = RL_LABEL_PLAN
_BP = RL_LABEL_BILLING_PERIOD
_BW = RL_LABEL_BILLING_WEEK

# ⚠️ NO `model` / `plane` dimension here, by design. Since the #532 shared-budget
# cutover the monthly budget is ONE counter per (account, plan) on the gateway-wide
# BackendTrafficPolicy (`shared: true` keys the bucket by POLICY name), spanning
# every model route and both planes — so the exporter's keys carry neither label.
# Filtering on an absent label with the multi-var default `.+` matches NOTHING, so
# a `$model` variable here would blank the whole board, not just its own panels.
# Per-model spend still lives in the Mimir/Loki cost dashboards (ADR-0058/0046).
#
# All filters refine the same metric. $billing_period / $billing_week are each
# single-select (default newest) so totals are for ONE period; the rest are
# multi (default All → .+). The legacy `window` label still exists on the
# metric (kept by the exporter for the lingering pre-rollover bucket) but is
# deliberately NOT selected on here — it's a vestigial 30-day epoch artifact,
# not something a user should filter by directly; summing across it within one
# billing_period/billing_week gives the correct total even if the underlying
# window happened to roll over mid-period.
#
# Monthly and weekly are TWO SEPARATE selectors, not one toggle. A monthly row
# has billing_week empty and a weekly row has billing_period empty (the
# exporter's regexes are anchored so the two value shapes never collide — see
# `prometheus-redis-exporter.yaml` in ai-helm-values), so `billing_week=~"X"`
# already excludes every monthly row on its own — no extra period-type label
# needed. Deliberately NOT one PromQL selector switched by a "mode" variable:
# that would need $billing_week's value substituted INTO another variable's
# raw value (nested variable interpolation), which is not a verified-reliable
# Grafana behaviour here — two parallel, always-valid selectors are simpler
# and can't silently break if that assumption were ever wrong.
_MONTHLY_SEL = f'{{{_BP}=~"$billing_period", {_PL}=~"$plan", {_A}=~"$account"}}'
_WEEKLY_SEL = f'{{{_BW}=~"$billing_week", {_PL}=~"$plan", {_A}=~"$account"}}'
_MSEL = f"{_M}{_MONTHLY_SEL}"
_WSEL = f"{_M}{_WEEKLY_SEL}"

_LEGEND_ACCOUNT = "{{" + _A + "}}"
_LEGEND_PLAN = "{{" + _PL + "}}"

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


# ── Mimir leaderboards (the numbers) ───────────────────────────────────────────
# Every panel below is parametrized by `msel` (the FULL metric+selector string —
# either `_MSEL` or `_WSEL`) and `period` (a title suffix), so the SAME panel
# shapes render twice: once for the selected calendar month, once for the
# selected ISO week. `_period_section()` assembles one full row set at a given
# grid `y` and returns where the NEXT section should start.
def _panel_total_spend(*, period: str, msel: str, grid: tuple[int, int, int, int]) -> object:
    return sh.stat_panel(
        title=f"Total spend — {period}",
        expr=sh.usd(f"sum({msel})"),
        unit="currencyUSD",
        color="orange",
        grid=grid,
    )


def _panel_active_accounts(*, msel: str, grid: tuple[int, int, int, int]) -> object:
    return sh.stat_panel(
        title="Active accounts",
        expr=f"count(count by ({_A}) ({msel}))",
        unit="short",
        color="blue",
        grid=grid,
    )


def _panel_counters(*, msel: str, grid: tuple[int, int, int, int]) -> object:
    return sh.stat_panel(
        title="Tracked counters (account x plan)",
        expr=f"count({msel})",
        unit="short",
        color="purple",
        grid=grid,
    )


def _panel_plans(*, msel: str, grid: tuple[int, int, int, int]) -> object:
    # Was "Models in use" before the shared-budget cutover removed the model
    # dimension from the budget counters. Same grid slot, plan-keyed.
    return sh.stat_panel(
        title="Plans in use",
        expr=f"count(count by ({_PL}) ({msel}))",
        unit="short",
        color="green",
        grid=grid,
    )


def _panel_top_accounts(*, period: str, msel: str, grid: tuple[int, int, int, int]) -> object:
    return sh.bargauge_panel(
        title=f"Top accounts by spend — {period}",
        expr=sh.usd(f"topk(20, sum by ({_A}) ({msel}))"),
        legend=_LEGEND_ACCOUNT,
        unit="currencyUSD",
        color="orange",
        grid=grid,
    )


def _panel_spend_by_plan(*, period: str, msel: str, grid: tuple[int, int, int, int]) -> object:
    # Was "Spend share by model". Same grid slot; billing tier is the dimension
    # the shared budget actually has.
    return sh.pie_panel(
        title=f"Spend share by plan — {period}",
        expr=sh.usd(f"sum by ({_PL}) ({msel})"),
        legend_label=_LEGEND_PLAN,
        grid=grid,
    )


def _panel_breakdown_table(*, period: str, msel: str, y: int) -> table.Panel:
    # One row per account x plan, instant → table, ranked by spend.
    expr = sh.usd(f"sum by ({_A}, {_PL}) ({msel})")
    panel = (
        table.Panel()
        .title(f"Consumption by account x plan — {period}")
        .datasource(sh.MIMIR_DS)
        .grid_pos(dm.GridPos(h=12, w=24, x=0, y=y))
        .filterable(True)
        .with_target(sh.prom_target(expr, ref_id="A", instant=True, fmt="table"))
        .with_transformation(
            dm.DataTransformerConfig(
                id_val="organize",
                options={
                    "renameByName": {
                        _A: "Account",
                        _PL: "Plan",
                        "Value #A": "Spend ($)",
                    },
                    "excludeByName": {"Time": True},
                    "indexByName": {
                        _A: 0,
                        _PL: 1,
                        "Value #A": 2,
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


def _panel_spend_over_time(*, period: str, msel: str, y: int) -> object:
    # The gauge over time — accumulation within the period, per top account.
    expr = sh.usd(f"topk(10, sum by ({_A}) ({msel}))")
    return sh.daily_bars_panel(
        title=f"Spend over time — top accounts ({period})",
        expr=expr,
        legend=_LEGEND_ACCOUNT,
        unit="currencyUSD",
        grid=(10, 24, 0, y),
        legend_calcs=["last", "max"],
    )


def _period_section(*, row_title: str, period: str, msel: str, y0: int) -> tuple[list[object], int]:
    """Row + 4 stats + top-accounts/spend-by-plan + breakdown table, for ONE
    period (monthly or weekly). Returns (panels, next_free_y)."""
    y = y0
    panels: list[object] = [sh.row(row_title, y=y)]
    y += 1
    stat_y = y
    panels += [
        _panel_total_spend(period=period, msel=msel, grid=(4, 6, 0, stat_y)),
        _panel_active_accounts(msel=msel, grid=(4, 6, 6, stat_y)),
        _panel_counters(msel=msel, grid=(4, 6, 12, stat_y)),
        _panel_plans(msel=msel, grid=(4, 6, 18, stat_y)),
    ]
    y += 4
    panels += [
        _panel_top_accounts(period=period, msel=msel, grid=(12, 12, 0, y)),
        _panel_spend_by_plan(period=period, msel=msel, grid=(12, 12, 12, y)),
    ]
    y += 12
    panels.append(_panel_breakdown_table(period=period, msel=msel, y=y))
    y += 12
    return panels, y


# ── Redis census (the live "who's active now", RAW — every row, no period filter) ─
def _panel_live_census(*, y: int) -> table.Panel:
    # Direct redis-datasource tmscan of the per-account counter keys (any
    # *-match-0* = an x-account-id-keyed budget/burst counter). Zero scrape-lag,
    # the limiter's own current view. extractFields carves Account + Model out of
    # the raw key (JS RegExp named groups — this transform runs in the browser).
    #
    # ⚠️ The `/converse/<model>/` segment is OPTIONAL and must stay so. Only the
    # PER-MODEL keys carry it; the gateway-wide shared-budget keys (`shared: true`
    # ⇒ keyed by policy, not route) do not. When that segment was mandatory this
    # regex failed outright on the shared keys, so the rows holding the ACTUAL
    # monthly budget showed neither Account nor Model — they rendered as raw
    # unparsed keys. The leading `.*/` inside the optional group is load-bearing
    # too: without it the group matches empty at position 0 and Model is dropped
    # from the per-model keys as well.
    #
    # The trailing (also optional) group carries "Billing period" (ADR-0111):
    # after the non-greedy Account capture ends at the first `_rule-N-match-1`,
    # that literal's own Exact-match value (which repeats the same
    # `_rule-N-match-1` token — Exact selectors carry their rule/match name as
    # the descriptor value) is consumed, then an optional
    # `_rule-N-match-2_<YYYY-MM>` is tried. Legacy pre-rollover keys (no
    # match-2 segment) simply leave BillingPeriod empty, so a row here is a
    # direct, zero-scrape-lag view of which accounts have rotated to the new
    # calendar-aligned key vs. which are still on their old 30-day-epoch one —
    # useful for watching the rollout finish. The $billing_period Mimir filter
    # above can't show this: it only ever sees keys the exporter has already
    # scraped and relabeled, not the raw-key rotation state.
    #
    # ⚠️ Two Grafana-model gotchas here, both pre-dating this file (verified
    # against Grafana's own source, packages/grafana-data/src/text/string.ts
    # + public/app/features/transformers/extractFields/{types,fieldExtractors}.ts,
    # v12.3.1 — the pinned chart version, charts/observability/values.yaml):
    #   1. `format` must be the literal `FieldExtractorID` enum value
    #      `"regexp"`, not `"regex"` — an unrecognized format id fails the
    #      WHOLE transform with "Error transforming data: unknown extractor"
    #      (the registry has no `"regex"` entry: json|kvp|auto|regexp|delimiter).
    #   2. The pattern must be wrapped in `/…/` delimiters, like a JS regex
    #      literal. `stringToJsRegex` special-cases this: `stringStartsAsRegEx`
    #      only checks the FIRST character is `/`; without both delimiters the
    #      whole option is silently discarded and Grafana falls back to its own
    #      built-in default `/(?<NewField>.*)/` — which is exactly why the
    #      table used to render one big "NewField" column holding the whole raw
    #      key instead of Account/Model/Billing period, with no error at all.
    #      (The trailing `/` before `stringToJsRegex`'s own non-greedy `.*?`
    #      still finds the TRUE closing delimiter correctly across our
    #      pattern's internal `/`s — verified live, not just reasoned about.)
    #
    # ADR-0119: the match-2 group now tries TWO alternative named captures —
    # BillingPeriod (`\d{4}-\d{2}`, monthly) or BillingWeek (`\d{4}-W\d{2}`,
    # weekly) — since a row is one or the other, never both. JS regex allows
    # differently-named groups in each alternation branch; whichever doesn't
    # match a given row is simply `undefined` → renders empty, same as the
    # existing "legacy key, no match-2 at all" case already handles.
    return (
        table.Panel()
        .title("Live limiter counters — direct from Redis (zero scrape-lag, RAW/unfiltered)")
        .datasource(_REDIS_DS)
        .grid_pos(dm.GridPos(h=12, w=24, x=0, y=y))
        .filterable(True)
        .with_target(_RedisTmscanTarget(ref_id="A", match="*-match-0*"))
        .with_transformation(
            dm.DataTransformerConfig(
                id_val="extractFields",
                options={
                    "source": "key",
                    "format": "regexp",
                    "regExp": (
                        r"/^(?:.*\/converse\/(?<Model>[^/]+)\/)?"
                        r".*_rule-\d+-match-0_(?<Account>.+?)_rule-\d+-match-1"
                        r"(?:_rule-\d+-match-1)?"
                        r"(?:_rule-\d+-match-2_"
                        r"(?:(?<BillingPeriod>\d{4}-\d{2})|(?<BillingWeek>\d{4}-W\d{2})))?/"
                    ),
                    "keepFields": True,
                },
            )
        )
        .with_transformation(
            dm.DataTransformerConfig(
                id_val="organize",
                options={
                    "renameByName": {
                        "key": "Redis key",
                        "BillingPeriod": "Billing period",
                        "BillingWeek": "Billing week",
                    },
                    "excludeByName": {"type": True, "memory": True, "cursor": True, "count": True},
                    "indexByName": {
                        "Account": 0,
                        "Model": 1,
                        "Billing period": 2,
                        "Billing week": 3,
                        "Redis key": 4,
                    },
                },
            )
        )
    )


_DESCRIPTION = (
    "WHO is consuming the Envoy AI Gateway and HOW MUCH of their budget, read from "
    "the rate-limit service's LIVE counters in redis-ha (ADR-0070) — the only place "
    "that current-window state exists. Two parallel Mimir leaderboards rank spend "
    "per account/plan — one for the selected calendar month ($billing_period, "
    "ADR-0111), one for the selected ISO week ($billing_week, Monday-start, "
    "ADR-0119) — from prometheus-redis-exporter's gateway_ratelimit_spend_micro_usd "
    "(÷1e6 → USD). The bottom table is a direct redis-datasource census — RAW, "
    "zero scrape-lag, every row (both monthly and weekly rules) with no period "
    "filter at all — with Billing period / Billing week columns parsed straight "
    "from the raw key so you can see rotation state live, without waiting on a "
    "scrape (a row has exactly one of the two, never both). RAW consumption "
    "only — budget limits are static Helm config + ai-helm-values "
    "(ADR-0021/0035/0119), not derivable per-user here. "
    "NO per-model breakdown: since the #532 shared-budget cutover the budget is one "
    "counter per (account, plan) spanning ALL models and both planes, so the keys "
    "carry no model label — see the Mimir/Loki cost dashboards for per-model spend. "
    "The weekly rule is ADDITIVE to the monthly one (composes via AND at "
    "enforcement time) — it never raises the monthly ceiling, only tightens "
    "pacing within a week; the two leaderboards below are independent VIEWS of "
    "that same relationship, not alternatives. "
    "Filters: plan, account. "
    "GENERATED — source: tools/dashboards/envoy_ai_gateway/ratelimit_quota.py."
)


def _billing_period_var() -> db.QueryVariable:
    # Single-select, newest-first so the current calendar month is the default.
    # No "All" — totals must be for ONE budget period. ALPHABETICAL_DESC sorts
    # a "YYYY-MM" string newest-first identically to a numerical sort, since the
    # format is zero-padded and lexicographic order matches chronological order.
    return (
        db.QueryVariable("billing_period")
        .label("Billing period (calendar month)")
        .datasource(sh.MIMIR_DS)
        .query(sh.label_values(_M, _BP))
        .refresh(dm.VariableRefresh.ON_TIME_RANGE_CHANGED)
        .sort(dm.VariableSort.ALPHABETICAL_DESC)
        .multi(False)
        .include_all(False)
    )


def _billing_week_var() -> db.QueryVariable:
    # ADR-0119. Same shape/reasoning as _billing_period_var(): single-select,
    # newest-first. "GGGG-Www" (ISO week-numbering year + zero-padded week
    # number) sorts lexicographically newest-first exactly like "YYYY-MM" does.
    return (
        db.QueryVariable("billing_week")
        .label("Billing week (ISO, Monday-start)")
        .datasource(sh.MIMIR_DS)
        .query(sh.label_values(_M, _BW))
        .refresh(dm.VariableRefresh.ON_TIME_RANGE_CHANGED)
        .sort(dm.VariableSort.ALPHABETICAL_DESC)
        .multi(False)
        .include_all(False)
    )


def _dashboard() -> db.Dashboard:
    monthly_panels, y = _period_section(
        row_title="Monthly budget consumption — selected calendar month",
        period="this month",
        msel=_MSEL,
        y0=0,
    )
    weekly_panels, y = _period_section(
        row_title="Weekly budget consumption — selected ISO week (additive to monthly, ADR-0119)",
        period="this week",
        msel=_WSEL,
        y0=y,
    )
    over_time_y = y + 1
    census_y = over_time_y + 10 + 10 + 1

    d = (
        db.Dashboard("AI Gateway — rate-limit quota")
        .uid("envoy-ai-gateway-ratelimit-quota")
        .tags(["ai-gateway", "rate-limit", "quota", "redis"])
        .description(_DESCRIPTION)
        .timezone("browser")
        .editable()
        .tooltip(dm.DashboardCursorSync.CROSSHAIR)
        .refresh("1m")
        .time("now-30d", "now")
        .with_variable(_billing_period_var())
        .with_variable(_billing_week_var())
        .with_variable(sh.multi_var(name="plan", label="Plan", definition=sh.label_values(_M, _PL)))
        # NB: no `$model` variable — the shared-budget counters carry no `model`
        # label, and the multi-var default `.+` would match nothing at all.
        .with_variable(
            sh.multi_var(name="account", label="Account", definition=sh.label_values(_M, _A))
        )
    )
    for p in monthly_panels:
        d = d.with_panel(p)
    for p in weekly_panels:
        d = d.with_panel(p)
    d = (
        d.with_panel(sh.row("Spend over time (gauge history)", y=y))
        .with_panel(_panel_spend_over_time(period="monthly", msel=_MSEL, y=over_time_y))
        .with_panel(_panel_spend_over_time(period="weekly", msel=_WSEL, y=over_time_y + 10))
        .with_panel(
            sh.row(
                "Live limiter census — direct from Redis (RAW, unfiltered, every row)",
                y=census_y - 1,
            )
        )
        .with_panel(_panel_live_census(y=census_y))
    )
    return d


def build() -> dict:
    return json.loads(json.dumps(_dashboard().build(), cls=JSONEncoder))
