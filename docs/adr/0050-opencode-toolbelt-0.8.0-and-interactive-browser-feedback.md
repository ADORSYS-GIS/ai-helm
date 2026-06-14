# ADR-0050: Bump the @vymalo OpenCode Toolbelt to 0.8.0 and register the `interactive` browser-feedback group

**Status:** Accepted
**Date:** 2026-06-14
**Deciders:** @stephane-segning

## Context

The org-wide opencode `.well-known` config (ADR-0014/0042/0044/0048) pins the four
`@vymalo/*` plugins on one version line, last at `0.7.3`. The maintainer
([[maintainer]], who authors these plugins) released **0.8.0** — the point at
which the workspace is rebranded the "**OpenCode Toolbelt**", a five-plugin suite
(`opencode-oauth2`, `opencode-models-info`, `opencode-ratelimit`,
`opencode-browser`, `opencode-browser-mcp`). The 0.7.1→0.8.0 span is mostly
internal to the browser plugin (a multi-client routing broker, 16 new actions,
full-page capture, plugin-initiated release, a `ws` transport so the bridge runs
on Node not just Bun, and a stdout-flooding fix), all of which ride in
transparently with a version bump. Two earlier additions we *already* consume —
`oauth2.responseApi` (#37) and `models-info.meta.modelsInfoOverwrite` (#38) —
turn out to have landed in **0.7.1**, not the 0.6.x our comments cited.

The one change that needs a deliberate choice is new in **0.8.0**: the browser
plugin gains a **`browser_request_feedback`** tool in a brand-new **`interactive`**
tool group (opt-in, like `debug`). It is a human-in-the-loop tool — the agent
asks the human to respond *on the page* (modes: confirm / choose / point /
element / region / comment) and **blocks up to 300s** for the answer, returning
`{ timedOut: true }` on no response. We register browser groups explicitly
(ADR-0048 → `page`+`control`+`debug` = 33 tools), so a new opt-in group is only
active if we add it.

## Decision

1. **Bump the four `@vymalo/*` plugins `0.7.3` → `0.8.0`** in
   `charts/librechat-opencode-wellknown/values.yaml`, keeping them on one
   version line (deterministic, exact-pin org-wide push per ADR-0048). The
   non-vymalo pins (`@tarquinen/opencode-dcp`, `opencode-skills-collection`) are
   unchanged.

2. **Register the new `interactive` browser group** by adding `interactive` to
   the `@vymalo/opencode-browser` plugin-tuple `groups` →
   `[page, control, debug, interactive]` = **34 tools**. No permission change is
   needed: the `interactive` tool is named `browser_request_feedback`, so the
   existing root `"browser_*": deny` baseline keeps it off every agent and the
   `@browser` subagent's `"browser_*": allow` re-injects it there — it lands
   **only** on `@browser`, exactly like the other browser tools (ADR-0048's
   per-agent injection model). The `@browser` prompt is updated to use it when a
   screenshot/snapshot is not enough to disambiguate user intent.

3. **Correct the stale minimum-version citations** in the values comments:
   `responseApi` and `modelsInfoOverwrite` are documented as needing plugin
   `≥ 0.7.1` (per the 0.8.0 changelog), not the `0.6.2`/`0.6.3` previously noted;
   all are satisfied by the `0.8.0` pin.

`interactive` is registered org-wide because it is materially safer than the
already-registered `debug` group (no arbitrary in-page JS — it only renders a
prompt overlay and reads the human's marks) and fits the org's frontend/design
loop and the 0.8.0 "collaborative human-centered tool" theme: the `@browser`
subagent can now ask the operator to point at the element they meant instead of
guessing.

## Consequences

**Positive**

- The closed-loop UI workflow (ADR-0048) gains a disambiguation step: `@browser`
  can ask the human to confirm/point/annotate on the live page and resolve the
  answer to an element ref it can then click — fewer wrong guesses on ambiguous
  UI requests.
- All transparent 0.7.1→0.8.0 browser improvements (multi-client broker,
  full-page capture, `ws`/Node transport, no stdout flooding) come along with the
  bump.
- The new tool adds **zero** cost to the default context — per ADR-0048's
  per-agent injection, it is injected only into `@browser`, never the lean
  `frontend` primary or any other agent.

**Negative**

- `browser_request_feedback` **blocks up to 300s**. A subagent that calls it
  while the user is away stalls that delegation until the timeout — the agent is
  prompted to fall back on `{ timedOut: true }`, but it is a longer-tail tool
  than the rest of the catalog.
- Like every browser tool it is **local-only** (needs the bridge + companion
  extension on the user's machine); a user without that setup sees it fail to
  connect, same accepted trade-off as the rest of the plugin (ADR-0048).
- One more org-wide-pushed surface to keep in mind, though a tame one.

**Neutral / follow-ups**

- Refines ADR-0048 (adds a fourth registered group; that ADR's `page`+`control`+
  `debug` = 33-tool figure becomes `+interactive` = 34). ADR-0048 stays
  Accepted/immutable; this records the delta.
- Future browser-group additions follow the same rule: register the group here,
  rely on the `browser_*` deny-baseline + `@browser` allow to scope it.

## Alternatives considered

- **Bump to 0.8.0 but leave `interactive` unregistered** — rejected. The tool is
  low-risk (no code execution), directly serves the design loop, and the
  maintainer's standing preference (the ADR-0048 `debug` re-enable) is to expose
  capability rather than withhold it. Keeping it off would forgo the headline
  0.8.0 feature for no real safety gain.
- **Register `interactive` but on a separate `@feedback` subagent** — rejected.
  `browser_request_feedback` needs a live page and the bridge; it belongs with
  the rest of the browser toolset on `@browser`. A separate agent would fragment
  one capability and add a needless delegation hop.
- **Hold at 0.7.3** — rejected. Stays off the suite's current line, misses the
  transparent browser fixes (`ws`/Node transport, stdout flooding), and leaves
  the version comments mis-citing 0.6.x minimums.

## Related

- Charts/files: `charts/librechat-opencode-wellknown/values.yaml` (plugin pins,
  browser `groups`, `@browser` prompt, version-citation fixes)
- Docs: [`docs/opencode-well-known.md`](../opencode-well-known.md) (the *how*:
  plugin list, agent/tool table)
- Upstream: [vymalo/opencode-oauth2 CHANGELOG](https://github.com/vymalo/opencode-oauth2/blob/main/CHANGELOG.md)
  (0.8.0 — `browser_request_feedback`, #49/#50/#51)
- Builds on / refines: [0048](./0048-global-browser-plugin-and-per-agent-tool-injection.md)
  (the global browser plugin, per-agent injection, and group registration);
  [0044](./0044-opencode-role-subagents-and-permission-scoped-tools.md),
  [0042](./0042-opencode-wellknown-mcp-catalog.md),
  [0014](./0014-split-librechart-and-opencode-wellknown.md)
