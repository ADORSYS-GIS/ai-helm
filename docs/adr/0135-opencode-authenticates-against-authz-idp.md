# ADR-0135: opencode authenticates against `authz-idp`, not Keycloak

**Status:** Accepted
**Date:** 2026-08-31
**Deciders:** @stephane-segning

**Relates to:** [ADR-0011](0011-oidc-downstream-headers.md) (the `x-oidc-*` header contract), [ADR-0014](0014-split-librechart-and-opencode-wellknown.md) (the `.well-known/opencode` surface), [ADR-0021](0021-burst-budget-billing-and-dual-plane-authconfigs.md) (the gateway authz + rate-limit planes), [ADR-0063](0063-grafana-readonly-keycloak-datasource.md) (the read-only identity datasource), lightbridge-authz ADR-0012/ADR-0020/ADR-0023/ADR-0025

## Context

`lightbridge-authz`'s `authz-idp` is live and is a full OIDC broker (its
ADR-0023: every route mounted on every deployment). It serves
`https://auth.ai.camer.digital` — discovery and JWKS both answer 200, advertising
`device_authorization_endpoint`, `authorization_endpoint`, `refresh_token`,
RFC 8693 token-exchange and `client_credentials`.

opencode, meanwhile, still logged in against **Keycloak**
(`https://auth.verif.fyi/realms/camer-digital`) through
`@vymalo/opencode-oauth2`, configured in the org-wide well-known
(`charts/librechat-opencode-wellknown`). We own an IdP; opencode was not using
it.

Three facts, established by reading the code rather than assumed, determine the
shape of the change:

1. **The device-code token is already the credential the gateway wants.**
   `authz-idp`'s device-code grant mints an access token carrying `project_id`,
   `account_id`, `budget_tier`, `quota_tier`, `model_policy` and
   `allowed_models` (`crates/lightbridge-authz-rest/src/oauth2_op/store.rs`),
   signed by authz's own key with `iss = https://auth.ai.camer.digital`. That
   `iss` is exactly what the gateway AuthConfig's `lightbridge-apikey` JWT
   identity is pinned to (`ai-helm-values`
   `environments/prod/values/security-policies.yaml`), and that identity enforces
   no audience. There is nothing left to trade the token for.

2. **`@vymalo/opencode-lightbridge` is not a drop-in replacement**, despite being
   the plugin built for exactly this platform. It *always* performs an RFC 8693
   exchange when its `gateway` block is set (`plugin.ts`, `getProjectToken` →
   `exchangeTo`), and lightbridge validates a `subject_token` against a **single**
   `oauth2.jwks_url` — Keycloak's (`crates/lightbridge-authz-bearer/src/lib.rs`).
   A token this IdP signed can therefore never be its own subject token. Its
   premise (one credential shared by the gateway bearer and the OTEL export) is
   also not yet load-bearing here: nothing exports OTLP from opencode today.

3. **`@vymalo/opencode-oauth2` cannot simply be removed.** It is what *registers*
   the `camer-digital` provider and *discovers* its models;
   `@vymalo/opencode-models-info` only enriches entries that already exist (and
   `modelsInfoHideUnmatched` only deletes). Dropping it would empty the model
   picker. The two plugins are also documented upstream as "never on the same
   provider", with separate cache namespaces — i.e. two device-code logins.

## Decision

**Repoint the existing `oauth2` block at `authz-idp`.** That is the entire
cutover: no new plugin, no token exchange, no Keycloak realm work.

1. **`ai-helm-values`** — register an `opencode-cli` **public** client with the
   `device_code` + `refresh_token` grants, `require_pkce: true`, and the
   `openid profile email offline_access` scopes. It goes in **both** the `api:`
   and `idp:` `oauth2.clients` registries, which that file requires be kept
   byte-identical.
   - No `token-exchange` grant — see Context 1; it is unnecessary and could not
     work.
   - No `authorization_code` / `redirect_uris` — opencode uses the device flow,
     and authz matches redirect URIs by string equality with no RFC 8252 §7.3
     loopback exemption (the same constraint documented on `governance-auth-cli`).
   - `email` is requested so the token carries the claim the gateway stamps as
     `x-oidc-email` (ADR-0067's `jwt-tokens` dashboard keys on it).

2. **`ai-helm`** — `charts/librechat-opencode-wellknown/values.yaml` sets
   `issuer: https://auth.ai.camer.digital` and `clientId: opencode-cli`, adds the
   `email` scope, and keeps `authFlow: device_code`.

**Ordering is not optional.** The client must be on `ai-helm-values` `main`
before the chart change ships, or every `opencode auth login` fails
`invalid_client` — the standard values-repo-first rule, with teeth here because
`oauth2.clients` fails **closed**: an empty or unmatched registry rejects every
request rather than leaving the endpoint open.

### `x-account-id` is now the acting lightbridge account id

The gateway derives `x-account-id` (the rate-limit bucket) and `x-oidc-user-id`
(the Loki/Mimir `user_id` label) from the token's `sub`. For an `authz-idp` token
that `sub` is the **acting lightbridge account id**, not a raw Keycloak `sub`.

Today this is a distinction without a difference: lightbridge-authz ADR-0025
grandfathers every pre-existing account so the minted `sub` is byte-identical to
the Keycloak one, pinned by a dedicated regression test
(`grandfathered_account_mints_a_byte_identical_sub_to_the_pre_stage_3_signer`).
Rate-limit buckets and per-user dashboards carry over unchanged.

It stops being true at ADR-0025 **Stage 5** (designed, not implemented), which
introduces accounts that were never grandfathered. ADR-0025's own text asks every
consumer assuming `x-account-id == raw sub` to be audited before then. Ours are
the `x-account-id`/`x-oidc-user-id` CEL expressions and the `user-directory`
dashboard. This ADR records the contract so the assumption is written down rather
than implicit.

### The revocation gate resolves, it does not deny

The minted token carries `api_key_id` (reused for the session id, lightbridge-authz
ADR-0020), which trips the AuthConfig's `lightbridgeintrospect` metadata step —
gated on `api_key_id != ""`. This is correct behaviour, not a misfire:
`introspect_api_key` dispatches any bearer with no matching `api_keys` row through
to `introspect_exchange_token`/`resolve_exchange_token_context`, the live path
that already serves exchange tokens (ADR-0020 §6). It is also what supplies
`x-billing-plan`. **Verify live on cutover** — a 403 on the first real completion
is the signal this reasoning is wrong.

## Consequences

**Good.** We use our own IdP. One fewer dependency on the Keycloak realm for the
opencode plane: the device grant is verified through `authz-idp`'s own RP leg, so
neither a Keycloak client nor the audience mapper the old issuer required is
involved. The token arrives already project-scoped, carrying budget/quota/model
policy the gateway and the Lyft rate-limiter can act on. Model discovery,
rate-limit tiers, and the whole agent/MCP surface of the well-known are untouched.

**Costs and limits, stated plainly.**

- **Every opencode user must re-authenticate once.** The issuer changed; cached
  Keycloak tokens are not valid at the new one.
- **⚠️ The LLM plane and the MCP plane now authenticate against different IdPs.**
  This cutover moves only the `camer-digital` *provider*. The remote MCP servers
  in the same well-known (`mcp.<name>.oauth`, the `&mcpOAuth` anchor) carry only
  a `clientId` + `scope` and **no issuer** — an MCP route advertises its own
  issuer through RFC 9728 discovery, and per ADR-0038 that is verified by Envoy's
  native `jwt_authn` against **Keycloak**. So the Keycloak `opencode-cli` client
  and its `lightbridge-api-key` audience mapper are **not** dead weight; they
  remain load-bearing for `/mcp/*`. Two clients now share one id across two IdPs,
  and a user who enables a remote MCP gets a *second* device-code login. This is
  latent rather than acute: every remote ships `enabled: false` (ADR-0074), so
  nobody hits it until they opt in. Converging the MCP plane onto `authz-idp` is
  follow-up work, and it is a gateway-side change (the `MCPRoute` security
  policy's issuer), not a well-known one.
- **Rollback** is reverting the two files — the Keycloak client is still there
  and still works.
- **`@vymalo/opencode-lightbridge` is not adopted**, so its one-credential design
  buys us nothing yet and no opencode telemetry is exported. Closing that means
  porting provider registration + model discovery into that plugin upstream, so
  it can own the provider outright instead of coexisting with `opencode-oauth2`.
  Tracked as follow-up, not smuggled in here.
- **Exposing the OTLP ingest endpoint was scoped in and then deliberately not
  shipped.** `lightbridge-authz-usage`'s ingest listener (`/v1/otel/*`, port
  3000) applies no JWT, Basic-auth or mTLS check by design — upstream
  `docs/usage-api.md` warns that anyone who reaches it can write fabricated
  usage records for any account. Fronting it with an `HTTPRoute` on the
  `api-https` listener would inherit the Authorino boundary and is the right
  shape (the mTLS query API is on a separate port, 3006, so a port-scoped route
  cannot reach it). It is not shipped because the backend serves TLS from the
  internal CA and this repo has **no established BackendTLSPolicy pattern for an
  internal CA** — only `wellKnownCACertificates: System` — and the result could
  not be verified against the cluster. Shipping an unverified route to an
  unauthenticated-by-design listener is the wrong trade. Even once fronted,
  attribution still comes from the OTLP payload rather than the Authorino-stamped
  `x-account-id`, so an authenticated caller could write records attributed to
  someone else; closing that is an upstream change against `lightbridge-authz`.
- **The `user-directory` dashboard cannot yet resolve a non-grandfathered
  account.** Its "empty Name" column no longer *claims* such rows are non-human
  (that inference would mislabel a real person once Stage 5 lands); it now reads
  as "unresolved" in both the panel tooltip and the dashboard description.
  Actually resolving them needs the lightbridge `accounts` table as a second
  lookup source, which needs a **new least-privilege DB role**: the existing
  `grafana_ro` on `lightbridge-main-db` is a member of `pg_read_all_data`, so
  pointing Grafana at the `authz` database would hand it SELECT on `signing_keys`
  and `federated_identities.token_envelope` — precisely the over-privilege
  ADR-0063 refused for the Keycloak datasource. Not done here on purpose.

## Alternatives considered

- **Swap in `@vymalo/opencode-lightbridge` as-is.** Rejected: it always
  exchanges, and the exchange cannot validate a self-issued subject token
  (Context 2). It would also empty the model picker (Context 3).
- **Keep the Keycloak login and use the plugin's exchange to mint a project
  token.** Workable with plugin 0.15.0, but it keeps Keycloak as the login IdP —
  the opposite of the goal — and requires a Keycloak audience mapper on a
  manually-managed realm (`charts/keycloak-baseline` is not reconciled by
  anything).
- **Adopt the plugin for `otel` only, alongside `opencode-oauth2`.** Avoids the
  same-provider conflict, but separate cache namespaces mean a second device-code
  login per user — the exact cost the umbrella plugin exists to remove.
- **Hand-maintain `provider.models` in the well-known** so the plugin could
  replace `opencode-oauth2` outright. Rejected: trades dynamic discovery for a
  list that silently rots.
