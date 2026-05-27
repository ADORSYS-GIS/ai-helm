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

Conventional Commits. Common prefixes:

| Prefix | When to use |
|---|---|
| `feat(scope):` | New user-facing behavior (a new chart, a new dashboard, a new endpoint) |
| `fix(scope):` | Bug fix |
| `chore(scope):` | Maintenance: dep bumps, CI tweaks, file renames |
| `refactor(scope):` | Restructure with no behavior change (chart split, helper extraction) |
| `docs(scope):` | Documentation only |

Body: explain **why**, not what (the diff shows what). When a commit
implements an ADR, link it: `(ADR-NNNN)`. Long bodies are encouraged for
non-trivial changes — see recent commit history for the style.

Co-author trailer for AI-assisted commits:

```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

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

Five workflows under `.github/workflows/`:

| Workflow | Triggers on | What it does |
|---|---|---|
| `helm-lint.yaml` | every push + PR | `helm lint --strict` + `helm template --dry-run` per chart |
| `dashboards-drift.yml` | changes under `tools/dashboards/` or `**/files/**/*.json` | re-runs the Python generator, fails if committed JSON differs |
| `opencode.yml` | PRs + comment `/oc` or `/opencode` | runs OpenCode auto-review (or manual-review on demand) |
| `release-helm-charts.yml` | manual dispatch + branch pushes touching `charts/` | trivy config scan, then `helm/chart-releaser-action` on dispatch |
| `security.yml` | every push | reusable workflow at `ADORSYS-GIS/ai-ops` for trivy + dep scan |

A PR is mergeable when **helm-lint** + **dashboards-drift** (when
relevant) + **security** are green. **opencode** is informational —
its review surfaces issues to think about; humans decide.

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
