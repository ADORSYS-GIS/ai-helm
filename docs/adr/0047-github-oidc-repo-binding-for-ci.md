# ADR-0047: Bind GitHub orgs to accounts via OIDC for CI gateway access

**Status:** Proposed
**Date:** 2026-06-14
**Deciders:** @stephane-segning

## Context

CI runners (GitHub Actions) need to use the AI gateway for agentic coding
(opencode). Today the only machine path is a Keycloak service-account client
(`adorsys-gis-github-ci` in the `serviceAccountClients` allowlist) — a long-lived
shared credential that every runner reuses, with no per-org attribution and no
self-service onboarding. We want a customer's CI to authenticate with **nothing
but the standard GitHub Actions OIDC token** it already mints, attributed to that
customer's billing account, with no per-runner registration and no shared secret
in customer repos.

The constraint that shapes the design: a GitHub Actions OIDC token carries
`repository_owner_id` (GitHub's numeric, server-set, immutable org id), but the
token alone says nothing about *who is paying*. Anyone can mint a perfectly valid
GitHub OIDC token for *their* org. So we need a trusted record of which
`repository_owner_id` belongs to which account — established out-of-band, at a
moment only a real org admin can reach.

## Decision

Adopt a **control-plane / data-plane** split, enforced in **Authorino** (not a
Keycloak SPI):

- **Control plane** — a GitHub App (`metadata:read` + install events only, *no*
  code access) whose `installation.*` webhooks are handled by a new service,
  [`lightbridge-repo-auth`](https://github.com/ADORSYS-GIS/lightbridge-repo-auth).
  It records the binding `account_id ↔ repository_owner_id` in Postgres, keyed on
  the numeric owner id captured **from the webhook payload** (never a user form).
  The account is *claimed* by the dashboard during the post-install redirect.
- **Data plane** — the runner sends its **raw GitHub OIDC token** as the gateway
  bearer. Authorino's `main` (external) AuthConfig gains a second JWT
  authentication method for issuer `https://token.actions.githubusercontent.com`.
  On a GitHub identity (`when: iss == …githubusercontent.com`) it calls
  `lightbridge-repo-auth` `POST /v1/resolve` (HTTP metadata, `X-Internal-Token`
  shared secret, ClusterIP-only). The service confirms the token's
  `repository_owner_id` is bound to a **claimed, active** Source (and, for
  `selected` scope, that `repository_id` is in the synced set) and returns
  `{account_id, billing_plan}`. An authorization step gates `allowed == true`;
  the response headers branch via CEL to stamp `x-account-id` / `x-billing-plan`
  from the resolve result. The existing Keycloak path (humans + SA clients) is
  untouched — every new step is `when`-gated to the GitHub issuer.

Enforcement is in Authorino because Keycloak 26.6's native `jwt-bearer` grant
(RFC 7523) requires the token `sub` to link to a *pre-existing Keycloak user* —
incompatible with emergent CI identities (`sub = repo:org/repo:ref:…`), which
must never be pre-registered. Authorino (already the gateway's authz plane,
ADR-0021) has no such requirement and already does external HTTP metadata.

## Consequences

**Positive**
- Self-service onboarding: an org admin installs the App, the dashboard claims
  it, done. No shared secret in customer repos; the only per-customer value is
  the `audience` URL.
- Unforgeable binding: `repository_owner_id` is numeric + server-set; a forged
  token fails JWT validation, a fork carries the fork-owner's id, an attacker's
  own install bills the attacker.
- Per-account attribution + billing reuse the existing `x-account-id` /
  `x-billing-plan` rate-limit/budget machinery (ADR-0021/0035) verbatim.
- The GitHub App never touches a runtime request (auth-only permissions), so the
  blast radius of the App credential is "knows which orgs are customers", nothing
  more.

**Negative**
- New runtime dependency in the auth hot path: a GitHub-issuer request now makes
  an in-cluster HTTP call to `lightbridge-repo-auth`. If that service is down,
  GitHub-OIDC auth fails closed (Keycloak auth is unaffected). Mitigated by 2
  replicas + readiness gating; Keycloak tokens never hit it.
- `repository_owner_id` authorizes the **whole org** — any repo/branch/workflow
  under a bound org can spend the account's quota (`selected` scope narrows to a
  repo set, but not to a branch). Intra-org abuse is out of scope for v1.
- A second public ingress surface (the webhook) to operate + TLS.

**Neutral / follow-ups**
- The `serviceAccountClients` Keycloak path stays as a fallback / for non-GitHub
  machine callers; it is not removed.
- Soft quota under concurrency (parallel runners) is unchanged from ADR-0021.
- Tighter scoping (gate on `environment` / protected GitHub Environments) is a
  future option if intra-org abuse becomes real.
- GHES / custom-issuer support (different `iss`) is future work.

## Alternatives considered

- **Keycloak `jwt-bearer` grant (RFC 7523, GA Keycloak 26.6)** — rejected: requires
  a pre-linked Keycloak user per `sub`; CI `sub`s are emergent and ephemeral, so
  this fights the no-registration goal and adds a user-provisioning step. Its
  `jwt-claim-enforcer` is also static-regex only, so the *dynamic* per-Source
  `owner_id` binding would still need an external lookup.
- **Keycloak Authenticator/Mapper SPI** — rejected: custom Java in the IdP, the
  highest-maintenance, highest-risk option, to do what Authorino external metadata
  already does.
- **Off-the-shelf OIDC brokers (Octo STS, gardener/github-oidc-federation)** —
  rejected: they exchange GitHub OIDC for *GitHub API tokens* (PAT replacement),
  not AI-gateway access. Wrong target; only the trust-policy *idiom* was reused.
- **Shared Keycloak SA client (status quo)** — rejected for the customer-facing
  case: one shared credential, no per-org attribution, no self-service. Kept as a
  fallback.

## Related

- Service: [ADORSYS-GIS/lightbridge-repo-auth](https://github.com/ADORSYS-GIS/lightbridge-repo-auth) (`docs/auth-model.md` = the full trust model + threat table)
- Builds on: [ADR-0021](./0021-burst-budget-billing-and-dual-plane-authconfigs.md) (dual-plane AuthConfigs, descriptors), [ADR-0011](./0011-oidc-downstream-headers.md) (`x-oidc-*` / `x-account-id`), [ADR-0035](./0035-per-person-monthly-budget-and-free-50.md) (per-person budget)
- Charts/files touched: `charts/apps/values.yaml` (AuthConfig `main`), `charts/kuadrant-policies/` (passthrough), the `lightbridge-repo-auth` Application + secrets
