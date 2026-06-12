# ADR-0044: Role subagents with permission-scoped tools in the opencode well-known

**Status:** Accepted
**Date:** 2026-06-12
**Deciders:** @stephane-segning
**Relates to:** refines [ADR-0042](0042-opencode-wellknown-mcp-catalog.md) (the MCP catalog's enablement model); builds on [ADR-0014](0014-split-librechart-and-opencode-wellknown.md), [ADR-0038](0038-mcp-oauth-protected-resource-metadata.md)

## Context

ADR-0042 gave the org-wide opencode `.well-known` an MCP catalog with a single
on/off knob per server (`config.mcp.<name>.enabled`) and a "lean default" of
brave + context7 on, the rest opt-in. That knob is too coarse: it can't say
*who* may use a tool or *what* an agent may touch. We want **role separation** —
e.g. a web-search helper that can search but never write; a docs writer that can
write only under `docs/`; an IaC agent that can run `terraform` but not `rm`.

opencode supports this natively: agents (`config.agent.<name>`) each carry a
**`permission`** block (the modern replacement for the deprecated per-agent
`tools` map), values `allow`/`ask`/`deny` or a **glob-keyed map, last-match-wins**.
The keys cover built-in tools (`edit`, `bash`, `read`, `webfetch`, …), **path
globs** for `edit`/`bash` (`{"*":"deny","docs/**":"allow"}`), and **MCP tool
globs** (`"<server>_*"`). A per-agent `permission` overrides the root one. Two
facts shape the design:

- A tool only exists if its MCP server is **connected** (`enabled: true`). So
  "give terraform to the IaC agent" requires terraform *connected*, not disabled.
- Plugins/servers pushed via the well-known are merged under each user's config,
  so these agents + permissions become a shared org-wide baseline.

## Decision

Model tool access on **two decoupled axes**, and express roles as **delegated
subagents** behind a **lean primary agent**:

1. **Connectivity** (`config.mcp.<name>.enabled`) = whether opencode connects to
   the server at all. Connect every server some role needs (now: brave,
   context7, **terraform**, **refero**, and the local **chrome-devtools** —
   flipped on). `enabled: false` means *not connected* → reserved for servers
   no role uses yet (firecrawl).
2. **Access** (`config.permission` + `config.agent.<name>.permission`):
   - A **global `permission` deny-baseline** denies every connected MCP tool
     (`brave_*`, `context7_*`, `terraform_*`) so the **primary/default agent is
     lean** — it has none of them.
   - Each role is a **`mode: subagent`** the primary delegates to (`@name` / the
     task tool), and is a **whitelist**: it re-allows only its own tools + its
     file/bash scope; everything else falls through to the deny-baseline.

Initial roles (extend by copying a block). **Models are pinned cost-lean** —
the cheap/fast tier for high-volume low-stakes roles, a stronger model only
where the stakes warrant it — and referenced by a **branded `adorsys-*` alias**
(see below), never the raw model id, so the backing can change without editing
this config. A user can override per agent locally; the PRIMARY agent keeps the
user default.

| Agent | model (alias) | edit | bash | MCP tools |
|---|---|---|---|---|
| `web-search` | `adorsys-researcher` | deny | deny | `brave_*` (read-only researcher) |
| `doc-research` | `adorsys-researcher` | only `docs/**` | deny | `context7_*` |
| `iac` | `adorsys-planner` | allow | `ask`; allow `terraform *`/`tofu *`; deny `rm *` | `context7_*`, `terraform_*` |
| `reviewer` | `adorsys-reviewer` | deny | deny | `context7_*` (read-only code review) |
| `test` | `adorsys-coder` | allow | `ask`; allow common test runners; deny `rm *` | `context7_*` (TDD: write + run tests) |
| `skill` | `adorsys-researcher` | only `.opencode/skills/**`, `skills/**` | deny | `context7_*` + `skill` (author opencode skills) |
| `frontend` | `adorsys-coder-pro` | allow | `ask`; allow JS toolchain (`pnpm`/`npm`/`bun`/`yarn`); deny `rm *` | `context7_*`, `refero_*`, `chrome-devtools_*` (design-aware UI + browser inspect) |

### Branded model aliases

Agents (and users) select **branded catalog aliases** — `adorsys-researcher`,
`adorsys-coder` / `-pro`, `adorsys-reviewer` / `-pro`, `adorsys-planner` / `-pro`
(`charts/ai-models`) — whose **backing model can be swapped without informing
users**: the id they selected never changes, and only the alias
`info.displayName` parenthetical reveals today's backing (e.g. *"Adorsys Coder
(MiniMax M2.7)"*, *"Adorsys Reviewer Pro (GLM-5)"*). Each alias is a normal
catalog entry (own route + `BackendTrafficPolicy` + budget bucket); a swap is a
one-line `modelNameOverride` + displayName edit in `charts/ai-models`, invisible
to the well-known and to users. Backings deliberately avoid `qwen3-5-4b-local`
(single-GPU capacity) and `gemma-4` (maintainer preference).

This **refines ADR-0042**: brave + context7 are no longer "on for the primary
agent" — they're connected but scoped to their specialist subagents. The
lean-default intent is preserved and strengthened (the main agent now has *no*
MCP tools; each lives behind a named role).

## Consequences

- The primary experience stays lean and governed; risky capability (IaC apply,
  doc writes) is funnelled through narrow, auditable subagents.
- **terraform + refero now connect for every user** (an OAuth handshake to
  `/mcp/terraform` and `/mcp/refero` at startup) even though only `@iac` /
  `@frontend` can call them. firecrawl stays unconnected until a role needs it.
- **chrome-devtools is connected too** (scoped to `@frontend`), kept on purpose
  despite being **local**: it spawns `npx chrome-devtools-mcp` on every user's
  box and needs a real Chrome, so users without that setup see it fail to start
  — an accepted trade for the unified DevTools experience.
- Each new branded alias carries a uniform per-model monthly budget cap
  (`rateLimitBudgeting`: free $30 / pro $100; tunable per alias in
  `charts/ai-models`). The pre-existing `adorsys-planner` / `-pro` keep their
  own (tiered) caps.
- Adding a role = one `agent` block (+ connecting its server if new). The pattern
  generalizes (e.g. `code-review`: read-only, no MCP; `test-runner`: `bash`
  scoped to the test command).
- **Runtime enforcement must be validated on a live opencode before this is
  relied on** — the rendered JSON is valid, but agent-vs-root permission
  precedence and MCP-glob gating are opencode-version behaviors, not contracts.
  Validate with `opencode` (delegate to each role; confirm the primary lacks the
  MCP tools and each subagent's scope holds) before merge/deploy. This follows
  the project's "validate the live path before shipping" rule.
- Inline agent `prompt` strings are shipped (opencode uses them directly); we do
  **not** use `{file:...}` prompts since the well-known can't ship files to users.
