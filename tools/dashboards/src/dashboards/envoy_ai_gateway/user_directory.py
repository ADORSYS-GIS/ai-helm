"""Envoy AI Gateway — user directory / identity attribution (GENERATED SOURCE).

The per-user cost dashboards key on the gateway `user_id` label, which for a
Keycloak access token is the `sub` — a UUID. When the token doesn't carry the
email/name claims (so Alloy stamps the `missing:`/`unstamped:` sentinels), that
opaque UUID is the only stable identifier left and the dashboards can't say WHO
it is. This dashboard closes that gap by joining the Mimir per-`user_id` spend
against a **read-only Postgres datasource onto the Keycloak DB** (ADR-0063), so
every UUID resolves to a real name/email at query time — no JWT claim required.

Two panels:
  1. "Spend by user — resolved to identity" — a MIXED-datasource table: Mimir
     `sum by (user_id)` cost/requests OUTER-joined to the Keycloak directory on
     `user_id`. Rows with no Keycloak match keep their cost with an empty Name —
     those are the non-human subjects (CI repo subs, internal-key-* services).
  2. "Keycloak user directory (camer-digital)" — the raw user_id → identity
     lookup table, straight from `user_entity`.

The Keycloak role (`grafana_ro`) is scoped to user+token tables only and is NOT
granted the `realm` table, so the realm is filtered by its literal internal id
(`_common.CAMER_DIGITAL_REALM_ID`), not by name. See ADR-0063.

The JSON file is regenerated from this module — do **not** hand-edit it::

    uv run dashboards build

ADR: docs/adr/0063-grafana-readonly-keycloak-datasource.md (+ ADR-0008).
"""

from __future__ import annotations

import json
import typing

from grafana_foundation_sdk.builders import dashboard as db
from grafana_foundation_sdk.builders import table
from grafana_foundation_sdk.cog.encoder import JSONEncoder
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

OUTPUT_PATH: str = "charts/observability-dashboards/files/envoy-ai-gateway/user-directory.json"

_KEYCLOAK_DS = dm.DataSourceRef(type_val="postgres", uid=KEYCLOAK_UID)
# Panel-level datasource for the joined table: the Grafana "-- Mixed --" handle,
# so each target carries its own (Mimir vs Keycloak) datasource.
_MIXED_DS = dm.DataSourceRef(type_val="datasource", uid="-- Mixed --")

_SEL = sh.selector('azp=~"$azp"', 'model=~"$model"')

# Mimir spend/requests per user_id over the dashboard range (instant → table).
_COST_BY_USER_ID = sh.usd(
    f"sum by ({LABEL_USER_ID}) (increase({METRIC_COST_MICRO_USD}{_SEL}[$__range]))"
)
_REQS_BY_USER_ID = f"sum by ({LABEL_USER_ID}) (increase({METRIC_REQUESTS}{_SEL}[$__range]))"

# Keycloak directory: user_id (sub) → identity, for the trusted realm only.
# `name` collapses first/last to one column (NULL when both blank).
_DIRECTORY_SQL = (
    "SELECT id AS user_id, username, email, "
    "NULLIF(TRIM(COALESCE(first_name, '') || ' ' || COALESCE(last_name, '')), '') AS name "
    "FROM user_entity "
    f"WHERE realm_id = '{CAMER_DIGITAL_REALM_ID}'"
)
_DIRECTORY_SQL_ORDERED = _DIRECTORY_SQL + " ORDER BY username"


class _SqlTarget:
    """Minimal `cogbuilder.Builder[Dataquery]` for a raw Postgres SQL target.

    The SDK ships no postgres/sql query builder, but `table.Panel.with_target`
    only calls `.build()` and appends the result to `panel.targets`; the cog
    JSONEncoder serialises a plain dict natively. So a tiny wrapper returning the
    raw Grafana postgres query object is enough (same pattern as per_user's
    `_RowBuilder`). `rawQuery: True` makes Grafana use `rawSql` verbatim.
    """

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


def _panel_spend_resolved() -> table.Panel:
    # Mixed-datasource OUTER join on `user_id`: Mimir A=cost, C=requests (one row
    # per user_id) ⋈ Keycloak B=identity. organize renames/reorders and drops the
    # join's leftover Time/realm noise; sortBy ranks by cost. An empty Name marks
    # a non-human subject (CI repo sub / internal-key-* service).
    panel = (
        table.Panel()
        .title("Spend by user — resolved to identity (selected range)")
        .datasource(_MIXED_DS)
        .grid_pos(dm.GridPos(h=14, w=24, x=0, y=1))
        .filterable(True)
        .with_target(sh.prom_target(_COST_BY_USER_ID, ref_id="A", instant=True, fmt="table"))
        .with_target(sh.prom_target(_REQS_BY_USER_ID, ref_id="C", instant=True, fmt="table"))
        .with_target(_SqlTarget(ref_id="B", sql=_DIRECTORY_SQL))
        .with_transformation(
            dm.DataTransformerConfig(
                id_val="joinByField",
                options={"byField": LABEL_USER_ID, "mode": "outer"},
            )
        )
        .with_transformation(
            dm.DataTransformerConfig(
                id_val="organize",
                options={
                    "renameByName": {
                        "name": "Name",
                        "email": "Email",
                        "username": "Username",
                        LABEL_USER_ID: "User ID (sub)",
                        "Value #A": "Cost ($)",
                        "Value #C": "Requests",
                    },
                    "excludeByName": {"Time": True, "Time 1": True, "Time 2": True},
                    "indexByName": {
                        "name": 0,
                        "email": 1,
                        "username": 2,
                        LABEL_USER_ID: 3,
                        "Value #A": 4,
                        "Value #C": 5,
                    },
                },
            )
        )
        .with_transformation(
            dm.DataTransformerConfig(
                id_val="sortBy",
                options={"fields": {}, "sort": [{"field": "Cost ($)", "desc": True}]},
            )
        )
    )
    return panel.override_by_name(
        "Cost ($)",
        [
            dm.DynamicConfigValue(id_val="unit", value="currencyUSD"),
            dm.DynamicConfigValue(id_val="decimals", value=2),
        ],
    )


def _panel_directory() -> table.Panel:
    # Raw user_id → identity lookup straight from Keycloak. Resolves every UUID
    # in the trusted realm regardless of whether it has any gateway traffic.
    return (
        table.Panel()
        .title("Keycloak user directory (camer-digital)")
        .datasource(_KEYCLOAK_DS)
        .grid_pos(dm.GridPos(h=16, w=24, x=0, y=16))
        .filterable(True)
        .with_target(_SqlTarget(ref_id="A", sql=_DIRECTORY_SQL_ORDERED))
        .with_transformation(
            dm.DataTransformerConfig(
                id_val="organize",
                options={
                    "renameByName": {
                        "name": "Name",
                        "email": "Email",
                        "username": "Username",
                        "user_id": "User ID (sub)",
                    },
                    "excludeByName": {},
                    "indexByName": {
                        "name": 0,
                        "email": 1,
                        "username": 2,
                        "user_id": 3,
                    },
                },
            )
        )
    )


_DESCRIPTION = (
    "Resolves the Envoy AI Gateway per-user `user_id` (a Keycloak `sub` UUID) to "
    "a real person by joining the Mimir per-user spend (ADR-0058) against a "
    "read-only Postgres datasource onto the Keycloak DB (ADR-0063). Use this when "
    "the per-user/cost dashboards show opaque UUIDs because the access token "
    "lacked the email/name claims. Rows with an empty Name are non-human subjects "
    "(CI repo subjects, internal-key-* services). Realm filtered by literal id "
    "(the role can't read the `realm` table). Filters: azp, model. "
    "GENERATED — source: tools/dashboards/envoy_ai_gateway/user_directory.py."
)


def _dashboard() -> db.Dashboard:
    return (
        db.Dashboard("AI Gateway — user directory (identity attribution)")
        .uid("envoy-ai-gateway-user-directory")
        .tags(["ai-gateway", "per-user", "identity", "keycloak"])
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
        .with_panel(sh.row("Identity attribution", y=0))
        .with_panel(_panel_spend_resolved())
        .with_panel(_panel_directory())
    )


def build() -> dict:
    return json.loads(json.dumps(_dashboard().build(), cls=JSONEncoder))
