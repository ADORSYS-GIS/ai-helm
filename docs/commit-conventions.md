# Commit message conventions

This repo uses **[Conventional Commits](https://www.conventionalcommits.org/)**.
It is not cosmetic here: the commit `type` drives **release-please** version bumps
and changelog sections (ADR-0082), and — because we squash-merge — the **PR title**
is usually the commit that lands on `main`. Getting the structure right is what
makes automated releases work.

- **Validator (single source of truth):** [`tools/commit-lint.sh`](../tools/commit-lint.sh)
- **Enforced by:** the local `commit-msg` hook + the `Commit Lint` CI gate (both call that script — see [Enforcement](#enforcement)).

---

## The format

```
<type>[optional scope][!]: <description>

[optional body — explain WHY, wrap ~72 cols]

[optional footer(s)]
```

- **`<type>`** — one of the [types below](#types). Lowercase. **Required.**
- **`[scope]`** — `(name)`, lowercase. Optional but expected for chart changes: use the **chart directory name** (`core-gateway`, `observability`, `ai-model`), or a non-chart area (`deps`, `adr`, `release`, `ci`). See [Scope](#scope).
- **`!`** — breaking-change marker, placed before the colon: `feat(mcp)!: …`. See [Breaking changes](#breaking-changes).
- **`: <description>`** — the mandatory `": "` separator then a **non-empty**, imperative, present-tense summary (“add …”, not “added …”). No trailing period. Keep it ≤ ~100 chars (the validator nudges past that; it doesn’t fail).
- **body** — the repo norm is a substantive body that explains **why** (the diff already shows *what*); 20–60 lines are common for non-trivial changes.
- **footers** — `BREAKING CHANGE: …`, `Co-Authored-By: …`, `Refs: #123`, etc.

---

## Types

What each type does under [release-please / ADR-0082](./adr/0082-release-please-changelog-and-minor-major-floor.md):

| Type | Release effect (release-please) | Changelog | Use for |
|---|---|---|---|
| `feat` | **MINOR** bump of the chart floor (pre-1.0 charts: minor too) | **Features** | New user-facing behavior — a new chart, endpoint, dashboard, capability |
| `fix` | **PATCH** — **cosmetic only**: the OCI publish (ADR-0055) still derives the deployed patch from commit-count, so a `fix`-only release PR is effectively **changelog-only** | **Bug Fixes** | A bug fix |
| `feat!` / any `!` / `BREAKING CHANGE:` | **MAJOR** bump (pre-1.0 charts: **MINOR**, per `bump-minor-pre-major`) | Features + a **⚠ BREAKING** note | A change that breaks consumers |
| `perf` | none on its own | Performance | Performance improvement, no behavior change |
| `refactor` | none on its own | Refactoring | Restructure with no behavior change (chart split, helper extraction) |
| `docs` | none on its own | Documentation | Docs/ADRs only |
| `revert` | none on its own | Reverts | Reverting a prior change |
| `chore`, `ci`, `build`, `test`, `style` | none | **hidden** | Maintenance, CI, build/deps, tests, formatting |

> **“none on its own”** means the type is included in a release’s changelog when a
> `feat`/`fix` in the same batch triggers that release, but it never *starts* a
> release by itself. Only `feat` and `fix` (and breaking changes) do.

### The load-bearing bit (ADR-0082 hybrid)

release-please owns each chart’s **`MAJOR.MINOR` floor** in `Chart.yaml` + the
`CHANGELOG.md`. The **deployed `PATCH`** is still computed by
`publish-charts-oci.yml` as `git rev-list --count` of the chart dir — so the patch
release-please writes is **cosmetic** (publish ignores it). Practical upshot:

- `feat` → the floor moves (0.4 → 0.5, or 1.2 → 1.3) → a real deploy on merge.
- `fix` → floor unchanged; the fix already deployed via commit-count patch when it merged. The release PR just records it in the changelog.
- Breaking → major (or minor while the chart is still `0.x`).

---

## Scope

- **For a chart change, the scope is the chart directory name**: `feat(observability): …`, `fix(ai-model): …`. This is what appears in that chart’s `CHANGELOG.md` (`**observability:** …`).
- ⚠️ **Attribution is by file path, not by the scope string.** release-please assigns a commit to a chart’s changelog/version because the commit **touched files under `charts/<name>/`** — not because of the `(name)` text. So the scope is for humans; keep it accurate, but a commit that edits `charts/core-gateway/**` bumps `core-gateway` even if you mistype the scope.
- **A commit that touches several charts** is attributed to **each** of them (you’ll see it in multiple changelogs). Prefer one chart per commit; split when you can.
- **Non-chart scopes** are fine for non-chart work: `docs(adr)`, `ci(release-please)`, `chore(deps)`, `build(ci)`. Work outside `charts/**` (docs, `tools/`, workflows) is **not** attributed to any chart and won’t appear in a chart changelog.
- **`bjw-common` / `bjw-template` are not release-please-tracked** (dependents exact-pin `4.6.2`); you may still scope commits to them for clarity, but they won’t auto-version — bump them deliberately in `Chart.yaml`.

---

## Breaking changes

Two equivalent ways, use either or both:

```
feat(core-gateway)!: rename the AuthConfig host key

BREAKING CHANGE: the `spec.hosts[0]` key moved from x-cd-* to x-oidc-*; update
downstream references before upgrading.
```

- The `!` and/or the `BREAKING CHANGE:` footer trigger a **MAJOR** bump — **except while the chart is still `0.x`**, where our config (`bump-minor-pre-major: true`) makes a breaking change a **MINOR** bump (semver’s “anything may change before 1.0”).

---

## The PR title matters as much as the commits

We allow squash, merge, and rebase merges, and squash uses `COMMIT_OR_PR_TITLE`.
So the subject that ends up on `main` — the one release-please parses — is:

- the **PR title**, when a multi-commit PR is squashed, or
- the **single commit’s subject**, for a one-commit squash / rebase / merge.

Therefore **the PR title must itself be a valid Conventional Commit** (the CI gate
enforces it), and every non-merge commit must be valid too. When in doubt, make the
PR title the clean, release-worthy line — it’s what the changelog will quote.

---

## AI-assisted commits

Add the co-author trailer with the running model version (see the global rule):

```
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

When a commit implements an ADR, link it in the body or subject: `(ADR-0082)`.

---

## Examples

**Good**

```
feat(observability): rate-limit quota dashboard from live Redis counters

Reads the limiter's per-account budget counters straight from redis-ha …
(20–60 line body explaining WHY)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

```
fix(ai-model): spell out invert:false on BackendTrafficPolicy headers
docs(adr): ADR-0082 — release-please changelog automation
chore(deps): bump azure/setup-helm to v5
refactor(core-gateway)!: rename the AuthConfig host key
```

**Rejected**

| Subject | Why |
|---|---|
| `add a dashboard` | no type |
| `Feat(x): …` | type must be lowercase |
| `feature(x): …` | `feature` isn’t an allowed type (use `feat`) |
| `feat: ` | empty description |
| `feat(x) missing colon` | missing `: ` |
| `wip` / `FIX bug` | not Conventional |

Auto-generated `Merge …`, `Revert "…"`, and `fixup!/squash!` subjects are **skipped** (allowed).

---

## Enforcement

Two layers, both driven by the same validator so they can’t disagree:

### 1. Local `commit-msg` hook (reject at `git commit`)

Not installed automatically. Enable once per clone:

```bash
git config core.hooksPath .githooks
```

Now a bad message is rejected before the commit is created. Bypass a single commit
with `git commit --no-verify` (rarely needed).

### 2. CI gate — `Commit Lint` (reject at the PR)

[`.github/workflows/commit-lint.yml`](../.github/workflows/commit-lint.yml) runs on
every PR and validates **the PR title + every non-merge commit** in the PR. It uses
no third-party actions/npm — it calls [`tools/commit-lint.sh`](../tools/commit-lint.sh),
the same script the hook uses.

To make it **block merges** (not just show red), add `commit-lint` to the branch’s
required status checks (repo Settings → Branches, or):

```bash
gh api -X PATCH repos/ADORSYS-GIS/ai-helm/branches/main/protection/required_status_checks \
  -f 'checks[][context]=commit-lint'
```

> The `Commit Lint` gate is about message **structure**. It’s independent of the
> **AI Governance** gate (which checks the PR **body** for an AI-usage declaration,
> a source-of-truth reference, and verification evidence). A PR must satisfy both.

### Changing the rules

Edit the `TYPES` / `PATTERN` in [`tools/commit-lint.sh`](../tools/commit-lint.sh)
— the hook and CI both pick it up. Keep the [Types](#types) table and
`release-please-config.json`’s `changelog-sections` in sync.
