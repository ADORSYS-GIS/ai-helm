# ADR-0041: firecrawl request protocol-version pin via an openresty proxy engine

**Status:** Accepted
**Date:** 2026-06-11
**Deciders:** @stephane-segning
**Relates to:** [ADR-0040](0040-external-mcps-via-caddy-normalizing-proxy.md) (the Caddy normalizing-proxy pattern this extends)

## Context

After [ADR-0040](0040-external-mcps-via-caddy-normalizing-proxy.md) made the three
external MCPs reachable, **firecrawl alone** kept failing — every
`opencode mcp auth firecrawl` ended in `failed to create new session: failed to
create MCP session to any backend`. context7 and refero worked.

Three wrong hypotheses preceded the real cause (all recorded in
`docs/2026-06-10-mcp-external-server-proxy-debug.md` §9.6–§9.7): stale opencode
creds; firecrawl being stateless (the mcpproxy actually tolerates that); and a
protocol-version *downgrade* (the mcpproxy does not in fact compare echoed vs
requested versions). Reproducing with the **MCP SDK** (not curl) and reading the
mcpproxy's own log (`component=mcp-proxy`, in the `ai-gateway-controller`) gave the
real cause:

```
backend=firecrawl error="MCP message is not a response: <nil>"
```

**firecrawl frames its `initialize` SSE response differently per requested protocol
version.** For the version modern clients send (`2025-11-25`, the MCP SDK / opencode
default) firecrawl prepends an **empty leading SSE event** (`id: …` + `data:` with no
content) before the real `event: message`. The AIEG v0.7.0 mcpproxy reads that first,
empty event, parses it to nil, and fails session creation → HTTP 500. For
`2025-06-18` firecrawl emits clean framing (the real `event: message` first), which
the mcpproxy parses fine.

A/B proof (live gateway): firecrawl init with `2025-06-18` → 200; with `2025-11-25`
→ 500 — same backend, only the requested version differs. The discriminator is the
**framing**, not any version comparison (a response-side version rewrite had no
effect; client `2025-06-18` succeeds even when the response version is altered). This
is an **upstream bug** — the mcpproxy's SSE reader should skip non-response /
keep-alive events — filed as
[envoyproxy/ai-gateway#2219](https://github.com/envoyproxy/ai-gateway/issues/2219).
v0.7.0 is the latest AIEG release; no fix yet.

The fix has to change the **request** (make firecrawl receive a version it frames
cleanly). Neither Caddy nor stock nginx can rewrite a request body.

## Decision

Add an **`openresty` proxy engine** to `charts/mcp` (`proxy.engine: openresty`,
default `caddy`) and a `proxy.pinRequestProtocolVersion` option. openresty
(`openresty/openresty:alpine`, off-the-shelf — nginx + Lua) does the upstream TLS,
injects the Bearer credential, and runs a `rewrite_by_lua_block` that pins the
request body's `protocolVersion`:

```lua
ngx.req.read_body()
local b = ngx.req.get_body_data()
if b then ngx.req.set_body_data((b:gsub([["protocolVersion":"[^"]*"]], [["protocolVersion":"2025-06-18"]]))) end
ngx.req.set_header("Authorization", "Bearer " .. (os.getenv("MCP_TOKEN") or ""))
```

firecrawl thus always receives `2025-06-18` and frames cleanly, so the mcpproxy
parses the response and creates the session. The MCPRoute still points at the
in-cluster proxy Service (plain HTTP). The token comes from the ExternalSecret via
`env MCP_TOKEN;` + `os.getenv` (openresty has no envsubst entrypoint).

context7 and refero stay on the **Caddy** engine. Only firecrawl uses openresty.

The earlier `proxy.statelessUpstream` synthesis (v01–v03) and `proxy.engine: nginx`
+ `rewriteResponseProtocolVersion` (v04) were both based on wrong hypotheses and are
**removed**.

## Consequences

- **firecrawl works in modern MCP clients** (opencode etc.). Validated end-to-end
  against the live gateway with the MCP SDK: `initialize` → 200, `tools/list` → 19
  tools (the chart-rendered manifests, not just a hand-written config).
- **This is an INTERIM.** The pin (`2025-06-18`) is firecrawl's current max clean
  version. When AIEG ships an mcpproxy whose SSE reader skips non-response events
  (#2219), **delete the openresty engine + `pinRequestProtocolVersion` and move
  firecrawl back to the Caddy engine.**
- A second proxy engine (openresty) is now a maintained surface in `charts/mcp`,
  selected only by `engine: openresty`; the default and every other MCP are
  unchanged Caddy. CI render-tests both engines
  (`charts/mcp/ci/proxiedexternal{,-openresty}-values.yaml`).
- The Lua `gsub` assumes compact JSON (`"protocolVersion":"…"`, no spaces), which the
  MCP SDK emits; if a client sent spaced JSON the pin would no-op and firecrawl would
  fail again (acceptable for the interim).
