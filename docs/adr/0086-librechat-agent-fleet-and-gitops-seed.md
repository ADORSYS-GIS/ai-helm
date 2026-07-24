# ADR-0086: LibreChat agent fleet (subagents) + GitOps seed via /api/agents

**Status:** Proposed
**Date:** 2026-07-24
**Deciders:** @stephane-segning

## Context

LibreChat's **Agents** are first-class, tool-using assistants (a model +
instructions + a selected tool/MCP set), and since they gained the
**`subagents`** capability an agent can delegate to *other agents as tools*
(isolated-context children) — the same "primary delegates to a fleet" shape we
already run for opencode (ADR-0074). We want a curated fleet available to every
Converse (LibreChat) user, grounded in the tooling we actually expose.

Two hard facts constrain *how* we ship them (both verified against the deployed
image, `global.librechat.version = v0.8.7`):

1. **Agents are DB objects, not `librechat.yaml` config.** The chart's `agents`
   block is only capability/limit config (`recursionLimit`, `capabilities`,
   citations) and on/off toggles — there is **no schema to declare a named
   agent** (instructions/model/tools) in YAML. Agents are created via the Agent
   Builder UI or the REST API and stored in Mongo.
2. **Every agent doc requires an `author` — a real `User` ObjectId.** LibreChat
   has no service-account concept.

So a reproducible/GitOps fleet needs an out-of-band **seed mechanism**, not a
values edit. The available tool surface for LibreChat agents (after ADR-0086's
MCP work, see below) is: the GitHub suite, `lightbridge_self_service`, `coder`,
`terraform`, `context7`, `refero`, plus the built-in capabilities
(`execute_code`, `file_search`, `web_search`, `artifacts`, `ocr`).

## Decision

Adopt a **curated agent fleet** — specialist *leaf* subagents plus *orchestrator*
primaries that delegate to them — and seed it into LibreChat **via the REST API**
(`POST/PATCH /api/agents`) from a run-once, idempotent Job, owned by a dedicated
platform user.

### 1. Expose the additive gateway MCPs to LibreChat *(done)*

Wire `terraform`, `context7`, `refero` (the `charts/mcps` children, ADR-0038/0040)
into `charts/librechat-app` `config.mcpServers`, reusing the existing
`self-service-mcp-api` Keycloak client (its `redirectUris` already carry a `*`
wildcard → no keycloak-baseline change, no new secret). `brave`/`firecrawl` are
omitted — redundant with the built-in `webSearch` pipeline.

### 2. The fleet

**Leaf subagents** (single-purpose, no delegation), each `model` from the
Converse catalog (ADR-0075/0044) + a minimal tool set:

| Agent | Model | Tools |
|---|---|---|
| `coder` | `adorsys-coder-pro` | `execute_code`, `context7_mcp`, `github_repos` |
| `reviewer` | `adorsys-reviewer-pro` | `github_pull_requests`, `github_repos`, `file_search` |
| `researcher` | `adorsys-researcher` | `web_search`, `file_search`, `context7_mcp` |
| `frontend` | `adorsys-frontend-pro` | `artifacts`, `refero_mcp`, `execute_code` |
| `iac` | `adorsys-coder` | `terraform_mcp`, `execute_code`, `github_repos` |
| `project-manager` | `adorsys-planner` | `github_issues`, `github_projects`, `github_pull_requests` |
| `platform-concierge` | `gemma-4` | `lightbridge_self_service`, `coder_mcp` |

**Orchestrator primaries** (`subagents.enabled: true`, delegating to the leaves):

| Agent | Model | Delegates to |
|---|---|---|
| `Builder` | `adorsys-planner-pro` | coder, reviewer, iac, frontend, researcher |
| `Analyst` | `glm-5p2` | researcher, coder |
| `Platform Copilot` | `adorsys-planner` | platform-concierge, project-manager, iac |

The roster lives as a values block in `charts/librechat-app`
(`agentSeed.agents[]`), rendered to a ConfigMap the Job consumes — so the fleet
is versioned in git like everything else.

### 3. The seed mechanism (verified contract)

A run-once Job on the **LibreChat image** (has the mongoose models + `MONGO_URI`
+ `JWT_SECRET` env) that:

1. **Ensures a platform user** (`platform@ai.camer.digital`, an admin-capable
   role) in Mongo, capturing its `_id`.
2. **Mints a LibreChat access token** — `jwt.sign({ id, role }, JWT_SECRET)`
   (HS256), the payload `requireJwtAuth`'s passport-jwt strategy expects.
3. **Two-phase, idempotent upsert** against the in-cluster LibreChat Service:
   - The server **generates `agent.id` (`agent_<nanoid>`)** on POST — so POST is
     **not idempotent**. The Job `GET`s the agent list, matches by `name`, and
     `PATCH`es an existing agent or `POST`s a new one.
   - **Phase A** seeds the leaves and records each returned `id`.
   - **Phase B** seeds the orchestrators with
     `subagents: { enabled: true, agent_ids: [<resolved leaf ids>] }` — the
     referenced agents must already exist and be accessible to the author, so
     ordering is load-bearing.
4. **Makes the fleet visible to all users** (promote/category + a global ACL
   grant — the exact call to be pinned during the first live run; see Open
   items).

`provider` = the custom endpoint name (`Converse`); `model` = the catalog id.

## Consequences

**Positive**
- A consistent, curated fleet every user gets for free, grounded in real tooling.
- Subagent delegation mirrors the opencode fleet doctrine — one lean primary,
  specialist children, no single agent carrying every tool schema.
- The roster is versioned in git and re-seeds on change (idempotent).

**Negative**
- The seed path is genuinely stateful and **cannot be fully verified from the
  chart repo** — it needs a live LibreChat + Mongo. First deploy is a supervised
  smoke test, not fire-and-forget.
- Reusing `JWT_SECRET` to mint an admin token is powerful; the Job must be
  tightly scoped (its own SA, no extra RBAC) and the platform user least-priv.
- `refero` rides a shared Pro quota (8k calls/mo, ADR-0027) — a `frontend`-heavy
  fleet can burn it; instructions steer agents to query deliberately.

**Neutral / follow-ups**
- If the create/visibility contract shifts in a future LibreChat bump, the seed
  script (not the chart) is where it breaks — pin the image and re-smoke on bump.

## Alternatives considered

- **Declare agents in `librechat.yaml`** — impossible; no such schema exists
  (verified v0.8.7). This is *why* a seed mechanism is needed at all.
- **Mongo-direct upsert** (bypass the API) — rejected: skips server-side
  validation, ACL, version tracking, and `mcpServerNames` extraction; the API is
  the supported contract.
- **UI-only (build + share/publish)** — rejected as the *primary* path: not
  reproducible/GitOps'd. Still available for ad-hoc user agents.
- **Expose all 5 gateway MCPs** — rejected: `brave`/`firecrawl` duplicate the
  built-in `webSearch` pipeline for no added value and extra cost.

## Related

- ADR-0038/0040 — the `charts/mcps` gateway MCP catalog these agents consume.
- ADR-0074 — opencode primary+fleet doctrine (the shape mirrored here).
- ADR-0075/0044/0050 — the Converse model catalog the agents pick models from.
- ADR-0027 — Refero Pro subscription + quota.
- `charts/librechat-app` — where the MCP wiring + `agentSeed` + Job live.
