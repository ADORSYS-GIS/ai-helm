# ADR-0031: Tag-based deploys (`release-YYYY.MM.DD`), never `main`

**Status:** Superseded by [ADR-0055](./0055-oci-charts-and-image-updater-writeback-to-values-repo.md)
**Date:** 2026-06-08
**Deciders:** @stephane-segning

> **Why superseded (2026-06-22):** ADR-0055 retires the tag-based model in favour
> of continuous delivery — charts publish as OCI on merge and float on a semver
> range, image tags flow via argocd-image-updater write-back to the private
> `ai-helm-values` repo. Immutability (this ADR's core benefit) is **deliberately
> abandoned**: a merge to `main` is now a live deploy, and rollback becomes
> `git revert` in the values repo rather than repointing to a prior tag. The
> `tools/release.sh` automation this ADR introduced is retired. Body preserved as
> historical record.

## Context

ArgoCD reconciles this repo through the root `ai-apps-v2` Application (`charts/apps`),
which renders one child Application per workload; orchestrators (`ai-models`,
`librechart`, `observability`) render further children. Every one of those
children carries a `targetRevision` that points back at **this** repo (a
"self-reference").

Historically those self-references — and the root — tracked a **mutable branch**:
first `main`, then the long-lived deploy branch `claude/magical-bohr-390242`. Two
consequences:

- **No immutability.** Any push to the tracked branch was an immediate, live
  cluster event across ~50 Applications. A known-good deployment could drift the
  moment someone committed; there was no stable "this exact thing is in prod" ref.
- **No clean rollback.** Reverting meant `git revert` gymnastics on the branch,
  not "point back at the last good state."

The originally-intended "deployment state" repo `ai-gitops` (ADR-0010 image-updater
write-back; deferred by ADR-0013) was **never built**, so there was no external
place pinning a deploy version either. The earlier "flip `targetRevision` back to
`main` on PR merge" plan was explicitly retired (`main` accumulates work that is
not necessarily deployable; see the 2026-06-08 cutover where `main` had 33
divergent, superseded commits).

We need: an **immutable, reproducible** deploy reference, **trivial rollback**, and
a repeatable release procedure — without standing up a second repo.

## Decision

**Deploys are pinned to an immutable git tag `release-YYYY.MM.DD`. `main` is never
a deploy target.**

1. **Every self-referencing `targetRevision` pins the tag** — `argocd.selfTargetRevision`
   + the per-app self-Source revisions in `charts/apps`, and the orchestrator
   children in `charts/ai-models`, `charts/librechart`, `charts/observability`.
   (`HEAD`/version revisions that point at **other** repos are unaffected — see
   "external sources" below.)
2. **Self-consistency:** the tag must point at a commit whose charts already
   reference **that** tag. Because the root renders `charts/apps` *from the tag*
   and that render emits the children's `targetRevision`, a mismatched tag would
   make children resolve to the *previous* release. So the version bump and the
   tag are the **same commit**.
3. **The root `ai-apps-v2` Application** points at the tag too. It is applied
   manually from a maintainer-held manifest outside this repo (there is no
   `ai-gitops`), so repointing a release is a manual `kubectl apply` of that
   manifest with `spec.source.targetRevision: <tag>` (a live `kubectl patch`
   alone reverts when the manifest re-applies).
4. **External first-party sources are pinned to commit SHAs**, not `HEAD`, so a
   release is fully reproducible: `opencode-k8s-agent.git`
   (`aii-opencode-k8s-agent`, `aii-apprise-api`) and `converse-frontends`
   (`aii-converse-ui`). Upstream Helm charts are pinned to chart versions
   (`aieg v0.6.0`, `eg v1.8.0`, `external-secrets`, …). These do **not** ride the
   ai-helm tag (different repos); bump their refs deliberately, then re-release.
5. **`tools/release.sh` automates the cut** (guide: `docs/releasing.md`): bump all
   self-ref tags in one commit, `helm template`-check, tag that commit, push the
   **tag first**, then branch + `main`; print/`--repoint` the root. It does **not**
   touch external SHAs (manual bumps).
6. **`main` mirrors the deploy branch** as a record but is never deployed.

First release under this model: **`release-2026.06.08`** (cut over from the
branch); **`release-2026.06.08-v02`** is the first fully-pinned release (adds the
external-source SHA pins).

## Consequences

- **Immutable + reproducible.** A tag is a frozen snapshot; re-rendering it always
  yields the same fleet. Every source resolves to a fixed ref (tag / SHA / chart
  version) — no `HEAD` anywhere in the `ai` AppProject.
- **Trivial rollback.** Repoint the root to any prior `release-*` tag → the exact
  prior state redeploys. No code revert.
- **A branch push is no longer a deploy.** Day-to-day commits to the deploy branch
  are safe; nothing ships until a new tag is cut and the root is repointed.
- **Manual root repoint per release** (the maintainer-held `ai-apps-v2` manifest is
  the durable source of its `targetRevision`). This is the one non-automated step;
  `release.sh --repoint` offers a live-patch stop-gap that reverts until the
  manifest is updated. Accepted cost of not having `ai-gitops`.
- **External SHA bumps are manual + deliberate** — first-party sibling repos don't
  auto-update into a release.
- **Tags don't trigger CI** (`release-helm-charts` fires on branch push + manual
  dispatch, not on tags), so cutting a deploy tag is side-effect-free. Chart-
  packaging tags (`<chart>-<semver>`) are a separate concern.
- Per-env image-tag overrides still belong in chart defaults, **not** chart logic
  (ADR-0013 unchanged).

## Relationships

- **Retires** the "deploy from a branch / flip `targetRevision` to `main` on merge"
  plan (older notes, ADR-0006-era).
- **Relates to** [ADR-0010](./0010-argocd-image-updater-writeback-to-ai-gitops.md)
  / [ADR-0013](./0013-defer-image-updater-writeback.md): `ai-gitops` was never
  built; immutable tags in *this* repo fill the "pinned deploy state" role those
  ADRs anticipated (image-updater write-back remains deferred).
- **Builds on** [ADR-0017](./0017-home-remote-destination-invariant.md) (the root
  + control objects target in-cluster; workloads → home-remote) and
  [ADR-0018](./0018-umbrella-apps-and-env-overlays.md) (self-repo sources for the
  deps overlays, which also pin the tag).
