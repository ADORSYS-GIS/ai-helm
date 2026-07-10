# ADR-0082: release-please for changelogs + the MAJOR.MINOR floor (hybrid with ADR-0055 OCI versioning)

**Status:** Accepted
**Date:** 2026-07-10
**Deciders:** @stephane-segning
**Amends:** [ADR-0055](./0055-oci-charts-and-image-updater-writeback-to-values-repo.md)

## Context

We had no changelog. Release notes were produced by hand (`git log` archaeology),
and the deliberate part of a chart's version — the human-set `MAJOR.MINOR` floor in
`charts/<name>/Chart.yaml` — was bumped ad hoc in ordinary PRs with no record of
*why* beyond the commit body.

[ADR-0055](./0055-oci-charts-and-image-updater-writeback-to-values-repo.md) makes
`publish-charts-oci.yml` derive the **deployed** version at publish time as

```
<MAJOR.MINOR from Chart.yaml>.<git rev-list --count of the chart dir>
```

— it reads only the `MAJOR.MINOR` floor and always recomputes `PATCH` from the
commit count, and it **never commits a version back** (so the publish workflow
cannot re-trigger itself). That property is load-bearing and we are not giving it
up.

We want [`googleapis/release-please-action`](https://github.com/googleapis/release-please-action)
(the same conventional-commits release automation used across the org's tooling)
to (a) maintain human-readable per-chart `CHANGELOG.md`s and cut GitHub Releases,
and (b) propose the `MAJOR.MINOR` floor bumps — **without** touching the derived
`PATCH` or the "never commit a version back from the publish job" invariant.

The friction: release-please's whole mechanism is to *commit* a version into a
file via a "release PR", which is the opposite of ADR-0055's derive-at-publish
model. Naively adopting per-chart release-please (bumping the full semver and
publishing *that*) would supersede ADR-0055's PATCH scheme and reintroduce a
committed-version-back path. We don't want that.

## Decision

Adopt release-please in **manifest mode**, scoped so it owns **only the
`MAJOR.MINOR` floor + the changelog**, and let ADR-0055's publish job keep owning
the deployed `PATCH`. The two are orthogonal because **publish reads only
`MAJOR.MINOR` and ignores the `PATCH` component release-please writes**.

Concretely:

- `.github/workflows/release-please.yml` runs `googleapis/release-please-action@v5`
  on push to `main`. It (re)opens **one** aggregated release PR
  (`separate-pull-requests: false`).
- `release-please-config.json` + `.release-please-manifest.json` at the repo root.
  `release-type: helm`, one package per tracked chart (`component` = chart name,
  `include-component-in-tag: true` → tags `<chart>-vX.Y.Z`).
- **Hybrid floor semantics:** `bump-minor-pre-major: true` +
  `bump-patch-for-minor-pre-major: false` → for both pre- and post-1.0 charts,
  `feat` bumps `MINOR`, a breaking change bumps `MAJOR` (pre-1.0: `MINOR`), and
  `fix` bumps only `PATCH`. Because publish discards the `PATCH` release-please
  writes, a `fix`-only release PR is effectively **changelog-only** — the deployed
  patch stays the commit-count. Only the `MAJOR.MINOR` release-please writes is
  load-bearing.
- Merging a release PR touches `charts/**`, which triggers
  `publish-charts-oci.yml`; the floor bump deploys via the normal OCI float. The
  publish job still commits nothing, so there is **no loop** (ADR-0055's invariant
  is preserved).
- **Token:** the default `GITHUB_TOKEN`. PRs it opens do not trigger other
  workflows (GitHub anti-recursion), so the release PR needs no CI and never trips
  the `governance` gate (which is `pull_request`-triggered). A human reviews and
  merges; that merge (a push to `main`) fires publish normally.
- **Excluded packages:** `bjw-common` and `bjw-template` are **not** tracked.
  Dependents pin them at an **exact** version (`4.6.2`), so a release-please bump
  would break every dependent's `helm dependency build`. They remain deliberately
  hand-versioned. `common` (consumed with `*`) and the non-published umbrella
  `apps` stay tracked (changelog value; bumps are dep-build-safe / cosmetic).
- `bootstrap-sha` is pinned to the adoption commit so the first release PR accrues
  only commits made *after* adoption (no giant retroactive changelog).

This **amends, does not supersede,** ADR-0055: the OCI float, the derived `PATCH`,
the write-back to `ai-helm-values`, and the root tracking `main` are all
unchanged. release-please adds a changelog/floor-proposal layer on top.

## Consequences

- **Positive:** every chart accrues a real `CHANGELOG.md`; `MAJOR.MINOR` bumps
  become reviewable release PRs with rationale instead of silent Chart.yaml edits;
  GitHub Releases/tags give humans a version timeline. Zero change to the deploy
  path or ADR-0055's invariants.
- **Cosmetic drift:** the `PATCH` (and possibly `appVersion`) release-please writes
  into `Chart.yaml` is ignored by publish — readers must know Chart.yaml's `PATCH`
  is not the deployed patch (documented in the workflow header + CLAUDE.md).
- **`fix`-only release PRs** bump a patch that doesn't affect the deployment; they
  exist for the changelog/Release. Acceptable (a merge still republishes at the
  commit-count patch).
- **Per-chart, not one repo-wide, changelog.** Manifest mode writes one
  `CHANGELOG.md` per chart, surfaced together in the single release PR body. A
  consolidated root changelog is a possible future add-on (post-release
  concatenation), not done here.
- Non-`charts/**` work (ADRs, `docs/`, `tools/dashboards`) is outside every package
  and is not changelogged; that history stays in git + the ADR index.

## Alternatives considered

- **Repo-level single release (simple release-type):** one root `CHANGELOG.md` +
  one `vX.Y.Z` tag. Simplest, but loses per-chart version/floor granularity, which
  is the unit consumers and ADR-0055 actually version on. Rejected.
- **Per-chart full-semver release-please (supersede ADR-0055):** let release-please
  own the whole version and publish *that*. "More correct" semver, but it commits
  versions back, reworks `publish-charts-oci.yml`, and drops the commit-count PATCH
  + the no-self-trigger invariant. Too invasive for the value; rejected in favor of
  the hybrid.
- **Custom versioning strategy to literally skip PATCH:** release-please has no
  "bump minor/major, never patch" strategy. Emulating it (`always-bump-minor`)
  would inflate the minor on every `fix`. Unneeded, since publish already discards
  the PATCH — the hybrid gets the same result with stock config.
