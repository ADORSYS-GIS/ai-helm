# ADR-0048: Global browser plugin, a lean frontend primary, and the per-agent tool-injection token model

**Status:** Accepted
**Date:** 2026-06-14
**Deciders:** @stephane-segning

## Context

opencode users doing UI work needed a *real browser* in the loop — open a page,
interact, screenshot, look at the result, fix the code, reload, repeat. Until
now that was approximated by the local `chrome-devtools` MCP (ADR-0042, scoped to
`@frontend` in ADR-0044). The maintainer authors [`@vymalo/opencode-browser`](https://github.com/vymalo/opencode-oauth2/tree/main/packages/opencode-browser)
([[maintainer]]), a plugin that gives an agent `browser_*` tools (open/click/
type/scroll/screenshot in named tab groups) over a localhost WebSocket bridge a
companion browser extension dials into. Adding it to the org-wide opencode
`.well-known` (ADR-0014/0042/0044) raised a real question: it ships **33 tools**
across three groups (`page`/`control`/`debug`) — would that flood every agent's
context?

Answering that forced a correction to how we understood opencode's tool model.
A first reading of `tool/registry.ts` (which builds the *full* tool catalog)
suggested opencode advertises every registered tool to every agent and that
per-agent `permission` only gates execution — i.e. that ADR-0044's deny-baseline
saved no tokens. **That was wrong.** Re-tracing to the actual model call (opencode
1.17.6) showed tools are filtered **per agent** in request-prep before they're
sent. This ADR records both the browser-plugin decision and the corrected model
that makes the ADR-0044 pattern actually pay off.

## Decision

**1. Ship `@vymalo/opencode-browser` as a global plugin**, version-pinned to the
`0.7.0` `@vymalo/*` line (the dual-form `["@vymalo/opencode-browser", {opts}]`
plugin-tuple — this plugin reads its config from the tuple's second arg, not from
`provider.options.meta`). Register **only the `page` (8) + `control` (19)
groups**; **drop `debug`** (its `browser_eval` is arbitrary in-page JS, plus
`console`/`network`/`cookies` — too sharp to push org-wide).

**2. Remove the `chrome-devtools` MCP entirely.** The plugin's `browser_*` tools
replace it as the live-browser capability. With it gone, every connected MCP
server is now remote (gateway `/mcp/*`).

**3. Promote `frontend` to a *lean* default primary; split the heavy tools onto
model-less subagents.** Make `frontend` the org-wide default agent
(`config.default_agent: frontend`, `mode: primary`) but keep it **lean**: it holds
only `edit` + the JS toolchain (it *implements* directly) and **delegates**
everything tool-heavy — driving the browser, design references, library docs — to
subagents. Lift `browser_*` onto a dedicated **`@browser`** subagent and Refero
onto **`@design`**; library docs route to the existing `@doc-research`. The
deny-baseline keeps `browser_*`/`refero_*`/`context7_*` **out of the primary's
injected toolset**, so the default context never carries the 27 `browser_*`
schemas — they load only in `@browser`'s context, on delegation. The loop becomes
**primary implements → `@browser` reloads + screenshots + reports → primary decides
→ iterates**.

**Model tiering.** The primary pins the **multimodal** `adorsys-frontend` (the
"most important model"). The split-off subagents (`@browser`, `@design`) carry
**no `model`** → they inherit the session model (`input.model ?? agent.model ??
currentModel`, `prompt.ts`), so `@browser` runs a vision model and can read its
screenshots. The existing role subagents (`web-search`, `doc-research`, `iac`,
`reviewer`, `test`, `skill`) keep their **cost-lean `adorsys-*` pins** (ADR-0044).

**4. One source only — do not also connect the browser *MCP* form.**
`@vymalo/opencode-browser` is a dual package: the same `browser_*` catalog ships
as this plugin *and* as an MCP server. Connecting both would register the 27 tools
twice (same names). The plugin is the right form — it's local-only (bridge +
extension on the user's machine, so it can't ride the remote `/mcp/*` routes) and
its opencode adapter saves screenshots to disk for the model to read.

**Load-bearing finding (corrects the ADR-0044 token rationale):** opencode scopes
the **injected** tool set per agent. In `session/llm/request.ts`, `resolveTools()`
runs every tool name through `Permission.disabled()`, which **drops a tool from
that agent's injected `tools`/`activeTools`** when its effective rule is a
`pattern:"*"` **deny** (`permission/index.ts`); the filtered set is what's sent to
the model. A config **string-form** `"glob": "deny"` compiles to `pattern:"*"` →
removed from injection; `"glob": "allow"` re-injects; an agent's own rules merge
**after** the root baseline and win via `findLast`. This is uniform across
built-in, MCP, **and plugin** tools (keyed on name). ⇒ the deny-baseline genuinely
keeps a tool out of every agent except those that re-allow it, so the 27
`browser_*` schemas are injected into the `@browser` subagent **only** — never the
lean primary or any other agent. This is what makes decision **3** cheap.

## Consequences

**Positive**

- Real closed-loop UI development from opencode: implement → verify in a real
  browser → iterate, grounded in design references — now spanning *primary →
  `@browser` → primary* (the primary implements; `@browser` reloads, screenshots,
  and reports back; the primary decides and edits again).
- **The default context stays light.** The primary holds only `edit` + the JS
  toolchain, so a user's everyday session never carries the 27 `browser_*` schemas
  (~2–4k tokens) or the MCP tool schemas — those load only in the subagent that
  owns them, on delegation. This is the per-agent injection win put to work.
- The corrected model validates the whole ADR-0044 design: the deny-baseline + per
  agent allow-lists are a **real per-agent token lever**, not just a safety gate.
- Removing `chrome-devtools` drops a local MCP and consolidates two roles
  (inspect + drive) into one better-integrated capability (`@browser`).
- Model tiering keeps cost down: cheap `adorsys-*` pins on the existing roles, one
  multimodal model on the primary, inherited (not re-paid-for) by the split-offs.

**Negative**

- The loop now crosses an agent boundary: the primary doesn't see the screenshot
  itself — `@browser` reads it (multimodal, inherited) and *describes* it back.
  Slightly less direct than one-context vision, traded for a lean default context.
- **Model inheritance is load-bearing for screenshots.** `@browser` has no pinned
  model, so if a user switches the primary to a non-multimodal model, `@browser`
  loses screenshot vision. Documented trade-off; acceptable because the org default
  primary is multimodal.
- Forcing `default_agent: frontend` org-wide makes every user start on the
  frontend-flavoured primary (a user can still override in their own config, which
  wins on merge). Reasonable for a frontend/marketing-heavy org; not neutral.
- The browser plugin is **local**: each user installs the companion extension once
  and pastes the bridge URL+token; a user without that setup sees the tools fail to
  connect (Node ≥22 required). Same accepted trade-off the local `chrome-devtools`
  MCP had.
- A subtle footgun the team must remember: only the **string-form** deny removes a
  tool from injection. The **nested** form (`"glob": {sub: "deny"}`) yields a
  non-`*` pattern → gates execution but still injects the schema. Use the string
  form for tool-name gating.

**Neutral / follow-ups**

- Partially overrides ADR-0042 (which shipped `chrome-devtools` in the catalog) and
  ADR-0044 (whose token rationale this corrects and whose `@frontend` row this
  rewrites). Those ADRs stay Accepted/immutable; this one records the deltas.
- `debug`/`browser_eval` stays unregistered. Revisit only with an explicit decision
  — arbitrary in-page JS pushed org-wide is a meaningful surface.
- Plugin-tool execution is **not** `ctx.ask`-gated the way MCP tools are (the
  browser plugin doesn't call `ctx.ask`); moot today because denied tools are never
  injected, but relevant if a future role is given browser tools with finer intent.

## Alternatives considered

- **Keep the closed loop in one agent (browser on the primary, or on a single
  `@frontend` subagent)** — the prior shape in this ADR. Rejected: it injects the
  27 `browser_*` schemas (plus refero/context7) into the agent users talk to every
  turn. Since per-agent injection lets us push `browser_*` onto a delegated
  `@browser` subagent at *zero* cost to the default context, a lean primary that
  delegates is strictly cheaper; the only cost is the cross-agent hop (the primary
  reads `@browser`'s text report instead of the screenshot directly).
- **Per-group browser subagents (`browser-page` + `browser-control`)** — rejected:
  a single `@browser` already isolates the whole 27-tool set from the default
  context; splitting page-vs-control further fragments one capability for no real
  gain (the browsing work wants both groups together).
- **Keep `chrome-devtools` alongside the plugin** — rejected: redundant (both are
  local live-browser tools), and the plugin is better integrated (native
  screenshot-to-disk, named tab groups) and authored in-house.
- **Deliver the browser tools via the MCP form** (through the gateway `/mcp/*`) —
  rejected: the bridge is inherently local (extension dials a localhost socket), so
  an MCP form would also be local; and running it *alongside* the plugin double
  registers the 27 tools. One source, the plugin.
- **Register all three groups (incl. `debug`)** — rejected: `browser_eval` =
  arbitrary in-page JS, plus cookies/network/console; too broad for a mandatory
  org-wide push.

## Related

- Commits: `0261f33` (add plugin), `b54b9ec` (groups + initial split), `c945803`
  (remove chrome-devtools), `06cbfdd` (correct the token model), `f44321f`
  (dual-package guardrail), + the lean-primary restructure (`default_agent:
  frontend`; `@browser`/`@design` model-less subagents)
- Docs: [`docs/opencode-well-known.md`](../opencode-well-known.md) (the *how*:
  plugin config, agent table, the per-agent injection note)
- Charts/files: `charts/librechat-opencode-wellknown/values.yaml` (`default_agent`,
  plugin entry, deny-baseline, the `frontend` primary + `@browser`/`@design`
  subagents), `charts/ai-models/values.yaml` (`adorsys-frontend` multimodal rationale)
- Refines / overrides in part: [0042](./0042-opencode-wellknown-mcp-catalog.md)
  (removes `chrome-devtools` from the catalog), [0044](./0044-opencode-role-subagents-and-permission-scoped-tools.md)
  (corrects the token rationale; rewrites the `@frontend` role); builds on
  [0014](./0014-split-librechart-and-opencode-wellknown.md)
