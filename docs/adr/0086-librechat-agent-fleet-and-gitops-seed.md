<!-- ai-governance:stanza -->
# ADR-0086: LibreChat Agent Fleet & GitOps Seed Mechanism

- **Status**: Accepted
- **Date**: 2026-06-25
- **Authors**: @benie-joy-possi, @Guy-Ghis

---

## Context

LibreChat supports **DB Agents** (custom assistants created at `/api/agents` with custom instructions, avatar, model selection, capabilities like `execute_code` / `file_search`, attached tools / MCP servers, and **subagent delegation** via `@agent-name` mentions).

Prior to this ADR, agent definitions were manually created in the LibreChat UI database. For our self-hosted AI platform, manual UI creation violates GitOps doctrine:
1. Agent definitions are lost if MongoDB is wiped or re-created.
2. Agent configurations drift across environments.
3. Fleet updates cannot be code-reviewed via Pull Requests.

---

## Decision

We establish an automated **GitOps Agent-Seed Mechanism** that idempotently seeds the platform agent fleet into LibreChat MongoDB on deployment.

### 1. Fleet Architecture & Roster

The platform provisions a structured fleet consisting of **leaf subagents** and **orchestrator primaries**.

**Leaf subagents** (single-purpose, no delegation), each `model` from the
Converse catalog (ADR-0075/0044) + a minimal tool set:

| Agent | Model | Tools |
|---|---|---|
| `coder` | `adorsys-coder-pro` | `execute_code`, `github_repos`, `coder` (MCP) |
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

- The agent fleet is fully declaratively specified in Helm `values.yaml`.
- The PostSync job guarantees database state matches Git state after every deployment.
