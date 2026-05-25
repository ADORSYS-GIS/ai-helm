# ADR-0011: Canonical `x-oidc-*` downstream header contract

**Status:** Accepted
**Date:** 2026-05-24
**Deciders:** @stephane-segning
**Supplements:** [ADR-0005](./0005-per-user-attribution-via-authorino-headers.md)

## Context

ADR-0005 established the **pattern** — Authorino injects JWT claims as
response headers, the Envoy access log carries them through, Alloy
promotes selected ones to Loki labels. The initial implementation
shipped three headers under the ad-hoc `x-cd-*` prefix (`x-cd-user-id`,
`x-cd-user-name`, `x-cd-azp`).

Reviewing real Keycloak tokens from the `camer-digital` realm
surfaces a larger set of claims that downstream services would benefit
from receiving without re-parsing the JWT:

- **Realm-level roles** (`realm_access.roles`) — e.g. "is this caller
  a realm-admin?"
- **Per-client roles** (`resource_access.<client>.roles`) — the actual
  authorization signal most downstream apps want (LibreChat checks
  `converse: [admin]`, Phoenix used to check `phoenix: [admin]`, etc.)
- **OAuth scopes** (`scope`) — scope-based feature gating
- **JTI** — per-request token id, useful for cross-system tracing
- **Issuer** (`iss`) — multi-realm future-proofing
- **Profile fields** (`email`, `name`) — currently expected by some
  downstream services that would otherwise call `/userinfo` per request

The `x-cd-*` prefix was a placeholder — not self-documenting. The
`x-oidc-*` prefix is the de facto convention used across the
OAuth/OIDC tooling ecosystem; anyone reading a header named
`x-oidc-roles-realm` immediately knows it came from JWT-claim
extraction, not application logic.

## Decision

Rename all Authorino-injected JWT-derived headers from the `x-cd-*`
placeholder to the canonical `x-oidc-*` prefix, and expand the set to
the inventory below.

### The contract

| Header | Selector | Always set? | Notes |
|---|---|---|---|
| **Identity** | | | |
| `x-oidc-user-id` | `auth.identity.sub` | Yes | Keycloak user UUID. **Promoted to Loki label `user_id`.** |
| `x-oidc-user-name` | `auth.identity.preferred_username` | Yes | Human: login. SA: `service-account-<clientid>`. Body only — never a label. |
| `x-oidc-azp` | `auth.identity.azp` | Yes | Authorized Party (client_id). **Promoted to Loki label `azp`.** |
| `x-oidc-iss` | `auth.identity.iss` | Yes | Issuer URL. Constant today; multi-realm future-proofing. |
| **Authorization** | | | |
| `x-oidc-roles-realm` | `auth.identity.realm_access.roles` | Yes | JSON-encoded array. Bounded cardinality. |
| `x-oidc-resource-access` | `auth.identity.resource_access` | Yes | JSON-encoded map `{client: [roles]}`. Lets downstream pick the relevant client without coordinating. |
| `x-oidc-scope` | `auth.identity.scope` | Yes | OAuth scopes, space-separated per spec. |
| **Tracing** | | | |
| `x-oidc-jti` | `auth.identity.jti` | Yes | Per-token unique ID. **Body only — NEVER a Loki label** (per-request unique ⇒ cardinality explosion). Pair with `x-request-id` for cross-system tracing. |
| **Profile (PII)** | | | |
| `x-oidc-email` | `auth.identity.email` | Empty for SAs | PII. Downstream services consuming this MUST treat as PII (redact in logs, restrict access, observe retention). |
| `x-oidc-name` | `auth.identity.name` | Empty for SAs | Full display name. Same PII obligations. |

### Cardinality discipline (Loki labels)

| Label | Status |
|---|---|
| `user_id` | Promoted (bounded by user count; safe at < few thousand) |
| `azp` | Promoted (bounded by client count, ~10–20) |
| Everything else | Body only |

### Explicitly NOT injected

- `acr` (auth context class) — add when a downstream needs step-up auth
- `sid` (session id) — PII-adjacent, add only for session-invalidation flows
- `clientHost` / `clientAddress` (SA tokens only) — Envoy access log
  already captures `downstream_remote_address`; redundant
- `email_verified` — always `true` in our realm flow; add if that changes
- `family_name` / `given_name` — `x-oidc-name` covers the display-name
  need; the separate fields are redundant

## Consequences

**Positive**
- Self-documenting prefix. Anyone reading an access log or downstream
  service header sees `x-oidc-*` and knows the origin.
- Downstream services can do meaningful authz checks
  (`x-oidc-resource-access` is the load-bearing field) without
  re-parsing JWTs or making `/userinfo` calls.
- Tracing improves: `x-oidc-jti` paired with `x-request-id` gives a
  per-request correlation key across the gateway, Authorino, and
  downstream services.
- One canonical inventory in this ADR; downstream services depend on
  the contract, not on whatever shape happened to ship first.

**Negative**
- **PII expansion.** `x-oidc-email` and `x-oidc-name` are now in every
  downstream access log unless that log explicitly redacts. The choice
  was deliberate (per the in-session conversation), but it raises the
  bar on downstream log hygiene. Document the PII obligation in every
  downstream's runbook.
- **Header size.** `x-oidc-resource-access` is JSON-encoded and can be
  several hundred bytes for users with broad role grants. Envoy's
  default header limits (~60KB total) handle this comfortably, but
  worth knowing.
- **Rename is a contract break.** Anything downstream that already
  read `x-cd-*` headers stops working until updated. In practice
  nothing downstream consumed them yet (the per-user dashboard reads
  Loki labels, not headers).

**Neutral / follow-ups**
- If/when a downstream truly wants `acr` or step-up auth, add
  `x-oidc-acr` as a deliberate ADR amendment.
- If the user_id cardinality ever bites, drop the label promotion
  (the header stays). The dashboard query would shift from
  `{user_id=…}` to `| json | user_id="…"`.
- The `x-oidc-resource-access` JSON shape is the de-facto contract.
  Document it in `docs/per-user-observability.md` so downstream
  services don't have to guess the schema.

## Alternatives considered

- **Keep `x-cd-*`** — works, but the prefix has no meaning beyond
  "Camer Digital" which isn't useful identity-system context.
  Rejected on self-documentation grounds.
- **`x-jwt-*`** — clearer than `x-cd-*` but conflates "JWT" the
  format with "OIDC" the protocol. The semantics here are
  OIDC-specific (issuer, scopes, profile claims). Rejected.
- **Inject everything from the JWT verbatim** (full claim set as
  one `x-oidc-claims` JSON blob). Simpler to extend; harder to
  reason about per-header policy (e.g. PII handling). Rejected.
- **Inject only the labels we actually promote** (just user_id + azp
  in headers; everything else stays in the JWT). Forces every
  downstream to verify and parse JWTs themselves. Rejected — the
  whole point of ADR-0005's pipeline is that Authorino has already
  done verification, downstream should reap the benefit.
- **PII-free contract** (drop `x-oidc-email` and `x-oidc-name`).
  Considered; rejected per the in-session decision because some
  existing downstream services key on email.

## Related

- **Supplements** [ADR-0005](./0005-per-user-attribution-via-authorino-headers.md)
  — the propagation pipeline; this ADR specifies the payload contract.
- [ADR-0003](./0003-skip-opa-for-service-accounts.md) — SA detection
  via `azp`; the renamed `x-oidc-azp` is the same value.
- Doc: `docs/per-user-observability.md` (updated to the new contract).
- Files touched: `charts/apps/values.yaml` (response.success.headers),
  `charts/core-gateway/templates/envoy-proxy.yaml` (access-log JSON).
