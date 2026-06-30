# ADR-0073: Issue-tracker MCPs — Jira/Confluence per-user local npx; GitHub via centralized GitHub-App gateway route

**Status:** Accepted
**Date:** 2026-06-29
**Deciders:** @stephane-segning

> **Amended by [ADR-0074](./0074-opencode-opt-in-mcps-and-multi-primary-fleet.md) (2026-06-30):** the Jira/Confluence local servers added in phase 1 now ship `enabled: false` — MCPs are opt-in org-wide. The catalogue entries, deny-baseline, and the `@atlassian` subagent below are unchanged; only the default connectivity flips. (Phase 2 GitHub gateway route is unaffected.) Body below is immutable.

## Context

The persona research behind ADR-0072 confirmed the maintainer's tracker stack
is **GitHub** + **Jira/Confluence**, and that these are the highest-value
product/PM integrations. Unlike the local batches, the tracker servers do not
share one runtime story:

- **Jira/Confluence** have clean `npx` servers (`@aashari/mcp-server-atlassian-*`)
  authenticated by a single Atlassian API token.
- **GitHub** has **no** viable `npx` server — the official
  `@modelcontextprotocol/server-github` npm package is **deprecated**, and the
  replacement `github/github-mcp-server` is a Go binary / remote-hosted server.

Two auth/identity models were weighed: a **centralized** in-cluster server +
gateway `/mcp` route (one shared credential, users authenticate with their
Keycloak JWT, zero per-user setup) vs **per-user local** `npx` (each user
supplies their own token, preserving per-user identity). The maintainer chose a
**hybrid**: per-user local for Atlassian, and — because GitHub can't be local —
a **GitHub App** (which only fits the centralized route) for GitHub.

## Decision

**Phase 1 (this commit) — Jira/Confluence as per-user local `npx`.** Add `jira`
(`@aashari/mcp-server-atlassian-jira`) and `confluence`
(`@aashari/mcp-server-atlassian-confluence`) as `type: local` servers, both
reading the user's own credentials via `{env:...}` passthrough — the two servers
share the **same** three vars so a user sets them once:
`ATLASSIAN_SITE_NAME`, `ATLASSIAN_USER_EMAIL`, `ATLASSIAN_API_TOKEN`. Both are
denied on the lean primary and re-allowed only on a new **`@atlassian`**
subagent (read/search-first; no edit/bash; no model pin). A user without the env
vars sees `@atlassian` fail when invoked — the same accepted local-toolchain
trade-off as `@mobile`/`@vcs`.

**Phase 2 (planned, follow-up) — GitHub via centralized GitHub-App gateway
route.** Self-host `github/github-mcp-server` (Go container) in-cluster as an
HTTP MCP backend (the way `terraform` is self-hosted), expose it as an AIEG
`MCPRoute` `/mcp/github` with route-level `SecurityPolicy.oauth` (ADR-0038), and
add a `github` **remote** entry to the well-known behind a `@github` subagent.
The service authenticates to GitHub as an **org-installed GitHub App**
(fine-grained, rotating installation tokens) — credential provisioned **out of
band** in `ssegning-aws` and surfaced via an ExternalSecret in the
`ai-helm-values` deps overlay, **values-repo-first**. All gateway users act as
the single App identity (acceptable for read; write attribution is shared —
revisit with a read-only App scope if that matters).

## Consequences

**Positive**
- Atlassian ships immediately with zero cluster/secret work — pure well-known
  config, no cross-repo dependency.
- GitHub's centralized route removes per-user-token friction entirely (right for
  non-coder POs) and reuses the proven gateway `/mcp` + Keycloak-JWT pattern.
- One `@atlassian` subagent covers both Jira and Confluence (shared creds).

**Negative**
- Per-user Atlassian setup is real friction for non-coders (three env vars);
  accepted as the maintainer's explicit choice to keep Atlassian identity
  per-user.
- The GitHub App route is a multi-file, cross-repo effort with hard out-of-band
  prerequisites (create + install the App; mint/rotate installation tokens;
  provision the secret) — it cannot land until those exist.
- GitHub-App installation tokens expire hourly; the self-hosted server needs a
  PAT-style token or a token-refresher sidecar — to be settled in phase 2.
- Shared GitHub identity loses per-user write attribution through the gateway.

**Neutral / follow-ups**
- Phase 2 prerequisites (do these first, values-repo-first): (1) create an
  org GitHub App with the needed fine-grained repo/issues/projects scopes and
  install it; (2) put its credentials in `ssegning-aws`; (3) add the in-cluster
  server chart + AIEG route here and the deps/values in `ai-helm-values`.
- Live-validate the `{env:...}` passthrough behaviour for `jira`/`confluence`
  (and `memory`) — confirm opencode merges the declared `environment` over the
  inherited process env (so `npx`/PATH still resolve).
- Per-agent injection check as with ADR-0044/0048/0071/0072.

## Alternatives considered

- **GitHub as per-user local** — impossible cleanly: no maintained `npx` server;
  the Go binary is `docker`/binary, not viable for non-coder org-wide push.
- **Atlassian via the centralized gateway route too** — rejected by the
  maintainer for Atlassian: the official Atlassian server is remote-only OAuth
  2.1 (hard to proxy with a static token), and per-user identity was preferred
  there; the `@aashari` npx servers give a clean single-token local path.
- **Atlassian official remote server** — richer toolset but remote-only OAuth;
  deferred in favour of the simpler per-user npx servers.
- **GitHub org PAT instead of a GitHub App** — rejected: a PAT is tied to one
  account, coarser-grained, and manually rotated; an App is the correct org-wide
  identity.

## Related

- Charts/files touched (phase 1): `charts/librechat-opencode-wellknown/values.yaml`
- Docs: `docs/opencode-well-known.md`
- Builds on: ADR-0071/0072 (local npx batches + the subagent pattern), ADR-0044
  (role subagents), ADR-0048 (lean primary). Phase 2 uses ADR-0038 (MCP OAuth
  route) + ADR-0040 (external-MCP in-cluster proxy/self-host pattern).
- Follow-up: phase 2 GitHub-App gateway route (own commit once the App + secret
  exist).
