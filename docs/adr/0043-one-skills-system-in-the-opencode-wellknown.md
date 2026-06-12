# ADR-0043: One skills system in the opencode well-known — decline `superpowers`

**Status:** Accepted
**Date:** 2026-06-12
**Deciders:** @stephane-segning
**Relates to:** [ADR-0042](0042-opencode-wellknown-mcp-catalog.md) and [ADR-0014](0014-split-librechart-and-opencode-wellknown.md) (the org-wide opencode `.well-known` this governs)

## Context

The opencode `.well-known` `config.plugin` array (ADR-0014) is pushed to **every**
user via `opencode auth login` and opencode auto-installs each entry — so it is
org-wide policy, not personal config. It already carries
**`opencode-skills-collection@latest`**, a curated 1000+ skill catalog behind a
token-efficient "SkillPointer" loader, as our skills system.

We were asked to evaluate adding **[obra/superpowers](https://github.com/obra/superpowers)**
(`superpowers@git+https://github.com/obra/superpowers.git`, latest `v5.1.0`) — a
zero-config, multi-model plugin providing ~13 curated methodology skills (TDD,
systematic-debugging, brainstorming, writing/executing-plans, code review,
git-worktrees, subagent-driven-dev) plus a per-conversation system-prompt bootstrap
injected via `experimental.chat.system.transform`.

On investigation, **superpowers plays the same role as `opencode-skills-collection`** —
both are *skills systems*: each registers a skills directory and injects context.
Two facts make stacking them a poor fit for an org-wide push:

- **Plugins have no per-user `enabled` flag** (unlike the ADR-0042 MCP servers, which
  ship `enabled: false` for opt-in). A plugin added here is **mandatory-on for every
  user, no opt-out** — and superpowers actively *steers* the agent (a brainstorm →
  plan → TDD methodology), so it would impose a workflow on everyone.
- Running two skills systems means **two skill catalogs + two system-prompt
  injections** every conversation (a token cost we otherwise work to reduce — see the
  DCP plugin), plus likely **duplicate skills** (a broad aggregator such as
  skills-collection may already bundle obra's skills).

## Decision

**Do not add `superpowers` to the well-known.** Keep `opencode-skills-collection`
as the **single skills system** in the org-wide config.

General principle: **run one skills system at a time in the well-known, and don't
stack plugins whose roles overlap.** Because pushed plugins are mandatory-on,
overlapping-role plugins double the cost and the imposition on every user. Before
adding any plugin here, check it doesn't duplicate an existing one's role.

## Consequences

- No change to the chart or the live descriptor (`release-2026.06.12-v03` stands);
  this ADR records a decision, not a deployment.
- If superpowers is wanted later, the right move is a **swap** (superpowers
  *replacing* skills-collection — leaner, pinnable to a release tag like `#v5.1.0`,
  a single coherent methodology) rather than running both. That would be a new ADR
  superseding this one's "keep skills-collection" stance.
- This generalizes the ADR-0042 org-push filter (no other-provider auth, no
  third-party telemetry, no no-op-without-local-config plugins) with a role-overlap
  guard.
- Individual users who specifically want superpowers can still add it to their own
  local `opencode.json` (opencode merges it over the well-known); we simply don't
  impose it platform-wide.
