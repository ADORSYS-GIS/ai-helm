# ADR-0056: Move workload Helm values out of `charts/apps` into `ai-helm-values`

**Status:** Accepted
**Date:** 2026-06-23
**Deciders:** @stephane-segning
**Amends:** [ADR-0055](./0055-oci-charts-and-image-updater-writeback-to-values-repo.md), [ADR-0018](./0018-umbrella-apps-and-env-overlays.md)

## Context

[ADR-0055](./0055-oci-charts-and-image-updater-writeback-to-values-repo.md) scoped
the private `ai-helm-values` repo to **"values + image tags"** but in practice only
moved the *image tags* (the write-back targets) and the `environments/` overlays.
The bulk of each app's actual workload configuration still lived **inline** in
`charts/apps/values.yaml`, in per-app `source.helm.valuesObject` blocks.

That file had grown to **1689 lines**, and a handful of `valuesObject` blocks
dominated it — the largest being **`security-policies` at ~405 lines** (the
Authorino `AuthConfig`s + the Envoy `SecurityPolicy`), then `eg` (~120) and
`opencode-k8s-agent` (~66). Keeping that config inline has two problems:

1. **It conflates chart structure with deployment config.** Editing an app's env
   vars, replica counts, or — for `security-policies` — the entire gateway auth
   policy meant a PR against the *chart* repo, gated by the chart governance flow,
   even though nothing about the chart changed.
2. **The auth policy is sensitive and `ai-helm` is public.** The full `AuthConfig`
   (Keycloak issuer wiring, CEL descriptor logic, the internal-plane apiKey/SA
   review rules — [ADR-0021](./0021-burst-budget-billing-and-dual-plane-authconfigs.md))
   sat in a public repo.

The multi-source `$values` mechanism that ADR-0055 built for image tags is exactly
the tool needed: a chart `source` can read a values file from `ai-helm-values` via
a `$values` ref. The maintainer chose to move the **three heaviest** `valuesObject`
blocks first (security-policies, eg, opencode-k8s-agent ≈ 590 lines — ~90% of the
benefit), leaving the small ones and the orchestrators for later.

## Decision

- **Workload Helm values may live in `ai-helm-values`**, at
  `environments/<env>/values/<app>.yaml`, read by the app's chart source as a
  `$values` valueFiles ref. This **amends ADR-0055's scope** from "values + image
  tags" to explicitly include **workload config**.
- **Opt-in via one flag.** An app entry in `charts/apps/values.yaml` sets
  `valuesFromRepo: true`. The `charts/apps` template (`applications.yaml`) then,
  for a singular-`source:` app, deep-copies the source, injects
  `helm.valueFiles: [$values/environments/<env>/values/<app>.yaml]` +
  `ignoreMissingValueFiles: true`, and appends the `ref: values` source (and the
  `depsOverlay` deps source if present). No per-app source restructuring; the app
  keeps its `source:` verbatim and just drops the flag.
- **The inline `valuesObject` is removed** for migrated apps; the file in
  `ai-helm-values` is the single source of truth. (A leftover inline `valuesObject`
  would still layer on top, so removal is required to avoid a stale override.)
- **Migrated:** phase 1 — `security-policies`, `eg`, `opencode-k8s-agent` (the
  heaviest); phase 2 — `apprise-api`, `aieg`, `core-gateway`, `lightbridge-repo-auth`,
  `mongodb-backup`, `converse-ui`. That is **every** flat `charts/apps` app that
  carried a `valuesObject`. (`converse-ui`'s config was deep-merged into its existing
  image-updater-owned values file, preserving the `image.tag` write-back path;
  `mongodb-backup`, being a top-level-`chart:` OCI app, already had the `$values`
  valueFiles ref injected, so it needed no flag — just the file + inline removal.)
- **A render-check CI** in `ai-helm-values` (`render-check.yml`) YAML-validates
  every values file and `helm template`s the OCI-sourced charts (kuadrant-policies,
  gateway-helm, core-gateway, ai-gateway-helm, mongodb-backup) against their file —
  because `ignoreMissingValueFiles` means a
  malformed file does **not** fail loudly; it silently falls back to chart defaults
  (which for `security-policies` would drop the gateway auth policy entirely).
- **Ordering invariant:** the `ai-helm-values` file MUST exist on `main` before the
  matching `charts/apps` change merges, or the app briefly renders on chart
  defaults. Cut over values-repo-first, chart-repo-second.

## Consequences

**Positive**
- `charts/apps/values.yaml` shrinks 1689 → ~1109 lines; the sensitive AuthConfig
  now lives in the **private** values repo, not the public chart repo.
- App config changes are commits to `ai-helm-values` (where image tags + env
  overlays already live), decoupled from chart-logic changes — continuous, no
  ai-helm chart release.

**Negative / trade-offs**
- **Local render coverage splits across two repos.** `helm template charts/apps`
  now renders only the Application CR with a `valueFiles` *reference*; verifying the
  actual workload render needs both repos
  (`helm template charts/<x> -f <ai-helm-values>/.../<x>.yaml`). The `render-check.yml`
  workflow in `ai-helm-values` compensates for the OCI-sourced charts.
- A change spanning chart structure *and* values now spans two PRs.
- The values files are not schema-validated against the chart beyond `helm template`
  succeeding; a key typo that renders (but is ignored by the chart) won't be caught.

**Not done (future work)**
- The **orchestrators** (`observability`, `ai-models`, `librechart`, `mcps`,
  `lightbridge`) hold child config in their own chart `values.yaml`, baked into the
  OCI chart; moving those needs a `$values` override on each orchestrator and is a
  separate, larger effort.
