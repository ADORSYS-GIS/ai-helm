# ADR-0064: Keycloak sessions & grants visibility (extends ADR-0063)

**Status:** Accepted
**Date:** 2026-06-26
**Deciders:** @stephane-segning
**Builds on:** [ADR-0063](./0063-grafana-readonly-keycloak-datasource.md), [ADR-0021](./0021-burst-budget-billing-and-dual-plane-authconfigs.md), [ADR-0035](./0035-per-person-monthly-budget-and-free-50.md), [ADR-0058](./0058-precompute-gateway-usage-metrics-to-mimir.md)

## Context

ADR-0063 added a read-only Keycloak datasource to resolve the per-user `user_id`
(a `sub` UUID) to a person, and — at the maintainer's request — already grants
SELECT on the offline session/token tables. The follow-up ask: surface the
**token objects** so we can see *which grants are still in use, which are revoked,
and which used which budget*.

Answering that honestly requires respecting what Keycloak actually persists
(verified live against the running cluster, Keycloak 26.6.1):

- **Access tokens** — the credentials that actually hit the AI gateway — are
  **stateless signed JWTs**. They are **never stored** in the DB. There is no row
  to enumerate, "still in use", or attribute per-token.
- **Persistent sessions (KC 26).** There is no `user_session` table — instead,
  this Keycloak persists **both online and offline** sessions into the **same**
  `offline_{user,client}_session` tables, distinguished by **`offline_flag`**
  (`'1'` = offline grant, `'0'` = online login). So online sessions *are* in the
  DB here (an earlier "online sessions are in-memory" reading was wrong for this
  version) — every grant query must filter `offline_flag = '1'` or it
  miscounts online web/CLI logins (e.g. the grafana/argocd console sessions) as
  offline grants.
- **Offline sessions** (`offline_*_session` with `offline_flag='1'`) — the
  long-lived refresh-token grants from `offline_access` (opencode CLI caches,
  LibreChat "remember me", service accounts) — are the dashboard's subject. Live:
  127 offline client-sessions, dominated by `opencode-cli` (109).
- **Revocation deletes the row** (no tombstone). Keycloak's `revoked_token` table
  is the live revocation list (currently 0 rows); `not_before` covers bulk
  invalidation. So you observe *present (active)* vs *gone* — you cannot list
  "these were revoked".

And budget: gateway cost is attributed by `x-account-id` (= the user `sub`),
bucketed **per-user** (ADR-0035) and **per-client (`azp`)**. The Mimir cost
metrics carry `user_id`/`azp` labels but **no `jti`/session label** (confirmed
live), and one offline token mints many access tokens — so **per-individual-token
budget is neither available nor well-defined**.

## Decision

Surface offline grants and tie them to budget at the level the data actually
supports, rather than implying per-token precision we don't have.

1. **Column-level `client` grant.** Extend the `grafana-ro-grant` Job (home-os
   `charts/home-apps/keycloak-ha`) with `GRANT SELECT (id, client_id, name) ON
   client TO grafana_ro` — the three columns needed to resolve an offline
   session's client UUID → its `clientId`/name. Pointedly **column-level**, so
   `client.secret` stays out of reach. (`offline_{user,client}_session` were
   already granted under ADR-0063.)

2. **Generated `sessions-grants` dashboard** (`user_directory.py`'s sibling,
   ADR-0008) → `…/files/envoy-ai-gateway/sessions-grants.json`:
   - Stats + a per-(user, client) detail table: who holds a standing grant, on
     which client, when granted, last active, and **idle-days** (a proxy for
     "still in use" — small = active).
   - Offline-grants-by-client bargauge.
   - Two **Mixed-datasource** tables OUTER-joining the Keycloak grant counts to
     the Mimir spend: per-**`azp`** ("which credential channel used which budget")
     and per-**user**. These are the attributable answers to "which used which
     budget".

## Consequences

- **What it answers:** who holds standing long-lived grants, on which client,
  active vs idle, and how that maps to per-user / per-channel spend.
- **What it deliberately does NOT claim:** live access-token tracking (stateless,
  not stored), an enumerable "revoked" list (deletion leaves no tombstone), or
  per-individual-token budget (no `jti` cost label, and the unit is ill-defined).
  The dashboard description states these limits inline so the view isn't
  mis-read as more than it is.
- **Per-token budget would require** promoting `jti` to a Mimir label — an
  **unbounded-cardinality** explosion (every access token is a new `jti`).
  Explicitly rejected; per-`azp`/per-user is the bounded answer.
- **Security boundary holds:** the only new grant is three non-secret columns of
  `client`. No `client.secret`, no `credential`, no authz/consent tables.
- **Cutover ordering** (same as ADR-0063): the home-os column grant lands before
  the dashboard's client-name resolution works; without it the `client`-joining
  panels error while the per-user panel still renders.
