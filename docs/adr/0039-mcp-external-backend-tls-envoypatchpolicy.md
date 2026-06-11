# ADR-0039: Repair external MCP backend upstream TLS via EnvoyPatchPolicy

**Status:** Superseded by [ADR-0040](0040-external-mcps-via-caddy-normalizing-proxy.md)
**Date:** 2026-06-10
**Deciders:** @stephane-segning

> **Superseded (2026-06-11) by [ADR-0040](0040-external-mcps-via-caddy-normalizing-proxy.md).**
> The `EnvoyPatchPolicy` below worked for RSA-cert externals (firecrawl, refero)
> but was brittle (AIEG cluster-name coupling), couldn't reach context7's ECDSA
> cert (BoringSSL), and didn't fix refero's empty-tools (content-type
> mislabeling, #2218). ADR-0040 replaces it with per-MCP in-cluster **Caddy
> normalizing proxies** that do the upstream TLS (Go TLS handles ECDSA) + fix the
> content-type — and **removes this EnvoyPatchPolicy** (`charts/core-gateway`
> `mcpBackendTls`). The body below is retained as the record of the interim fix.
> (The earlier "context7 self-hosted/dropped" notes are also obsolete — context7
> is back via the Caddy proxy.)

## Context

After [ADR-0038](0038-mcp-oauth-protected-resource-metadata.md) made the MCPs
reachable, the three **external** hosted MCPs (context7, firecrawl, refero)
failed at the gateway→upstream hop while self-hosted ones (brave, terraform)
worked. Root cause, traced through the live Envoy config (full debug in
[`docs/2026-06-10-mcp-external-server-proxy-debug.md`](../2026-06-10-mcp-external-server-proxy-debug.md)):

The Envoy AI Gateway's extension server generates the upstream cluster for each
external MCP backend and stamps a **placeholder `dummy.transport_socket`** on it
— an `UpstreamTlsContext` with an **empty `common_tls_context`**: no SNI, no CA.
EG's `BackendTLSPolicy` (and inline `Backend.spec.tls.sni`, tested) **never reach
that AIEG-generated cluster** — EG's Backend-TLS translation runs before the
extension hook that creates it. So the gateway opens upstream TLS to CDN-fronted
MCP servers with **no SNI**; the CDN can't select a cert and the handshake fails
(`ssl.connection_error`, `0` handshakes) → `failed to create MCP session to any
backend`. This is the EG #9137 / AIEG MCP-backend-TLS class; **no released AIEG
or EG version fixes it** (confirmed v0.6.0 **and** v0.7.0).

EG's `EnvoyPatchPolicy` is enabled on this gateway (`enableEnvoyPatchPolicy:
true`) and runs **last** in the xDS pipeline — after AIEG's extension server — so
it *can* overwrite that cluster's transport socket.

## Decision

Render an **`EnvoyPatchPolicy`** (in `charts/core-gateway`, namespace
`converse-gateway` = the Gateway's namespace, as EG requires) that, for each
external HTTPS MCP backend, **replaces the `dummy.transport_socket`** with a real
`envoy.transport_sockets.tls` `UpstreamTlsContext` carrying the upstream **SNI**
+ **system-CA** validation (`/etc/ssl/certs/ca-certificates.crt`). Driven by a
`mcpBackendTls.backends: [{name, sni}]` list; the patched cluster name is the
AIEG-derived `httproute/<mcpNamespace>/ai-eg-mcp-br-<name>-<name>/rule/0`.

**Scope = RSA-cert upstreams only.** firecrawl and refero serve RSA certs →
Envoy's BoringSSL handshakes fine once SNI is present (verified live: refero
returns `200`s, firecrawl handshakes succeed). **context7 serves an ECDSA cert**
(`ecdsa_secp256r1_sha256`) that Envoy's **BoringSSL rejects** at the handshake
(`BAD_ECC_CERT` — AIEG disabled context7 in their own CI for exactly this), SNI
or not. So context7 is **not** patched here — it is **self-hosted** in-cluster as
a plain-HTTP backend instead (charts/mcps), sidestepping the Envoy→external-TLS
hop entirely. (See ADR-0038's related work; the context7 self-host is tracked
separately.)

## Consequences

**Positive**

- firecrawl + refero work through the gateway (proven on the live cluster before
  shipping). No upstream AIEG fix to wait on.
- Self-contained in `charts/core-gateway` (the Gateway owner); GitOps-managed and
  prune-safe, unlike a hand-applied patch.

**Negative**

- **Brittle coupling to AIEG's internal cluster naming.** The patch targets
  `httproute/<ns>/ai-eg-mcp-br-<name>-<name>/rule/0`. If AIEG renames its
  generated clusters (a future version, or the planned `MCPBackend` CRD), the
  `op: replace` silently no-ops and external MCP TLS breaks again. **Re-verify the
  cluster name after any AIEG bump** (`/config_dump`, grep `br-<name>`).
- **DRY cost:** the external+TLS MCP list lives in both `charts/mcps`
  (the MCPs themselves) and `charts/core-gateway` `mcpBackendTls.backends`
  (the patch). Adding/removing an external HTTPS MCP means editing both.
- Hostname (SAN) pinning is omitted — validation is chain-to-system-CA + SNI,
  not a SAN-match against the FQDN (the proven-working config; EG's normal
  BackendTLSPolicy would add the SAN match). Residual risk is low (needs a
  CA-issued cert for another domain + DNS compromise); hardening is a follow-up.
- BoringSSL ECDSA upstreams (context7 today) can't use this path at all.

**Neutral / follow-ups**

- File the AIEG upstream issue (dummy-socket / BackendTLSPolicy-not-propagated to
  MCP backend clusters) so the workaround can eventually be retired.
- If AIEG ships the `MCPBackend` CRD with first-class TLS, drop this patch.

## Alternatives considered

- **`Backend.spec.tls.sni` (inline) / `BackendTLSPolicy`** — rejected: **tested
  live, no effect.** The AIEG-generated cluster keeps the dummy socket; EG's
  Backend-TLS translation never reaches it.
- **Self-host all external MCPs** (the context7 route) — rejected as the general
  answer: refero has no self-host option, and firecrawl/refero already work via
  the patch. Self-hosting is reserved for the BoringSSL-incompatible case
  (context7).
- **Wait for an AIEG/EG fix** — rejected: none exists through v0.7.0, and the
  feature is wanted now.

## Related

- [ADR-0038](0038-mcp-oauth-protected-resource-metadata.md) (MCP OAuth edge),
  [ADR-0027](0027-mcps-orchestrator-split-and-coder-removal.md) (the mcps charts).
- [`docs/2026-06-10-mcp-external-server-proxy-debug.md`](../2026-06-10-mcp-external-server-proxy-debug.md) — full diagnosis + reproduction.
- EG [#9137](https://github.com/envoyproxy/gateway/issues/9137) (Host-vs-FQDN SNI), AIEG [#1880](https://github.com/envoyproxy/ai-gateway/pull/1880) (context7 TLS disabled in CI).
