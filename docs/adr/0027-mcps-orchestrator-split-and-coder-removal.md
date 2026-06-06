# ADR-0027: Split the MCP servers into per-MCP Applications; remove Coder

**Status:** Accepted
**Date:** 2026-06-06
**Deciders:** @stephane-segning

## Context

Two unrelated changes to the `charts/apps` app set, recorded together because
they landed in one commit.

### 1. MCP servers were one monolithic Application

`charts/mcps` deployed **every** MCP server (brave, terraform, firecrawl,
context7) as raw resources inside a **single** flat Application (`mcps`,
namespace `converse-mcp`). One Application for N heterogeneous servers means:

- no per-MCP sync / rollback / health — a bad change to one MCP shows up as the
  whole `mcps` app degrading;
- the API-key Secrets each MCP needs (`brave-token`, `firecrawl-token`,
  `context7-token`) were **not** owned by the chart — they came from the
  wholesale `secrets` Application that was **removed 2026-06-04**, so they were
  unprovisioned casualties (same failure class as coder/lightbridge);
- adding a server (e.g. Refero) meant editing the monolith.

### 2. Coder is no longer in use

The Coder workload (ADR-0019: a `coder` App-of-Apps orchestrator → `coder-db` +
`coder-app`) is not needed for now. Its ingress cert was also stuck (wildcard
SAN can't issue via HTTP-01; Traefik redirect breaks HTTP-01 — see the
Route53 DNS-01 work) and its Keycloak/admin secrets were unprovisioned.

## Decision

### MCPs → orchestrator + generic leaf (the ai-models pattern, ADR-0012)

- `charts/mcps` becomes an **orchestrator**: it emits ONE `ApplicationSet` whose
  List generator has one element per enabled MCP, each pointing at a new generic
  leaf chart `charts/mcp` with per-MCP inline values. `controlPlane: true` in
  `charts/apps` (it emits a control object → lands in-cluster/argocd; the
  children deploy workloads to `home-remote`/`converse-mcp`, ADR-0017).
- `charts/mcp` (generic leaf) renders one MCP in either mode:
  - **external** — `Backend` → upstream FQDN + `BackendTLSPolicy` (System CA);
  - **selfHosted** — `Deployment` + `Service` + `Backend` → the in-cluster svc.
  Plus an `MCPRoute` (optional `apiKey` securityPolicy) and an **optional
  in-chart `ExternalSecret`** scoped to that MCP. So each MCP is now its own
  Application (`mcps-brave`, `mcps-terraform`, `mcps-firecrawl`,
  `mcps-context7`, `mcps-refero`) owning its own credential.
- **Added Refero** (`api.refero.design`, external, Bearer apiKey) — a
  design-reference MCP (requires a Refero Pro subscription).
- **API-key contract:** the AIEG `MCPRoute` `apiKey.secretRef` requires the
  Secret key to be **`apiKey`** (not `token`), and an `Authorization` header
  auto-prefixes `Bearer ` — so the Secret holds the raw token. brave's container
  env reads the same `apiKey` key. The maintainer populates these properties
  under ssegning-aws `ai/camer/digital/prod/env`: `brave_api_key`,
  `firecrawl_api_key`, `context7_api_key`, `refero_api_key` (terraform needs
  none).

### Remove Coder (supersedes ADR-0019)

- Deleted `charts/coder`, `charts/coder-db`, `environments/{base,prod}/deps/coder`,
  and the `coder` entry in `charts/apps`. ArgoCD prunes the `coder` orchestrator
  and its children (`coder-app`, `coder-db`).
- Removed the LibreChat `coder_mcp` server + its `librechat-mcp-coder-credentials`
  ExternalSecret + `CODERS_MCP_*` env (charts/librechat-app), which pointed at
  the now-gone `coder.ai.camer.digital`.
- **Left in place** (harmless, eases re-introduction): the Keycloak `coder`
  client in `charts/keycloak-baseline` and the illustrative `coder.…` host in
  `environments/prod/cluster.yaml` comments.

## Consequences

- Per-MCP Applications: independent sync/rollback/health; adding an MCP is a new
  `mcps.<name>` block; each owns its credential in-chart (no external secrets app).
- The old flat `mcps` app's resources in `converse-mcp` are re-adopted by the
  per-MCP children (same names/namespace) — verify no orphan prune churn on first
  sync.
- ADR-0019 is superseded; re-introducing Coder needs a new ADR (the charts live
  in git history).

Supersedes [ADR-0019](./0019-coder-app-of-apps-orchestrator.md). Builds on
[ADR-0012](./0012-split-ai-models-applicationset.md) (orchestrator pattern),
[ADR-0017](./0017-home-remote-destination-invariant.md),
[ADR-0018](./0018-umbrella-apps-and-env-overlays.md).
