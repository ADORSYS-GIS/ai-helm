# ADR-0074: Opencode well-known — MCPs opt-in by default + a multi-primary agent fleet

**Status:** Accepted
**Date:** 2026-06-30
**Deciders:** @stephane-segning

> Amends [ADR-0048](./0048-global-browser-plugin-and-per-agent-tool-injection.md)
> (single lean primary → a *fleet* of primaries) and
> [ADR-0071](./0071-local-npx-mcp-servers-and-role-subagents.md) /
> [ADR-0072](./0072-no-key-local-mcp-batch.md) /
> [ADR-0073](./0073-issue-tracker-mcps-atlassian-local-github-gateway.md)
> (every catalogued MCP server flips from `enabled: true` to `enabled: false`).
> Those ADRs' bodies stay immutable; this one revises the two operational knobs
> they set. The scoping mechanics of
> [ADR-0044](./0044-opencode-role-subagents-and-permission-scoped-tools.md) and
> the per-agent tool-injection finding of ADR-0048 are unchanged and load-bearing
> here.

## Context

The org-wide opencode config served at `.well-known/opencode`
(`charts/librechat-opencode-wellknown/values.yaml`, ADR-0042) had grown to **16
MCP servers**, and ADR-0071/0072/0073 shipped almost all of them
`enabled: true`. Because `enabled` controls *connectivity* — opencode actually
connects to a server on startup — a fresh `opencode auth login` user inherited a
config that, on day one, tries to:

- dial 4 remote `/mcp/*` routes (each can trigger an OAuth device-code prompt),
  and
- cold-`npx`-install ~11 local Node MCP servers (memory, sequential-thinking,
  mobile, git, drawio, shadcn, reddit, youtube, rss, jira, confluence).

That is a lot of startup cost, network chatter, and tool surface for servers most
users never touch in a given session — "too many MCPs," in the maintainer's
words. The deny-baseline (ADR-0044/0048) already keeps these tools off the
*primary's context*, but it does nothing about the *connection* cost or the
prompts — those are paid the moment a server is `enabled`, regardless of which
agent may eventually call it.

Separately, the agent topology had a single primary, `frontend` (ADR-0048).
Every non-frontend workflow — backend, infra, docs, marketing/PO research,
architecture, security, testing — ran through that one frontend-flavoured default
or was pushed into a subagent. One primary carrying every persona is both a poor
default (a backend or marketing user starts in a frontend agent) and a missed
opportunity: ADR-0048's own finding is that **adding a primary is cheap** —
a primary is just a prompt + a permission scope; the heavy tool schemas live
behind subagents, so extra primaries cost ~nothing in injected context.

## Decision

Two changes to `charts/librechat-opencode-wellknown/values.yaml`.

### 1. Every MCP server is opt-in (`enabled: false`)

All 16 catalogued servers ship `enabled: false`. MCPs become **opt-in**: a user
(or a team standardising on a workflow) enables only the servers they need — by
dropping the snippet into their own `opencode.json`, or by us flipping one line
here when a server graduates to org-default. The agent wiring that *handles* each
server is kept **fully intact** — the deny-baseline entry and the dedicated
subagent stay — so enabling a server is a one-line `enabled: true` flip with its
specialist subagent already in place. Nothing about the access model changes; only
the default connectivity does.

This trades day-one capability for a lean, honest startup: no surprise OAuth
prompts, no dozen cold `npx` installs, and a tool surface that reflects what the
user actually opted into.

### 2. A fleet of selectable primaries (default `assistant`)

`frontend` is demoted from *the* default to *one of* several `mode: primary`
agents the user picks via the agent switcher. The fleet:

| Primary | Role | Writes | Shell |
|---|---|---|---|
| **`assistant`** (default) | neutral general-purpose | code | JS/Rust/Go/Python/make/just (safe), `rm` gated |
| `frontend` | frontend impl (kept verbatim) | code | JS + Rust/WASM, `rm` gated |
| `backend` | services / APIs / DB / migrations | code | Go/Python/Node/Rust/make/just, `rm` gated |
| `devops` | k8s / Helm / Terraform / CI | charts/manifests | safe read/plan only; apply→ask, destroy/delete→deny |
| `marketing` | non-dev content & research | `docs/**` only | none |
| `docs` | technical writing / ADRs | `docs/**` only | none |
| `ux` | design/experience-led frontend | code | JS, `rm` gated |
| `architect` | deep code / systems architecture | `docs/**` only | none (read-heavy) |
| `enemy` | hard adversarial red-team | — (read-only) | none |
| `tester` | TDD | code | test commands only |
| `security` | security review & reporting | `docs/**` only | none (read-only) |

Every primary keeps the ADR-0048 discipline: **no MCP/browser re-allow** (the
deny-baseline keeps those schemas off it), **no `model` pin** (inherits the
session model; only the three visual subagents `@browser`/`@design`/`@mobile`
pin the multimodal `adorsys-frontend` alias). A persona is its *prompt +
permission scope*, not a private toolset — it delegates tool-heavy work to the
existing subagents (`@web-search`, `@doc-research`, `@vcs`, `@planner`, `@test`,
`@diagram`, `@memory`, `@iac`, `@reviewer`, `@content`, `@atlassian`, `@ui`,
`@browser`, `@design`, `@mobile`). The default is the **neutral `assistant`**.

**Naming guard.** Primary names must avoid opencode's built-ins, which a config
entry would clobber: `build` / `plan` are built-in **primaries** and
`general` / `explore` / `scout` are built-in **subagents** (the task tool's
default delegate is `general`). The neutral default is therefore named
**`assistant`, not `general`** — same trap the existing `@planner`-not-`plan`
note documents. The marketing persona is named `marketing`, not `content`,
because `content` is already the research **subagent**.

**Permission hardening (order-independent by design).** Three refinements close
gaps a primary's prompt would otherwise only *promise*:

- `firecrawl_*` is added to the global deny-baseline (it was the one catalogued
  server without one) and re-allowed on `@web-search` — so opting it in can't
  inject its tools onto every primary. Every catalogued server now has both a
  deny entry and a handling subagent.
- `enemy` (a read-only adversary) gets a `permission.task` allowlist —
  `{"*": deny, reviewer/planner/web-search/doc-research: allow}` — so it cannot
  launder a write through a *writable* subagent (e.g. `@test`, which has
  `edit: allow`). `edit`/`bash` deny alone don't govern delegation; `task` does.
- `backend` uses a **curated** bash allowlist of specific safe sub-commands
  (build/test/dev/dep) instead of blanket language wrappers, so any migration
  (`npm run migrate`, `python manage.py migrate`, `uv run alembic upgrade`,
  `prisma migrate`, …) falls through to `"*": ask` — matching its prompt.

⚠️ **Load-bearing constraint — `toJson` sorts permission keys.** opencode
resolves a permission map by **last-matching-rule-wins in config order**, but
this chart serializes via Helm `toJson`, which **sorts object keys
alphabetically** — authored order is lost. So permission maps MUST be
**order-independent**: one catch-all `"*"` (ASCII 42 → always sorts first) plus
**non-overlapping** specific rules. The naive "broad allow then narrow deny"
(`"npm *": allow` then `"*migrate*": ask`) is defeated — `npm *` sorts last and
wins. This is why `backend` curates its allowlist rather than layering a migrate
deny over `npm *`, and it's a permanent rule for editing any agent's bash/`task`.

## Consequences

**Positive**

- Lean, predictable startup: no auto-connect to a dozen servers, no surprise
  OAuth prompts or cold `npx` installs for capabilities a session never uses.
- Honest tool surface — what's connected is what the user opted into.
- The right default agent per user: backend/infra/marketing/security users start
  in a fit-for-purpose primary instead of a frontend one.
- Enabling any MCP stays a one-line flip — every server already has its handling
  subagent and deny-baseline entry.
- Cheap by construction: extra primaries add ~no injected-context cost (tools
  live behind subagents — the ADR-0048 finding).

**Negative**

- Day-one capability regresses: a user must opt a server in before its subagent
  works (e.g. `@web-search` is inert until `brave` is enabled). Mitigated by the
  one-line flip and clear in-file comments.
- More primaries = more choice to learn. Mitigated by a neutral `assistant`
  default that delegates everywhere and points the user at the focused primary
  when a task clearly fits one.

**Neutral / follow-ups**

- Some primaries deliberately overlap a subagent of similar intent
  (`tester`↔`@test`, `security`↔`@reviewer`, `ux`↔`@design`): the primary is the
  *driver* persona, the subagent the *delegated worker*. Kept both on purpose.
- If a server proves universally useful, graduate it back to `enabled: true`
  here (a deliberate, reviewed flip — not the silent default it was before).
- `firecrawl` remains `enabled: false` with no subagent (reserved), unchanged.

## Alternatives considered

- **Keep MCPs enabled, just trim the catalogue.** Rejected — the maintainer's
  concern is the *default-on* connection cost, not the catalogue's existence.
  Opt-in keeps every server one flip away without paying for all of them always.
- **A single `enabled` master toggle for all MCPs.** Rejected — too coarse; the
  value is per-user, per-workflow selection, which per-server `enabled` already
  expresses.
- **Promote subagents to primaries (drop the subagent tier).** Rejected — that
  would push MCP/browser tool schemas back onto primaries and defeat the
  lean-context model. Primaries delegate; subagents own tools.
- **Name the neutral default `general`.** Rejected — clobbers opencode's
  built-in general-purpose subagent used by the task tool.
