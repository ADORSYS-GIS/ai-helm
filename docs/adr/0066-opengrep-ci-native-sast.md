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

We already run **in-cluster self-hosted GitHub Actions runners**, and they
already authenticate to the AI gateway with their **raw GitHub Actions OIDC
token** (ADR-0047/0049 — `lightbridge-repo-auth` only binds org→account; it is
read-only `metadata:read` and mints **no** GitHub write token). So the runner
*compute* for "the runner posts the check" exists today; the GitHub **write**
credential for posting feedback is a separate concern (see Decision), and the
repo already has a precedent for it — the opencode review workflow posts as
`github-actions[bot]` via the workflow `GITHUB_TOKEN`.

## Decision

**Adopt [opengrep](https://github.com/opengrep/opengrep) as a CI-native, rules-as-code
SAST scanner — no server, no database, no license.** opengrep is an open-source
fork of Semgrep (kept OSS after Semgrep relicensed). It runs as a **CLI step inside
the existing in-cluster runners**:

- Scan in the pipeline; emit **SARIF**.
- The **runner** turns results into GitHub PR feedback (a check-run / PR
  annotations and/or a SARIF code-scanning upload), posting with the workflow
  **`GITHUB_TOKEN`** — exactly how the existing opencode review workflow posts as
  `github-actions[bot]` (`permissions: pull-requests: write`, …) — or, for SARIF
  upload, the `security-events: write` scope (or a dedicated write-scoped App).
  **Not** the read-only `lightbridge-repo-auth` App. Same "runner decorates the
  PR" shape we'd weighed for SonarQube, but with **nothing** running server-side.
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
- **Output path & write credential** — GitHub code-scanning via SARIF upload
  (needs `security-events: write`) vs an inline check-run/comment via the workflow
  `GITHUB_TOKEN` (`pull-requests` / `checks: write`). If a dedicated write-scoped
  GitHub App is ever chosen over `GITHUB_TOKEN`, scope it least-privilege
  (`checks:write` / `pull-requests:write` only, installation restricted to the
  scanned repos) — mirroring ADR-0047's blast-radius discipline; do **not** widen
  the read-only `lightbridge-repo-auth` App for this.
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
- Builds on: [0047](./0047-github-oidc-repo-binding-for-ci.md) / [0049](./0049-source-claim-operator-cli-not-self-serve.md) — the in-cluster runner + GHA-OIDC **gateway-auth** infra those ADRs established. ⚠️ That path is *gateway* auth (read-only App); **PR-feedback posting uses the workflow `GITHUB_TOKEN`**, as the opencode review workflow does — not a `lightbridge-repo-auth`-minted token.
- Follow-up: a design/runbook doc once the rule home + gating + output path are settled.
