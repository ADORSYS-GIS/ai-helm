# ADR-0048: Global browser plugin, a closed-loop frontend agent, and the per-agent tool-injection token model

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

**3. Own the full browser surface on a single closed-loop `frontend` agent.** Fold
`edit` + the JS toolchain + Refero (design refs) + Context7 (docs) + the full
`browser_*` surface onto one multimodal `@frontend` subagent so it runs the whole
loop in one context: **implement → reload → snapshot → screenshot → compare to the
reference → decide → iterate**. It is multimodal (`adorsys-frontend` → Nemotron
Omni) so it reads the screenshots it captures. `browser_*` is denied at the global
baseline and re-allowed **only** on `@frontend`.

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
keeps a tool out of every agent except those that re-allow it, and the 27
`browser_*` schemas are injected into `@frontend` **only**.

## Consequences

**Positive**

- Real closed-loop UI development from opencode: implement → verify in a real
  browser → iterate, in one agent's context, grounded in design references.
- Token cost is **bounded and isolated**: the ~27 browser schemas (~2–4k tokens)
  land in `@frontend` only — never the primary or the other six subagents. No
  context flood, no duplication.
- The corrected model validates the whole ADR-0044 design: the deny-baseline + per
  agent allow-lists are a **real per-agent token lever**, not just a safety gate.
  The primary agent is genuinely lean.
- Removing `chrome-devtools` drops a local MCP and consolidates two roles
  (inspect + drive) into one better-integrated capability.

**Negative**

- `@frontend` is the heaviest agent (browser + refero + context7 + edit + JS
  toolchain). Acceptable — it's the one role that needs all of it — but it sets the
  ceiling on that agent's per-request overhead.
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

- **Per-group browser subagents (`browser-page` + `browser-control`)** — the
  original shape. Rejected: the iterate loop needs *both* groups (screenshot *and*
  reload/navigate) plus `edit` in one context, so splitting breaks the loop; and
  since per-agent injection already isolates the cost to `@frontend`, splitting
  buys no further token win for the rest of the roster. (It *would* isolate page-vs
  control tokens from each other — but that's not the bottleneck here.)
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
  (remove chrome-devtools + unify frontend), `06cbfdd` (correct the token model),
  `f44321f` (dual-package guardrail)
- Docs: [`docs/opencode-well-known.md`](../opencode-well-known.md) (the *how*:
  plugin config, agent table, the per-agent injection note)
- Charts/files: `charts/librechat-opencode-wellknown/values.yaml` (plugin entry,
  deny-baseline, `frontend` agent), `charts/ai-models/values.yaml` (`adorsys-frontend`
  multimodal rationale)
- Refines / overrides in part: [0042](./0042-opencode-wellknown-mcp-catalog.md)
  (removes `chrome-devtools` from the catalog), [0044](./0044-opencode-role-subagents-and-permission-scoped-tools.md)
  (corrects the token rationale; rewrites the `@frontend` role); builds on
  [0014](./0014-split-librechart-and-opencode-wellknown.md)
