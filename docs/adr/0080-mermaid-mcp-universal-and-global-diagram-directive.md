# ADR-0080: Mermaid MCP available to every agent + a global "explain via diagrams" directive

**Status:** Accepted
**Date:** 2026-07-08
**Deciders:** @stephane-segning

> Amends [ADR-0074](./0074-opencode-opt-in-mcps-and-multi-primary-fleet.md) for
> ONE server: it takes ADR-0074's own follow-up ("if a server proves universally
> useful, graduate it back to `enabled: true` — a deliberate, reviewed flip") and
> exercises it for `mermaid`. The opt-in default and the per-subagent scoping of
> ADR-0074 / [ADR-0044](./0044-opencode-role-subagents-and-permission-scoped-tools.md)
> stay in force for every OTHER server; only `mermaid` is exempted. The
> lean-context finding of [ADR-0048](./0048-global-browser-plugin-and-per-agent-tool-injection.md)
> is respected, not overturned — see Context.

## Context

Diagram-as-explanation is a cross-cutting output style, not a specialist
capability. When any agent explains architecture, a flow, a sequence, a
relationship, or state, a small Mermaid graph communicates it faster than prose
— and the LibreChat / opencode UIs render a ` ```mermaid ` fenced code block
**client-side**, with no tool call at all. So the value we want ("agents draw
graphs to explain things to the user") is fundamentally a *prompt* concern that
every agent shares, not a tool one agent owns.

Two facts shape the mechanism:

1. **opencode has no top-level inline system prompt.** The config schema exposes
   a per-agent `prompt` and a global `instructions` field, but `instructions`
   takes **file paths only** — and the org-wide config ships as a merged JSON
   blob served at `.well-known/opencode` (ADR-0042), which cannot deliver a file
   to the user's machine. So a directive that must reach *every* agent has to be
   written into *every* agent's `prompt`.
2. **The Mermaid MCP schema is tiny** (a single generate/render tool), unlike the
   34-tool browser surface ADR-0048 deliberately keeps scoped to `@browser`. The
   lean-context concern that motivated the deny-baseline is about *heavy* tool
   sets loaded on every turn; a one-tool server org-wide costs almost nothing.

The server is `mcp-mermaid` (`npx -y mcp-mermaid`, `type: local`, stdio). It
renders via `mermaid-isomorphic` + **playwright**, so turning a diagram into a
PNG/SVG *image* needs a local chromium — the same accepted trade-off as
`@vymalo/opencode-browser` and `@mobile` (a user without it sees the render tool
fail, not the whole agent). The always-works path — emitting a ` ```mermaid `
fenced block the UI renders — needs nothing.

## Decision

In `charts/librechat-opencode-wellknown/values.yaml`:

1. **Add the `mermaid` MCP server, `enabled: true`** — the one server on by
   default after ADR-0074 flipped the other 16 to opt-in.
2. **Do NOT add `mermaid_*` to the permission deny-baseline.** Every other MCP
   is denied at the root and re-allowed only on its subagent; `mermaid` is
   deliberately left undenied, so opencode injects its tool into **every primary
   AND every subagent** (tools default to enabled unless a rule restricts them).
   An in-file comment marks the omission as intentional so a future editor does
   not "fix" it by adding a deny.
3. **Append one identical Mermaid directive to all 27 agent prompts** (11
   primaries + 16 subagents): when a diagram would make something clearer for the
   user, explain it with a ` ```mermaid ` fenced block (the UI renders it live)
   instead of prose alone, and use the `mermaid_*` tool to validate/render to a
   shareable image when that helps. This is the only mechanism that reaches every
   agent given fact (1) above.

## Consequences

- Every agent — whichever primary a user picks, and every delegated subagent —
  now defaults to explaining visually, and every agent can call the Mermaid tool
  without an opt-in flip.
- The lean-context contract holds for the *heavy* servers (browser, mobile,
  atlassian, …): they stay opt-in and subagent-scoped. Only the one-tool Mermaid
  server is universal, by explicit exception.
- Image *rendering* needs local chromium (playwright); a user without it still
  gets client-side fenced-block rendering, which covers the stated goal.
- The directive is duplicated across 27 prompts (opencode offers no single
  point). It was applied by a guarded script that asserts each anchor matches
  exactly once, so the copies are byte-identical; changing the wording means
  re-running that pass, not editing 27 blocks by hand.

## Alternatives considered

- **Scope Mermaid behind a `@diagram` subagent (the ADR-0044 default).** Rejected
  for this server: `@diagram` already exists (draw.io) for *building an editable
  diagram deliverable*; the goal here is the opposite — every agent inlining a
  quick explanatory graph in its own answer, which a delegated subagent can't do
  without a round-trip. Universal availability is the point.
- **Ship the directive via `instructions`.** Rejected — `instructions` takes file
  paths, and a well-known config merge can't place a file on the user's machine.
- **Keep Mermaid opt-in like everything else.** Rejected — the maintainer's
  intent is that diagram-explanation is on for everyone by default; an opt-in
  server nobody enables delivers none of that.
- **A global inline prompt field.** Not available — opencode's schema has no
  top-level `prompt`; per-agent `prompt` is the only string carrier.
