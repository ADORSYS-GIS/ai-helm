# ADR-0081: A2A (Agent2Agent) agent platform — dynamic registry, Restate runtime, EAIG-fronted

**Status:** Proposed
**Date:** 2026-07-09
**Deciders:** @stephane-segning

> **Rev 2** — rewritten in place while still Proposed (the immutability rule binds
> Accepted ADRs only). The first draft proposed a *static, platform-owned* A2A
> server: a `charts/a2a` leaf + `charts/a2as` orchestrator mirroring the MCP
> split, one Helm-defined agent per Application. Design review moved every load-
> bearing assumption: agents are **tenant-authored and dynamic** (a database
> registry, not Git), the platform needs the **client role too** (server-only
> A2A is half a protocol), and execution belongs on a **durable-execution
> engine**, not per-agent charts or k8s Jobs. The static design survives only in
> *Alternatives considered*.

## Context

[A2A (Agent2Agent)](https://agent2agent.info/) — Google 2025, Linux Foundation,
**v1.0 in early 2026** ([spec](https://a2a-protocol.org/latest/specification/)) —
is the peer-delegation protocol: JSON-RPC 2.0 over HTTP + SSE, a public **Agent
Card** at `/.well-known/agent-card.json`, OAuth2-OIDC auth, and a defined task
lifecycle. It is MCP's structural sibling with an inverted contract: **MCP = the
remote is a toolbox and the *caller's* loop owns the reasoning; A2A = the remote
owns its own loop and the caller delegates a task.** The semantics A2A adds over
wrapping an agent as an MCP tool are, almost uniformly, *state that must survive
something dying*: a durable `taskId` + state machine (`submitted → working →
input-required/auth-required → completed/failed/canceled/rejected`),
disconnect-and-reattach (`tasks/get`/`tasks/resubscribe`), webhook push
notifications, confirmed cancel, mid-task `input-required` back to the caller,
`contextId` multi-turn memory, typed incremental artifacts
(`TextPart`/`FilePart`/`DataPart`), status-vs-content event streams, and
Agent-Card discovery/selection at runtime. (MCP has partial analogs —
elicitation, transport-level SSE replay, best-effort cancel — none durable.)

The platform intent is **not** a few platform-owned agents. It is a
**multi-tenant agent-hosting service**: tenants author/register agents at
runtime and get a custom URL (`…/a2a/<agent-id>`), the way they cannot with
models. That rules out the Git-defined per-agent chart shape. Inbound auth stays
with the Envoy AI Gateway (Keycloak JWT → `x-oidc-*`/`x-account-id`,
[ADR-0011](0011-oidc-downstream-headers.md)/[ADR-0021](0021-burst-budget-billing-and-dual-plane-authconfigs.md)) —
the backend never verifies tokens inbound. A Rust ecosystem now exists to build
on: A2A protocol crates ([`a2a-rs`](https://github.com/EmilLindfors/a2a-rs),
`ra2a`, `a2a-rust` — community, not Google-official), the
[`rig-core`](https://crates.io/crates/rig-core) agent framework (0xPlaygrounds,
~v0.36, 20+ providers, custom base URL → works against EAIG's OpenAI-compatible
surface), and [Restate](https://restate.dev)'s Rust SDK (`restate-sdk`,
macro-annotated handlers). Durable execution is where the industry converged
for long-horizon agents in 2025–26, and Restate's primitives map almost 1:1
onto A2A's: the journal ↔ resumable turns, **awakeables** ("park until an
external signal") ↔ `input-required`/`auth-required`/push-completion, virtual
objects ↔ `contextId` state.

## Decision

Build a **Rust A2A agent platform** behind `core-gateway`, in five layers:

- **Protocol plane** — one long-running axum `Deployment` using an A2A protocol
  crate (spike `a2a-rs` vs `ra2a` vs `a2a-rust` first: v1.0 completeness,
  license, storage abstraction, maintenance). It serves per-agent Agent Cards,
  dispatches JSON-RPC (`message/send`, `message/stream`, `tasks/*`, push-config),
  and holds client SSE connections. Exposed via **one wildcard `HTTPRoute`**
  `/a2a/*` on the `api-https` listener
  ([charts/core-gateway/templates/gateway.yaml:27](../../charts/core-gateway/templates/gateway.yaml))
  — there is no AIEG A2A route type (v1.0, [ADR-0069](0069-adopt-envoy-ai-gateway-v1.md)),
  and with a dynamic registry none is wanted. Inbound identity = the
  gateway-stamped `x-oidc-*` / `x-account-id`; the card discovery paths
  (`/a2a/{id}/.well-known/agent-card.json`, dynamic ids) are exempted from
  Authorino via a **pattern-based allow-all `SecurityPolicy`** — the
  [ADR-0038](0038-mcp-oauth-protected-resource-metadata.md) carve-out trick,
  regex form (spike early; fiddliest gateway bit).
- **Registry / control plane** — agents are **rows in Postgres (CNPG)**, not
  Git: CRUD scoped by `x-account-id` ownership, per-agent card generated from
  the row, custom URL minted as `/a2a/<agent-id>`. Cards declare the Keycloak
  OIDC `securityScheme`.
- **Execution plane (managed runtime)** — the agent loop is
  **`rig-core` inside `restate-sdk` handlers** on a self-hosted **Restate**
  server. Every model call goes through the EAIG **internal plane**
  (ADR-0021 static apiKey / per-user `X-LibreChat-User`-style attribution), so
  hosted agents inherit governance + cost attribution. Restate buys the task
  state machine, retries, crash-resume, `input-required` parking (awakeables),
  and `contextId` state (virtual objects) — the hardest third of a hand-rolled
  build. Token-level live streaming is relayed handler → redis pub/sub
  (redis-ha, existing) → the protocol plane's SSE; Restate does not pipe
  partial handler output natively.
- **Client plane + MCP bridge** — the platform can *call* remote A2A agents
  (outbound token acquisition — Keycloak client-credentials / token-exchange per
  the remote card's `securitySchemes` — is our own code; EAIG covers inbound
  only), and an **A2A→MCP bridge** exposes registered agents as MCP tools so
  the MCP-native fleet (opencode, LibreChat) can consume them. Internal
  composition may equally keep using plain agent-behind-MCP-tool wrapping; A2A
  is justified by *ecosystem interop* (external A2A-native callers) + the
  durable-task semantics above.
- **Observability** — handlers + protocol plane log **structured JSON to
  stdout**; Alloy's node-level tail (`/var/log/pods`) collects it with zero
  wiring and **no pod egress needed** (works under the Cilium deny baseline).
  `agent-id`/`x-account-id` become pod labels promoted to Loki stream labels by
  one `discovery.relabel` rule in the Alloy config (**in `ai-helm-values`**,
  `environments/prod/values/alloy.yaml`; zero Go-template braces — the
  [ADR-0046] `tpl` trap); `taskId` stays in the log **body** (per-run label
  would explode stream cardinality — the ADR-0064/0067 `oidc_jti` lesson).
  Restate's journal additionally gives per-task step introspection logs can't.

**Explicitly not chosen:** per-agent k8s **Jobs** for execution, **Coder**
Tasks/Agents as the runtime, and the Rev-1 static chart-per-agent shape — see
Alternatives.

## Consequences

**Positive**
- The full A2A semantic set (durable tasks, reattach, push, `input-required`,
  typed artifact streams, discovery) is *bought* — Restate + the protocol crate
  cover what a hand-rolled build would spend most of its effort on.
- Small operational footprint for a whole product: one `Deployment` + Restate +
  existing redis/CNPG + one `HTTPRoute` + one Authorino carve-out.
- Auth, governance, and per-account model-cost attribution are inherited from
  EAIG on both edges (inbound callers; hosted agents' model calls).
- Tenants get self-service agents with custom URLs — a capability class the
  model catalog can't offer.

**Negative**
- **Restate is a new stateful platform component** (single binary, wants a
  PVC) — to operate, upgrade, and back up. Its home (home-os as shared infra à
  la redis/CNPG, vs an ai-helm StatefulSet as A2A-private) is an unresolved
  follow-up.
- Community-crate risk: the A2A crates are not Google-official; budget for
  forking/upstreaming. The Phase-0 spike is mandatory.
- **No cost meter maps to A2A tasks** — the µ$ budget model
  (ADR-0021/[ADR-0035](0035-per-person-monthly-budget-and-free-50.md)) prices
  tokens, not tasks. Hosted agents' *model* calls are attributed via the
  internal plane, but task-level pricing/limits need their own decision.
  Burst-limit on `x-account-id` is available meanwhile.
- Estimated **~9–13+ engineering-weeks** (one Rust dev) for server + client +
  bridge; Restate trims code but adds ops.

**Neutral / follow-ups**
- Phase-0 crate spike (protocol crate choice); early spike of the dynamic-card
  Authorino regex carve-out.
- Restate placement ADR (home-os vs ai-helm) before build.
- Signed Agent Cards (JWS): decide if required; key in ssegning-aws.
- MCP-bridge shape (one MCP server exposing all owned agents as tools vs
  per-agent) — decide with real consumers.
- Fast-failing pods: stdout alone can race Alloy's discovery; audit-relevant
  events also go through redis to the control plane, and Jobs-style
  short-lived pods are avoided by design (long-running handlers).

## Alternatives considered

- **Static per-agent Helm charts (`charts/a2a` + `charts/a2as`, this ADR's
  Rev 1)** — rejected: agents are tenant-authored at runtime; a Git-reconciled
  chart per agent can't mint self-service custom URLs, and the ApplicationSet
  machinery adds nothing over a DB row + wildcard route.
- **k8s Jobs as the agent runtime** — rejected: Jobs fit long *non-interactive*
  runs, but A2A's `input-required` means pause/resume over hours (a blocked pod
  is the batch-primitive-doing-interactive-work anti-pattern), Job retry
  semantics collide with A2A's own failure model, and very short-lived pods
  race Alloy's log discovery. Everything a Job would have provided (isolation
  deadline, restart) Restate provides better, minus a sandbox boundary we can
  add later if tenant code (vs tenant *config*) ever runs.
- **Coder Tasks / Coder Agents as the runtime** — rejected: Tasks is removed
  from new releases at v2.37 (2026-09-01) with Coder Agents as successor —
  stability timing unclear; both are coding-agent-specific (workspace + repo
  framing); and Coder was deliberately removed from this platform
  ([ADR-0027](0027-mcps-orchestrator-split-and-coder-removal.md)).
- **MCP-tool-wrapping only, no A2A** — partially retained: for *internal*
  composition, agent-behind-an-MCP-tool reaches the same goal and stays the
  simpler choice. A2A is adopted for what wrapping can't express — durable
  tasks, reattach, push, `input-required`, discovery — and for external
  A2A-native callers.
- **Delegation-only model (tenant hosts the brain, we front card+auth+lifecycle)**
  — not chosen as the primary shape (the point is *hosted* agents), but nothing
  in the registry precludes adding a `delegated` agent kind later: same card,
  same lifecycle, upstream endpoint instead of a Restate handler.
- **Hand-rolled durable state machine (Postgres + redis, no Restate)** —
  rejected: rebuilding resume/retry/park correctness is the highest-risk third
  of the build; a durable-execution engine is the industry-converged answer.
  Temporal/DBOS considered; Restate wins on Rust-SDK ergonomics (macros) and
  single-binary self-hosting.

## Related

- Source of truth: https://agent2agent.info/ ; spec
  https://a2a-protocol.org/latest/specification/ (v1.0);
  https://restate.dev ; https://crates.io/crates/rig-core ;
  https://github.com/EmilLindfors/a2a-rs
- Builds on: [ADR-0021](0021-burst-budget-billing-and-dual-plane-authconfigs.md)
  (dual-plane auth: inbound JWT + internal-plane model calls),
  [ADR-0038](0038-mcp-oauth-protected-resource-metadata.md) (Authorino
  displacement / unauthenticated-discovery carve-out),
  [ADR-0069](0069-adopt-envoy-ai-gateway-v1.md) (EG/AIEG v1.0 baseline),
  [ADR-0011](0011-oidc-downstream-headers.md) (`x-oidc-*`)
- Relates to: [ADR-0034](0034-restore-streaming-timeouts-and-extproc-headroom.md)
  (SSE timeouts; push notifications reduce dependence on them),
  [ADR-0017](0017-home-remote-destination-invariant.md) (destinations),
  ADR-0064/0067 (label-cardinality discipline), ADR-0046 (Alloy `tpl` trap),
  [ADR-0056](0056-workload-values-in-ai-helm-values.md) (where the Alloy relabel
  + service values live)
- Charts/files (proposed, not yet created): the A2A service chart (Deployment +
  HTTPRoute + card carve-out), Restate placement TBD, Alloy relabel rule in
  `ai-helm-values`
</content>
</invoke>
