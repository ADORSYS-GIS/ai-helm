#!/usr/bin/env python3
"""Provider billing exporter.

Polls DeepInfra's read-only billing API (GET /payment/usage/tokens) for UTC
calendar-month usage and exposes cumulative monthly usage as Prometheus gauges
for scrape into Mimir.

Uses the `prometheus_client` library (installed at container start from the
requirements.txt in this ConfigMap). Runs on python:3.12-alpine.

Design (see docs/playbooks/provider-billing-reconciliation.md):
  * GAUGES, not counters - each poll OVERWRITES the absolute cumulative value
    the provider reports for the billing period, so restarts / re-polls can
    never double count (FR-003).
  * UTC calendar billing periods (YYYY-MM), computed at each poll so the month
    rolls over automatically (FR-001/FR-007).
  * One range request per poll (from=current(-1)&to=current) returns both the
    previous and current month in a single call - efficient (FR-001).
  * Provider corrections are picked up automatically: a corrected invoice value
    simply overwrites the gauge on the next poll.
  * Bounded labels only: provider, provider_model, pricing_type, billing_period,
    task. Never the API token or account identifiers (FR-002).
  * 429/5xx handled with exponential backoff + jitter; surfaced as up=0.
  * Delayed invoices: invoice_id NOT_FINAL/EMPTY exposed as invoice_final=0.

Environment:
  DEEPINFRA_API_TOKEN  (required) DeepInfra API bearer token.
  DEEPINFRA_API_URL    (default https://api.deepinfra.com)
  POLL_INTERVAL        (default 3600) seconds between polls.
  BILLING_PERIOD       (default = previous + current UTC YYYY-MM) comma-separated.
  LISTEN_ADDR          (default 0.0.0.0)
  LISTEN_PORT          (default 8080)
"""

from __future__ import annotations

import datetime
import json
import os
import random
import sys
import threading
import time
import urllib.request
from urllib.parse import urlencode

from prometheus_client import Gauge, start_http_server

# 1 cent = 10,000 micro-USD (the repo's cost convention is micro-USD, /1e6 -> USD).
MICRO_PER_CENT = 10_000

# Provider label value for every series this exporter emits.
PROVIDER = "deepinfra"


class Metrics:
    """Prometheus gauges for provider billing. One instance, shared by threads."""

    def __init__(self) -> None:
        self.cost = Gauge(
            "provider_billing_cost_micro_usd",
            "Provider-billed cost for the billing period, cumulative, in micro-USD.",
            ["provider", "provider_model", "pricing_type", "billing_period", "task"],
        )
        self.units = Gauge(
            "provider_billing_units",
            "Provider-billed units (tokens or seconds) for the billing period.",
            ["provider", "provider_model", "pricing_type", "billing_period", "task"],
        )
        self.total = Gauge(
            "provider_billing_total_cost_micro_usd",
            "Provider-billed total cost for the billing period, cumulative, in micro-USD.",
            ["provider", "billing_period"],
        )
        self.invoice_final = Gauge(
            "provider_billing_invoice_final",
            "1 if the month's invoice is final (has a Stripe invoice id), 0 if still accruing (NOT_FINAL/EMPTY).",
            ["provider", "billing_period"],
        )
        self.up = Gauge(
            "provider_billing_up",
            "1 if the last poll for the billing period succeeded, 0 otherwise.",
            ["provider", "billing_period"],
        )
        self.last_success = Gauge(
            "provider_billing_last_success_timestamp_seconds",
            "Unix timestamp of the last successful poll.",
        )
        self.scrape_duration = Gauge(
            "provider_billing_scrape_duration_seconds",
            "Duration of the last poll in seconds.",
        )


# ---------------------------------------------------------------------------
# Pure, testable helpers
# ---------------------------------------------------------------------------
def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def current_billing_period(now: datetime.datetime) -> str:
    """UTC calendar billing period for `now`, as YYYY-MM."""
    return now.strftime("%Y-%m")


def previous_billing_period(now: datetime.datetime) -> str:
    """The UTC calendar month before `now`, as YYYY-MM."""
    first_of_this_month = now.replace(day=1)
    prev = first_of_this_month - datetime.timedelta(days=1)
    return prev.strftime("%Y-%m")


def normalize_period(period: str) -> str:
    """Normalise a DeepInfra period (YYYY.MM) to the repo's YYYY-MM convention."""
    period = (period or "").strip()
    return period.replace(".", "-")


def resolve_periods(periods_env: str) -> list[str]:
    """Resolve the billing periods to poll: explicit list, else prev + current."""
    if periods_env:
        return [normalize_period(p) for p in periods_env.split(",") if p.strip()]
    now = utc_now()
    return [previous_billing_period(now), current_billing_period(now)]


def parse_usage(payload: dict) -> tuple[list, dict, bool]:
    """Parse a DeepInfra UsageOut payload into metric series.

    Returns (series, invoice_final, ok):
      series:        list of (name, labels, value) for per-item cost/units gauges
                     plus per-provider monthly totals.
      invoice_final: dict {(provider, period): bool} - True if the month has a
                     final Stripe invoice id.
      ok:            True if at least one month parsed.
    """
    series: list = []
    invoice_final: dict = {}
    totals: dict = {}
    months = payload.get("months") or []
    if not months:
        return series, invoice_final, False
    for month in months:
        period = normalize_period(month.get("period") or "")
        if not period:
            continue
        invoice_id = month.get("invoice_id") or ""
        invoice_final[(PROVIDER, period)] = invoice_id not in ("", "NOT_FINAL", "EMPTY")
        items = month.get("items") or []
        for item in items:
            model = item.get("model") or {}
            provider = (model.get("provider") or "unknown").strip() or "unknown"
            provider_model = (model.get("model_name") or "unknown").strip() or "unknown"
            task = (model.get("task") or "").strip()
            pricing_type = (item.get("pricing_type") or "unknown").strip() or "unknown"
            cost_cents = item.get("cost")
            # Missing cost field -> skip this item (missing-fields handling).
            if cost_cents is None:
                continue
            cost_micro = int(cost_cents) * MICRO_PER_CENT
            labels = {
                "provider": provider,
                "provider_model": provider_model,
                "pricing_type": pricing_type,
                "billing_period": period,
                "task": task,
            }
            series.append(("cost", labels, float(cost_micro)))
            units = item.get("units")
            if units is not None:
                series.append(("units", labels, float(units)))
            key = (provider, period)
            totals[key] = totals.get(key, 0) + cost_micro
    for (provider, period), total in totals.items():
        series.append(
            (
                "total",
                {"provider": provider, "billing_period": period},
                float(total),
            )
        )
    return series, invoice_final, True


def fetch_usage(api_url: str, token: str, from_period: str, to_period: str | None = None) -> dict:
    """One GET /payment/usage/tokens call covering [from_period, to_period]."""
    params = [("from", from_period)]
    if to_period:
        params.append(("to", to_period))
    url = f"{api_url}/payment/usage/tokens?{urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def poll(api_url: str, token: str, periods: list[str], metrics: Metrics) -> tuple[bool, str | None]:
    """Poll the API for the period range and update the gauges. Returns (ok, error)."""
    start = time.time()
    try:
        data = fetch_usage(api_url, token, periods[0], periods[-1])
        series, invoice_final, ok = parse_usage(data)
        if not ok:
            for p in periods:
                metrics.up.labels(provider=PROVIDER, billing_period=p).set(0)
            return False, "no months returned for period range"
        for name, labels, value in series:
            if name == "cost":
                metrics.cost.labels(**labels).set(value)
            elif name == "units":
                metrics.units.labels(**labels).set(value)
            elif name == "total":
                metrics.total.labels(**labels).set(value)
        for (provider, period), final in invoice_final.items():
            metrics.invoice_final.labels(provider=provider, billing_period=period).set(1 if final else 0)
        for p in periods:
            metrics.up.labels(provider=PROVIDER, billing_period=p).set(1)
        metrics.last_success.set(time.time())
        metrics.scrape_duration.set(time.time() - start)
        return True, None
    except Exception as exc:  # noqa: BLE001 - surface any fetch/parse failure as down
        for p in periods:
            metrics.up.labels(provider=PROVIDER, billing_period=p).set(0)
        return False, str(exc)


def _backoff_delay(attempt: int, base: float = 30.0, cap: float = 900.0) -> float:
    """Exponential backoff with jitter for transient API failures (429/5xx)."""
    exp = min(cap, base * (2 ** attempt))
    return exp * (0.5 + random.random())


def main() -> int:
    token = os.environ.get("DEEPINFRA_API_TOKEN")
    if not token:
        sys.stderr.write("DEEPINFRA_API_TOKEN is required\n")
        return 1
    api_url = os.environ.get("DEEPINFRA_API_URL", "https://api.deepinfra.com").rstrip("/")
    poll_interval = int(os.environ.get("POLL_INTERVAL", "3600"))
    listen_addr = os.environ.get("LISTEN_ADDR", "0.0.0.0")
    listen_port = int(os.environ.get("LISTEN_PORT", "8080"))
    periods_env = os.environ.get("BILLING_PERIOD", "").strip()

    metrics = Metrics()
    # Initial poll before serving so /metrics is populated immediately.
    poll(api_url, token, resolve_periods(periods_env), metrics)

    def loop() -> None:
        attempt = 0
        while True:
            time.sleep(poll_interval)
            ok, err = poll(api_url, token, resolve_periods(periods_env), metrics)
            if ok:
                attempt = 0
            else:
                attempt += 1
                sys.stderr.write(f"poll error: {err}\n")
                # Back off before the next attempt on transient failures.
                time.sleep(_backoff_delay(attempt))

    threading.Thread(target=loop, daemon=True).start()
    start_http_server(listen_port, addr=listen_addr)
    # Block the main thread forever. start_http_server() and the poller loop
    # run on daemon threads, so main() must not return or the process exits.
    threading.Event().wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
