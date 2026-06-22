# ADR-0055: OCI-published charts + argocd-image-updater write-back to a private `ai-helm-values` repo

**Status:** Proposed
**Date:** 2026-06-22
**Deciders:** @stephane-segning
**Supersedes:** [ADR-0013](./0013-defer-image-updater-writeback.md), [ADR-0031](./0031-tag-based-deploys.md)
**Amends:** [ADR-0018](./0018-umbrella-apps-and-env-overlays.md)

## Context

Under [ADR-0031](./0031-tag-based-deploys.md) every image bump or config tweak
requires `tools/release.sh`: bump every self-referencing `targetRevision` to a
new immutable `release-YYYY.MM.DD` tag **in one commit**, render-check, tag, push
the tag first, then **manually repoint the root `ai-apps-v2` Application's
`targetRevision` in the `home-os` repo**. That bought immutability + trivial
rollback at the cost of a manual, order-sensitive release dance on *every* change
— including routine first-party `sha-*` image rebuilds that the team's own CI
already gates.

[ADR-0013](./0013-defer-image-updater-writeback.md) deferred argocd-image-updater
write-back because (a) `ai-gitops` was never built, so there was no clean
write-back target, and (b) writing back to `ai-helm` would conflate chart source
with deployment state. Both objections are now answerable: we are building the
deployment-state repo (`adorsys-gis/ai-helm-values`), and the full pattern —
image-updater + git write-back + cosign verification + a `$values` multi-source —
**already runs in production** for `charts/lightbridge-code-intelligence` (the CRD
`ImageUpdater` controller + operator are installed; operator in
`home-os/charts/argocd-image-updater`). This ADR generalizes that proven pattern.

The maintainer has decided to trade away ADR-0031's immutability for continuous
delivery: "they can change n:n."

## Decision

**Adopt continuous delivery via OCI-published charts + image-updater git
write-back to a new private repo, retiring the tag-based release model.**

1. **Charts become pure source, published as OCI.** On merge to `main`, a CI job
   publishes each changed chart (and its transitive `file://` dependents) to
   `oci://ghcr.io/adorsys-gis/charts`, auto-semver'd from conventional commits.
   The version is **derived at publish time** (passed via `helm package --version`)
   — *not* committed back into `Chart.yaml` — so the publish never re-triggers
   itself. Local subcharts (`common`, `bjw-common`, `bjw-template`) are **vendored
   at package time** (`helm dep build`, dependency-ordered) and need no separate
   OCI publish. The OCI package is **public** (charts carry no secrets — ESO
   injects at sync), so ArgoCD needs no credential to pull charts.

2. **A new PRIVATE repo `adorsys-gis/ai-helm-values` holds deployment state** —
   scoped to **values + image tags only**: per-app value files
   (`environments/prod/values/<app>.yaml`, owned by image-updater) plus the
   `environments/` per-env overlays **migrated out of this repo** (kustomize deps +
   `cluster.yaml`). The root `ai-apps-v2` Application **stays applied from
   `home-os`** (it is *not* moved into the values repo).

3. **Child Applications float chart versions on a semver range** (`">=0.0.0"`),
   resolving to the newest published chart on each reconcile. Image tags float via
   image-updater write-back. **Immutability is deliberately abandoned** — a merge
   to `main` is now a live cluster event once charts publish.

4. **Write-back is direct-commit to the values repo `main`, cosign-gated.** No PR.
   First-party `sha-*` images use `newest-build` + cosign signature verification +
   `allow-tags: regexp:^sha-[0-9a-f]+$`; upstream images use `semver` + `allow-tags`;
   mutable refs use `digest`. Write-back covers first-party signed images, upstream
   semver images, and self-hosted model images.

5. **`tools/release.sh` is retired.** The "release" is now the merge (charts
   publish) + image-updater (tags flow). The values-repo git log is the deploy
   ledger; rollback is `git revert` there.

The `charts/apps` umbrella itself is **not** OCI-published-and-consumed — the root
renders it directly from this git repo (OCI-ifying the umbrella would create a
bootstrap chicken-and-egg). OCI consumption is for leaf/workload charts only.

## Consequences

**Positive**
- Routine image bumps need **zero** human action — image-updater commits the new
  signed tag, ArgoCD syncs. Chart-logic changes ship on merge, no tag dance, no
  manual root repoint.
- The chart-source / deployment-state split ADR-0010 wanted finally exists, cleanly
  (values repo = state, `ai-helm` = source).
- The values-repo git log is a precise, per-change deploy ledger (who/what bumped
  which tag, when) — better audit granularity than batched release tags.
- Backward-compatible rollout: an app opts in by setting `chart:` on its entry; un-migrated apps keep their path-based source. No big-bang cutover.

**Negative**
- **Immutability is gone.** A merge to `main` (or an upstream registry publishing a
  new in-range tag) is a live deploy. There is no frozen "this exact fleet is in
  prod" ref; reproducing a past state means checking out a values-repo commit *and*
  knowing which chart versions the range resolved to at that time.
- **New credential surface.** The private values repo needs **two** creds: a GitHub
  App (`contents:write`) for image-updater to commit, **and** an ArgoCD repository
  read-secret so ArgoCD can fetch the `$values` source. (The lightbridge precedent
  only needed the write cred because its Source B repo is public.) Miss the read
  cred → every migrated app goes `ComparisonError`.
- A `file://` library change (`common`, `bjw-template`) must fan out a republish to
  all dependents or consumers silently pin stale logic.
- cosign-gating protects first-party images; **upstream/model images opted into
  write-back auto-land unsigned in-range tags** — a bad upstream tag reaches prod in
  one reconcile (mitigated by strict `allow-tags`).

**Neutral / follow-ups**
- The `environments/` tree moves to the values repo; `depsOverlay` sources retarget
  from `argocd.selfRepoURL` to the new `argocd.valuesRepoURL` (ADR-0018 amended; the
  overlay *mechanism* is unchanged, only its repo home).
- Orchestrator children (`ai-models`/`librechart`/`observability`/`mcps`/`lightbridge`
  ApplicationSets) need the parallel `path:`→`chart:`+OCI change.
- Semver ranges exclude pre-release versions unless written `-0`; keep published
  versions clean `X.Y.Z`.

## Alternatives considered

- **Keep tag-based deploys (ADR-0031), automate only the root repoint.** Rejected:
  doesn't remove the per-change tag-everything commit; the maintainer wants routine
  image bumps to need no release at all.
- **Full deployment-state repo (root Application + everything in `ai-helm-values`).**
  Rejected for now (scope): the root stays in `home-os` where ArgoCD's `cd` app
  already manages it; moving it is extra blast radius for no immediate gain.
- **Float charts on a semver range with NO version write-back vs. CI writes exact
  versions back (preserving immutability).** The maintainer chose floating ("n:n"),
  explicitly trading immutability for simplicity — no version ledger, fewer moving
  parts.
- **PR + auto-merge write-back** (ADR-0010's original). Rejected: more moving parts;
  cosign + strict `allow-tags` on direct-commit is the precedent already trusted in
  prod for lightbridge.
- **release-please / chart-releaser for OCI publishing.** Rejected: chart-releaser is
  a GH-Pages index tool (no OCI push); release-please needs ~30 per-chart manifest
  entries and a batched release-PR that fights "publish on merge." A hand-rolled
  changed-chart-detection + conventional-commit bump + `helm push` reuses the existing
  workflow's dependency-build scaffolding.

## Related

- **Supersedes** [ADR-0013](./0013-defer-image-updater-writeback.md) (un-defers
  write-back) and [ADR-0031](./0031-tag-based-deploys.md) (retires tag-based
  immutability).
- **Amends** [ADR-0018](./0018-umbrella-apps-and-env-overlays.md) (`environments/`
  moves to `ai-helm-values`; `depsOverlay` sources retarget).
- **Generalizes** the live pattern in `charts/lightbridge-code-intelligence`
  (image-updater + cosign + `$values` write-back) and
  `charts/lightbridge-code-intelligence-imageupdater` (CRD `ImageUpdater` activation).
- **Builds on** [ADR-0017](./0017-home-remote-destination-invariant.md) (destinations
  unchanged) and the deferred design in
  [ADR-0010](./0010-argocd-image-updater-writeback-to-ai-gitops.md).
- Docs (the *how*): `docs/continuous-delivery.md` (cutover runbook), `CLAUDE.md`
  (revision-strategy + environments + release sections).
