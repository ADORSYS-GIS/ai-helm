# ADR-0066: Adopt opengrep for CI-native SAST instead of a code-quality server

**Status:** Proposed
**Date:** 2026-06-27
**Deciders:** @stephane-segning

## Context

We want static analysis with pull-request feedback on our repos. The first
attempt ([ADR-0065](./0065-sonarqube-community-build-with-branch-plugin.md))
proposed self-hosting **SonarQube Community Build**, but the architecture team
**rejected** it as a "dinosaur" solution: a stateful, heavyweight platform (a
long-running JVM server + a PostgreSQL database + an embedded Elasticsearch + a
node `vm.max_map_count` sysctl) whose *free* tier can't even decorate PRs without
an unofficial, version-lockstep third-party plugin. That's a large, brittle,
manually-pinned footprint for what is fundamentally CI-time static analysis.

We already run **in-cluster self-hosted GitHub Actions runners**, and we already
mint GitHub App installation tokens in CI via `lightbridge-repo-auth` (GHA OIDC →
token, ADR-0047/0049). So the cheap, stateless half of the SonarQube alternative
("the runner posts the check") is infrastructure we have today.

## Decision

**Adopt [opengrep](https://github.com/opengrep/opengrep) as a CI-native, rules-as-code
SAST scanner — no server, no database, no license.** opengrep is an open-source
fork of Semgrep (kept OSS after Semgrep relicensed). It runs as a **CLI step inside
the existing in-cluster runners**:

- Scan in the pipeline; emit **SARIF**.
- The **runner** turns results into GitHub PR feedback (code-scanning upload
  and/or a check-run/annotations), authenticating with the GitHub App token
  `lightbridge-repo-auth` already mints — the same "runner decorates the PR" shape
  we'd weighed for SonarQube, but with **nothing** running server-side.
- **Rules are versioned code** (a ruleset in-repo or a shared rules repo), not
  state in a Postgres box.

This is a GitOps/CI concern, not a deployed workload — there is **no chart, no
namespace, no CNPG, no Keycloak client, no `ai-helm-values` entry**. ai-helm's
involvement is limited to the CI workflow/wiring (and this ADR).

## Consequences

**Positive**
- Zero stateful infra, zero license, zero plugin version-lockstep. Nothing to keep
  off argocd-image-updater; nothing to back up.
- Runs where CI already runs; reuses the `lightbridge-repo-auth` GitHub-token path.
- Findings are reviewable, versioned rules — diffable, PR-able, portable.

**Negative**
- opengrep is **rule-matching SAST only**, not a code-quality *platform*: no
  historical trend dashboards, coverage tracking, quality-gate-over-time, or a
  security-hotspot management UI. If the team later wants those, that's a separate
  decision (and not a reason to resurrect SonarQube by default).
- **Rule curation becomes our responsibility** — pick/maintain rulesets, tune
  noise, own false positives.
- opengrep is a **young fork** (post-2024 Semgrep relicense); track its maturity
  and rule-ecosystem compatibility.

**Neutral / open decisions (to settle before/with implementation)**
- **Rule home** — per-repo rulesets vs a central rules repo consumed by all.
- **Gating** — advisory (annotate only) vs blocking (fail the check), and at what
  severity threshold.
- **Output path** — GitHub code-scanning via SARIF upload (needs the
  `security-events: write` permission) vs an inline check-run/comment posted with
  the runner's GitHub App token.
- **Scope** — which repos onboard first.

## Alternatives considered

- **SonarQube Community Build + community-branch-plugin** (ADR-0065) — rejected: a
  heavyweight, stateful "dinosaur" needing an unofficial version-lockstep plugin
  for the one feature we wanted. See ADR-0065.
- **Semgrep (upstream)** — rejected: the relicense moved key capability behind
  commercial gating; opengrep forked specifically to keep it OSS.
- **GitHub CodeQL** — rejected (for now): powerful but heavier to author rules for
  and oriented around GitHub Advanced Security; opengrep's rules-as-code +
  runner-native model is a closer fit to how we already run CI.

## Related

- Relates to (reverses the direction of): [0065](./0065-sonarqube-community-build-with-branch-plugin.md) (Rejected).
- Builds on: [0047](./0047-github-oidc-repo-binding-for-ci.md) / [0049](./0049-source-claim-operator-cli-not-self-serve.md) (the `lightbridge-repo-auth` GitHub-token path the runner uses to post PR feedback).
- Follow-up: a design/runbook doc once the rule home + gating + output path are settled.
