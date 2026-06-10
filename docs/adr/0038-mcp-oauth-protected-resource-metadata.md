# ADR-0038: MCP OAuth discovery via native AIEG MCPRoute `securityPolicy.oauth`

**Status:** Accepted
**Date:** 2026-06-10
**Deciders:** @stephane-segning

## Context

MCP clients (VS Code, the MCP inspector, recent SDKs) implement the [MCP
authorization spec](https://modelcontextprotocol.io/specification/latest/basic/authorization)
(2025-11-25 revision): on a 401 from an MCP endpoint they discover the
**OAuth Protected Resource Metadata** (RFC 9728) — either from the
`WWW-Authenticate: Bearer …, resource_metadata="…"` header (priority) or by
probing the RFC 9728 **path-insertion** URL
(`/.well-known/oauth-protected-resource<mcp-path>`, then the root) — and from
it the authorization server's metadata (Keycloak). Our five MCPRoutes
(`/mcp/{brave,terraform,firecrawl,context7,refero}`, ADR-0027) sat behind the
gateway-level Authorino extAuth (ADR-0021): valid Keycloak JWT = in, but a
401 carried **no discovery surface at all** — no spec-compliant client could
bootstrap auth against `api.ai.camer.digital/mcp/*`.

The deployed Envoy AI Gateway **v0.6.0** has this exact feature built in:
`MCPRoute.spec.securityPolicy.oauth` (issuer + `protectedResourceMetadata`)
makes the gateway verify JWTs with Envoy's native `jwt_authn` filter and
synthesize, on the MCPRoute's own generated HTTPRoute, **unauthenticated**
exact-match DirectResponse rules for
`/.well-known/{oauth-protected-resource,oauth-authorization-server,openid-configuration}<path>`
(AIEG's xDS extension server strips the auth filters from those rules), plus a
`BackendTrafficPolicy` ResponseOverride that stamps the 401
`WWW-Authenticate` challenge with `resource_metadata` (URL derived from the
configured `resource`). CORS headers for the MCP inspector are included.

## Decision

Adopt the **native AIEG mechanism** for every MCP child:

- `charts/mcp` gains an `oauth` values block; when enabled the MCPRoute
  renders `securityPolicy.oauth` with `issuer:
  https://auth.verif.fyi/realms/camer-digital`, `protectedResourceMetadata.resource =
  <publicOrigin><mcp.path>` (e.g. `https://api.ai.camer.digital/mcp/brave`)
  and a human `resourceName`. The orchestrator (`charts/mcps`) carries the
  shared `oauth` config and deep-merges per-MCP overrides into each child.
- **ADR-0011 `x-oidc-*` parity via `claimToHeaders`**: the route-level
  SecurityPolicy AIEG generates *displaces* the gateway-attached Authorino
  policy for the whole MCPRoute (EG policy precedence is whole-policy, not
  merge), so Authorino's headers stop on `/mcp/*`. The leaf maps the full
  ADR-0011 set (`sub`→`x-oidc-user-id`, `azp`, `preferred_username`, `iss`,
  `realm_access.roles`, `resource_access`, `scope`, `jti`, `email`, `name`)
  from the gateway-verified JWT; client-supplied values for those names are
  stripped by AIEG (no spoofing).
- **Path-appended alias**: AIEG serves the PRM only at the path-insertion
  URL. For lenient clients that probe
  `<mcp.path>/.well-known/oauth-protected-resource` instead, the leaf also
  renders an exact-match `HTTPRoute` + `HTTPRouteFilter` DirectResponse
  (byte-equivalent JSON, same CORS headers, no pod) + a route-level
  `SecurityPolicy { authorization.defaultAction: Allow }` whose only purpose
  is to displace the gateway Authorino extAuth so the document is publicly
  readable.
- **No audience validation yet** (`audiences: []`) and **no
  `scopesSupported`**: parity with the Authorino main AuthConfig, which
  checks issuer only; clients omit `scope` and Keycloak applies the client's
  default scopes.

The authz boundary is unchanged from ADR-0021 — a valid `camer-digital`
realm JWT admits you — only the enforcement point on `/mcp/*` moves from
Authorino (extAuth) to Envoy's native JWT filter, same issuer/JWKS.

## Consequences

**Positive**

- Spec-compliant MCP auth bootstrap: PRM at
  `/.well-known/oauth-protected-resource/mcp/<name>`, AS-metadata aliases,
  and the 401 `resource_metadata` challenge — all gateway-synthesized, no
  pods, ~30 lines of values+template.
- Keycloak AS metadata is also exposed per-MCP
  (`/.well-known/{oauth-authorization-server,openid-configuration}/mcp/<name>`),
  snapshotted at reconcile time by the controller (fine — Keycloak's
  endpoints are static).
- Per-user attribution on MCP backends preserved (ADR-0005 spirit) via
  `claimToHeaders`.

**Negative**

- Authorino no longer runs on `/mcp/*`: the ADR-0021 rate-limit descriptors
  (`x-account-id`/`x-org-id`/`x-billing-plan`) are **not stamped** there.
  Nothing consumes them today (no MCP `BackendTrafficPolicy` rate limit; MCP
  backends use their own upstream API keys) — if MCP rate limiting is ever
  wanted, add descriptor stamping back (claimToHeaders can carry
  `sub`→`x-account-id`, but the CEL defaulting for `billing_plan` would need
  AIEG-side support or an extAuth re-attach with `mergeType`).
- Non-primitive claims (`realm_access.roles`, `resource_access`) are
  serialized by Envoy as base64url(JSON), unlike Authorino's plain-JSON
  strings — a consumer parsing those two headers must decode first.
- JWT verification on `/mcp/*` now depends on the `ai-gateway-controller`
  reaching `auth.verif.fyi` at reconcile (metadata + JWKS discovery — a
  discovery failure **fails reconciliation**) and Envoy fetching the remote
  JWKS at runtime. Verified: `envoy-ai-gateway-system`,
  `envoy-gateway-system` and `converse-mcp` carry **no** deny-egress
  baseline today; if one ever lands there, both need an
  `toFQDNs: auth.verif.fyi` allow.

**Neutral / follow-ups**

- AIEG v0.6.0 has a stale TODO claiming "only one MCPRoute per listener can
  use OAuth"; in practice each MCPRoute's well-known rules are exact-match
  on its own path-inserted URLs, so our five routes don't collide — but
  **verify all five discovery endpoints on the live cluster** after the next
  release.
- Audience validation (RFC 8707 `resource` → token `aud`) is the spec's
  recommendation and our gap: requires a Keycloak audience mapper deriving
  `aud` from the requested resource before `audiences:` can be enforced
  without breaking existing tokens.
- Clients with no pre-registered Keycloak client need Dynamic Client
  Registration (Keycloak: trusted-host policy) or Client ID Metadata
  Documents to onboard fully automatically; today a pre-registered client is
  assumed.
- The root form `/.well-known/oauth-protected-resource` (no suffix) is
  intentionally absent — with five MCP resources on one host a single root
  PRM cannot name one canonical `resource` (AIEG 404s it for the same
  reason).

## Alternatives considered

- **Keep Authorino in front and hand-serve static PRM JSON** (HTTPRoute +
  DirectResponse + an anonymous-access carve-out in the main AuthConfig +
  hand-built `WWW-Authenticate` 401 header via Authorino's denyWith) —
  rejected: we'd own four contracts the gateway already implements
  (documents, URL forms, challenge header, CORS), the AuthConfig carve-out
  weakens the "whole host = JWT" invariant, and the descriptors it preserves
  have no consumer on `/mcp/*`.
- **nginx static-serve chart** (the `librechat-opencode-wellknown` pattern,
  ADR-0014) — rejected: a pod + ConfigMap + the subPath-remount gotcha for
  content that two CRs express declaratively; and it still needs the same
  auth carve-out.
- **Path-appended form only** (as originally phrased in the request) —
  rejected: spec-compliant clients probe the path-insertion form and honor
  the 401 `resource_metadata` URL; serving only the non-spec form would miss
  them. We serve both.

## Related

- ADR-0011 (x-oidc header contract), ADR-0021 (dual-plane AuthConfigs — the
  displaced plane), ADR-0027 (mcps orchestrator/leaf split — the charts
  carrying this).
- MCP authorization spec (2025-11-25), RFC 9728, RFC 8414, RFC 8707.
- AIEG v0.6.0 implementation: `internal/controller/mcp_route.go`
  (well-known rule synthesis), `mcp_route_security_policy.go` (PRM JSON, 401
  override), `internal/extensionserver/mcproute.go` (auth-filter strip).
