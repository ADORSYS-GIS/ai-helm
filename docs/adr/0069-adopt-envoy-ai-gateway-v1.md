# ADR-0069: Adopt Envoy AI Gateway v1.0 and migrate AIEG manifests to `v1beta1`

**Status:** Accepted
**Date:** 2026-06-27
**Deciders:** @stephane-segning

## Context

[Envoy AI Gateway v1.0](https://aigateway.envoyproxy.io/release-notes/v1.0)
shipped — the project's first stable release. We run **AIEG v0.7.0**
(`ai-gateway-crds-helm` + `ai-gateway-helm`) on **Envoy Gateway v1.8.0**, pinned in
`charts/apps/values.yaml`. v1.0 is a **stability milestone, not a breaking
release**: it declares the `v1beta1` API stable (byte-identical to v0.7's
`v1beta1`), forces no apiVersion bump, and documents a drop-in upgrade. Three facts
shape the decision: (1) the stated **minimum Envoy Gateway floor moves to v1.8.1**
(a patch over our v1.8.0); (2) `v1alpha1` is now **served-but-deprecated** — the
CRD warns `"use aigateway.envoyproxy.io/v1beta1 instead"`, and every AIEG CR in our
templates was authored as `v1alpha1`; (3) v1.0 promotes the **MCP authorization
surface** to first-class `v1beta1` fields (per-backend tool include/exclude,
CEL per-tool authorization, per-backend header forwarding) that map directly onto
our `/mcp` carve-out (ADR-0038). The two open external-MCP bugs we work around —
AIEG [#2218](https://github.com/envoyproxy/ai-gateway/issues/2218) (refero
content-type) and [#2219](https://github.com/envoyproxy/ai-gateway/issues/2219)
(firecrawl SSE framing) — are **not** fixed in v1.0.

## Decision

Adopt AIEG v1.0 deliberately rather than as a blind tag bump:

- **Bump versions** in `charts/apps/values.yaml`: `aieg-crd` + `aieg`
  `v0.7.0 → v1.0.0`, `eg` (gateway-helm) `v1.8.0 → v1.8.1` (the new floor).
- **Migrate our AIEG manifests `v1alpha1 → v1beta1`** — `apiVersion` line only, the
  `v1beta1` schema is a superset so spec bodies are unchanged. Six kinds across five
  files: `MCPRoute`, `AIGatewayRoute`, `AIServiceBackend`, `BackendSecurityPolicy`,
  `GatewayConfig`/`GatewayConfigList`. This is safe **today** (it is already the
  v0.7 storage version) and removes the future forced break + deprecation warnings.
  The upstream **`gateway.envoyproxy.io`** CRDs (Backend, BackendTrafficPolicy,
  ClientTrafficPolicy, EnvoyProxy, SecurityPolicy, HTTPRouteFilter) are a **separate
  API group** and keep their own `v1alpha1` — untouched.
- **Wire the v1.0 MCP capabilities into `charts/mcp` as opt-in, default-off** so
  every existing MCPRoute renders byte-identically except the apiVersion line:
  `mcp.toolFilter` → `backendRefs[].toolSelector` (include/exclude, deny-wins),
  `mcp.forwardHeaders` → `backendRefs[].forwardHeaders`, and `mcp.authorization.rules`
  → `securityPolicy.authorization.rules[].cel`. As the one concrete activation,
  forward the gateway-stamped `x-oidc-user-id` to the self-hosted backends (brave,
  terraform) for per-user attribution.
- **Keep the external-MCP normalizing proxies** (Caddy/openresty, ADR-0040/0041)
  unchanged — #2218/#2219 remain mitigated there until upstream fixes land.

## Consequences

**Positive**
- On the stable v1.0 API; deprecation warnings cleared; no future forced `v1alpha1`
  removal break to chase.
- The MCP authz toolkit (tool filtering, CEL per-tool authz where `tools/list` is
  filtered by the same rules, claim/header projection) is available repo-wide as a
  reusable, documented chart capability.

**Negative**
- Per-tool CEL authorization is plumbed but **not policy-activated** — defining live
  rules is a deliberate follow-up (a values edit in `charts/mcps/values.yaml`).
- The `eg` floor bump (v1.8.1) couples us to a specific upstream patch; future AIEG
  releases may move the floor again.

**Neutral / follow-ups**
- Continuous delivery (ADR-0055): merge = deploy. `aieg-crd` reconciles first; no
  CRD-before-CR ordering hazard since `v1beta1` already existed at v0.7.
- Drop the Caddy/openresty proxies once #2218/#2219 are fixed upstream.
- Candidate next step: gate destructive MCP tools (e.g. terraform apply/delete) via
  `authorization.rules` keyed on Keycloak realm roles.

## Alternatives considered

- **Pure version bump, leave templates on `v1alpha1`** — rejected: still served, but
  emits deprecation warnings and merely defers the migration to a later forced break;
  the migration is free now (v1beta1 is the v0.7 storage version).
- **Fold in live per-tool authz policy now** — deferred: defining which tools to gate
  and under which CEL/role conditions is a security-policy call, not a mechanical
  upgrade; ship the capability, decide the policy separately.
- **Drop the external-MCP proxies hoping v1.0 fixed them** — rejected: #2218 is still
  open and #2219 shows no v1.0 fix; removing the proxies would re-break
  context7/firecrawl/refero.

## Related

- Docs: `docs/architecture.md`, `docs/arc42.md` §9
- Charts/files: `charts/apps/values.yaml`, `charts/mcp/{values.yaml,templates/mcproute.yaml}`,
  `charts/mcps/values.yaml`, `charts/ai-model/templates/aigatewayroute.yaml`,
  `charts/ai-models-backends/templates/{aiservicebackend,backendsecuritypolicy}.yaml`,
  `charts/core-gateway/templates/gateway-config.yaml`
- Builds on [0021](./0021-burst-budget-billing-and-dual-plane-authconfigs.md),
  [0038](./0038-mcp-oauth-protected-resource-metadata.md),
  [0034](./0034-restore-streaming-timeouts-and-extproc-headroom.md),
  [0055](./0055-oci-charts-and-image-updater-writeback-to-values-repo.md); the
  external-MCP workarounds it retains live in
  [0040](./0040-external-mcps-via-caddy-normalizing-proxy.md),
  [0041](./0041-firecrawl-protocol-version-rewrite-nginx-engine.md)
