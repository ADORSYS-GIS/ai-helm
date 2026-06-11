# ADR-0040: External MCPs via in-cluster Caddy normalizing proxies

**Status:** Accepted
**Date:** 2026-06-11
**Deciders:** @stephane-segning
**Supersedes:** [ADR-0039](0039-mcp-external-backend-tls-envoypatchpolicy.md)

## Context

Exposing external **hosted** MCP servers (context7, firecrawl, refero) through
the Envoy AI Gateway as direct TLS backends proved fragile, in three distinct
ways the gateway can't fix at the Envoy layer:

1. **Empty SNI** — AIEG stamps a `dummy.transport_socket` on the cluster it
   generates for an external MCP backend; `BackendTLSPolicy`/`Backend.spec.tls`
   never reach it. [ADR-0039](0039-mcp-external-backend-tls-envoypatchpolicy.md)
   worked around this with an `EnvoyPatchPolicy` injecting SNI — but it's
   **brittle** (couples to the AIEG-internal cluster name) and **BoringSSL-only**.
2. **ECDSA certs** — context7 serves an ECDSA cert that Envoy's **BoringSSL
   rejects** at the handshake (`BAD_ECC_CERT`), SNI or not. No Envoy-side fix.
3. **Mislabeled content-type** — refero's `tools/list` returns a plain-JSON body
   with `Content-Type: text/event-stream`; the AIEG mcpproxy parses it as SSE,
   finds no events, and returns **empty tools**
   ([envoyproxy/ai-gateway#2218](https://github.com/envoyproxy/ai-gateway/issues/2218)).

Meanwhile the **self-hosted** MCPs (brave, terraform) — plain-HTTP, in-cluster —
work flawlessly. The common factor in every failure is the **Envoy→external-TLS
hop**, not MCP itself.

## Decision

Front each external hosted MCP with a per-MCP **Caddy "normalizing proxy"**
running in-cluster (`charts/mcp` `mode: proxiedExternal`), turning it into a
plain-HTTP in-cluster backend like the self-hosted ones. The MCPRoute points at
the Caddy `Service` (plain HTTP); Caddy:

- **does the upstream TLS** — Caddy uses **Go's TLS stack, which handles ECDSA**
  certs (validated: context7 handshakes through Caddy), with correct SNI from the
  upstream host;
- **injects the credential** (`header_up Authorization "Bearer {env.MCP_TOKEN}"`,
  token from the in-chart `ExternalSecret`, `optional` so the pod still starts
  anonymously if unsynced);
- **optionally rewrites the response Content-Type** (`header_down`) — refero gets
  `→ application/json` so the mcpproxy parses it (the #2218 workaround); context7
  and firecrawl emit real SSE and need no rewrite.

Off-the-shelf `caddy:2-alpine` + a generated Caddyfile `ConfigMap` — **no custom
image** (Caddy is an established pattern here, ADR-0030). The ADR-0039
`EnvoyPatchPolicy` (`charts/core-gateway` `mcpBackendTls`) is **removed** — no
external MCP terminates TLS at Envoy anymore. Validated live before shipping:
refero → 8 tools (content-type rewritten), context7 → ECDSA handshake + valid
init, firecrawl → 19 tools.

## Consequences

**Positive**

- All three external MCPs work, uniformly, with no Envoy-internal coupling.
- **context7 is back** — Caddy's Go TLS handles the cert BoringSSL rejected (and
  the *remote* context7 needs no Redis, unlike self-hosting it).
- The brittle ADR-0039 `EnvoyPatchPolicy` is gone; external MCPs are now reliable
  in-cluster plain-HTTP backends, same as brave/terraform.

**Negative**

- One extra lightweight pod (Caddy) per external MCP.
- The refero Content-Type rewrite is a **workaround for #2218** — if refero ever
  emits real SSE it would break (its tools are request/response, so safe today).
  Remove the rewrite once #2218 is fixed.
- `context7_api_key` is **unpopulated** in `ssegning-aws` → context7 runs
  anonymous/rate-limited until the maintainer sets it (the `optional` token env
  keeps the pod healthy meanwhile).

**Neutral / follow-ups**

- Drop refero's `rewriteResponseContentType` when #2218 lands — tracked by Epic
  [ai-helm#369](https://github.com/ADORSYS-GIS/ai-helm/issues/369).
- Populate `context7_api_key` for authenticated context7 access.
- `mode: external` (direct TLS backend) is now legacy — prefer `proxiedExternal`
  for any new external MCP.

## Alternatives considered

- **Keep the ADR-0039 EnvoyPatchPolicy** — rejected: brittle cluster-name
  coupling, can't reach ECDSA (context7) or fix content-type (refero).
- **Drop the external MCPs** (as context7 was, briefly) — rejected: the maintainer
  needs them; the proxy makes them reliable without a custom image.
- **Self-host the MCP servers** — rejected for these: context7's HTTP server needs
  a custom build + Upstash Redis; refero is proprietary (no self-host). The proxy
  fronts the *hosted* endpoints instead.
- **Patch the AIEG backend-listener route to fix the content-type** — rejected:
  not feasible (that route config is created by AIEG's extension server *after*
  the stage `EnvoyPatchPolicy` can reach — `ResourceNotFound`).

## Related

- [ADR-0039](0039-mcp-external-backend-tls-envoypatchpolicy.md) (superseded),
  [ADR-0038](0038-mcp-oauth-protected-resource-metadata.md) (MCP OAuth edge),
  [ADR-0027](0027-mcps-orchestrator-split-and-coder-removal.md) (mcps charts),
  [ADR-0030](0030-merge-model-and-proxy-into-one-statefulset-bjw.md) (Caddy precedent).
- [`docs/2026-06-10-mcp-external-server-proxy-debug.md`](../2026-06-10-mcp-external-server-proxy-debug.md) — the full diagnosis.
- [envoyproxy/ai-gateway#2218](https://github.com/envoyproxy/ai-gateway/issues/2218) (the content-type mcpproxy bug).
