# ADR-0048: Global browser plugin, a lean frontend primary, and the per-agent tool-injection token model

**Status:** Accepted
**Date:** 2026-06-14
**Deciders:** @stephane-segning

> **Amendment 2026-06-14 (post-merge):** the `debug` group — dropped in
> Decision 1 below (`browser_eval` = arbitrary in-page JS + console/network/
> cookies, deemed too sharp for an org-wide push) — was **re-enabled at the
> maintainer's explicit request**. The browser plugin now registers all three
> groups (`page` + `control` + `debug` = 33 tools); `debug` remains scoped to
> the `@browser` subagent only (the deny-baseline keeps it off every other
> agent). The original decision body is unchanged; only the registered `groups`
> differ. Shipped in `release-2026.06.14-v02`.

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
delegated subagents.** Make `frontend` the org-wide default agent
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

**Model pinning — only where vision is required (no-risk rule).** Pin a
multimodal model **only** on the agents whose tools return images the agent must
interpret: `@browser` (`browser_screenshot`) and `@design`
(`refero_get_screen_image`). Both pin the branded multimodal alias
`adorsys-frontend`, which **guarantees** they have vision regardless of the
user's session model. **Every other agent** — the `frontend` primary *and* all
role subagents (`web-search`, `doc-research`, `iac`, `reviewer`, `test`, `skill`)
— carries **no `model`** and inherits the user's session model (`input.model ??
agent.model ?? currentModel`, `prompt.ts`). This supersedes the ADR-0044 per-role
cost-lean pins: simpler and risk-free (no agent can lose vision by inheriting the
wrong model), at the cost that those roles no longer *force* a cheap model — they
run on whatever the user picks.

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
- Pinning a multimodal model **only** on the vision agents (`@browser`, `@design`)
  removes the inheritance risk entirely: they always have vision, whatever the user
  runs. Every other agent inherits the session model, so there's one model to think
  about per session, not a per-role matrix.

**Negative**

- The loop now crosses an agent boundary: the primary doesn't see the screenshot
  itself — `@browser` reads it (multimodal, inherited) and *describes* it back.
  Slightly less direct than one-context vision, traded for a lean default context.
- Dropping the per-role cost-lean pins means `web-search`/`reviewer`/etc. now run
  on the user's session model instead of a forced-cheap `adorsys-*` model — a
  possible cost regression for those high-volume roles (the deliberate trade for a
  simpler, risk-free model policy). Re-pin a cheap model per role if cost matters
  more than simplicity.
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
  frontend`; the `@browser`/`@design` vision subagents + the model-pinning rule)
- Docs: [`docs/opencode-well-known.md`](../opencode-well-known.md) (the *how*:
  plugin config, agent table, the per-agent injection note)
- Charts/files: `charts/librechat-opencode-wellknown/values.yaml` (`default_agent`,
  plugin entry, deny-baseline, the `frontend` primary + `@browser`/`@design`
  subagents), `charts/ai-models/values.yaml` (`adorsys-frontend` multimodal rationale)
- Refines / overrides in part: [0042](./0042-opencode-wellknown-mcp-catalog.md)
  (removes `chrome-devtools` from the catalog), [0044](./0044-opencode-role-subagents-and-permission-scoped-tools.md)
  (corrects the token rationale; rewrites the `@frontend` role); builds on
  [0014](./0014-split-librechart-and-opencode-wellknown.md)
