# ADR-0041: firecrawl protocol-version rewrite via an nginx proxy engine

**Status:** Accepted
**Date:** 2026-06-11
**Deciders:** @stephane-segning
**Relates to:** [ADR-0040](0040-external-mcps-via-caddy-normalizing-proxy.md) (the Caddy normalizing-proxy pattern this extends)

## Context

After [ADR-0040](0040-external-mcps-via-caddy-normalizing-proxy.md) made the three
external MCPs reachable, **firecrawl alone** kept failing at the gateway — every
`opencode mcp auth firecrawl` ended in `failed to create MCP session to any
backend`. context7 and refero worked.

The cause is **not** the key, the Caddy proxy, the TLS, or firecrawl being
stateless (an earlier hypothesis — the AIEG mcpproxy supports stateless backends
fine; `internal/mcpproxy/session.go` reads the backend session id but explicitly
tolerates an empty one). The real cause is **MCP protocol-version negotiation**:

- Modern MCP clients (the MCP TypeScript SDK, hence opencode ≥ 1.16) request
  protocol version **`2025-11-25`** on `initialize`.
- firecrawl supports up to `2025-06-18`, so — **correctly, per the MCP spec** — it
  *negotiates down*: it accepts the connection and echoes back
  `"protocolVersion":"2025-06-18"`.
- context7 and refero instead **mirror** the requested `2025-11-25`.
- The **AIEG v0.7.0 mcpproxy requires the backend to echo the client's EXACT
  requested version**; when firecrawl returns a *different* (downgraded) version it
  treats session creation as failed → HTTP 500 `failed to create MCP session to
  any backend`.

A/B proof against the live gateway: firecrawl with `protocolVersion:2025-06-18`
→ **200**; the same firecrawl backend with `2025-11-25` → **500** (only the
requested version differs). firecrawl **direct** accepts `2025-11-25` (200,
echoing `2025-06-18`). So the rejection is the AIEG mcpproxy's, and it's an
**upstream bug** — a spec-compliant downgrade should be honoured. v0.7.0 is the
latest AIEG release; no upstream fix exists yet
([envoyproxy/ai-gateway#2219](https://github.com/envoyproxy/ai-gateway/issues/2219)).

Caddy can't fix this: the negotiated version is in the **response body**, and
Caddy core has no response-body rewriting (only a plugin would, which needs a
custom image — out of bounds per our off-the-shelf-images rule).

## Decision

Add an **`nginx` proxy engine** to `charts/mcp` (`proxy.engine: nginx`, default
`caddy`) for the one case Caddy can't serve — rewriting the response body — and a
`proxy.rewriteResponseProtocolVersion: {from, to}` option that uses nginx
`sub_filter` to rewrite firecrawl's echoed `initialize` protocol version back to
what the client requested:

```nginx
sub_filter '"protocolVersion":"2025-06-18"' '"protocolVersion":"2025-11-25"';
```

nginx (`nginx:alpine`, off-the-shelf — same class as Caddy) does the upstream TLS
(OpenSSL handles firecrawl's cert), injects the Bearer credential from the
ExternalSecret via the image's `envsubst` template feature (`${MCP_TOKEN}`,
scoped by `NGINX_ENVSUBST_FILTER=MCP_TOKEN` so nginx's own `$vars` survive), and
rewrites the version. The MCPRoute still points at the in-cluster proxy Service
(plain HTTP), exactly like the Caddy engine.

context7 and refero stay on the **Caddy** engine (Caddy's TLS handles context7's
ECDSA cert; refero needs the Caddy-only `rewriteResponseContentType`). Only
firecrawl uses nginx.

The earlier `proxy.statelessUpstream` Mcp-Session-Id synthesis (shipped
v01–v03 of 2026-06-11) was based on the wrong premise and is **removed** — the
mcpproxy never required a non-empty backend session id.

## Consequences

- **firecrawl works in modern clients** (opencode, etc.) again.
- **This is an INTERIM.** The `to` version is pinned (`2025-11-25`); a client
  requesting a *different* version (a future MCP spec bump, or an old client on
  `2025-06-18`) would mismatch again. When AIEG ships a mcpproxy that tolerates
  protocol-version downgrade, **delete the nginx engine + `rewriteResponseProtocolVersion`
  and move firecrawl back to the Caddy engine.** Tracked alongside the upstream issue.
- A second proxy engine is now a maintained surface in `charts/mcp`. Kept minimal:
  nginx is selected only by `engine: nginx`; the default and every other MCP are
  unchanged Caddy.
- CI render-tests both engines (`charts/mcp/ci/proxiedexternal{,-nginx}-values.yaml`).
- `sub_filter` on an SSE/streamed body is mildly fragile (a match split across
  chunk boundaries would be missed); validated working against the live upstream,
  and the version string sits within a single `data:` line so this is not a
  practical risk for `initialize`.
