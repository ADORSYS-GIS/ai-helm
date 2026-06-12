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
   context7, **terraform** — flipped on). `enabled: false` means *not connected*
   → reserved for servers no role uses yet (refero, firecrawl, chrome-devtools).
2. **Access** (`config.permission` + `config.agent.<name>.permission`):
   - A **global `permission` deny-baseline** denies every connected MCP tool
     (`brave_*`, `context7_*`, `terraform_*`) so the **primary/default agent is
     lean** — it has none of them.
   - Each role is a **`mode: subagent`** the primary delegates to (`@name` / the
     task tool), and is a **whitelist**: it re-allows only its own tools + its
     file/bash scope; everything else falls through to the deny-baseline.

Initial roles (extend by copying a block). **Models are pinned cost-lean** —
the cheap/fast catalog tier for high-volume low-stakes roles, a stronger model
only where the stakes warrant it (`camer-digital/<id>` → our gateway catalog;
a user can override per agent locally; the PRIMARY agent keeps the user default):

| Agent | model | edit | bash | MCP tools |
|---|---|---|---|---|
| `web-search` | `deepseek-v4-flash` | deny | deny | `brave_*` (read-only researcher) |
| `doc-research` | `deepseek-v4-flash` | only `docs/**` | deny | `context7_*` |
| `iac` | `adorsys-planner` (GLM-5) | allow | `ask`; allow `terraform *`/`tofu *`; deny `rm *` | `context7_*`, `terraform_*` |
| `reviewer` | `reviewer-flash` | deny | deny | `context7_*` (read-only code review) |
| `test` | `minimax-m2p7` | allow | `ask`; allow common test runners; deny `rm *` | `context7_*` (TDD: write + run tests) |
| `skill` | `deepseek-v4-flash` | only `.opencode/skills/**`, `skills/**` | deny | `context7_*` + `skill` (author opencode skills) |

This **refines ADR-0042**: brave + context7 are no longer "on for the primary
agent" — they're connected but scoped to their specialist subagents. The
lean-default intent is preserved and strengthened (the main agent now has *no*
MCP tools; each lives behind a named role).

## Consequences

- The primary experience stays lean and governed; risky capability (IaC apply,
  doc writes) is funnelled through narrow, auditable subagents.
- **terraform now connects for every user** (an OAuth handshake to `/mcp/terraform`
  at startup) even though only `@iac` can call it. Acceptable; the tool stays
  gated. refero/firecrawl remain unconnected until a role needs them.
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
