# ADR-0134: Retire the firecrawl openresty MCP proxy engine

**Status:** Accepted
**Date:** 2026-08-25
**Deciders:** @stephane-segning

**Supersedes:** [ADR-0041](0041-firecrawl-protocol-version-rewrite-nginx-engine.md) (the openresty engine + `proxy.pinRequestProtocolVersion` request-body rewrite)
**Relates to:** [ADR-0040](0040-external-mcps-via-caddy-normalizing-proxy.md) (the Caddy normalizing-proxy pattern), Story ai-helm #997

## Context

[ADR-0041](0041-firecrawl-protocol-version-rewrite-nginx-engine.md) added an
`openresty` proxy engine to `charts/mcp` — the ONLY case Caddy core could not
handle: rewriting the **request body**. Firecrawl frames its `initialize` SSE
response with an empty leading event for the protocol version the MCP SDK /
opencode send (`2025-11-25`), and the AIEG mcpproxy (≤ v0.7/v1.0) read that first
empty event and failed (`MCP message is not a response: <nil>` → 500 "failed to
create MCP session to any backend" — upstream [envoyproxy/ai-gateway#2219](https://github.com/envoyproxy/ai-gateway/issues/2219)). The openresty (nginx+Lua)
proxy pinned the request body's `protocolVersion` down to `2025-06-18` so
firecrawl framed cleanly.

Upstream fixed the root cause: AIEG's mcpproxy now **skips non-response SSE
events** during `initialize` (PR #2267). The fix ships in **AIEG v1.1.0**
(released 2026-08-21); our pin at the time (v1.0.0, released 2026-06-23) predated
it, so the workaround could not be dropped until the bump.

## Decision

Bump the AI Gateway to **AIEG v1.1.0** (`aieg-crd` + `aieg` → v1.1.0, in lockstep
per ADR-0069) **and** retire the firecrawl openresty workaround in the same
change:

- Remove `proxy.engine: openresty` and `proxy.pinRequestProtocolVersion` from
  firecrawl's `charts/mcps` config — firecrawl now proxies through the default
  **Caddy** engine like context7/refero.
- Remove the `openresty` engine branch from `charts/mcp/templates/deployment.yaml`,
  the `proxy.engine`/`proxy.pinRequestProtocolVersion` schema from
  `charts/mcp/values.yaml`, and the `proxiedexternal-openresty-values.yaml` CI
  fixture. Caddy is now the only proxy engine.

### Scope boundary

The retirement is strictly the **`charts/mcp` proxy engine**. The **Coder OpenCode
workspace sidecar** (`.coder/templates/opencode-{task,web}/main.tf`, ADR-0131) is
an unrelated openresty usage — a per-request rotating-SA-token injector — and is
**not** touched. Caddy cannot replace it (verified: its `{file.read}` placeholder
does not resolve in `header_up`).

## Consequences

**Positive**

- Removes the only case that needed a non-Caddy proxy engine and a request-body
  rewrite — firecrawl is now a stock `proxiedExternal` Caddy MCP like the others.
- Retires the `openresty/openresty:alpine` image and the Lua rewrite from the MCP
  footprint, and the `proxiedexternal-openresty-values.yaml` CI fixture.
- Rides the AIEG v1.1.0 upgrade, which also brings MCP hostname routing,
  `backendSelector` (default Deny) and merged backend capabilities.

**Negative**

- Couples the (isolated) workaround removal to the (gateway-wide) AIEG upgrade in
  one change — if v1.1.0 has an issue the two roll together.
- AIEG v1.1.0 sets a restricted controller security context (non-root UID 65532,
  caps dropped); we use the stock image, so no override is needed, but it is the
  one operator-facing breaking change to be aware of.

## Alternatives considered

- **Defer the removal** (keep openresty, bump AIEG separately) — rejected: the
  fix is confirmed in v1.1.0, and retiring the workaround alongside the bump
  avoids shipping a second PR and a second gateway change.
- **Remove only firecrawl's usage, keep the engine** — rejected for a fuller
  retire: nothing else uses `engine: openresty`, so the dormant engine + CI
  fixture are dead code.

## Related

- Supersedes: [ADR-0041](0041-firecrawl-protocol-version-rewrite-nginx-engine.md).
- Upstream: [envoyproxy/ai-gateway#2219](https://github.com/envoyproxy/ai-gateway/issues/2219) (fixed by [PR #2267](https://github.com/envoyproxy/ai-gateway/pull/2267), shipped in v1.1.0); [#2218](https://github.com/envoyproxy/ai-gateway/issues/2218) (refero) is **still open** — refero's `rewriteResponseContentType` stays.
- Charts/files: `charts/apps/values.yaml` (`aieg-crd`, `aieg` → v1.1.0),
  `charts/mcps/values.yaml`, `charts/mcp/templates/deployment.yaml`,
  `charts/mcp/values.yaml`, `charts/mcp/ci/proxiedexternal-openresty-values.yaml`.
