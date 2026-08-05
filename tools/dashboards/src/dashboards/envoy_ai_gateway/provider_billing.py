"""Envoy AI Gateway — provider-billed cost & reconciliation (GENERATED SOURCE).

Shows PROVIDER-BILLED cost (the invoice source of truth, polled from DeepInfra's
billing API by the provider-billing-exporter) and reconciles it against the
gateway's ESTIMATED cost (ADR-0058 Mimir metric) and the Redis limiter spend
(ADR-0070). Reads Mimir via PromQL for the provider/gateway/limiter numbers and
Loki for missing-cost/disconnected gateway requests.

Provider metrics are cumulative GAUGES per UTC billing period
(provider_billing_cost_micro_usd / provider_billing_total_cost_micro_usd), so
they are queried directly (NOT increase()) and filtered by billing_period.
Poll health (provider_billing_up / last_success / scrape_duration) and billed
units (provider_billing_units) are surfaced alongside the cost panels.

The JSON file is regenerated from this module — do **not** hand-edit it.

    uv run dashboards build

ADR: docs/adr/0058-precompute-gateway-usage-metrics-to-mimir.md,
docs/adr/0070-*.md, provider-billing runbook.
"""

from __future__ import annotations

import json

from grafana_foundation_sdk.builders import common as cb
from grafana_foundation_sdk.builders import dashboard as db
from grafana_foundation_sdk.builders import loki, stat
from grafana_foundation_sdk.cog.encoder import JSONEncoder
from grafana_foundation_sdk.models import common as cm
from grafana_foundation_sdk.models import dashboard as dm

from dashboards._common import (
    GATEWAY_SERVICE_NAME,
    LOKI_UID,
    METRIC_COST_MICRO_USD,
    METRIC_RATELIMIT_SPEND_MICRO_USD,
    MIMIR_UID,
)
from dashboards.envoy_ai_gateway import _shared as sh

OUTPUT_PATH: str = "charts/observability-dashboards/files/envoy-ai-gateway/provider-billing.json"

_MIMIR_DS = dm.DataSourceRef(type_val="prometheus", uid=MIMIR_UID)
_LOKI_DS = dm.DataSourceRef(type_val="loki", uid=LOKI_UID)

# Provider-billed metrics (cumulative gauges, per UTC billing period).
METRIC_PROVIDER_COST = "provider_billing_cost_micro_usd"
METRIC_PROVIDER_UNITS = "provider_billing_units"
METRIC_PROVIDER_TOTAL = "provider_billing_total_cost_micro_usd"
METRIC_PROVIDER_INVOICE_FINAL = "provider_billing_invoice_final"
METRIC_PROVIDER_UP = "provider_billing_up"
METRIC_PROVIDER_LAST_SUCCESS = "provider_billing_last_success_timestamp_seconds"
METRIC_PROVIDER_SCRAPE_DURATION = "provider_billing_scrape_duration_seconds"

# Selector scoped to the chosen provider + billing period.
_SEL = '{provider=~"$provider", billing_period="$billing_period"}'

# Gateway-estimated cost over the selected range (ADR-0058 counter).
_GATEWAY_EST = f"sum(increase({METRIC_COST_MICRO_USD}[$__range]))/1e6"
# Provider-billed total for the billing period.
_PROVIDER_TOTAL = f"sum({METRIC_PROVIDER_TOTAL}{_SEL})/1e6"
# Absolute reconciliation delta (provider - gateway).
_DELTA_ABS = f"(({_PROVIDER_TOTAL}) - ({_GATEWAY_EST}))"
# Percentage reconciliation delta.
_DELTA_PCT = f"(({_PROVIDER_TOTAL}) - ({_GATEWAY_EST})) / ({_GATEWAY_EST}) * 100"


def _loki_target(expr: str, *, legend: str = "", ref_id: str = "A") -> loki.Dataquery:
    q = loki.Dataquery().expr(expr).ref_id(ref_id).query_type("range").datasource(_LOKI_DS)
    return q.legend_format(legend) if legend else q


def _stat_panel(
    *, title: str, expr: str, unit: str, color: str, grid: tuple[int, int, int, int]
) -> object:
    h, w, x, y = grid
    return sh.stat_panel(title=title, expr=expr, unit=unit, color=color, grid=(h, w, x, y))


def _loki_stat(
    *, title: str, expr: str, unit: str, color: str, grid: tuple[int, int, int, int]
) -> object:
    h, w, x, y = grid
    return stat_panel_loki(title=title, expr=expr, unit=unit, color=color, grid=(h, w, x, y))


def stat_panel_loki(*, title, expr, unit, color, grid):
    h, w, x, y = grid
    return (
        stat.Panel()
        .title(title)
        .datasource(_LOKI_DS)
        .grid_pos(dm.GridPos(h=h, w=w, x=x, y=y))
        .unit(unit)
        .thresholds(sh.single_color_thresholds(color))
        .reduce_options(cb.ReduceDataOptions().calcs(["lastNotNull"]).fields("").values(False))
        .text_mode(cm.BigValueTextMode.AUTO)
        .color_mode(cm.BigValueColorMode.VALUE)
        .graph_mode(cm.BigValueGraphMode.AREA)
        .with_target(_loki_target(expr))
    )


# --- Row 1: invoice truth vs gateway estimate vs limiter ---------------------


def _panel_provider_total() -> object:
    return _stat_panel(
        title="Provider-billed total (billing period)",
        expr=_PROVIDER_TOTAL,
        unit="currencyUSD",
        color="orange",
        grid=(4, 5, 0, 1),
    )


def _panel_gateway_estimate() -> object:
    return _stat_panel(
        title="Gateway estimate (range)",
        expr=_GATEWAY_EST,
        unit="currencyUSD",
        color="blue",
        grid=(4, 5, 5, 1),
    )


def _panel_delta_abs() -> object:
    return _stat_panel(
        title="Reconciliation delta (abs, $)",
        expr=_DELTA_ABS,
        unit="currencyUSD",
        color="purple",
        grid=(4, 5, 10, 1),
    )


def _panel_delta_pct() -> object:
    return _stat_panel(
        title="Reconciliation delta (%)",
        expr=_DELTA_PCT,
        unit="percent",
        color="red",
        grid=(4, 5, 15, 1),
    )


def _panel_limiter_spend() -> object:
    return _stat_panel(
        title="Redis limiter spend (live)",
        expr=f"sum({METRIC_RATELIMIT_SPEND_MICRO_USD})/1e6",
        unit="currencyUSD",
        color="green",
        grid=(4, 4, 20, 1),
    )


# --- Row 2: provider poll health ---------------------------------------------


def _panel_poll_up() -> object:
    # min() over the period: 1 only if EVERY poll for the period succeeded.
    inner = f"min({METRIC_PROVIDER_UP}{_SEL})"
    return _stat_panel(
        title="Provider poll up (1=healthy)",
        expr=inner,
        unit="short",
        color="green",
        grid=(4, 6, 0, 6),
    )


def _panel_last_success() -> object:
    # Seconds since the last successful poll (no labels on this metric).
    expr = f"time() - {METRIC_PROVIDER_LAST_SUCCESS}"
    return _stat_panel(
        title="Seconds since last successful poll",
        expr=expr,
        unit="s",
        color="blue",
        grid=(4, 6, 6, 6),
    )


def _panel_scrape_duration() -> object:
    expr = f"{METRIC_PROVIDER_SCRAPE_DURATION}"
    return _stat_panel(
        title="Last poll duration",
        expr=expr,
        unit="s",
        color="purple",
        grid=(4, 6, 12, 6),
    )


def _panel_units_total() -> object:
    inner = f"sum({METRIC_PROVIDER_UNITS}{_SEL})"
    return _stat_panel(
        title="Provider-billed units (billing period)",
        expr=inner,
        unit="short",
        color="orange",
        grid=(4, 6, 18, 6),
    )


# --- Row 3: breakdowns -------------------------------------------------------


def _panel_by_model() -> object:
    inner = f"sum by (provider_model) ({METRIC_PROVIDER_COST}{_SEL})"
    return sh.bargauge_panel(
        title="Provider-billed by model (billing period)",
        expr=f"topk(20, {sh.usd(inner)})",
        legend="{{provider_model}}",
        unit="currencyUSD",
        color="orange",
        grid=(8, 12, 0, 11),
    )


def _panel_by_pricing_type() -> object:
    inner = f"sum by (pricing_type) ({METRIC_PROVIDER_COST}{_SEL})"
    return sh.pie_panel(
        title="Provider-billed by pricing type",
        expr=sh.usd(inner),
        legend_label="{{pricing_type}}",
        grid=(8, 12, 12, 11),
    )


def _panel_over_time() -> object:
    # The provider gauge is cumulative; a timeseries shows the MTD total growing
    # as polls update it (step 1d for daily granularity).
    expr = sh.usd(f"sum by (provider_model) ({METRIC_PROVIDER_COST}{_SEL})")
    return sh.daily_bars_panel(
        title="Provider-billed cumulative by model",
        expr=expr,
        legend="{{provider_model}}",
        unit="currencyUSD",
        grid=(8, 24, 0, 19),
    )


def _panel_units_by_model() -> object:
    inner = f"sum by (provider_model) ({METRIC_PROVIDER_UNITS}{_SEL})"
    return sh.bargauge_panel(
        title="Provider-billed units by model (billing period)",
        expr=f"topk(20, {inner})",
        legend="{{provider_model}}",
        unit="short",
        color="orange",
        grid=(4, 6, 12, 28),
    )


# --- Row 4: cache read/write, units & invoice finality ------------------------


def _panel_cache_read() -> object:
    inner = f'sum({METRIC_PROVIDER_COST}{{provider=~"$provider", billing_period="$billing_period", pricing_type="cache_read"}})'
    return _stat_panel(
        title="Cache read cost",
        expr=sh.usd(inner),
        unit="currencyUSD",
        color="blue",
        grid=(4, 6, 0, 28),
    )


def _panel_cache_write() -> object:
    inner = f'sum({METRIC_PROVIDER_COST}{{provider=~"$provider", billing_period="$billing_period", pricing_type="cache_write"}})'
    return _stat_panel(
        title="Cache write cost",
        expr=sh.usd(inner),
        unit="currencyUSD",
        color="purple",
        grid=(4, 6, 6, 28),
    )


def _panel_invoice_final() -> object:
    inner = f"min({METRIC_PROVIDER_INVOICE_FINAL}{_SEL})"
    return _stat_panel(
        title="Invoice final (1=yes, 0=accruing)",
        expr=inner,
        unit="short",
        color="green",
        grid=(4, 6, 18, 28),
    )


# --- Row 5: missing-cost / disconnected gateway requests (Loki) ---------------


def _panel_missing_cost() -> object:
    # Gateway access logs where the cost field is absent/empty ("-" per ADR-0046).
    # These are requests that never got terminal usage/cost metadata (e.g.
    # successful streaming disconnects).
    expr = (
        f'sum(count_over_time({{service_name="{GATEWAY_SERVICE_NAME}"}} '
        f'| json cost=`["gen_ai.usage.custom_total_cost"]` '
        f'| cost=~"^$|-" [$__range]))'
    )
    return _loki_stat(
        title="Gateway requests missing cost metadata",
        expr=expr,
        unit="short",
        color="red",
        grid=(4, 12, 0, 33),
    )


def _panel_gateway_requests() -> object:
    expr = f'sum(count_over_time({{service_name="{GATEWAY_SERVICE_NAME}"}} [$__range]))'
    return _loki_stat(
        title="Gateway requests (range)",
        expr=expr,
        unit="short",
        color="blue",
        grid=(4, 12, 12, 33),
    )


_DESCRIPTION = (
    "Provider-billed cost (invoice source of truth, polled from DeepInfra by the "
    "provider-billing-exporter) reconciled against the gateway's estimated cost "
    "(ADR-0058 Mimir metric) and the Redis limiter spend (ADR-0070). Provider "
    "metrics are cumulative gauges per UTC billing period. The reconciliation "
    "delta = provider-billed minus gateway-estimated (absolute $ and %). "
    "GENERATED — source: tools/dashboards/envoy_ai_gateway/provider_billing.py."
)


def _dashboard() -> db.Dashboard:
    return (
        db.Dashboard("AI Gateway — provider billing & reconciliation")
        .uid("envoy-ai-gateway-provider-billing")
        .tags(["ai-gateway", "cost", "billing", "provider", "mimir"])
        .description(_DESCRIPTION)
        .timezone("browser")
        .editable()
        .tooltip(dm.DashboardCursorSync.CROSSHAIR)
        .refresh("1h")
        .time("now-30d", "now")
        .with_variable(
            sh.multi_var(
                name="provider",
                label="Provider",
                definition=sh.label_values(METRIC_PROVIDER_TOTAL, "provider"),
            )
        )
        .with_variable(
            sh.multi_var(
                name="billing_period",
                label="Billing period (YYYY-MM)",
                definition=sh.label_values(METRIC_PROVIDER_TOTAL, "billing_period"),
            )
        )
        .with_panel(sh.row("Invoice truth vs gateway estimate vs limiter", y=0))
        .with_panel(_panel_provider_total())
        .with_panel(_panel_gateway_estimate())
        .with_panel(_panel_delta_abs())
        .with_panel(_panel_delta_pct())
        .with_panel(_panel_limiter_spend())
        .with_panel(sh.row("Provider poll health", y=5))
        .with_panel(_panel_poll_up())
        .with_panel(_panel_last_success())
        .with_panel(_panel_scrape_duration())
        .with_panel(_panel_units_total())
        .with_panel(sh.row("Breakdown", y=10))
        .with_panel(_panel_by_model())
        .with_panel(_panel_by_pricing_type())
        .with_panel(_panel_over_time())
        .with_panel(sh.row("Cache read/write, units & invoice finality", y=27))
        .with_panel(_panel_cache_read())
        .with_panel(_panel_cache_write())
        .with_panel(_panel_units_by_model())
        .with_panel(_panel_invoice_final())
        .with_panel(sh.row("Missing-cost / disconnected gateway requests", y=32))
        .with_panel(_panel_missing_cost())
        .with_panel(_panel_gateway_requests())
    )


def build() -> dict:
    return json.loads(json.dumps(_dashboard().build(), cls=JSONEncoder))
