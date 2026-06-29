# ADR-0072: No-key local MCP batch (git, drawio, shadcn, reddit, youtube, rss) + subagents

**Status:** Accepted
**Date:** 2026-06-29
**Deciders:** @stephane-segning

## Context

ADR-0071 added the first batch of `type: local` (`npx`) MCP servers to the
opencode well-known and established the pattern: each local server is connected,
denied on the lean primary, and re-allowed only on a dedicated subagent. A
follow-up research pass (developers / marketing / product personas, verified
against the live npm registry on 2026-06-29) surfaced a larger field of
npm-only candidates. The decisive constraint for an org-wide push is that these
servers run on the **user's own laptop**, so any required token must come from
that user's shell env (`{env:VAR}`) — not our cluster ESO. That cleanly
separates *no-key / no-signup* servers (work for everyone on day one) from
token-gated ones (spawn fine but fail until the user sets an env var) and
paid-key ones (strict opt-in). This ADR ships the **no-key** subset first.

## Decision

Add six no-key `type: local` servers (bare `npx`, no API key / token / signup),
each gated behind a new `mode: subagent` (deny-baseline off the primary, allow
only on its subagent), following the ADR-0071/0044/0048 model:

- **`git`** → `@cyanheads/git-mcp-server` — local git on the working tree
  (status/diff/log/commit/branch/stash); shells to the `git` binary. Fills the
  gap left by the **deprecated** official GitHub npm server. → **`@vcs`**.
- **`drawio`** → `@drawio/mcp` (official) — generates editable diagrams
  (Mermaid/CSV/XML + editor URL); pure node, no browser binary, no token. →
  **`@diagram`**.
- **`shadcn`** → `@jpisnice/shadcn-ui-mcp-server` — shadcn/ui v4 component
  source/usage/install metadata; keyless (a user's own
  `GITHUB_PERSONAL_ACCESS_TOKEN` lifts the rate limit, **not** injected by us to
  avoid empty-string passthrough). → **`@ui`**.
- **`reddit`** → `reddit-mcp-server` — anonymous read mode, no credentials. →
  **`@content`**.
- **`youtube`** → `@sinco-lab/mcp-youtube-transcript` — transcripts, no key. →
  **`@content`**.
- **`rss`** → `rss-mcp` — RSS/Atom feeds, no key. → **`@content`**.

Four new subagents: `@vcs` (git), `@ui` (shadcn), `@diagram` (drawio), and
`@content` (reddit + youtube + rss + webfetch — one marketing-research agent for
the three readers). All are non-visual → **no model pin** (inherit the session
model). The primary's prompt gains delegation lines for each. Servers are not
version-pinned (separate processes behind a tool boundary → float like the
remotes, per ADR-0071).

Token-gated servers from the same research (Notion, Figma, Tavily/Exa, Sentry,
21st.dev Magic, the Atlassian npx trackers) are **deferred to opt-in batches**,
and **GitHub / Linear / rich Atlassian** are deferred as **remote gateway
`/mcp` routes** (they are remote-only — not `npx`-able) — see Related.

## Consequences

**Positive**
- Six broadly-useful capabilities across all three personas reach every user
  with **zero setup** — no token, no signup, works on first `opencode`.
- Same two-axis model as before; no new mechanism, and the lean primary's
  context is unchanged (tools inject only on delegation).
- `@vcs` gives structured git without granting the primary general `bash` git.

**Negative**
- Three of the readers (`reddit`/`youtube`/`rss`) are **low-maturity**
  solo-maintainer packages — acceptable for read-only no-key tools, but worth
  re-vetting periodically (and pinning if one breaks).
- `git` shells out to the `git` binary; a user without git on PATH sees `@vcs`
  fail (same accepted local-toolchain trade-off as `@mobile`).
- More subagents (16 total) means more agent *descriptions* in the primary's
  delegation catalog — kept tight; the heavy cost (tool schemas) stays out.

**Neutral / follow-ups**
- Live-validate per-agent injection (the six tool families must NOT reach the
  primary; each subagent must get only its own), as with ADR-0044/0048/0071.
- The token-gated and remote-tracker batches are the next decisions (the
  maintainer's stack is GitHub + Jira/Confluence — both lean remote-route).

## Alternatives considered

- **Ship the token-gated servers (Notion/Figma/etc.) in the same batch** —
  deferred: each needs a per-user env var, real friction for non-coder users;
  better as explicit opt-in batches so a key-less user isn't handed agents that
  silently fail.
- **Add GitHub as a local `npx` server** — impossible: the official
  `@modelcontextprotocol/server-github` npm package is **deprecated**, and the
  replacement `github/github-mcp-server` is a Go binary / remote-hosted server.
  GitHub belongs on a gateway `/mcp` route (ADR-0038/0040), not here.
- **One mega "tools" subagent instead of four** — rejected: distinct
  descriptions make the primary's delegation decisions cleaner, and each
  subagent stays a tight whitelist.
- **A Mermaid-renderer server for diagrams** — rejected: the maintained ones
  (`mcp-mermaid`, `@rtuin/mcp-mermaid-validator`) pull Chromium/Puppeteer on
  first run; `@drawio/mcp` accepts Mermaid syntax with no binary and no key.
- **Playwright `@playwright/mcp`** — rejected here: overlaps the shipped
  `@vymalo/opencode-browser`; only adds a11y-snapshot E2E codegen and downloads
  Chromium.

## Related

- Charts/files touched: `charts/librechat-opencode-wellknown/values.yaml`
- Docs: `docs/opencode-well-known.md` (the *how*)
- Builds on: ADR-0071 (the first local npx batch + the pattern), ADR-0044
  (role subagents + permission-scoped tools), ADR-0048 (lean primary + per-agent
  injection), ADR-0042 (MCP catalog), ADR-0038/0040 (the remote `/mcp` route +
  proxied-external pattern the deferred GitHub/Atlassian routes will use).
- Follow-ups: token-gated opt-in batch (Notion/Figma/search/…); GitHub +
  Jira/Confluence as remote gateway `/mcp` routes.
