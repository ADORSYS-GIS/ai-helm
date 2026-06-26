"""Envoy AI Gateway — sessions & grants (GENERATED SOURCE).

Shows the **offline grants** Keycloak persists (long-lived refresh-token sessions:
`opencode auth login` caches, LibreChat "remember me", service accounts), resolved
to people + client names via the read-only Keycloak datasource (ADR-0063), and
cross-referenced with gateway spend.

⚠️ Scope is bounded by what Keycloak actually stores:
  * Access tokens (what hits the gateway) are STATELESS JWTs — never in the DB.
  * This Keycloak (26.x) runs PERSISTENT SESSIONS, so BOTH online and offline
    sessions live in `offline_{user,client}_session`, told apart by `offline_flag`
    ('1' = offline grant, '0' = online login). This dashboard filters to the
    OFFLINE grants ('1') — standing long-lived grants — so online web/CLI logins
    aren't miscounted. (Online-session visibility would be a flag-'0' variant.)
  * Revocation DELETES the row (no tombstone) — you see active vs gone, not a
    list of "revoked"; Keycloak's `revoked_token` table is the live revocation
    list. So a missing grant = revoked OR expired OR never existed.

Budget is attributed per-USER (`x-account-id` = sub) and per-CLIENT (`azp`) — NOT
per individual token (one offline token mints many access tokens; the cost metrics
carry no `jti`/session label). So the "x budget" panels join grants to per-user and
per-`azp` spend — i.e. "which credential CHANNEL used which budget", the
attributable version of the question. See ADR-0063.

The JSON file is regenerated from this module — do **not** hand-edit it::

    uv run dashboards build
"""

from __future__ import annotations

import json
import typing

from grafana_foundation_sdk.builders import bargauge, stat, table
from grafana_foundation_sdk.builders import common as cb
from grafana_foundation_sdk.builders import dashboard as db
from grafana_foundation_sdk.cog.encoder import JSONEncoder
from grafana_foundation_sdk.models import common as cm
from grafana_foundation_sdk.models import dashboard as dm

from dashboards._common import (
    CAMER_DIGITAL_REALM_ID,
    KEYCLOAK_UID,
    LABEL_AZP,
    LABEL_MODEL,
    LABEL_USER_ID,
    METRIC_COST_MICRO_USD,
    METRIC_REQUESTS,
)
from dashboards.envoy_ai_gateway import _shared as sh

OUTPUT_PATH: str = "charts/observability-dashboards/files/envoy-ai-gateway/sessions-grants.json"

_KEYCLOAK_DS = dm.DataSourceRef(type_val="postgres", uid=KEYCLOAK_UID)
_MIXED_DS = dm.DataSourceRef(type_val="datasource", uid="-- Mixed --")

_R = CAMER_DIGITAL_REALM_ID
_SEL = sh.selector('azp=~"$azp"', 'model=~"$model"')

# --- Mimir spend (instant → table), keyed by the join fields ----------------
_COST_BY_AZP = sh.usd(f"sum by ({LABEL_AZP}) (increase({METRIC_COST_MICRO_USD}{_SEL}[$__range]))")
_COST_BY_USER = sh.usd(
    f"sum by ({LABEL_USER_ID}) (increase({METRIC_COST_MICRO_USD}{_SEL}[$__range]))"
)

# --- Keycloak SQL (validated live against the camer-digital realm) ----------
# A "grant" = one OFFLINE client-session row (a (user, client) tuple). ⚠️ This
# Keycloak (26.x) runs PERSISTENT SESSIONS, so ONLINE sessions are stored in the
# SAME offline_{user,client}_session tables, distinguished by `offline_flag`
# ('1' = offline grant, '0' = online login). Every query therefore filters
# `offline_flag = '1'` so online web/CLI logins (e.g. the grafana/argocd console
# sessions) aren't miscounted as offline grants. Counts/joins all key on the
# CLIENT-session table so the per-user / per-azp / total numbers stay consistent;
# activity is the per-client `offline_client_session.timestamp` (not the shared
# user-session refresh), so two clients on one user-session don't show identical
# last-active.
_NAME = "NULLIF(TRIM(COALESCE(ue.first_name, '') || ' ' || COALESCE(ue.last_name, '')), '')"
_OFF = "offline_flag = '1'"

_SQL_DETAIL = (
    f"SELECT ue.username, {_NAME} AS name, c.client_id AS client, "
    "to_timestamp(ous.created_on) AS created, "
    "to_timestamp(ocs.timestamp) AS last_active, "
    "round(EXTRACT(EPOCH FROM (now() - to_timestamp(ocs.timestamp))) / 86400, 1) AS idle_days "
    "FROM offline_user_session ous "
    "JOIN user_entity ue ON ue.id = ous.user_id "
    f"JOIN offline_client_session ocs ON ocs.user_session_id = ous.user_session_id AND ocs.{_OFF} "
    "JOIN client c ON c.id = ocs.client_id "
    f"WHERE ous.realm_id = '{_R}' AND ous.{_OFF} "
    "ORDER BY ocs.timestamp DESC"
)

_SQL_BY_CLIENT = (
    "SELECT c.client_id AS client, count(*) AS grants "
    "FROM offline_client_session ocs JOIN client c ON c.id = ocs.client_id "
    f"WHERE ocs.realm_id = '{_R}' AND ocs.{_OFF} GROUP BY c.client_id ORDER BY grants DESC"
)

# Per-azp summary — joins to Mimir cost-by-azp on `azp`.
_SQL_BY_AZP = (
    "SELECT c.client_id AS azp, count(*) AS offline_grants, "
    "count(DISTINCT ous.user_id) AS users "
    "FROM offline_client_session ocs "
    "JOIN client c ON c.id = ocs.client_id "
    f"JOIN offline_user_session ous ON ous.user_session_id = ocs.user_session_id AND ous.{_OFF} "
    f"WHERE ocs.realm_id = '{_R}' AND ocs.{_OFF} GROUP BY c.client_id"
)

# Per-user summary — joins to Mimir cost-by-user_id on `user_id`. Counts CLIENT
# sessions (matching the total/per-azp), so the column sums to the grants stat.
_SQL_BY_USER = (
    f"SELECT ous.user_id, ue.username, {_NAME} AS name, "
    "count(ocs.user_session_id) AS offline_grants, "
    "max(to_timestamp(ocs.timestamp)) AS last_active "
    "FROM offline_user_session ous "
    "JOIN user_entity ue ON ue.id = ous.user_id "
    f"JOIN offline_client_session ocs ON ocs.user_session_id = ous.user_session_id AND ocs.{_OFF} "
    f"WHERE ous.realm_id = '{_R}' AND ous.{_OFF} "
    "GROUP BY ous.user_id, ue.username, ue.first_name, ue.last_name"
)

_SQL_COUNT_GRANTS = (
    f"SELECT count(*) AS grants FROM offline_client_session WHERE realm_id = '{_R}' AND {_OFF}"
)
_SQL_COUNT_USERS = f"SELECT count(DISTINCT user_id) AS users FROM offline_user_session WHERE realm_id = '{_R}' AND {_OFF}"
_SQL_COUNT_CLIENTS = (
    f"SELECT count(DISTINCT client_id) AS clients FROM offline_client_session "
    f"WHERE realm_id = '{_R}' AND {_OFF}"
)


class _SqlTarget:
    """Raw Postgres SQL target (the SDK has no sql builder; with_target just calls
    .build() and the cog JSONEncoder serialises the plain dict natively)."""

    def __init__(self, *, ref_id: str, sql: str) -> None:
        self._d: dict[str, typing.Any] = {
            "refId": ref_id,
            "datasource": {"type": "postgres", "uid": KEYCLOAK_UID},
            "format": "table",
            "rawQuery": True,
            "rawSql": sql,
        }

    def build(self) -> dict[str, typing.Any]:
        return self._d


def _sql_stat(*, title: str, sql: str, color: str, grid: tuple[int, int, int, int]) -> stat.Panel:
    h, w, x, y = grid
    return (
        stat.Panel()
        .title(title)
        .datasource(_KEYCLOAK_DS)
        .grid_pos(dm.GridPos(h=h, w=w, x=x, y=y))
        .unit("short")
        .thresholds(
            db.ThresholdsConfig()
            .mode(dm.ThresholdsMode.ABSOLUTE)
            .steps([dm.Threshold(color=color)])
        )
        .reduce_options(cb.ReduceDataOptions().calcs(["lastNotNull"]).fields("").values(False))
        .with_target(_SqlTarget(ref_id="A", sql=sql))
    )


def _panel_total_grants() -> stat.Panel:
    return _sql_stat(
        title="Active offline grants", sql=_SQL_COUNT_GRANTS, color="blue", grid=(4, 8, 0, 1)
    )


def _panel_users_with_grants() -> stat.Panel:
    return _sql_stat(
        title="Users with a grant", sql=_SQL_COUNT_USERS, color="purple", grid=(4, 8, 8, 1)
    )


def _panel_clients_with_grants() -> stat.Panel:
    return _sql_stat(
        title="Clients holding grants", sql=_SQL_COUNT_CLIENTS, color="green", grid=(4, 8, 16, 1)
    )


def _panel_detail() -> table.Panel:
    # One row per (user, client) offline grant: when granted, last refreshed, and
    # how many days idle (a proxy for "still in use" — small = active).
    return (
        table.Panel()
        .title("Offline grants — who · which client · last active")
        .datasource(_KEYCLOAK_DS)
        .grid_pos(dm.GridPos(h=12, w=24, x=0, y=5))
        .filterable(True)
        .with_target(_SqlTarget(ref_id="A", sql=_SQL_DETAIL))
        .with_transformation(
            dm.DataTransformerConfig(
                id_val="organize",
                options={
                    "renameByName": {
                        "name": "Name",
                        "username": "Username",
                        "client": "Client (azp)",
                        "created": "Granted",
                        "last_active": "Last active",
                        "idle_days": "Idle (days)",
                    },
                    "excludeByName": {},
                    "indexByName": {
                        "name": 0,
                        "username": 1,
                        "client": 2,
                        "last_active": 3,
                        "idle_days": 4,
                        "created": 5,
                    },
                },
            )
        )
        .override_by_name("Idle (days)", [dm.DynamicConfigValue(id_val="unit", value="d")])
    )


def _panel_by_client() -> bargauge.Panel:
    return (
        bargauge.Panel()
        .title("Offline grants by client")
        .datasource(_KEYCLOAK_DS)
        .grid_pos(dm.GridPos(h=8, w=24, x=0, y=17))
        .unit("short")
        .orientation(cm.VizOrientation.HORIZONTAL)
        # values(True): the SQL frame has one row per client, so render one bar
        # PER ROW (named by the client field) rather than reducing the whole
        # `grants` column to a single bar.
        .reduce_options(cb.ReduceDataOptions().fields("/^grants$/").values(True))
        .display_mode(cm.BarGaugeDisplayMode.BASIC)
        .thresholds(
            db.ThresholdsConfig()
            .mode(dm.ThresholdsMode.ABSOLUTE)
            .steps([dm.Threshold(color="blue")])
        )
        .with_target(_SqlTarget(ref_id="A", sql=_SQL_BY_CLIENT))
    )


def _panel_channel_budget() -> table.Panel:
    # Which credential CHANNEL (azp) holds how many grants AND spent how much.
    # Mixed OUTER join on azp: Keycloak grant counts ⋈ Mimir spend.
    return (
        table.Panel()
        .title("Per client channel — grants x spend (selected range)")
        .datasource(_MIXED_DS)
        .grid_pos(dm.GridPos(h=11, w=12, x=0, y=26))
        .filterable(True)
        .with_target(_SqlTarget(ref_id="A", sql=_SQL_BY_AZP))
        .with_target(sh.prom_target(_COST_BY_AZP, ref_id="B", instant=True, fmt="table"))
        .with_transformation(
            dm.DataTransformerConfig(
                id_val="joinByField", options={"byField": LABEL_AZP, "mode": "outer"}
            )
        )
        .with_transformation(
            dm.DataTransformerConfig(
                id_val="organize",
                options={
                    "renameByName": {
                        "azp": "Client (azp)",
                        "offline_grants": "Offline grants",
                        "users": "Users",
                        "Value #B": "Spend ($)",
                    },
                    "excludeByName": {"Time": True},
                    "indexByName": {"azp": 0, "offline_grants": 1, "users": 2, "Value #B": 3},
                },
            )
        )
        .with_transformation(
            dm.DataTransformerConfig(
                id_val="sortBy",
                options={"fields": {}, "sort": [{"field": "Spend ($)", "desc": True}]},
            )
        )
        .override_by_name(
            "Spend ($)",
            [
                dm.DynamicConfigValue(id_val="unit", value="currencyUSD"),
                dm.DynamicConfigValue(id_val="decimals", value=2),
            ],
        )
    )


def _panel_user_budget() -> table.Panel:
    # Per person: how many standing grants, last active, and total spend.
    return (
        table.Panel()
        .title("Per user — grants x spend (selected range)")
        .datasource(_MIXED_DS)
        .grid_pos(dm.GridPos(h=11, w=12, x=12, y=26))
        .filterable(True)
        .with_target(_SqlTarget(ref_id="A", sql=_SQL_BY_USER))
        .with_target(sh.prom_target(_COST_BY_USER, ref_id="B", instant=True, fmt="table"))
        .with_transformation(
            dm.DataTransformerConfig(
                id_val="joinByField", options={"byField": LABEL_USER_ID, "mode": "outer"}
            )
        )
        .with_transformation(
            dm.DataTransformerConfig(
                id_val="organize",
                options={
                    "renameByName": {
                        "name": "Name",
                        "username": "Username",
                        "offline_grants": "Offline grants",
                        "last_active": "Last active",
                        "Value #B": "Spend ($)",
                        LABEL_USER_ID: "User ID (sub)",
                    },
                    "excludeByName": {"Time": True},
                    "indexByName": {
                        "name": 0,
                        "username": 1,
                        "offline_grants": 2,
                        "last_active": 3,
                        "Value #B": 4,
                        LABEL_USER_ID: 5,
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
        .override_by_name(
            "Spend ($)",
            [
                dm.DynamicConfigValue(id_val="unit", value="currencyUSD"),
                dm.DynamicConfigValue(id_val="decimals", value=2),
            ],
        )
    )


_DESCRIPTION = (
    "Keycloak OFFLINE grants (long-lived refresh-token sessions — opencode auth "
    "login caches, LibreChat remember-me, service accounts) resolved to people + "
    "client names via the read-only Keycloak datasource (ADR-0063), cross-referenced "
    "with gateway spend. NB: access tokens are stateless (never in the DB); KC 26 "
    "persistent-sessions keeps online AND offline sessions in offline_*_session, so "
    "this filters offline_flag='1' (offline grants only). Revocation deletes the row "
    "(no tombstone), so a missing grant = revoked/expired/never. Budget is per-user "
    "and per-client (azp), NOT per individual token. Filters: azp, model. "
    "GENERATED — source: tools/dashboards/envoy_ai_gateway/sessions_grants.py."
)


def _dashboard() -> db.Dashboard:
    return (
        db.Dashboard("AI Gateway — sessions & grants")
        .uid("envoy-ai-gateway-sessions-grants")
        .tags(["ai-gateway", "per-user", "identity", "keycloak", "sessions"])
        .description(_DESCRIPTION)
        .timezone("browser")
        .editable()
        .tooltip(dm.DashboardCursorSync.CROSSHAIR)
        .refresh("5m")
        .time("now-30d", "now")
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
        .with_panel(sh.row("Offline grants (Keycloak)", y=0))
        .with_panel(_panel_total_grants())
        .with_panel(_panel_users_with_grants())
        .with_panel(_panel_clients_with_grants())
        .with_panel(_panel_detail())
        .with_panel(_panel_by_client())
        .with_panel(sh.row("Grants x budget", y=25))
        .with_panel(_panel_channel_budget())
        .with_panel(_panel_user_budget())
    )


def build() -> dict:
    return json.loads(json.dumps(_dashboard().build(), cls=JSONEncoder))
