# Coder Workspace URLs & Agent Contract

This document defines the platform URL structure, access patterns, domain routing mechanisms, and agent integration lifecycle for Coder workspace applications on `home-remote` (Kubernetes).

---

## Overview

Developer workspaces hosted in Coder frequently run web applications (e.g. Next.js, Vite, or tRPC dev servers) that require accessible HTTPS URLs. To ensure both human developers and LibreChat UI chat sessions can interact with scaffolded applications, Coder provides flat wildcard subdomains and REST API port sharing capabilities.

---

## 1. Domain & URL Architecture

### Base Access Domain
All Coder workspace applications use the dedicated wildcard domain:
`*.coder-ws.camer.digital`

### Domain Separation & Security Isolation
Workspace applications are purposefully served on `*.coder-ws.camer.digital` rather than subdomains of the main Coder dashboard (`coder.ai.camer.digital`). This design ensures:
- **Origin Isolation**: Prevents untrusted workspace applications from accessing Coder session cookies or localStorage credentials.
- **TLS Certificate Delegation**: Allows independent cert-manager issuance via Cloudflare DNS-01 ACME challenge (`cert-cloudflare` ClusterIssuer) without interfering with HTTP-01 challenges on the primary domain.

### Flat Wildcard Subdomain Pattern
Coder uses a flat, 4-part hyphen-separated label structure:
`https://<port>--<agent-name>--<workspace-name>--<username>.coder-ws.camer.digital`

**Example**:
- Workspace: `my-nextjs-app`
- Agent: `main`
- User: `alex`
- Port: `3000`
- **Resulting URL**: `https://3000--main--my-nextjs-app--alex.coder-ws.camer.digital`

> ⚠️ **RFC 1035 Hostname Limit**: The total length of `<port>--<agent>--<workspace>--<user>` must not exceed **63 characters**.

---

## 2. Default Access Control & Port Sharing Lifecycle

### Security Posture by Default
- **Unshared Ports**: Ports default to `owner` visibility. Unauthenticated requests trigger a `303 See Other` redirect to `/api/v2/applications/auth-redirect`. Authenticated requests from non-owners return `404 Not Found`.
- **Public Port Share**: Explicitly publishing a port makes it accessible to external unauthenticated callers (`HTTP 200 OK`).

---

## 3. LibreChat Coder Agent (`coder_mcp`) Integration Contract

The LibreChat Coder agent (`coder`) is registered as a **Subagent** delegated to by primary orchestrators (such as `@converse` via `subagentNames: ["coder"]`).

When a user in LibreChat requests app prototyping or hosting, `@converse` delegates workspace provisioning to `@coder`. The `@coder` subagent executes the following contract:

### Step-by-Step Publishing Lifecycle

1. **URL Synthesis**:
   Construct the flat wildcard subdomain URL:
   `https://<port>--<agent>--<workspace>--<user>.coder-ws.camer.digital`

2. **Programmatic Port Publishing**:
   Send a `POST` request to the Coder REST API:
   ```http
   POST /api/v2/workspaces/{workspace_id}/port-share HTTP/1.1
   Host: coder.ai.camer.digital
   Coder-Session-Token: <agent_session_token>
   Content-Type: application/json

   {
     "agent_name": "main",
     "port": 3000,
     "share_level": "public",
     "protocol": "http",
     "workspace_id": "<workspace_id>"
   }
   ```
   *Note*: `share_level` can be set to `"public"` for instant browser previews or `"authenticated"` if Keycloak SSO is required.

3. **URL Verification**:
   Verify that the URL returns `HTTP 200 OK` rather than `303 See Other` (`auth-redirect`).

4. **Revocation**:
   When the demo or preview session ends, revoke public access by issuing a `DELETE` request to `/api/v2/workspaces/{workspace_id}/port-share` with a body identifying the share:
   ```http
   DELETE /api/v2/workspaces/{workspace_id}/port-share HTTP/1.1
   Host: coder.ai.camer.digital
   Coder-Session-Token: <agent_session_token>
   Content-Type: application/json

   {
     "agent_name": "main",
     "port": 3000
   }
   ```

---

## References

- [ADR-0121: Coder Workspace URL Exposure Strategy](../adr/0121-coder-workspace-url-exposure-strategy.md)
- [`coder-agent-system-prompt.md`](coder-agent-system-prompt.md) — LibreChat Coder Agent System Prompt Specification (Ticket #832)
- ADR-0019 — App-of-Apps orchestrator pattern (`charts/coder`)
- ADR-0083 — Coder re-introduction
- [`coder-platform-integration.md`](coder-platform-integration.md) — the wider Coder integration
- [Coder docs: wildcard access URL](https://coder.com/docs/admin/setup#wildcard-access-url)
