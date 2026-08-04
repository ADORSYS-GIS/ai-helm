"""Weekly / monthly / raw time-picker quick-ranges for the cost dashboards."""

from __future__ import annotations

# Every dashboard in this set reads spend/usage data that's meaningful bucketed
# by ISO week (Monday-start) or calendar month, matching the gateway's own
# rate-limit budget windows (ai-helm ADR-0111/0119). Injecting quick-range
# shortcuts into the time picker gives a uniform "Weekly / Monthly / raw"
# 3-way filter across all of them with NO panel-query changes: every panel
# already scopes its PromQL/LogQL to the dashboard's own time range
# ($__range), so snapping that range via the picker is enough.
#
# Deliberately excludes `chat_overview` (a Tempo trace-feed / chat-quality
# board, not a cost/usage one) and the GPU/engine/platform dashboards (no
# cost or billing dimension at all).
PERIOD_FILTER_MODULES: frozenset[str] = frozenset(
    {
        "dashboards.envoy_ai_gateway.per_user",
        "dashboards.envoy_ai_gateway.cost_by_model",
        "dashboards.envoy_ai_gateway.actor_consumption",
        "dashboards.envoy_ai_gateway.user_tokens_cost",
        "dashboards.envoy_ai_gateway.user_directory",
        "dashboards.envoy_ai_gateway.sessions_grants",
        "dashboards.envoy_ai_gateway.jwt_tokens",
        "dashboards.envoy_ai_gateway.scoreboard",
        "dashboards.envoy_ai_gateway.ratelimit_quota",
        "dashboards.envoy_ai_gateway.my_usage",
        "dashboards.envoy_ai_gateway.chats_by_user",
    }
)

# `{display, from, to}` — Grafana's dashboard-level time-picker quick-ranges
# (added ~Grafana 10.3, confirmed present in the in-cluster 12.x). The
# grafana-foundation-sdk's typed `TimePicker` model (schema v39) exposes only
# the older `time_options` (relative-duration strings like "7d") and has no
# field for this newer, richer `{display, from, to}` shape — same class of gap
# as `SCHEMA_VERSION` (no fluent setter), so it's injected as a raw dict in
# `main.py::_emit`, the same single choke point `_report.py` uses.
#
# `now/w` / `now/M` round DOWN to the start of the current ISO week/month —
# Grafana's week-start default is Monday, matching the gateway's own
# Monday-start ISO week (ADR-0119). If that default is ever overridden in
# Grafana's org preferences, these two stop agreeing — verify live if the
# "Weekly" quick-range ever looks like it starts on the wrong day.
# `to: "now"` (not `now/w` / `now/M`) deliberately gives a week/month-TO-DATE
# view, not the full (partly-future) calendar period.
_QUICK_RANGES: list[dict[str, str]] = [
    {"display": "Weekly (this ISO week, Mon-now)", "from": "now/w", "to": "now"},
    {"display": "Monthly (this calendar month, 1st-now)", "from": "now/M", "to": "now"},
]


def inject_period_quick_ranges(dashboard: dict, module_name: str) -> None:
    """Add the Weekly/Monthly time-picker shortcuts to an in-scope dashboard.

    "Raw" needs no entry of its own — it's simply the picker's existing
    default relative-range options (7d/30d/custom/...), left untouched.
    No-op for any dashboard not in `PERIOD_FILTER_MODULES`.
    """
    if module_name not in PERIOD_FILTER_MODULES:
        return
    timepicker = dashboard.get("timepicker") or {}
    timepicker["quickRanges"] = list(_QUICK_RANGES)
    dashboard["timepicker"] = timepicker
