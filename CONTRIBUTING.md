# Contributing to `ai-helm`

> **TL;DR:** branch from `main` → commit conventional → open a PR →
> CI passes → @stephane-segning reviews → merge. Non-trivial choices
> get an ADR (see below).

## Setting up locally

```bash
git clone git@github.com:ADORSYS-GIS/ai-helm.git
cd ai-helm
```

You need:
- **helm** v3.15+ (until we migrate to Helm 4 — see the 2026 audit
  punch-list item).
- **kubectl** for cluster work; not required for chart development.
- **uv** + **ruff** if you touch `tools/dashboards/` or any Python.
- **zsh** if you follow the team's local-shell convention (not required;
  the repo's scripts are POSIX-portable).

## Branches

- `main` is the only long-lived branch. Protected; no direct pushes.
- Feature branches: `<topic>/<short-name>` or `<gh-issue-id>-<topic>`
  (e.g. `feat/multi-source-appset` or `293-cnpg-backup-rollback`).
- Branches are short-lived. Open a PR within a day of starting work
  even if it's draft — that's where review conversation happens.

## Commit messages

**[Conventional Commits](https://www.conventionalcommits.org/), enforced.** The
full spec — every type, what it does to release-please/version bumps, scope rules,
breaking changes, and the enforcement — lives in
[`docs/commit-conventions.md`](docs/commit-conventions.md). The short version:

```
<type>[optional scope][!]: <description>
```

| Type | When to use | release-please effect |
|---|---|---|
| `feat(scope):` | New user-facing behavior (a new chart, dashboard, endpoint) | chart **MINOR** bump |
| `fix(scope):` | Bug fix | patch (cosmetic — publish derives the deployed patch) |
| `docs(scope):` / `refactor` / `perf` / `revert` | Docs-only / restructure / perf / revert | changelog only |
| `chore` / `ci` / `build` / `test` / `style` | Maintenance, CI, deps, tests, formatting | none (hidden) |
| any `!` or `BREAKING CHANGE:` footer | Breaks consumers | **MAJOR** (pre-1.0 chart: minor) |

- **Scope = the chart directory name** for chart changes (`feat(core-gateway): …`);
  attribution is by file path, so a commit touching `charts/<x>/**` versions `<x>`.
- **Body: explain *why*** (the diff shows what). Link the ADR: `(ADR-NNNN)`. 20–60
  line bodies are common for non-trivial changes.
- **Because we squash-merge, the PR title must also be a valid Conventional Commit**
  — it’s what lands on `main` and feeds release-please.

Co-author trailer for AI-assisted commits (running model version):

```
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

**Enforcement** (details in the doc): a local `commit-msg` hook rejects bad
messages at `git commit` — enable once with `git config core.hooksPath .githooks` —
and the `Commit Lint` CI gate validates the PR title + every commit on each PR.
Both call the same validator, [`tools/commit-lint.sh`](tools/commit-lint.sh).

## Architecture Decision Records (ADRs)

Anything non-obvious gets an ADR. See
[`docs/adr/README.md`](docs/adr/README.md) for what counts as
"non-obvious" and how to write one.

Process:
1. Copy [`docs/adr/template.md`](docs/adr/template.md) to
   `docs/adr/NNNN-short-imperative-title.md` (next free number,
   zero-padded to 4).
2. Status starts as `Proposed`. Move to `Accepted` when the
   implementation lands.
3. ADRs are **immutable once Accepted**. To change a decision, write
   a new ADR that supersedes the old one. Add `Status: Superseded by
   ADR-NNNN` to the old one's header with a short note explaining the
   change; preserve the body as historical record.
4. Update [`docs/adr/README.md`](docs/adr/README.md) index.

## Helm chart conventions

### Naming
- Chart directory and `Chart.yaml` `name:` must match. Audit-flagged
  drift exists in older charts; align when touching.
- First-party charts use kebab-case names (`librechat-app`, not
  `librechatApp`).

### Pinning
- **No `:latest`, no `'*'`.** Pin to explicit semver (`v1.20.2`) or
  commit SHA. The 2026 currency audit lists exceptions and the path
  to fix them.
- Chart-version pins go in `Chart.yaml` `dependencies[*].version`.
- Image tag pins go in the chart's `values.yaml`
  (`image.tag: v1.2.3`).

### Templates
- Use the `common` library for standard labels (`common.labels.standard`)
  and name helpers (`common.names.namespace`).
- Render Service / ConfigMap / Secret names from `{{ .Release.Name }}`
  or `{{ include "common.names.fullname" . }}`; **never** hardcode.
- Required-value guards: use `{{- fail "..." -}}` at the top of the
  template that depends on the value. See
  `charts/ai-model/templates/aigatewayroute.yaml` for a worked example.

### Sync waves
Lower waves first. See [`docs/architecture.md`](docs/architecture.md#sync-waves)
for the conventions and [SYNC_WAVE_PATTERN.md](SYNC_WAVE_PATTERN.md)
for the canonical document.

### The orchestrator-plus-leaves pattern
For charts whose components have different lifecycles (sync waves,
rollback granularity, per-component lifecycle), prefer the pattern
introduced in [ADR-0012](docs/adr/0012-split-ai-models-applicationset.md)
and refined in [ADR-0014](docs/adr/0014-split-librechart-and-opencode-wellknown.md):

```
charts/<thing>/                  ← orchestrator; emits ApplicationSet
charts/<thing>-<componentA>/     ← leaf
charts/<thing>-<componentB>/     ← leaf
```

The orchestrator's `Chart.yaml` depends only on `common`. The leaves
carry their own values defaults; the orchestrator's `values.yaml`
carries ArgoCD wiring (project, destination, targetRevision, per-child
sync wave) and a `children: [{name, chartPath, syncWave, enabled}]`
list that drives the ApplicationSet's List generator.

## Python tooling

Per [ADR-0008](docs/adr/0008-python-dashboard-generation.md):

- **`uv`** for everything (lockfile, virtualenv, run, install). Not
  pip, not poetry.
- **`ruff`** for lint and format. Not black, not isort, not flake8.
- **Python 3.12+.**
- `pyproject.toml` (PEP 621), commit `uv.lock`.
- Project root has a `Makefile` with `install`, `build`, `check`,
  `format`, `lint` targets that wrap `uv` commands — muscle-memory
  shortcut, not authoritative.

Example: [`tools/dashboards/`](tools/dashboards/).

## CI

Ten workflows under `.github/workflows/`:

| Workflow | Triggers on | What it does |
|---|---|---|
| `helm-lint.yaml` | every push + PR (all branches) | per-chart `helm lint` + `helm template --dry-run`; `--strict` only for charts with own `templates/` (see below) |
| `commit-lint.yml` | PR opened/edited/synchronized/reopened | validates the PR title + every non-merge commit against Conventional Commits via `tools/commit-lint.sh` (no third-party action) |
| `governance.yml` | PR opened/edited/synchronized/reopened | delegates to `ADORSYS-GIS/ai-governance/.github/workflows/governance-check.yml` at SHA `959d8565041ddef86d3a10001b64393a6d4a60a2` (v1.0.0); fails the PR if the body lacks an AI Usage Declaration, source-of-truth link, or verification evidence |
| `security.yml` | every push + PRs targeting `main` | delegates to `ADORSYS-GIS/ai-governance/.github/workflows/security-gates.yml@f1735f92f24dd86c7707ed990a3f3ecb51e2ea9b` with `trivy-scan-type: config`, `trivy-target: charts/` (trivy + dep scan) |
| `dashboards-drift.yml` | PR paths `tools/dashboards/**` or dashboard JSON; push to `main` on the same paths | ruff format/lint the generator, then `uv run dashboards check` — fails if committed JSON differs |
| `envoy-gateway-lua.yml` | PR/push paths `charts/core-gateway/**` or `tests/envoy-gateway-lua/**` | runs `tests/envoy-gateway-lua/run.sh`, which translates every rendered Lua entry through Envoy Gateway's own `egctl x translate` (pinned `EG_VERSION=v1.8.2`) |
| `opencode.yml` | PR opened/synchronize, issue comments, review comments | OpenCode auto-review (manual-review on `/oc` or `/opencode`); no-op unless `OPENCODE_GATEWAY_AUDIENCE` is set |
| `release-helm-charts.yml` | push to any branch touching `charts/**` + manual dispatch | non-strict lint, renders charts, Trivy config scan; `helm/chart-releaser-action` runs only on dispatch |
| `publish-charts-oci.yml` | push to `main` touching `charts/**` + manual dispatch | publishes changed charts to `oci://ghcr.io/adorsys-gis/charts` with auto-semver (ADR-0055), cosign-signed |
| `release-please.yml` | push to `main` + manual dispatch | `googleapis/release-please-action@v5` maintains one changelog/version PR (ADR-0082) |

**The `helm-lint` strictness rule matters most to chart authors.** The workflow
reads the `ai-helm.adorsys-gis.github.io/lint-mode` annotation and decides three
ways:

- A chart with its **own `templates/` directory** is linted with `--strict`.
- A **subchart-only** chart (no own `templates/`, e.g. `bjw-template`) is linted
  **non-strict** — `--strict` would false-trip on `templates/: directory not
  found` even though it renders fine.
- A chart annotated `lint-mode: ci-values` (render-only leaves such as
  `ai-model`) is **linted AND rendered against each `ci/*-values.yaml` fixture**
  instead of its default values. If such a chart has **no** fixture, the job
  **fails**.

**The `security` gate delegates to `ADORSYS-GIS/ai-governance`, not
`ADORSYS-GIS/ai-ops`.** The reusable workflow is pinned to an immutable commit
SHA (`f1735f92f24dd86c7707ed990a3f3ecb51e2ea9b`), not `@main` or a movable tag:
a future push to `ai-governance` — or a moved tag — cannot change what runs here.
It lives in `ai-governance` (public) rather than `ai-ops` (private) because
ai-ops's Actions "Access" setting blocks external callers. Note this gate does a
bare checkout and scans `charts/` without `helm dependency build`, so charts
with subchart dependencies are skipped; the authoritative chart-config scan is
in `release-helm-charts.yml`.

**PR gates** are **helm-lint** + **commit-lint** + **governance** + **security**;
**dashboards-drift** and **envoy-gateway-lua** also gate a PR when its paths are
touched. **publish-charts-oci** and **release-please** are **not** PR gates —
they run only on push to `main`. **opencode** is informational — its review
surfaces issues to think about; humans decide.

Dashboard drift specifically: if you edit a `tools/dashboards/<area>/*.py`
file, you MUST run `uv run dashboards build` and commit the
regenerated JSON. CI will fail otherwise.

## Reviewing

Anyone can comment; @stephane-segning approves and merges. Reviewers
should look for:
- An ADR exists for non-obvious choices (or one is being written in
  the same PR).
- New charts follow the conventions above.
- Image pins are explicit (no `:latest`).
- Docs land alongside code (`docs/<feature>.md` for the *how*; the ADR
  is the *why*).
- Security: no plaintext credentials in `values.yaml`; secrets via
  ESO `secretKeyRef`.
- Sync-wave annotations match the convention.

## Documentation expectations

Code changes ship with their docs. Specifically:
- A chart change touches at minimum the chart's own files; ideally
  also a `docs/<feature>.md` how-to and (when architectural) an ADR.
- A new dashboard ships with its `README.md` co-located.
- An ops workflow (backup, restore, secret rotation) gets a runbook
  under `docs/`.

If you can't tell whether something deserves a doc, err toward writing
it — the cost of a stale doc is far lower than the cost of an
undocumented decision a year later.

## Getting unstuck

- **Chart won't render.** `helm dependency update && helm template
  . --debug` from the chart dir.
- **ArgoCD shows OutOfSync after merge.** Most often a sync-wave
  ordering issue; check [SYNC_WAVE_PATTERN.md](SYNC_WAVE_PATTERN.md)
  and the application's own annotations.
- **Drift on `tools/dashboards/`.** Run `uv run dashboards build`,
  commit, push.
- **uv installs fail.** Network blocked from the runner; pre-seed
  `~/.cache/uv/` from a known-good machine, or use the chart's
  Makefile's `install` target with `--offline`.
- **Something is missing from docs.** Open a PR with a stub
  `docs/<thing>.md` — getting the doc into git, even partial, is
  better than waiting for the perfect one.

## Code of conduct

Be kind, be precise, assume good faith. Disagreements about
architecture are healthy — write an ADR with the alternatives and let
the discussion happen on a PR.

## AI Governance

This repository follows the [ADORSYS-GIS AI Governance](https://adorsys-gis.github.io/ai-governance/) practices.

- **Issues** — use the structured forms (Epic / User Story / Development Ticket) under *New issue*. Each requires a source-of-truth link, verification evidence, and an accountable owner.
- **Pull requests** — fill the **AI Usage Declaration**, link a source of truth, and provide verification evidence. The `AI Governance` CI check enforces these on every PR.
- **Principle** — AI may accelerate the work, but it must not launder ignorance into polished artifacts; humans own intent, verification, and consequences.

See the [AI working agreement](https://adorsys-gis.github.io/ai-governance/12-ai-working-agreement) and the [doctrine](https://adorsys-gis.github.io/ai-governance/13-doctrine).

## Working with AI code review

Automated AI reviewers (Codex, Copilot, and the like) are **advisory — never a merge gate.** Only
**deterministic** checks (the governance CI check, linting, tests) may block a merge, because their
output is reproducible and cannot be confabulated. Keep AI review as a non-required status check.

**Every AI-review finding is a claim, not a verdict.** Before acting on one that asserts a specific
value or behavior, verify it against the actual cited lines. AI reviewers pattern-match known bug
*shapes* and will confidently assert details about code they did not actually read — especially code
in another repository (e.g., a reusable workflow referenced by SHA). The doctrine applies to the
reviewer too: **AI output is not truth.**

### When a finding is a false positive, close the loop — don't just ignore it

1. **Reply with the evidence** — the exact lines or command output that disprove it.
2. **React 👎** on the finding.
3. **Resolve the conversation.**

This three-step loop is not busywork; each step does something that silently ignoring does not:

- **👎 is the only lever that reduces recurrence.** It is the reviewer's feedback channel. Without it,
  the same confabulation fires again every time its trigger reappears — a single false "empty marker"
  finding recurred *three times* across PRs precisely because it was refuted in prose but never
  down-voted.
- **Resolving preserves signal-to-noise.** Real findings get buried under known-false ones if threads
  stay open; resolution stops both humans and the bot from re-litigating settled points.
- **The evidence reply is an audit trail.** The next person — or AI — who hits the same flag finds the
  refutation in-thread and does not have to re-verify from scratch. Silently ignoring a false positive
  looks unaddressed, erodes trust in the review, and teaches the bot nothing.
