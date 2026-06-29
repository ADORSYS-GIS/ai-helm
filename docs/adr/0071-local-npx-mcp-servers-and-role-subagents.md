# ADR-0071: Local npx MCP servers (memory, sequential-thinking, mobile) + their role subagents

**Status:** Accepted
**Date:** 2026-06-29
**Deciders:** @stephane-segning

## Context

Every MCP server in the opencode well-known so far is a `type: remote` server
reached through the gateway's `/mcp/*` routes (ADR-0038/0042) — brave, context7,
refero, firecrawl, terraform. The maintainer wants to add a batch of additional
servers that are distributed as plain Node packages and meant to run on the
**user's own machine**: `@mobilenext/mobile-mcp` (mobile-next), the official
`@modelcontextprotocol/server-memory` (knowledge-graph) with a custom
`MEMORY_FILE_PATH`, and `@modelcontextprotocol/server-sequential-thinking`.
Several other requested servers — `mem0` and `MCP-Mathematics` (Python, `uvx`)
and `pdfmux` (an npm wrapper that still requires `pip install pdfmux` + an LLM
API key) — are Python-backed and were explicitly deferred ("observe the python
plugins then"). The standing org-push policy (ADR-0042/0044/0048) is *lean by
default*: a global deny-baseline keeps the primary agent free of MCP tool
schemas, and each connected server lives behind a dedicated `mode: subagent`
whitelist.

## Decision

Add the three **npm-only** servers as `type: local` MCP entries (opencode spawns
each via `npx` over stdio) and gate each behind a new role subagent, following
the ADR-0044/0048 deny-then-re-allow discipline:

- **`memory`** → `npx -y @modelcontextprotocol/server-memory`, with
  `environment.MEMORY_FILE_PATH = {env:HOME}/.local/share/opencode/memory.json`
  (opencode's **data** dir, where `auth.json` is written on `opencode auth
  login` — so it reliably exists before the first write; NOT `~/.config/opencode`,
  the optional global-config dir a login-only user may lack). Scoped to the new
  **`@memory`** subagent (read/write the graph only; no edit/bash; no model pin).
- **`sequentialthinking`** → `npx -y @modelcontextprotocol/server-sequential-thinking`.
  Scoped to the new **`@planner`** subagent (read-only deep-reasoning; also
  allowed context7 for facts; no edit/bash; no model pin).
- **`mobile`** → `npx -y @mobilenext/mobile-mcp@latest`. Scoped to the new
  **`@mobile`** subagent. Because its tools return device screenshots the agent
  must interpret, it **pins the multimodal `camer-digital/adorsys-frontend`**
  alias — the same no-risk vision rule ADR-0048 applies to `@browser`/`@design`.

All three are added to the global `permission` deny-baseline
(`memory_*`/`sequentialthinking_*`/`mobile_*` → `deny`) so the lean `frontend`
primary never carries their schemas; the primary's prompt gains explicit
delegation lines for `@mobile`/`@planner`/`@memory`. Local servers are **not**
version-pinned (unlike the in-process `plugin:` list): they're separate
processes behind a tool-protocol boundary, so they float to `@latest` like the
remotes; pin a `name@x.y.z` later only if drift bites.

## Consequences

**Positive**
- Three broadly-useful capabilities (persistent memory, structured reasoning,
  mobile automation) reach every user without enlarging the default agent's
  context — they're injected only when the primary delegates to the matching
  subagent.
- Consistent with the existing two-axis model (connectivity via `enabled`,
  access via per-agent `permission`) — no new mechanism, just three more rows.
- The local/stdio form is the right one for client-side capabilities: nothing
  to route through the gateway, no OAuth anchor, no remote rate-limit bucket.

**Negative**
- Local servers need the user's toolchain: `npx` (Node) for all three, plus
  Xcode CLT / Android platform-tools + a running simulator/emulator for
  `@mobile`. A user without it just sees the tool fail to spawn — the same
  accepted trade-off as the `@vymalo/opencode-browser` bridge.
- Floating (`@latest`) trades reproducibility for zero-maintenance; a breaking
  upstream release could change behaviour under us. Mitigated by the
  tool-protocol boundary and the option to pin.
- The memory graph is global per user (cross-project); a single muddled graph is
  possible. Chosen over a package-relative per-project file to avoid writing
  into repos and to guarantee a writable path.

**Neutral / follow-ups**
- The Python-backed batch (mem0, MCP-Mathematics, pdfmux) is deferred to a later
  ADR once a packaging decision is made (uvx vs. a sidecar) — they are
  intentionally NOT added as local npx servers here.
- Live-validate per-agent injection (the primary should not receive
  `memory_*`/`sequentialthinking_*`/`mobile_*`; each subagent should) the same
  way ADR-0044/0048 are validated.

## Alternatives considered

- **Add the servers but allow them on the primary** — rejected: violates the
  lean-primary policy (ADR-0044/0048); the memory + mobile tool sets are large
  and would bloat every default turn's context.
- **Make `sequentialthinking` a tool allowed broadly across existing subagents**
  instead of a dedicated `@planner` — rejected for now: a single delegation target
  keeps it off every other context and matches the "delegate tool-heavy work"
  shape; it can be additionally allowed on reasoning-heavy roles later if useful.
- **Include pdfmux in this npm batch** (the maintainer specifically wants PDF
  support) — rejected: its `pdfmux-mcp` npm package is only a wrapper and still
  requires `pip install pdfmux` (Python 3.11+) plus an LLM API key, so it is
  Python-backed in practice and belongs in the deferred batch, not as a bare
  `npx` local server.
- **Version-pin the local servers like the plugins** — rejected: plugins run
  in-process (higher trust → pinned); MCP servers are isolated processes, so
  floating matches the remotes and avoids manual bump toil.

## Related

- Charts/files touched: `charts/librechat-opencode-wellknown/values.yaml`
- Docs: `docs/opencode-well-known.md` (the *how*)
- Builds on: ADR-0042 (MCP catalog), ADR-0044 (role subagents + permission-scoped
  tools), ADR-0048 (lean primary + per-agent injection + no-risk multimodal pin),
  ADR-0038 (the remote `/mcp/*` form these local servers sit alongside).
