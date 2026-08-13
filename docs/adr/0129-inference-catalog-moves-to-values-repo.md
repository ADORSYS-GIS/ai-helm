# ADR-0129: Move the GPU fleet catalog out of `charts/inference` into `ai-helm-values`

**Status:** Accepted
**Date:** 2026-08-13
**Deciders:** @stephane-segning

## Context

ADR-0126 moved the gateway's model catalog out of `charts/ai-models` into
`ai-helm-values`, on the ADR-0056 rule that this repo holds *how to render* and
the values repo holds *what is deployed*. It deliberately left
`charts/inference/values.yaml` — the GPU fleet's serving catalog — behind, on the
argument that "which card runs what" is closer to infrastructure than to the
gateway's commercial catalog, and that moving it would only relocate the
cross-repo guard problem rather than solve it.

Both halves of that argument turned out to be weak. The file is 957 lines of
pure deployment state: ArgoCD wiring, the engine profiles (image tags, security
contexts, health probes) and one entry per model with its weights, quantization
and serving flags. Adding, replacing, disabling or rolling back a model means
editing it — which under the old shape meant a chart change, a publish and a
float, for a change that deploys nothing but data. And the guard argument
inverted once the gateway half had already moved: with one catalog here and one
there, `check-model-catalogs.sh` had to clone across repos to compare them.

## Decision

**Move the entire contents of `charts/inference/values.yaml` to `ai-helm-values`
`environments/prod/values/inference.yaml`, and reduce the chart's own values to
an empty structural skeleton — exactly the ADR-0126 shape.**

- Everything moves: `argocd`, `defaults` (including every engine profile) and
  `models`. The `inference` app in `charts/apps/values.yaml` has been in OCI mode
  since ADR-0055, so the `$values` injection was already wired and no template
  change was needed to consume the file.
- A new `inference.requireCatalog` guard hard-fails the render when the catalog
  is absent — for a sharper reason than in ADR-0126, see below.
- CI lints and renders the chart through a new `ci/lint-values.yaml`
  (`lint-mode: ci-values`), which is also its Trivy scan input.
- `check-model-catalogs.sh` now reads **both** catalogs from the values repo's
  working tree. It still clones ai-helm for the *chart* (the `charts/inference`
  GHCR package is private, so an anonymous pull fails in CI).

## Consequences

**Positive**

- Adding or swapping a fleet model is now a single values-repo edit: no chart
  change, no publish, no float. That is the whole point of the model-per-entry
  design in ADR-0094, finally delivered end to end.
- The cross-catalog invariant is no longer cross-repo. Both halves sit in one
  working tree, so a PR is checked against exactly what it will deploy, instead
  of against the last published chart.
- Verified inert: `helm template inference charts/inference -f <the new file>` is
  byte-identical to the pre-move render (757 lines).

**Negative**

- **The prune hazard here is worse than ADR-0126's, and that is the reason the
  guard is not optional.** An empty catalog renders a valid ApplicationSet with
  no children; the controller then deletes each model's StatefulSet, Service,
  CiliumNetworkPolicy **and its PVC** — the volume holding tens of GB of
  downloaded weights. Recovery is not a re-sync, it is a re-seed from
  HuggingFace per model. For the gateway catalog the same accident deletes
  routes, which come back in seconds. `requireCatalog` makes it a render failure
  either way, but the cost of not having it differs by orders of magnitude.
- The fleet catalog is now in a private repo, so `docs/models/` and the
  `inference-ops` runbooks can no longer link to a line in it.
- Engine profiles (image tags, security contexts) are now deployment state rather
  than chart defaults. That is correct — they are what is deployed — but it does
  mean a chart-logic change and an engine-image bump are now reviewed in
  different repos.

**Neutral / follow-ups**

- `charts/inference-server` (the leaf) keeps its own defaults; only the
  orchestrator's catalog moved.
- The fixture keeps the real `defaults` block verbatim rather than a shrunken
  copy — a hand-trimmed version would just be another place for the engine
  profiles to drift.

## Alternatives considered

- **Leave it in the chart** (ADR-0126's original call) — rejected on the evidence
  above: it is deployment state, it forced a publish per model change, and it was
  the last thing keeping the catalog guard cross-repo.
- **Move only `models` and keep `defaults` as chart defaults** — rejected. The
  engine profiles carry image tags and security contexts, which are exactly the
  things that change per deployment, and splitting them would leave the same
  two-places-to-look problem ADR-0056 exists to remove.
- **Publish `charts/inference` publicly so the guard can pull it from OCI**
  instead of cloning — rejected as out of scope here; it is a packaging decision
  with its own security discussion, and the clone costs nothing.

## Related

- Follows: [0126](./0126-model-catalog-moves-to-values-repo.md) (identical shape,
  the gateway half), [0055](./0055-oci-charts-and-image-updater-writeback-to-values-repo.md),
  [0056](./0056-workload-values-in-ai-helm-values.md)
- Constrains: [0094](./0094-generic-model-serving-orchestrator.md),
  [0095](./0095-cluster-local-model-federation.md),
  [0101](./0101-load-gate-before-federation-no-exceptions.md) (serving ≠ federating)
- Files: `charts/inference/{values.yaml,Chart.yaml,ci/lint-values.yaml,templates/_helpers.tpl,templates/applicationset.yaml}`
- Values repo: `environments/prod/values/inference.yaml`, `tools/check-model-catalogs.sh`
