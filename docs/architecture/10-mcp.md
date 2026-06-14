# 10 · MCP servers

How Model Context Protocol tool servers are exposed through the gateway — the
OAuth discovery carve-out, and the in-cluster proxy modes that make flaky
external MCPs behave. Source ADRs: **0038** (OAuth discovery), **0040**
(proxiedExternal Caddy), **0041** (openresty request rewrite). Namespace
`converse-mcp`, orchestrator `charts/mcps`, leaf `charts/mcp`.

## The MCP catalog

```mermaid
flowchart TB
    GW["Envoy AI Gateway<br/>/mcp/* (native jwt_authn)"]:::own

    subgraph self["Self-hosted (in-cluster, plain HTTP)"]
        BRAVE["brave<br/>mcp/brave-search"]:::own
        TF["terraform<br/>hashicorp/terraform-mcp-server"]:::own
    end
    subgraph proxied["proxiedExternal (in-cluster proxy → external TLS)"]
        CTX["context7 → mcp.context7.com<br/><i>engine: caddy</i>"]:::own
        REF["refero → api.refero.design<br/><i>caddy + Content-Type rewrite</i>"]:::own
        FC["firecrawl → mcp.firecrawl.dev<br/><i>engine: openresty + protocol pin</i>"]:::own
    end

    EXT["external MCP services"]:::ext

    GW --> BRAVE & TF
    GW --> CTX & REF & FC
    CTX -.TLS.-> EXT
    REF -.TLS.-> EXT
    FC -.TLS.-> EXT

    classDef own fill:#eaf3ea,stroke:#4a8a4a;
    classDef ext fill:#eee,stroke:#888,stroke-dasharray:4 3;
```

| MCP | Mode | Proxy engine | Upstream |
|---|---|---|---|
| `brave` | selfHosted | — | in-cluster image |
| `terraform` | selfHosted | — | in-cluster image |
| `context7` | proxiedExternal | caddy | `mcp.context7.com` |
| `refero` | proxiedExternal | caddy | `api.refero.design` |
| `firecrawl` | proxiedExternal | openresty | `mcp.firecrawl.dev` (`/v2/mcp`) |

## The OAuth carve-out (ADR-0038)

`/mcp/*` is the one place Authorino is bypassed. Each `MCPRoute` carries
`securityPolicy.oauth`, and an Envoy route-level `SecurityPolicy` **displaces**
the gateway-attached Authorino policy *whole* (no merge).

```mermaid
sequenceDiagram
    autonumber
    participant C as MCP client (opencode)
    participant GW as Envoy gateway
    participant KC as Keycloak

    Note over C,GW: Discovery surface — served UNAUTHENTICATED
    C->>GW: GET /.well-known/oauth-protected-resource/mcp/(name)
    GW-->>C: 200 RFC 9728 metadata (resource + AS aliases)
    C->>GW: POST /mcp/(name) (no token)
    GW-->>C: 401 WWW-Authenticate: resource_metadata=...
    C->>KC: OAuth flow → Keycloak JWT
    C->>GW: POST /mcp/(name) (Bearer JWT)
    GW->>GW: native jwt_authn (Keycloak issuer)<br/>claimToHeaders → x-oidc-* (ADR-0011)
    GW->>GW: route to in-cluster MCP backend
    GW-->>C: tool result
```

- JWT verification = Envoy's native `jwt_authn` (same Keycloak issuer as Authorino).
- The gateway serves discovery itself: the path-insertion form
  `/.well-known/oauth-protected-resource/mcp/(name)`, AS-metadata aliases, the 401
  `resource_metadata` challenge, plus a non-spec path-appended alias.
- `claimToHeaders` re-stamps the `x-oidc-*` set (caveat: object/array claims
  arrive base64url(JSON), not plain JSON).
- **No rate-limit descriptors** on `/mcp/*` — no MCP rate limiting today.

## Why external MCPs go through in-cluster proxies (ADR-0040)

Direct external-TLS MCP backends were unfixable at the Envoy layer. The three
distinct failures and their fix:

```mermaid
flowchart TB
    subgraph problems["Why direct Envoy TLS backends failed"]
        P1["AIEG stamps empty-SNI<br/>dummy.transport_socket<br/>(BackendTLSPolicy never reaches it)"]:::warn
        P2["BoringSSL rejects context7's<br/>ECDSA cert (BAD_ECC_CERT)"]:::warn
        P3["refero mislabels JSON as<br/>text/event-stream → empty tools<br/>(AIEG #2218)"]:::warn
        P4["firecrawl prepends empty SSE event<br/>for protocol 2025-11-25 → 500<br/>(AIEG #2219)"]:::warn
    end

    subgraph fix["Fix: per-MCP in-cluster normalizing proxy"]
        CADDY["Caddy (caddy:2-alpine)<br/>Go TLS handles ECDSA ✅<br/>injects Bearer (header_up)<br/>refero: rewrite Content-Type (header_down)"]:::own
        ORS["openresty (nginx+Lua)<br/>rewrite_by_lua_block:<br/>pin request protocolVersion → 2025-06-18<br/>inject Bearer via os.getenv"]:::own
    end

    P1 --> CADDY
    P2 --> CADDY
    P3 --> CADDY
    P4 --> ORS

    classDef warn fill:#fbeaea,stroke:#a54a4a;
    classDef own fill:#eaf3ea,stroke:#4a8a4a;
```

```mermaid
flowchart LR
    MCPR["MCPRoute"]:::own -->|plain HTTP| PROXY["in-cluster proxy<br/>(Caddy or openresty)"]:::own
    PROXY -->|"TLS + credential + rewrites"| UP["external MCP"]:::ext
    classDef own fill:#eaf3ea,stroke:#4a8a4a;
    classDef ext fill:#eee,stroke:#888,stroke-dasharray:4 3;
```

The proxy turns an unreliable external TLS backend into a **reliable in-cluster
plain-HTTP backend** — identical to brave/terraform from Envoy's view. The
ADR-0039 `EnvoyPatchPolicy` was removed.

> ⚠️ **Token-bind race (`MCP_TOKEN`):** env vars from `secretKeyRef` bind at pod
> start and never refresh. A proxy that beats ESO with `optional: true` captures
> an **empty** token forever (`Bearer `) → upstream rejects every request as
> "Invalid API key". Guard: `charts/mcp` renders `MCP_TOKEN` with `optional:
> false`, so a keyed proxy **waits** in `ContainerCreating` for ESO. A keyless
> MCP disables `externalSecret` and proxies anonymously.
>
> ⚠️ **The openresty/Caddy engine choices are INTERIM.** Drop the firecrawl
> openresty engine once AIEG's SSE parser skips non-response events (#2219); drop
> refero's `rewriteResponseContentType` once #2218 lands. Full diagnosis:
> [`../2026-06-10-mcp-external-server-proxy-debug.md`](../2026-06-10-mcp-external-server-proxy-debug.md).

→ Related: [05 Auth (carve-out)](05-auth-identity.md) · [06 Networking & TLS](06-networking-tls.md)
