# ADR-0126: Move the model catalog out of `charts/ai-models` into `ai-helm-values`

**Status:** Accepted
**Date:** 2026-08-12
**Deciders:** @stephane-segning

## Context

ADR-0056 moved every app's workload config out of this repo into the private
`ai-helm-values`, on a simple rule: `ai-helm` holds *how to render*,
`ai-helm-values` holds *what is deployed*. The `ai-models` orchestrator was
explicitly left out of that pass, on the grounds that it had no inline
`valuesObject` in `charts/apps/values.yaml` — which was true, but only because
its config was somewhere else: `charts/ai-models/values.yaml` itself, ~2,000
lines of provider backends, the model catalog, prices, rate-limit plans and
ArgoCD wiring, shipped as chart *defaults*.

That is the largest body of deployment state left in this repo, and it is the
most operational: adding a model, repointing one at a different upstream,
disabling one, or correcting a price all mean a chart change here, and every one
of those is a deploy. It is also the only place in the fleet where prices live —
the per-1M rates that drive the gateway's monthly budget rate-limit (ADR-0021) —
and prices are the one kind of config that changes without anyone here doing
anything (see ADR-0127).

The plumbing to move it already existed and was already wired: the `models` app
entry in `charts/apps/values.yaml` has been in OCI mode since ADR-0055, and OCI
mode injects `$values/environments/<env>/values/<app>.yaml` into the chart's
`valueFiles` unconditionally. The file simply never existed.

## Decision

**Move the entire contents of `charts/ai-models/values.yaml` to
`ai-helm-values` `environments/prod/values/models.yaml`, and reduce the chart's
own values to an empty structural skeleton.**

- Everything moves — ArgoCD wiring, `gatewayRef`, `sharedBudget`,
  `rateLimitBudgeting`, `modelsInfo`, `externalSecrets`, `backendDefaults` /
  `modelDefaults` / `supportedParams` (the YAML anchors), `backends` and
  `models`. The anchor blocks move *with* the catalog because Helm merges
  documents, not anchors: an alias cannot reach across two values files, so the
  definitions must sit in the same file as their uses.
- The chart keeps empty containers only (`backends: {}`, `models: {}`, …), so
  the templates' dot-chains resolve. It is not a working default and is not
  meant to be one.
- A new render guard, `ai-models.requireCatalog`, hard-fails the render when the
  catalog is absent. This is the load-bearing part of the decision, not a
  nicety — see below.
- CI lints and renders the chart through a new `ci/lint-values.yaml` fixture
  (`lint-mode: ci-values`, the convention `charts/ai-model` already uses).
- The cross-catalog guard `tools/check-model-catalogs.sh` moves to
  `ai-helm-values`, which can pull both charts anonymously from the public OCI
  registry. The reverse is impossible: this repo's CI cannot read the private
  values repo.

## Consequences

**Positive**

- The ADR-0056 rule finally holds without an exception. Adding, repointing or
  disabling a model no longer touches this repo, needs no chart publish, and is
  not visible in a public repo — which also takes the commercial rate card
  private, where the rest of the deployment state already is.
- Prices become machine-writable, which is what ADR-0127 builds on. A bot
  committing to `charts/` on a schedule would have been a much harder sell.
- The move is provably inert: `helm template models charts/ai-models -f <the new
  file>` is byte-identical to the pre-move render (8,588 lines).

**Negative**

- **A missing values file would silently prune every model route**, because the
  `$values` source is mounted with `ignoreMissingValueFiles: true` and the empty
  defaults render *perfectly validly* — an ApplicationSet with a backends child
  and no model children, which the controller then reconciles by deleting every
  `ai-model` child, every AIGatewayRoute and every BackendTrafficPolicy, on a
  green sync. The pre-existing destination guard does not catch this
  (`argocd.destination` falls back to `home-remote` and renders happily). This
  is why `requireCatalog` exists and why it fails rather than warns: a render
  failure leaves the `aii-models` Application in ComparisonError with every
  running child untouched, which is the only safe direction for this failure.
- The catalog now lives in a private repo, so it is no longer readable by
  contributors without values-repo access, and `docs/models/` prose can no
  longer link to a line in it.
- The cross-catalog invariant is now cross-repo and asymmetric: the gateway half
  is checked from the values repo's working tree, the fleet half by cloning
  `ai-helm` `main`. Reading the *published* `inference` chart would have matched
  what ArgoCD resolves, but that GHCR package is **private** while
  `charts/ai-models` is public — an anonymous pull fails in CI, and a local run
  succeeds anyway on leftover docker credentials, which is precisely how that
  would have gone unnoticed. Cloning the public source needs no credentials and
  makes the guard slightly tighter than ArgoCD (checked at merge, not at
  publish); the cost is that it no longer proves what is *deployed*.

**Neutral / follow-ups**

- `charts/inference/values.yaml` — the GPU fleet's serving catalog — deliberately
  did **not** move. It is "which card runs what", closer to infrastructure than
  to the gateway's commercial catalog, and moving it would put the guard's two
  halves back in one repo only by moving the other one. Worth revisiting as its
  own change.
- `tools/dashboards/src/dashboards/_common.py` keeps `EMBEDDING_MODEL_KEYS` in
  manual sync with the catalog; it is now syncing against a file in another
  repo. Unchanged in kind, slightly worse in ergonomics.

## Alternatives considered

- **Move only `backends` + `models`, keep the rest as chart defaults** — rejected
  by the maintainer in favour of moving everything. Splitting would have left
  `rateLimitBudgeting.plans` (a list, so it *replaces* rather than merges) in two
  possible places, which is exactly the duplicate-source-of-truth failure the
  move exists to remove.
- **Leave the catalog here and only automate prices** — rejected. It would mean a
  scheduled bot committing to a public chart repo, and every price change would
  publish a new chart version for a value that is not chart logic.
- **Keep a working default in the chart as a fallback** — rejected, and it is the
  most tempting wrong answer. A fallback catalog would turn "the values file
  broke" from a loud render failure into a silent partial deploy against a stale
  rate card.
- **Extend `charts/apps` to inject a second values file** so the catalog could be
  split from a machine-owned prices file — rejected as unnecessary once the
  price sync was made line-precise (ADR-0127); it would have duplicated every
  price across two files.

## Related

- Docs: `docs/patterns/self-hosted-model-serving.md`, `ai-helm-values/README.md`
- Files: `charts/ai-models/{values.yaml,Chart.yaml,ci/lint-values.yaml,templates/_helpers.tpl}`,
  `.github/workflows/helm-lint.yaml`, `tools/check-model-catalogs.sh` (removed)
- Values repo: `environments/prod/values/models.yaml`,
  `tools/check-model-catalogs.sh`, `.github/workflows/render-check.yml`
- Builds on: ADR-0055 (OCI + values repo), ADR-0056 (workload config moves),
  ADR-0012 (orchestrator/leaf split), ADR-0017 (destinations)
- Enables: ADR-0127 (automated provider price sync)
