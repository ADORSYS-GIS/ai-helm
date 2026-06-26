# ADR-0063: Grafana read-only Keycloak datasource for user_id → identity attribution

**Status:** Accepted
**Date:** 2026-06-26
**Deciders:** @stephane-segning
**Builds on:** [ADR-0011](./0011-oidc-downstream-headers.md), [ADR-0021](./0021-burst-budget-billing-and-dual-plane-authconfigs.md), [ADR-0046](./0046-per-user-attribution-otlp-envelope-repair.md), [ADR-0058](./0058-precompute-gateway-usage-metrics-to-mimir.md), [ADR-0008](./0008-python-dashboard-generation.md)

## Context

The per-user cost observability (ADR-0046/0058) keys every gateway request on a
`user_id` label. For a Keycloak access token that is the `sub` — a **UUID**. The
human-readable `email`/`display_name` labels are populated from JWT claims
(`x-oidc-email`/`x-oidc-name`, ADR-0011), so when a token **lacks those claims**
Alloy stamps the `missing:<claim>` / `unstamped:<field>` sentinels and the opaque
UUID becomes the only stable identifier. On the dashboards those requests show up
as un-named UUIDs — "who is `49534505-4c60-…`?" Today answering that means a
manual Keycloak Admin API lookup.

Every un-named `user_id` is either a Keycloak `sub` (a real person whose token
was thin) or a non-human subject (a CI repo subject like
`repo:ADORSYS-GIS/ai-helm:pull_request`, or an `internal-key-*` service). We want
the Keycloak ones resolved **on the dashboard**, automatically.

Keycloak, Grafana and the gateway all run on the same (Hetzner `home-remote`)
cluster, and its CNPG Postgres holds the authoritative `user_entity` table
(`id` = the `sub`, plus `username`/`email`/`first_name`/`last_name`). So we can
resolve `user_id` → identity with a **read-only Grafana Postgres datasource onto
the Keycloak DB**, joined at query time against the Mimir per-user metrics. This
is the exact pattern the Lightbridge dashboards already use (`lci-postgres` →
its CNPG DB, ADR-0046) — a proven shape, not a new mechanism.

Two constraints shaped the design:

1. **It is the AUTH database.** The Keycloak DB also holds password/OTP hashes
   (`credential`), client secrets, federated-identity tokens, LDAP bind creds
   (`component_config`, `user_federation_*`). A blanket `pg_read_all_data` role
   (what `lci-postgres` uses for the low-sensitivity app DB) would hand all of
   that to Grafana. Unacceptable here.
2. **Cross-repo ownership.** home-os owns the Keycloak CNPG cluster
   (`charts/home-apps/keycloak-ha`); ai-helm/ai-helm-values own the Grafana
   stack. The read-only DB role must be created where the cluster is defined.

## Decision

Add a **least-privilege** read-only role and a Grafana datasource onto it,
joined to the Mimir metrics by a generated dashboard.

### 1. Read-only DB role — `grafana_ro` (home-os)

In `home-os` `charts/home-apps/keycloak-ha` (the Keycloak CNPG cluster):

- A CNPG `managed.roles` entry `grafana_ro` — `login: true`, **not** a member of
  `pg_read_all_data`. CNPG creates/maintains the role and sets its password from
  a basic-auth Secret.
- An `ExternalSecret` materialising that basic-auth Secret from `ssegning-aws`
  `prod/meta/test-app` → **`keycloak_grafana_ro_db_password`** (a new property).
- An idempotent **GRANT Job** (ArgoCD `Sync` hook, `BeforeHookCreation` delete)
  that, once CNPG has created the role, grants `SELECT` on the **user-identity +
  token tables only**: `user_entity`, `user_attribute`, `offline_user_session`,
  `offline_client_session`. CNPG managed roles can't express per-table grants, so
  the scoping runs as SQL by the `app` table owner. The Job has a bounded wait
  loop + `activeDeadlineSeconds` backstop so a never-created role (e.g. the
  password ExternalSecret never synced) fails the hook fast instead of hanging
  the ArgoCD Sync. **Deliberately NOT granted:** `credential`,
  `federated_identity`, `client`, `component_config`, `realm`,
  `user_federation_*` — and also the **authz/consent** tables
  (`user_role_mapping`, `user_group_membership`, `user_consent*`,
  `user_required_action`): they are neither identity nor tokens, the dashboard
  never queries them, and granting them would only widen the blast radius if the
  datasource credential leaked.

The grant scope is "users and tokens, only" — chosen over `pg_read_all_data`
because this is the auth DB.

### 2. Datasource + plumbing (ai-helm-values)

- A `Keycloak` Postgres `GrafanaDatasource` (`uid: keycloak`) inline-provisioned
  in `environments/prod/values/grafana.yaml`, pointing at the **read replica**
  `keycloak-ha-cluster-ro.keycloak.svc.cluster.local:5432`, database `app`, user
  `grafana_ro`, `sslmode: require` (the cluster serves TLS from `self-signed-ca`;
  `require` encrypts without needing a CA bundle mounted). Password injected via
  `$__env{KEYCLOAK_GRAFANA_RO_PASSWORD}` from a new `keycloak-grafana-ro`
  `ExternalSecret` (same `prod/meta/test-app` property), wired through Grafana's
  `envFromSecrets`.
- A vanilla `NetworkPolicy` `grafana-allow-egress-keycloak-db`
  (`base/deps/observability-secrets`) opening Grafana → the Keycloak CNPG pods on
  5432 — the observability namespace runs a deny-all-egress baseline, so without
  it every keycloak-backed panel times out (the `keycloak` namespace has no
  default-deny-ingress, so only egress needs opening). Mirrors the live
  `grafana-allow-egress-lightbridge-db` sibling.

### 3. Generated dashboard (ai-helm)

A new `user_directory.py` generator (ADR-0008) →
`charts/observability-dashboards/files/envoy-ai-gateway/user-directory.json`:

- **"Spend by user — resolved to identity"** — a `-- Mixed --` table: Mimir
  `sum by (user_id)` cost/requests OUTER-joined (`joinByField`) to the Keycloak
  directory on `user_id`. Rows with no Keycloak match keep their spend with an
  empty Name — that's the signal that the subject is non-human (CI / internal).
- **"Keycloak user directory (camer-digital)"** — the raw `user_id` → identity
  lookup, straight from `user_entity`.

Because `grafana_ro` can't read the `realm` table, both queries filter
`user_entity.realm_id` by the **literal** internal id of the trusted realm
(`camer-digital` = `04793949-13aa-48ef-9d4d-1c60761f0c97`,
`_common.CAMER_DIGITAL_REALM_ID`), not by name.

## Consequences

- **Cutover is values-repo-first AND out-of-band-secret-first.** Add the
  `keycloak_grafana_ro_db_password` property to `ssegning-aws`
  `prod/meta/test-app` **before** the home-os change syncs (else the role gets no
  password and both ExternalSecrets sit in `SecretSyncedError`). Merge order:
  (1) SM property, (2) home-os (role + grant), (3) ai-helm-values (datasource +
  egress + secret), (4) ai-helm (dashboard). The datasource only authenticates
  once (2) has run.
- **Blast radius is bounded to identity data.** Even with a leaked `grafana_ro`
  credential, an attacker reads usernames/emails/sessions for `camer-digital`
  users — never password hashes, client secrets, or federated tokens. Read
  replica + `maxOpenConns: 5` keep load off the primary.
- **Resolves ALL historical UUIDs** without re-processing logs or inflating
  metric cardinality, and stays correct as names change (Keycloak is the source
  of truth). It does **not** fix the upstream thin-token problem — tokens still
  arrive without email/name claims; this resolves them at read time. Making
  Authorino/Keycloak always emit those claims is a separate, complementary fix.
- **New cross-table grants** are needed only if a future query wants more columns
  (e.g. broker links in `federated_identity`) — add the table to the GRANT Job
  deliberately, never broaden to `pg_read_all_data`.
- The `realm_id` literal must be re-confirmed if the realm is ever recreated
  (`SELECT id FROM realm WHERE name='camer-digital'`).
