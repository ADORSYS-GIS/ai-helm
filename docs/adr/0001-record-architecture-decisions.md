# ADR-0001: Record architecture decisions in this repo

**Status:** Accepted
**Date:** 2026-05-24
**Deciders:** repo maintainers via `claude/magical-bohr-390242`

## Context

This repo has grown into a substantial GitOps definition for a multi-tenant
LLM platform — ~20 Helm charts, ~35 ArgoCD apps, custom Authorino policies,
an envoy AI gateway, a multi-backend observability stack. Decisions are
being made (and reversed) at a pace where the only record is `git log` and
free-form notes scattered across `docs/`, `MONITORING_FIX.md`,
`SYNC_WAVE_PATTERN.md`, and PR descriptions.

This produces three problems:
1. Why-questions ("why did we drop Phoenix?", "why is OPA skipped for SAs?")
   require archeology across commits, docs, and PR comments.
2. People making future changes don't see what was considered and rejected,
   so options re-litigate themselves.
3. There is no place where a new contributor can read the dozen highest-
   leverage choices and understand the shape of the system.

## Decision

Adopt Architecture Decision Records (Michael Nygard format) under
`docs/adr/`. Every meaningful architectural choice gets an immutable,
dated record with Context / Decision / Consequences / Alternatives. The
README in that directory is the index; `template.md` is the starting point.

Scope is deliberately narrow: ADRs cover choices that have non-obvious
consequences a year out. Routine bumps, bug fixes, and chart-level cleanups
do not need one — `git log` is enough for those.

## Consequences

**Positive**
- One place to find why-answers. Onboarding accelerates.
- Future debates have a clear thing to argue against (prior ADR), not a vague
  intuition.
- The "Alternatives considered" section forces explicit trade-off thinking
  at decision time.

**Negative**
- One more thing to remember to write. Mitigated by keeping ADRs short
  (~1–2 pages) and only writing them when scope rises above the bar.
- Immutability means the index must reflect supersession carefully — a
  poorly-linked chain is worse than no ADRs.

**Neutral / follow-ups**
- Backfill ADRs for the high-impact decisions made in this session
  (ADR-0002 through ADR-0005 cover already-implemented; ADR-0006 through
  ADR-0008 cover proposed work).
- Consider a CI hook that fails the build if a PR touching certain paths
  (e.g. `charts/apps/values.yaml` syncPolicy defaults, security policy
  templates) lacks a referenced ADR. Not blocking; track as a follow-up.

## Alternatives considered

- **PR descriptions / commit messages as the record** — what we did until
  now. Doesn't survive squashes or branch deletions, isn't indexable, and
  diffuses across hundreds of commits. Rejected.
- **Wiki / Notion / external doc site** — adds infra and an authentication
  surface, and decouples decisions from the code they govern. The repo is
  already the source of truth for everything else; ADRs belong here too.
- **RFC-style longer docs** — heavier-weight, more useful for proposals
  spanning weeks. We may use both: RFCs for in-flight design work, ADRs
  for the eventual recorded decision. Not adopting RFC structure today —
  no live proposal needs it.

## Related

- Docs: `docs/adr/README.md` (index + status legend + how to write one),
  `docs/adr/template.md` (copy this to start a new ADR)
- Commit: this commit
