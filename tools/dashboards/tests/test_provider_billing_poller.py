"""Unit tests for the provider-billing-exporter poller logic.

Covers the acceptance-criteria scenarios: repeated polling (idempotency), month
rollover, provider corrections, and missing fields. The poller lives in the
chart (charts/provider-billing-exporter/files/poller.py); this test imports it
directly so the pure parsing/period logic is exercised without a live API.

Run with:  uv run pytest tools/dashboards/tests/test_provider_billing_poller.py
"""

from __future__ import annotations

import datetime
import json
import sys
import urllib.error
from pathlib import Path

import prometheus_client

# Make the chart's poller importable (it imports prometheus_client, which is a
# dev dependency of this project).
POLLER_DIR = Path(__file__).resolve().parents[3] / "charts" / "provider-billing-exporter" / "files"
sys.path.insert(0, str(POLLER_DIR))

import poller  # noqa: E402

# The dashboard generator lives in this project's src tree; import it so the
# regression test below can build the dashboard and assert on its queries.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dashboards.envoy_ai_gateway import provider_billing  # noqa: E402


def _month(period: str, invoice_id: str = "in_x", items: list | None = None) -> dict:
    return {"period": period, "invoice_id": invoice_id, "items": items or []}


def _item(pricing_type: str, cost: int, model: str = "m", units: int = 1) -> dict:
    return {
        "model": {"provider": "deepinfra", "model_name": model, "task": "chat"},
        "units": units,
        "rate": 1.0,
        "cost": cost,
        "pricing_type": pricing_type,
    }


# --- month rollover -----------------------------------------------------------


def test_current_billing_period() -> None:
    now = datetime.datetime(2026, 8, 5, tzinfo=datetime.UTC)
    assert poller.current_billing_period(now) == "2026-08"


def test_previous_billing_period() -> None:
    now = datetime.datetime(2026, 8, 5, tzinfo=datetime.UTC)
    assert poller.previous_billing_period(now) == "2026-07"


def test_previous_billing_period_january_rollover() -> None:
    jan = datetime.datetime(2026, 1, 15, tzinfo=datetime.UTC)
    assert poller.previous_billing_period(jan) == "2025-12"


def test_normalize_period() -> None:
    assert poller.normalize_period("2026.08") == "2026-08"
    assert poller.normalize_period("2026-08") == "2026-08"


def test_resolve_periods_default_prev_plus_current() -> None:
    assert poller.resolve_periods("") == ["2026-07", "2026-08"]


def test_resolve_periods_explicit() -> None:
    assert poller.resolve_periods("2026.08") == ["2026-08"]
    assert poller.resolve_periods("2026-07,2026-08") == ["2026-07", "2026-08"]


# --- parse_usage: cache read/write, totals, invoice finality ------------------


def test_parse_usage_cache_read_write_separate_line_items() -> None:
    payload = {
        "months": [
            _month(
                "2026.08",
                "in_abc123",
                [
                    _item("input", 200, "anthropic/claude-sonnet-5"),
                    _item("cache_read", 100, "anthropic/claude-sonnet-5"),
                    _item("cache_write", 100, "anthropic/claude-sonnet-5"),
                    _item("output", 100, "anthropic/claude-sonnet-5"),
                ],
            )
        ]
    }
    series, invoice_final, ok = poller.parse_usage(payload)
    assert ok
    costs = [s for s in series if s[0] == "cost"]
    assert len(costs) == 4
    ptypes = {c[1]["pricing_type"] for c in costs}
    assert ptypes == {"input", "cache_read", "cache_write", "output"}
    # AC2: cache reads and writes appear as separate provider-billed line items.
    assert any(c[1]["pricing_type"] == "cache_read" for c in costs)
    assert any(c[1]["pricing_type"] == "cache_write" for c in costs)
    # cost is in micro-USD: 200 cents * 10000 = 2,000,000.
    input_cost = next(c for c in costs if c[1]["pricing_type"] == "input")
    assert input_cost[2] == 2_000_000
    # total = 500 cents * 10000 = 5,000,000.
    totals = [s for s in series if s[0] == "total"]
    assert totals[0][2] == 5_000_000
    assert invoice_final[("deepinfra", "2026-08")] is True


def test_parse_usage_not_final_invoice() -> None:
    payload = {"months": [_month("2026.08", "NOT_FINAL")]}
    _series, invoice_final, ok = poller.parse_usage(payload)
    assert ok
    assert invoice_final[("deepinfra", "2026-08")] is False


# --- missing fields -----------------------------------------------------------


def test_parse_usage_missing_cost_skipped() -> None:
    payload = {
        "months": [
            _month(
                "2026.08",
                "in_x",
                [
                    {
                        "model": {"provider": "deepinfra", "model_name": "m", "task": "chat"},
                        "pricing_type": "input",
                    },  # no cost -> skipped
                    _item("output", 10),
                ],
            )
        ]
    }
    series, _invoice_final, ok = poller.parse_usage(payload)
    assert ok
    costs = [s for s in series if s[0] == "cost"]
    assert len(costs) == 1  # only the item with a cost


def test_parse_usage_empty_payload_not_ok() -> None:
    _series, _invoice_final, ok = poller.parse_usage({"months": []})
    assert not ok


# --- repeated polling (idempotency) -------------------------------------------


def test_repeated_polling_idempotent() -> None:
    payload = {
        "months": [_month("2026.08", "in_x", [_item("input", 200), _item("cache_read", 100)])]
    }
    s_a, _, _ = poller.parse_usage(payload)
    s_b, _, _ = poller.parse_usage(payload)
    assert s_a == s_b


# --- provider corrections -----------------------------------------------------


def test_provider_correction_overwrites() -> None:
    payload = {"months": [_month("2026.08", "in_x", [_item("input", 999)])]}
    series, _, _ = poller.parse_usage(payload)
    cost = next(s for s in series if s[0] == "cost")[2]
    assert cost == 999 * 10000


# --- error classification (permanent vs transient) ----------------------------


def test_api_period_converts_dash_to_dot() -> None:
    # The repo uses YYYY-MM for labels/env, but the DeepInfra API expects YYYY.MM.
    # Sending the dash form yields HTTP 400 (the bug that caused "no data").
    assert poller._api_period("2026-08") == "2026.08"
    assert poller._api_period("2026-07") == "2026.07"
    # Idempotent if already in dot form.
    assert poller._api_period("2026.08") == "2026.08"


def test_fetch_usage_uses_dot_period_format(monkeypatch) -> None:
    """The request URL must use YYYY.MM (dot), not YYYY-MM (dash)."""
    captured = {}

    def _fake_urlopen(req, timeout=30):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        import io
        return io.BytesIO(b'{"months": []}')

    monkeypatch.setattr(poller.urllib.request, "urlopen", _fake_urlopen)
    poller.fetch_usage("https://api.deepinfra.com", "tok", "2026-07", "2026-08")
    assert "from=2026.07" in captured["url"]
    assert "to=2026.08" in captured["url"]
    assert "2026-07" not in captured["url"]
    assert captured["auth"] == "Bearer tok"


def test_permanent_http_errors() -> None:
    # Bad token / forbidden / missing endpoint are permanent: retrying cannot fix.
    for code in (400, 401, 403, 404, 405, 422):
        exc = urllib.error.HTTPError(url="u", code=code, msg="m", hdrs=None, fp=None)
        assert poller._permanent(exc) is True, f"expected {code} to be permanent"


def test_transient_errors() -> None:
    # 429/5xx and network errors are transient: retry with backoff.
    for code in (429, 500, 502, 503, 504):
        exc = urllib.error.HTTPError(url="u", code=code, msg="m", hdrs=None, fp=None)
        assert poller._permanent(exc) is False, f"expected {code} to be transient"
    assert poller._permanent(TimeoutError("boom")) is False
    assert poller._permanent(ValueError("parse")) is False


def test_poll_returns_transient_on_network_error(monkeypatch) -> None:
    """A network/transient failure is surfaced with permanent=False (retryable)."""
    def _raise(api_url, token, from_period, to_period=None):
        raise urllib.error.URLError("no network")
    monkeypatch.setattr(poller, "fetch_usage", _raise)
    metrics = poller.Metrics(registry=prometheus_client.CollectorRegistry())
    ok, err, permanent = poller.poll("https://api.deepinfra.com", "tok", ["2026-08"], metrics)
    assert ok is False
    assert permanent is False
    assert err  # a human-readable error is returned for logging
    # up is set to 0 for the period so the dashboard shows the poll is down.
    assert metrics.up.labels(provider="deepinfra", billing_period="2026-08")._value.get() == 0


def test_poll_returns_permanent_on_http_error(monkeypatch) -> None:
    """A bad token (403) is surfaced as permanent so main() logs it loudly."""
    def _raise(api_url, token, from_period, to_period=None):
        raise urllib.error.HTTPError(url="u", code=403, msg="Forbidden", hdrs=None, fp=None)
    monkeypatch.setattr(poller, "fetch_usage", _raise)
    metrics = poller.Metrics(registry=prometheus_client.CollectorRegistry())
    ok, err, permanent = poller.poll("https://api.deepinfra.com", "tok", ["2026-08"], metrics)
    assert ok is False
    assert permanent is True
    assert "403" in err
    assert metrics.up.labels(provider="deepinfra", billing_period="2026-08")._value.get() == 0


# --- dashboard selector regression (the "no data in fields" bug) -------------


def _panel_exprs(node) -> list[str]:
    """Recursively collect every PromQL `expr` from a built dashboard dict."""
    exprs: list[str] = []
    if isinstance(node, dict):
        if "expr" in node and isinstance(node["expr"], str):
            exprs.append(node["expr"])
        for v in node.values():
            exprs.extend(_panel_exprs(v))
    elif isinstance(node, list):
        for v in node:
            exprs.extend(_panel_exprs(v))
    return exprs


def test_dashboard_billing_period_uses_regex_selector() -> None:
    """Every provider query must select billing_period with =~ (regex), not =.

    The billing_period variable is multi-value with includeAll + allValue ".+".
    With the exact-match operator (`billing_period="$billing_period"`) the "All"
    default expands to `billing_period=".+"`, which matches the literal string
    ".+" and returns NO series — the dashboard shows "No data in fields". Using
    `=~` makes "All" expand to a working regex. This is the same convention as
    ratelimit_quota.py's _MONTHLY_SEL.
    """
    dash = provider_billing.build()
    exprs = _panel_exprs(dash)
    assert exprs, "expected the dashboard to contain query expressions"
    # Only queries that actually filter on billing_period are relevant (the
    # last_success / scrape_duration metrics carry no labels and are excluded).
    period_queries = [e for e in exprs if "billing_period" in e]
    assert period_queries, "expected billing_period-filtered queries in the dashboard"
    for expr in period_queries:
        # Every provider query that filters on billing_period must use =~.
        assert 'billing_period=~"$billing_period"' in expr, (
            f"billing_period must use =~ (regex) so the All default works: {expr}"
        )
        assert 'billing_period="$billing_period"' not in expr, (
            f"billing_period must NOT use = (exact match) — causes no data: {expr}"
        )
        # provider must also use =~ for the same reason.
        assert 'provider=~"$provider"' in expr, f"provider must use =~: {expr}"


def test_dashboard_json_matches_generator() -> None:
    """The committed provider-billing.json queries must equal the generator's.

    Guards against hand-editing the JSON (the generator is the source of truth)
    and against the =~ fix being reverted in one place but not the other. We
    compare the query expressions (not the whole dict — the orchestrator in
    main.py additionally injects the report link and schema-version stamp).
    """
    out = Path(__file__).resolve().parents[3] / "charts" / "observability-dashboards" / "files" / "envoy-ai-gateway" / "provider-billing.json"
    committed = json.loads(out.read_text())
    assert sorted(_panel_exprs(committed)) == sorted(_panel_exprs(provider_billing.build()))
