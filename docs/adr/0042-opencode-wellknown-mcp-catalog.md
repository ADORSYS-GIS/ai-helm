# ADR-0042: Ship a curated MCP catalog in the opencode `.well-known`

**Status:** Accepted
**Date:** 2026-06-12
**Deciders:** @stephane-segning
**Relates to:** [ADR-0014](0014-split-librechart-and-opencode-wellknown.md) (the well-known descriptor this extends), [ADR-0038](0038-mcp-oauth-protected-resource-metadata.md) (the `/mcp/*` gateway routes + OAuth these point at)

## Context

The opencode `.well-known/opencode` descriptor (ADR-0014) already pushes a
shared `config` to every user who runs `opencode auth login
https://ai.camer.digital/opencode` — the Keycloak provider, the OAuth2 /
models-info / ratelimit / DCP / skills plugins. opencode merges that `config`
*under* each user's own, so it is the natural place for org-wide defaults.

Until now MCP servers were **not** part of it: each user had to hand-configure
the gateway's `/mcp/<name>` routes (ADR-0038) in their local `opencode.json`,
copying the URL, the `opencode-cli` OAuth client, and the scopes for every
server. That is error-prone, drifts per user, and means a new MCP backend (or a
URL change) never reaches anyone automatically.

The maintainer — who is also the platform's **AI Advocate** — wants every user
to get **one curated, unified MCP experience** by default, including a
consistent Chrome DevTools tool, without each person reinventing the config.

opencode supports MCP servers natively under the config `mcp` key: `type:
local` (a `command` run on the user's machine) or `type: remote` (a `url`, with
a native `oauth` block), and an `enabled` flag. A server shipped with `enabled:
false` is *present but off* — a user opts in locally with `enabled: true`.

## Decision

Add an **`mcp` block to the well-known `config`** (`charts/librechat-opencode-wellknown`
`wellKnown.config.mcp`), so the curated catalog is pushed org-wide:

| Server | Type | Source | Default |
|---|---|---|---|
| `brave` | remote | gateway `/mcp/brave` (web search) | **enabled** |
| `context7` | remote | gateway `/mcp/context7` (library docs) | **enabled** |
| `refero` | remote | gateway `/mcp/refero` (design refs) | disabled |
| `firecrawl` | remote | gateway `/mcp/firecrawl` (web scraping) | disabled |
| `terraform` | remote | gateway `/mcp/terraform` (IaC) | disabled |
| `chrome-devtools` | local | `npx -y chrome-devtools-mcp@latest` | disabled |

All remotes target the ADR-0038 routes and authenticate with the **same**
`opencode-cli` Keycloak client (`scope: openid profile offline_access`), so the
`oauth` block is declared once as a YAML anchor (`&mcpOAuth`) and reused — a new
remote is three lines, never a copied credential.

### Default-enablement policy — lean by default, opt-in for the rest

Only the two **broadly-useful, low-friction** servers are on by default:
`brave` (web search) and `context7` (library-docs lookup) help almost any task
and need nothing on the user's machine. The **specialist** remotes
(`refero`/`firecrawl`/`terraform`) are present-but-disabled so the default tool
surface — and the agent's tool-selection space — stays small; a user enables
what their work needs.

`chrome-devtools` is shipped so the unified DevTools experience is *available to
everyone*, but **disabled by default**: it is a `local` server that needs a
real Chrome plus a bun/npx install on the user's box, so forcing it on would
break or surprise users who don't have that set up. Off-by-default makes it a
one-flag opt-in instead of an imposition — the AI-Advocate intent (everyone
*can* have it, uniformly configured) without the cost of forcing it.

## Consequences

- A new gateway MCP backend reaches every user by adding one entry here and
  cutting a release — no per-user config.
- Pushing `enabled: false` is *availability*, not enforcement: a user can flip
  any server on (or a default-on one off) in their own `opencode.json`, which
  opencode merges over the well-known.
- The catalog is only as reachable as the `/mcp/*` routes (ADR-0038/0040/0041);
  a broken backend surfaces as that server failing to connect in the user's
  opencode, not as a well-known error.
- `chrome-devtools-mcp@latest` is unpinned (auto-updates via npx), consistent
  with how the well-known references the opencode plugins.
- The credential is never in the descriptor — only the public `opencode-cli`
  client id; the JWT is minted by the user's own OAuth flow.
