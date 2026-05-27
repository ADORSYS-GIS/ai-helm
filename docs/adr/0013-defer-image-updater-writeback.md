## ADR-0013: Defer argocd-image-updater write-back; manual chart-version bumps stay

**Status:** Accepted
**Date:** 2026-05-24
**Deciders:** @stephane-segning
**Supersedes:** [ADR-0010](./0010-argocd-image-updater-writeback-to-ai-gitops.md)

## Context

ADR-0010 specified argocd-image-updater with git write-back to `ai-gitops`,
PR-based with auto-merge on green CI, reusing the existing GitHub App.
Two new tasks were created to implement it: a chart-shape audit (here)
and the per-Application annotation rollout (in `ai-gitops`).

Re-examining the existing repo structure surfaced a structural mismatch
that makes the original plan low-value or net-negative:

1. **Image tags live in `ai-helm` chart values, not in `ai-gitops`
   Application overrides.** Every ArgoCD `Application` we ship sets
   either `valuesObject: {}` or carries non-image overrides only. The
   actual image pin is in `charts/<x>/values.yaml`. With
   `targetRevision: HEAD`/`main`, every reconcile already pulls the
   latest chart values — so changing an image is "edit `ai-helm` and
   push." Image-updater's write-back to `ai-gitops` would update a
   field nothing reads.

2. **Writing back to `ai-helm` instead** would conflate chart-source-
   of-truth with deployment-state — explicitly rejected in ADR-0010's
   "Alternatives considered". The two-repo split was deliberate.

3. **Auto-merge on green CI is a weaker gate than it sounds.**
   `helm-lint` + `helm template` + `kubeconform` (planned) prove the
   chart still renders to valid Kubernetes — they do not catch behavior-
   changing upstream bumps. A bad upstream tag (or a registry
   compromise) lands in prod within one ArgoCD reconcile.

4. **The bump cadence isn't bottlenecked on automation.** The 2026
   currency audit's punch-list has ~15 stale chart pins. Closing it is
   release-notes-reading work, not bump-the-tag work. Automation
   wouldn't have helped get there faster; reading release notes one by
   one is the actual cost.

5. **First-party `sha-*` cadence (Lightbridge) is the strongest case**
   for write-back, but it routes through the team's own CI which
   already controls when the SHA gets minted and tagged. Image-updater
   would automate the last step but only by accepting the write-back-
   to-`ai-helm` coupling rejected above.

## Decision

**Defer argocd-image-updater write-back.** Manual chart-version bumps
remain the only path to update deployed images. ADR-0010 is superseded
by this ADR; the two follow-up tasks ("Audit ai-helm chart values for
image-updater-hostile shapes" and "ai-gitops: wire image-updater
annotations per Application") are dropped.

argocd-image-updater **stays installed** in the cluster. It's cheap to
run idle, and the moment one of the precondition shifts (per-env image
overrides in `ai-gitops`, sustained sha-* bump volume that humans can't
keep up with, or a real multi-cluster split where chart defaults can't
serve all envs) the path back is small: annotate the affected
Applications, no new operator.

## Consequences

**Positive**
- One less moving piece in the CI/CD loop. The PR + auto-merge surface,
  the GitHub App scopes for `ai-gitops`, the per-registry credentials
  image-updater would need, the chart-shape work to make every chart
  write-back-clean — all skipped.
- Trust posture clearer: every prod image change passes through a human
  reading release notes. Slower, but every change has an owner.
- Image-updater's idle install costs ~50 MiB / a few millicores;
  effectively free. Keeps the option open.

**Negative**
- Manual bumps lag behind upstream by whatever the team's cadence is.
  Acceptable today; revisit if a security-driven upstream bump becomes
  urgent and humans haven't pulled it in.
- ADR-0010 + the chart-shape audit task represent ~2 days of work that
  doesn't ship. Sunk cost; the analysis underlying ADR-0010 is preserved
  as historical record.

**Neutral / follow-ups**
- The 2026 currency audit's chart-bump punch-list remains the canonical
  way to keep current. Plan recurring "audit refresh" sessions (perhaps
  quarterly) so the gap doesn't widen.
- If the team adopts a per-env split (dev/staging/prod) and starts
  overriding image tags in `ai-gitops`, write-back becomes viable;
  revisit then with a new ADR.
- For the Lightbridge first-party case specifically, a dedicated bot
  that bumps `charts/lightbridge-*` values from your own CI pipeline
  (not generic image-updater) may be a lighter answer if the cadence
  ever justifies it.

## Alternatives considered

- **Proceed with ADR-0010 as written.** Rejected: the chart-shape
  prerequisite doesn't exist, and the value doesn't pay back the
  auto-merge risk surface.
- **Scoped to Lightbridge sha-* bumps only** (amended ADR-0010, write
  back to `ai-helm`). Rejected: accepts the chart-source/deployment-
  state coupling for one case, and the team's existing CI already
  controls SHA cadence. A bot dedicated to this one workflow is a
  lighter answer if/when needed.
- **Renovate Bot instead.** Strictly broader than image-updater (also
  Helm chart versions, Go modules, language deps). Could be valuable
  separately; not what was being decided here.

## Related

- **Supersedes** [ADR-0010](./0010-argocd-image-updater-writeback-to-ai-gitops.md)
  — the original plan; preserved as historical context.
- The dropped tasks: "Audit ai-helm chart values for image-updater-
  hostile shapes" and "ai-gitops: wire image-updater annotations per
  Application" were created based on ADR-0010 and are deleted with this
  ADR.
- 2026 currency audit (`docs/2026-currency-audit.md`) — the manual path
  for keeping current.
