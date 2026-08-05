# ADR-0121: Coder Workspace URL Exposure Strategy

**Status:** Accepted  
**Date:** 2026-08-05  
**Deciders:** @stephane-segning  

## Context

Under Epic #821 (LibreChat Autonomous App Scaffolding), the LibreChat Coder agent (`coder_mcp`) provisions developer workspace pods on our Kubernetes cluster (`home-remote`). Applications running inside these workspaces (e.g. Next.js, Vite, or tRPC dev servers) require accessible HTTPS URLs so that both human developers and LibreChat UI users can preview scaffolded web applications directly from chat.

We evaluated three candidate URL exposure strategies:
1. **Strategy A: Community / Reverse-Proxy Tunneling** (omitting `CODER_ACCESS_URL` and relying on built-in tunnel relays).
2. **Strategy B: Wildcard Access URLs (`CODER_WILDCARD_ACCESS_URL`) with Explicit Port Sharing** (using `*.coder-ws.camer.digital` and Coder API port shares).
3. **Strategy C: Coder Desktop P2P VPN** (WireGuard mesh routing via `<workspace>.coder:PORT`).

## Decision

Adopt **Strategy B: Wildcard Access URLs with Explicit Port Sharing** as the standard platform mechanism for workspace URL exposure, and formalize the Coder API integration contract for the LibreChat Coder agent.

Key technical specifications:
- **Domain Structure**: Workspace apps are served on `https://<port>--<agent>--<workspace>--<user>.coder-ws.camer.digital`.
- **TLS Certificate Issuance**: Wildcard certificates (`coder-wildcard-tls`) are managed via cert-manager using the `cert-cloudflare` ClusterIssuer (DNS-01 ACME challenge).
- **Default Security Posture**: Unshared workspace ports default to `owner` scope. Requests from unauthenticated callers return `303 See Other` (`/api/v2/applications/auth-redirect`). Requests from authenticated non-owners return `404 Not Found` (preventing workspace enumeration).
- **Programmatic Port Publishing**: The LibreChat Coder agent explicitly publishes scaffolded dev server ports via `POST /api/v2/workspaces/{id}/port-share` with `share_level: "public"` (for unauthenticated external preview links) or `"authenticated"` (for Keycloak SSO restricted previews).

## Consequences

**Positive**
- **Automated TLS & Resolution**: Every workspace app gets a valid Let's Encrypt wildcard HTTPS certificate automatically without manual port-forwarding or ingress configuration per application.
- **Granular Authorization & Security**: Default `owner` access prevents accidental exposure. Opt-in sharing allows explicit control over whether links require Keycloak login (`authenticated`) or open access (`public`).
- **Domain Security Isolation**: Keeping workspace apps on `*.coder-ws.camer.digital` (Cloudflare DNS) rather than subdomains of `coder.ai.camer.digital` isolates workspace app origin cookies from Coder dashboard credentials and satisfies Cloudflare DNS-01 ACME delegation constraints.
- **Agent Interoperability**: LibreChat Coder agents can generate, publish, and return deterministic preview URLs using standard Coder API endpoints.

**Negative**
- **Public Exposure Risk**: Dev servers published with `share_level: "public"` have no authentication layer. Agents and developers must explicitly revoke shares (`DELETE /api/v2/workspaces/{id}/port-share`) when demos complete.
- **63-Character Label Constraint**: RFC 1035 limits total hostname labels (`<port>--<agent>--<workspace>--<user>`) to 63 characters.

**Neutral / follow-ups**
- Integrate explicit port share lifecycle management (`POST` to publish, `DELETE` to revoke) into `coder_mcp` tool execution workflows.
- Retain Coder Desktop (Strategy C) as a supported secondary pattern for desktop-native developer workflows requiring direct P2P mesh access.

## Alternatives Considered

- **Strategy A: Community / Reverse-Proxy Tunneling** — Rejected because relying on external tunnel relays or disabling `CODER_ACCESS_URL` bypasses cluster ingress, Cloudflare WAF, and centralized RBAC controls.
- **Strategy C: Coder Desktop (P2P Mesh)** — Rejected as the primary mechanism for LibreChat UI preview links because it requires a client daemon on the end-user workstation, which is incompatible with pure web browser chat sessions.

## Related

- Epic: #821 (LibreChat Autonomous App Scaffolding)
- Ticket: #829 (Spike: Coder workspace public accessibility)
- Docs: [`docs/integrations/coder-workspace-urls.md`](../integrations/coder-workspace-urls.md)
- ADR-0083 (Re-introduce Coder as App-of-Apps Orchestrator)
