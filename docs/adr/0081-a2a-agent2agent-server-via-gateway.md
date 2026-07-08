# ADR-0081: Expose our agents as A2A (Agent2Agent) servers through the gateway

**Status:** Proposed
**Date:** 2026-07-09
**Deciders:** @stephane-segning

## Context

[A2A (Agent2Agent)](https://agent2agent.info/) is an open protocol — announced
by Google at Cloud Next 2025, donated to the Linux Foundation in June 2025, and
shipped as **v1.0 in early 2026** — for agent-to-agent interoperability. Where
[MCP](https://modelcontextprotocol.io) connects an agent to *tools*, A2A
connects an agent to *other agents* as peers. On the wire it is **JSON-RPC 2.0
over HTTP + Server-Sent Events** (gRPC binding optional): plain HTTP, no
special message framing. Discovery is a public **Agent Card** served at the
well-known path `/.well-known/agent-card.json` describing the agent's skills,
its JSON-RPC `url`, and its `securitySchemes` (API key / HTTP auth /
**OAuth2-OIDC** / mTLS), optionally JWS-signed. Its methods are `message/send`,
`message/stream` (SSE), `tasks/get`, `tasks/resubscribe`, and the push-config
family.

This platform is an AI gateway that already federates models and, since
[ADR-0038](0038-mcp-oauth-protected-resource-metadata.md)/[ADR-0040](0040-external-mcps-via-caddy-normalizing-proxy.md)/[ADR-0069](0069-adopt-envoy-ai-gateway-v1.md),
MCP servers behind `core-gateway`. A2A is MCP's structural sibling, and the
`/mcp/*` integration is ~90% reusable for it. The forcing question: **do we want
external agents (partner systems, other A2A-speaking platforms) to be able to
discover and call *our* agents** — LibreChat, the self-hosted GPU model, or a
purpose-built agent — as first-class A2A peers? This ADR records the design for
the **server role** so it can be reviewed before any chart work. It is a
**proposal**: no charts, values, or gateway config change on merge.

## Decision

Adopt a **server-role A2A integration that mirrors the MCP gateway pattern**,
with one deliberate structural change: because Envoy AI Gateway has a
first-class `MCPRoute` CRD but **no A2A route type**, A2A rides plain **Envoy
Gateway `HTTPRoute` + `SecurityPolicy`**, not `MCPRoute`.

Shape (to be built under a follow-up "Accepted" revision of this ADR, or a
successor):

- **New leaf chart `charts/a2a`** (one A2A agent per Application), mirroring
  `charts/mcp` ([ADR-0027](0027-mcps-orchestrator-split-and-coder-removal.md)).
  It renders, per agent:
  - A **`Backend` + `HTTPRoute`** attaching the JSON-RPC endpoint at
    `/a2a/<agent>` to the `core-gateway` `api-https` listener
    (`api.ai.camer.digital`, [charts/core-gateway/templates/gateway.yaml:27](../../charts/core-gateway/templates/gateway.yaml)).
  - A route-level **`SecurityPolicy` with native `jwt_authn`** against the
    Keycloak issuer (`https://auth.verif.fyi/realms/camer-digital`) — the same
    displacement of the gateway-level Authorino that ADR-0038 relies on (EG
    policy precedence is whole-policy, not merge). The ADR-0011 `x-oidc-*` set
    is re-stamped from JWT claims (reuse the `claimToHeaders` list from
    [charts/mcp/values.yaml:166](../../charts/mcp/values.yaml)).
  - The **Agent Card served unauthenticated** at
    `/.well-known/agent-card.json` (and, if we host >1 agent under one host, a
    per-agent card path). This reuses the exact **DirectResponse +
    allow-all `SecurityPolicy`** carve-out already written for MCP PRM in
    [charts/mcp/templates/oauth-discovery-alias.yaml](../../charts/mcp/templates/oauth-discovery-alias.yaml)
    — the allow-all policy's only job is to exempt the card from Authorino so
    discovery answers publicly. The card's `securitySchemes` declares the
    Keycloak OIDC scheme, telling a calling agent where to get a token — the
    same role RFC 9728 PRM plays for MCP.
- **New orchestrator `charts/a2as`** emitting one child Application per enabled
  agent via an **ApplicationSet List generator**, a direct copy of
  [charts/mcps/templates/applicationset.yaml](../../charts/mcps/templates/applicationset.yaml)
  (shared `oauth`/JWT config deep-merged per agent; children float from OCI on a
  semver range per [ADR-0055](0055-oci-charts-and-image-updater-writeback-to-values-repo.md);
  `controlPlane: true` entry in `charts/apps/values.yaml`; children →
  `home-remote`).
- **The split contract holds** ([ADR-0056](0056-workload-values-in-ai-helm-values.md)):
  `ai-helm` holds the chart templates; the private **`ai-helm-values`** repo
  holds each agent's `valuesObject`, its **Agent Card contents**, and any
  credential ExternalSecret refs — cut over values-repo-first.
- **Streaming:** the `message/stream` / `tasks/resubscribe` SSE streams inherit
  the streaming-timeout headroom from
  [ADR-0034](0034-restore-streaming-timeouts-and-extproc-headroom.md); the A2A
  route must be confirmed to be covered (it is a different route from the model
  routes).
- **Start flat, promote later.** For the first 1–2 agents, ship a single flat
  `charts/apps` umbrella entry + the card carve-out; introduce the `a2as`
  orchestrator only at >2 agents — exactly how MCP evolved (ADR-0027).

**Explicitly out of scope of this ADR:** the **client role** (our stack calling
*out* to remote A2A agents). opencode/LibreChat speak MCP, not A2A, so consuming
remote A2A peers needs an A2A→MCP bridge and a separate decision — deferred.

## Consequences

**Positive**
- Reuses proven machinery: the discovery carve-out, dual-plane AuthConfig
  boundary, `x-oidc-*` re-stamping, and the OCI leaf+orchestrator pattern all
  transfer with minimal new code.
- Plain HTTP+SSE means A2A **avoids** the MCP external-backend pain entirely —
  no Caddy/openresty normalizing proxies (ADR-0040/0041), no BoringSSL/ECDSA or
  SSE-framing workarounds — for agents we host in-cluster.
- One consistent identity boundary: a Keycloak JWT = "you may talk to our
  agents," identical to the rest of the gateway.

**Negative**
- **No `MCPRoute` equivalent** → we lose AIEG's built-in tool-listing and
  per-tool CEL authz. A2A skill-level authorization is our own concern
  (route-level JWT, plus any skill-level CEL we choose to build).
- **Cost attribution doesn't map.** A2A tasks aren't token-priced like model
  calls, so the per-account µ$-budget `BackendTrafficPolicy` model
  ([ADR-0021](0021-burst-budget-billing-and-dual-plane-authconfigs.md)/[ADR-0035](0035-per-person-monthly-budget-and-free-50.md))
  has no natural per-task meter. We can burst-limit on `x-account-id`, but a
  spend model for A2A needs its own decision.
- Net-new surface: a new leaf chart, orchestrator, ADR, and an externally
  reachable JSON-RPC endpoint to keep patched and monitored.

**Neutral / follow-ups**
- **Signed Agent Cards** (JWS) are optional in v1.0; decide whether external
  callers require signature verification of our card, and if so where the
  signing key lives (ssegning-aws).
- **Which agent first?** LibreChat, the self-hosted GPU model
  ([ADR-0022](0022-self-hosted-gpu-model-federated-into-gateway.md)), or a
  purpose-built agent — to be chosen when this moves to "Accepted."
- **Audience validation** — like ADR-0038, start with `audiences: []` (issuer
  check only) unless a Keycloak audience mapper is wired.
- **Multi-agent hosting** — if we expose several agents under one host, settle
  the card-path scheme (one `/.well-known/agent-card.json` per host vs.
  per-agent card URLs referenced from an index).

## Alternatives considered

- **Client/consumer role first** — rejected for now: nothing in our stack
  speaks A2A as a client (opencode is MCP-native), so it is blocked on building
  an A2A→MCP bridge. Bigger and more speculative than the server role, which the
  gateway is already shaped for.
- **A2A via a first-class AIEG route** — not available: Envoy AI Gateway has no
  A2A CRD as of v1.0 (ADR-0069). Plain EG `HTTPRoute` + `SecurityPolicy` is the
  supported path and is sufficient (A2A is ordinary HTTP+SSE).
- **Bridge A2A to the existing `/mcp/*` surface** — rejected: MCP and A2A are
  different protocols with different discovery and task-lifecycle semantics;
  forcing A2A through `MCPRoute` would misuse the tool-oriented framing and gain
  nothing.
- **Skip the gateway, expose an agent directly** — rejected: violates the
  home-remote destination invariant + the single-identity boundary
  ([ADR-0017](0017-home-remote-destination-invariant.md)/[ADR-0021](0021-burst-budget-billing-and-dual-plane-authconfigs.md));
  every externally reachable surface goes through `core-gateway`.

## Related

- Source of truth: A2A protocol — https://agent2agent.info/ ;
  spec https://a2a-protocol.org/latest/specification/ (v1.0)
- Builds on: [ADR-0038](0038-mcp-oauth-protected-resource-metadata.md) (the
  unauthenticated-discovery carve-out + Authorino displacement),
  [ADR-0027](0027-mcps-orchestrator-split-and-coder-removal.md) (leaf +
  orchestrator split), [ADR-0069](0069-adopt-envoy-ai-gateway-v1.md) (EG/AIEG
  v1.0 baseline), [ADR-0055](0055-oci-charts-and-image-updater-writeback-to-values-repo.md)/[ADR-0056](0056-workload-values-in-ai-helm-values.md)
  (OCI float + values-repo split)
- Relates to: [ADR-0011](0011-oidc-downstream-headers.md) (`x-oidc-*`),
  [ADR-0021](0021-burst-budget-billing-and-dual-plane-authconfigs.md) (auth/
  rate-limit boundary), [ADR-0034](0034-restore-streaming-timeouts-and-extproc-headroom.md)
  (SSE timeouts), [ADR-0017](0017-home-remote-destination-invariant.md)
  (destinations)
- Charts/files (proposed, not yet created): `charts/a2a`, `charts/a2as`,
  entry in `charts/apps/values.yaml`; agent-card + values in `ai-helm-values`
</content>
</invoke>
