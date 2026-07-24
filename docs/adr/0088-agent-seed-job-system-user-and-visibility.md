# ADR-0088: Agent-seed Job — SSO system user as author + public-permissions visibility

**Status:** Proposed
**Date:** 2026-07-24
**Deciders:** @stephane-segning

## Context

[ADR-0086](0086-librechat-agent-fleet-and-gitops-seed.md) proposed a GitOps
agent-seed Job but parked two unknowns that made it un-buildable: **(1)** every
LibreChat agent needs a real `author` User ObjectId (no service accounts), and
**(2)** how a seeded agent becomes visible to all users. Both are now resolved
(verified against v0.8.7), so the Job can be built. This also unblocks the
"reviewer with subagents" ask — subagent delegation needs real DB Agents
(`subagents.agent_ids`), which the git-native `modelSpecs` personas can't be.

## Decision

Build a run-once, idempotent **agent-seed Job** (ADR-0086's mechanism) with the
two pins resolved:

1. **Author = an SSO system user.** A dedicated Keycloak account
   `platform@ai.camer.digital` (created, admin) is the `author`. Because auth is
   Keycloak OIDC (`OPENID_AUTO_REDIRECT`), it must log into LibreChat once so its
   User doc is provisioned (ObjectId ↔ OIDC `sub`); the Job then looks that
   ObjectId up in Mongo and **mints a LibreChat JWT** (`jwt.sign({id}, JWT_SECRET)`
   — the payload `requireJwtAuth` expects). No fake service account.
2. **Visibility = a public ACL grant.** After create, the Job calls the generic
   resource-ACL endpoint **`PUT /api/permissions/agent/<id>`** with
   `{ updated: [], removed: [], public: true, publicAccessRoleId: "agent_viewer" }`
   (`updated`/`removed` are required arrays; the top-level `public` +
   `publicAccessRoleId` is expanded to a `PrincipalType.PUBLIC` principal
   server-side). This is the same access-role mechanism the skill sync uses
   (`skill_viewer`). Every seeded agent is world-visible under the Agents endpoint.

### Seed flow (all verified against v0.8.7)

- **Runs on the LibreChat image** (has `mongoose`, `jsonwebtoken`, Node `fetch`,
  `MONGO_URI`, `JWT_SECRET`), as an ArgoCD `Sync` hook Job
  (`hook-delete-policy: BeforeHookCreation`) so it re-runs when the fleet changes.
- **Idempotent by name:** `GET /api/agents` → match by `name` → `PATCH` existing
  or `POST` new (the server generates `agent_<nanoid>`, so POST alone isn't
  idempotent). Records the resolved id per name.
- **Two-phase:** Phase A seeds the leaf subagents and captures their ids; Phase B
  seeds orchestrators with `subagents: { enabled: true, agent_ids: [<leaf ids>] }`
  (referenced agents must already exist + be accessible — hence ordering).
- **Fails closed:** if the platform user's doc doesn't exist yet, the Job errors
  with a clear "log in once via SSO" message rather than authoring under the
  wrong user.

### Fleet & UX

- The starter fleet is a **deep-review** graph: `deep-reviewer` (orchestrator) →
  `security-reviewer` + `test-coverage-reviewer` (leaves), all carrying the
  `code-review` skill (ADR-0086 severity framework).
- These are **DB Agents** under the Agents endpoint — distinct from the flat
  `reviewer` **modelSpec** persona (the quick, single-pass review in the spec
  picker). Quick review = the spec; deep review with delegation = the agent.
  Wiring a modelSpec to a seeded agent (`preset.endpoint: agents, agent_id`) is
  possible but needs the id post-seed — deferred (the id is server-generated).
- **Fleet specs live in `ai-helm-values`** (`agentSeed.agents[]`, ADR-0056) — the
  Job template + seed script live in `charts/librechat-app`.

## Consequences

**Positive**
- A reproducible, git-managed agent fleet with real subagent delegation — the
  thing modelSpecs structurally can't do.
- No service-account hack; a real, scoped SSO principal owns the fleet.

**Negative**
- **Not verifiable from the chart repo** — the platform user's ObjectId, the
  two-phase subagent validation, and the public grant all need a live smoke test.
  First run is supervised.
- The Job mints an admin JWT from `JWT_SECRET`; scope it tightly (own SA, no
  extra RBAC) and keep the platform user least-privilege-but-admin.
- Two "reviewer" surfaces (modelSpec + agent) — mitigated by distinct names
  (`reviewer` spec vs `deep-reviewer` agent).

**Neutral / follow-ups**
- Wire a persona (modelSpec) to the seeded `deep-reviewer` once its id is known.
- Extend the fleet (Builder/Analyst/etc., ADR-0086) once the reviewer graph is
  proven live.

## Alternatives considered

- **Mongo-direct writes** — rejected: skips server validation, ACL, version
  tracking, and `mcpServerNames` extraction; the API is the supported contract.
- **modelSpec-only "sub-models"** — impossible: subagents reference real Agent
  ids; specs are ephemeral and can't delegate spec→spec.
- **Local (non-SSO) system user** — not viable: `OPENID_AUTO_REDIRECT` means
  local accounts are effectively off; the author must be a Keycloak identity.

## Related

- [ADR-0086](0086-librechat-agent-fleet-and-gitops-seed.md) — the fleet + seed
  proposal this makes buildable (resolves its two open pins). Issue #723.
- [ADR-0056](0056-workload-values-in-ai-helm-values.md) — fleet specs live in
  ai-helm-values.
- [ADR-0021](0021-burst-budget-billing-and-dual-plane-authconfigs.md) — the
  gateway identity the platform user authenticates through.
