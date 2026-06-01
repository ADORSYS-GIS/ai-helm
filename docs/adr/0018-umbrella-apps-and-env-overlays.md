# ADR-0018: Umbrella Applications (workload + app-scoped deps) with per-environment kustomize overlays

**Status:** Proposed
**Date:** 2026-05-31
**Deciders:** @stephane-segning

> Supersedes **ADR-0006** (the Proposed multi-source ApplicationSet migration).
> ADR-0006's core insight — split each Application into a workload source and
> a dependency source — is kept. What changed: (1) the **dependency layer is
> kustomize**, not a second Helm source, because the dep CRs are plain
> manifests this repo authors and kustomize patches them per-env with zero
> friction (Helm-output cannot be kustomize-patched in ArgoCD without the
> controller-wide `--enable-helm` flag); (2) **environment-specific knobs**
> (issuer, secret-store name, storageClass, domain base) live in an in-repo
> `environments/<env>/` overlay rather than being parameterized inline; (3)
> the **ApplicationSet conversion is decoupled** — umbrellas land inside the
> existing `range` template (it already passes `.sources` through), so the
> List/Matrix-generator migration stays separate future work.

## Context

`charts/apps` renders ~35 flat, single-source `Application` CRs via a Helm
`range` over `.Values.applications[]`. Two recurring pains: (a) app-scoped
prerequisites — the ingress `Certificate`, a private-registry image-pull
`ExternalSecret` — are either implicit (the `cert-manager.io/cluster-issuer`
annotation auto-creating a cert) or pushed entirely out to the external
`ai-ops-secrets.git`, so a workload and the things it *needs to start* are
owned by different Applications with implicit ordering; (b) cluster-specific
strings (`cert-home-cert-http`, `ssegning-aws`, `traefik`, storageClass) are
hardcoded across many values files, blocking a clean second environment. The
platform is mid-migration to a single Hetzner k3s cluster (see
[[platform-migration-externalize-infra]]) and wants to be multi-environment-ready
without yet standing up a separate deploy-state repo (there is no `ai-gitops`).

## Decision

Adopt an **umbrella Application** shape for flat leaf apps, plus an in-repo
**per-environment overlay** layer:

1. **`environments/` overlay layer (in this repo).**
   - `environments/<env>/cluster.yaml` — the human-readable source of truth
     for that environment's knobs: `clusterIssuer`, `secretStore`,
     `ingressClass`, `storageClass`, `domainBase`. Today only
     `environments/prod/` exists (Hetzner). A second env is a drop-in sibling.
   - `environments/base/deps/<app>/` — kustomize **base**: plain dependency
     manifests (`Certificate`, app-scoped `ExternalSecret`) with placeholder
     issuer/store values.
   - `environments/<env>/deps/<app>/` — kustomize **overlay**: references the
     base and patches the env's issuer / secret-store / domain in.

2. **Umbrella = multi-source `Application`** (rendered by the *existing* `range`
   template, which already emits `.sources`):
   - **Source A — workload**: the Helm chart (local `charts/*` or upstream).
   - **Source B — app-scoped deps**: the kustomize overlay
     `environments/<env>/deps/<app>` → the ingress `Certificate` and any
     per-app image-pull / app-scoped `ExternalSecret`.
   - **Source C — `ref: values`** (optional): a `$values` ref so Source A can
     pull per-env workload values via `helm.valueFiles: [$values/...]` when a
     workload knob (e.g. storageClass) actually diverges between environments.

   **Mechanism — `depsOverlay`.** An app entry sets a single field
   `depsOverlay: environments/<env>/deps/<app>`; the template folds it in as
   Source B pointing at this repo (`argocd.selfRepoURL` @
   `argocd.selfTargetRevision`). A workload's `source:` (singular) block and
   its `valuesObject` are kept **verbatim** — the template emits `sources:`
   (plural) and inserts the deps source as an extra element. This avoids
   re-indenting large inline `valuesObject`s (grafana ~490 lines) into a list,
   which would be the fragile part of the conversion. Apps that are already
   multi-source just get the deps source appended to their `sources:` list.

3. **Workloads get per-env *Helm values*, not kustomize patches.** Kustomize is
   confined to the plain-manifest dependency layer (Source B). This avoids the
   Helm-in-kustomize (`--enable-helm`) fragility entirely.

4. **Ownership split (per the "app-scoped only" decision).** Umbrellas own
   *app-scoped* deps: the ingress `Certificate` and per-app image-pull /
   session-type `ExternalSecret`s, all referencing the external `ssegning-aws`
   `ClusterSecretStore` by name. **Platform/shared secrets** (S3 creds,
   Keycloak client secrets, redis-auth) **stay external** in
   `ai-ops-secrets.git`. The store itself is never defined here (ADR-0017 /
   externalization invariant).

5. **Orchestrators are not wrapped.** `models` and `librechat` already emit
   ApplicationSets (ADR-0012/0014, `controlPlane: true`); they keep their
   shape. Umbrellas apply only to the flat leaf apps.

Roll out incrementally: convert apps with live app-scoped deps one at a
time, verifying each with `kubectl kustomize` + `helm template` before the
next.

## Consequences

**Positive**
- A workload and the prerequisites it needs to start (TLS cert, app-scoped
  secret) sync as **one Application** with one health/sync status — no more
  implicit cross-Application ordering for app-scoped deps.
- Cluster-specific strings collapse to **one file per environment**
  (`environments/<env>/cluster.yaml` + the overlay patches). A second
  environment is a new `environments/<env>/` directory, not a sweep across
  every chart.
- Kustomize is used **only where it fits** (plain CRs), so no controller-wide
  `--enable-helm`, no loss of Helm features on the workload charts.
- Explicit `Certificate` CRs replace the `cluster-issuer` annotation shortcut,
  making the issuer an env-overlay knob instead of a hardcoded annotation.

**Negative**
- More files per app (a kustomize base + per-env overlay) — offset by deleting
  hardcoded strings and inline cert annotations.
- Two render engines to reason about per umbrella (Helm for A, kustomize for
  B). Mitigated by the strict split: never kustomize-over-Helm.
- Multi-source `$values` requires all sources reachable at sync time (already
  true; all sources are this repo).

**Neutral / follow-ups**
- The **ApplicationSet conversion** (ADR-0006's List/Matrix generator) is now
  independent and can land later — the Matrix (env × app) generator is the
  natural multi-env step once a second environment is live.
- `environments/` is deploy-state living in the chart-source repo. Acceptable
  while there's no separate deploy-state repo; revisit if one is created.
- Per-env workload value files (Source C) are defined lazily — only authored
  for a chart once a workload knob actually diverges between environments.

## Alternatives considered

- **Kustomize over Helm everywhere** (the literal first ask) — rejected:
  ArgoCD renders a source as Helm *or* kustomize; patching Helm output needs
  the controller-wide `--enable-helm` build option and forfeits Helm features.
  Heavy machinery for what per-env Helm values already do.
- **Helm-only, centralize via a `global:`/anchor block** — rejected for the
  multi-env goal: YAML anchors are single-file and don't compose across
  environments; good enough for one cluster, not for overlays.
- **Second Helm source for deps (ADR-0006 as written)** — rejected: the dep
  CRs are plain manifests; a kustomize overlay patches issuer/store per-env
  far more directly than templating a throwaway Helm chart.
- **Stand up a separate deploy-state repo for overlays** — deferred: the
  maintainer declined deploy-state machinery; `environments/` in-repo is the
  pragmatic interim.

## Rollout scope (initial)

Converted to umbrellas (have a live ingress `Certificate`): **grafana**,
**lightbridge-backend** (two certs: self-service + mcp). (**coder** uses the
same per-env cert overlay but as a child of the `coder` App-of-Apps
orchestrator — ADR-0019 — rather than a flat umbrella.)

Left single-source — **no app-scoped deps**: the observability backends /
collectors / CRD installers (alloy, mimir, loki, tempo, grafana-operator,
kube-state-metrics, node-exporter, prometheus-operator-crds, metrics-server,
aieg-crd/eg/aieg, authorino-operator, …) and apps whose only secrets are
*platform* (S3, Keycloak, DB) which stay external. Orchestrators (`models`,
`librechat`) keep their ApplicationSet shape.

Known residue: lightbridge's `api-main/api-mcp/api-usage` sub-ingresses and
`adminer`'s ingress are `enabled: false` and retain their inline
`cert-manager.io/cluster-issuer` value (inert config — no Ingress is
rendered). When any is enabled, give it an overlay `Certificate` and drop the
annotation, same as the live ones.

## Related

- Supersedes: ADR-0006
- Builds on: ADR-0012, ADR-0014 (orchestrators unchanged), ADR-0017
  (destination invariant; store stays external)
- Charts/files touched: `charts/apps/values.yaml` (umbrella entries),
  `environments/**` (new)
- Docs: `docs/architecture.md` (to note the `environments/` layer)
