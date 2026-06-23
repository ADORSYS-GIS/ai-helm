# Continuous delivery: OCI charts + image-updater write-back (ADR-0055)

This is the **how**. The **why** is [ADR-0055](./adr/0055-oci-charts-and-image-updater-writeback-to-values-repo.md),
which supersedes the tag-based release model ([ADR-0031](./adr/0031-tag-based-deploys.md),
[`releasing.md`](./releasing.md)) and the deferred write-back ([ADR-0013](./adr/0013-defer-image-updater-writeback.md)).
Workload **config** moved to the values repo too ([ADR-0056](./adr/0056-workload-values-in-ai-helm-values.md)).

> **What lives where:** `ai-helm` holds chart logic + templates; the PRIVATE
> **`adorsys-gis/ai-helm-values`** holds everything *deployed* — per-app values,
> image tags, and per-env deps overlays. That repo documents its own layout, full
> per-app inventory, and the values-repo-first rule in **`ai-helm-values/README.md`**;
> the boundary contract is in [`CLAUDE.md`](../CLAUDE.md) ("ai-helm ↔ ai-helm-values").

> **Status: ✅ cutover complete (2026-06-22).** The entire fleet — flat apps, all
> five orchestrators, and the gateway/auth — runs on continuous delivery. The root
> `ai-apps-v2` tracks `main`; `tools/release.sh`, `docs/releasing.md`, the
> `release-*` tags, and this repo's `environments/` tree are retired/removed. The
> phase-by-phase steps below are kept as the reference for *how* it was done and
> how to onboard any future app.

## The model in one picture

```
 ai-helm (this repo)            ghcr.io/adorsys-gis/charts        ai-helm-values (PRIVATE)
 ─────────────────────          ──────────────────────────        ────────────────────────
 chart SOURCE + apps   ──merge──▶ OCI charts (auto-semver,         environments/<env>/
 umbrella + workflows    to main  float on a range)                  values/<app>.yaml  ◀── image-updater
                                          │                          deps/<app>/  (migrated)    write-back
                                          ▼                          cluster.yaml              (direct commit,
 root ai-apps-v2 (home-os) ──renders──▶ charts/apps ──emits──▶ child Applications              cosign-gated)
                                                                  Source A = OCI chart @ range
                                                                  Source B = $values (ai-helm-values)
                                                                  Source C = deps overlay
```

- **Routine image bumps need zero human action**: a new signed image is published →
  `argocd-image-updater` commits the new tag into `environments/<env>/values/<app>.yaml`
  on `ai-helm-values` `main` → ArgoCD syncs.
- **Chart-logic changes ship on merge**: merge to `ai-helm` `main` → the
  [`publish-charts-oci`](../.github/workflows/publish-charts-oci.yml) workflow publishes
  the changed charts → child Applications floating on `argocd.chartVersionRange` pick
  up the newest version on the next reconcile.
- **No more `release.sh`, no manual root repoint per release.** Rollback is `git revert`
  in `ai-helm-values` (+ optionally pin a chart version to roll a chart back).

## Prerequisites (out-of-band — maintainer / cluster, NOT in this repo)

1. **Create the private repo `adorsys-gis/ai-helm-values`.** ✅ Done (2026-06-22) —
   created private and seeded from this repo's `environments/` tree (`base/` + `prod/`,
   incl. `cluster.yaml` + `deps/`) plus the `environments/<env>/values/` dirs + READMEs.
   Per-app `values/<app>.yaml` files are added as each app is flipped (Phase B / D).
2. **OCI charts package visibility — NOT a required step.** Chart *pulls* need no
   special handling: this org defaults new GHCR packages to **public** (verified — the
   first `publish_all` run pushed 27/27 charts and `charts/core-gateway` came out
   `visibility=public`, anonymous `helm show chart` works), **and** even a private
   package is fine — ArgoCD on this cluster already pulls private GHCR/OCI packages with
   its existing registry creds (the `vymalo` / `vaam-store` Apps prove it). So there is
   no public-flip prerequisite and no new chart-pull credential. (Charts carry no secrets
   regardless — ESO injects at sync.)
3. **Credentials for the PRIVATE values repo — ALREADY SATISFIED.** ✅ Both read and
   write are covered by the existing org-wide ArgoCD `repo-creds` secret
   `argocd/github-app-creds--adorsys-gis` (the **`argocd-ssegning`** GitHub App, app_id
   2926172, installation 112379420 — `repository_selection: all`, `contents: write`).
   Because it is a `repo-creds` template scoped to the prefix `https://github.com/adorsys-gis`,
   it applies to **every** repo under that org, including the private `ai-helm-values` —
   so no per-repo secret is needed:
   - **ArgoCD read** of Source B (`$values`) → the prefix match provides it.
   - **image-updater write** → the same App has `contents: write` across all org repos;
     reference it as `git-credentials: secret:argocd/github-app-creds--adorsys-gis`.
   (Verified 2026-06-22. Nothing to provision. If the App were ever scoped to *selected*
   repos, `ai-helm-values` would need adding to its installation — but it is `all` today.)

## Cutover order of operations

Do these in order; each is safe because nothing references the new pieces until the flip.

**Phase A — publish.** ✅ Done — the machinery merged (PR #447) and the first
`publish_all` run pushed 27/27 charts. Confirm any time:
`helm show chart oci://ghcr.io/adorsys-gis/charts/<chart> --version <v>` resolves, and the
pulled `.tgz` contains the vendored subcharts (`charts/common*.tgz`, `charts/bjw-template*.tgz`).
No package-visibility step is needed (Prereq 2). ⚠️ Note: a brand-new workflow does
not run on the push that introduces it — the first publish was a manual
`workflow_dispatch` with `publish_all: true`; subsequent `charts/**` merges publish
the changed charts automatically.

**Phase B — seed values.** For each app you will migrate, create
`environments/<env>/values/<app>.yaml` in `ai-helm-values` with **just the image-tag field**
at the exact path the app's `helm.image-tag` annotation will target (see the recipe). Extract
the current tag from the app's chart default / inline `valuesObject`. `ignoreMissingValueFiles:
true` (set by the template) means an app flipped before its file exists just uses chart
defaults — so seeding can lag, but seed before enabling write-back to avoid a first-sync flap.

**Phase C — activation.** ✅ Credentials already exist (Prereq 3 — the org-wide
`github-app-creds--adorsys-gis` repo-creds). Just add an entry per app to
`charts/imageupdater` `values.yaml` `imageUpdaters[]` (`namePattern: aii-<app>`,
`useAnnotations: true`).

**Phase D — flip apps, one at a time.** For each app, add the write-back annotations + set
`chart:` on its `charts/apps` entry (recipe below). After each: `kubectl --context admin@homeos
-n argocd get application aii-<app>` → expect `Synced`/`Healthy`. Watch for `ComparisonError`
(missing read cred) and write-back path errors in the image-updater logs. Only then do the next.

**Phase E — root + env overlays.** Once apps float:
- The root `ai-apps-v2` stays in **home-os** rendering `charts/apps` from this git repo
  (do **not** OCI-ify the umbrella). No change needed unless you also move `environments/`.
- When `environments/` is fully migrated to `ai-helm-values`, set `argocd.depsRepoURL:
  https://github.com/adorsys-gis/ai-helm-values` + `argocd.depsTargetRevision: main` in
  `charts/apps/values.yaml` (uncomment) and delete `environments/` from this repo.

**Phase F — retire the tag model.** Delete `tools/release.sh` + `docs/releasing.md`; remove the
`selfTargetRevision` tag-pin note + the per-app `targetRevision` pins that are now OCI sources;
update the canonical note in `charts/apps/values.yaml`. (Orchestrators — Phase G.)

**Phase G — orchestrator children → OCI.** In each ApplicationSet template
(`charts/{ai-models,librechart,observability,mcps,lightbridge}/templates/applicationset.yaml`)
change `template.source` from `path: {{ .chartPath }}` + git repoURL to `chart: {{ .chartName }}`
+ `repoURL: oci://ghcr.io/adorsys-gis/charts` + `targetRevision: {{ .chartVersionRange }}`; have
each list element emit `chartName` (the bare chart name) instead of `chartPath`. Self-hosted
model write-back additionally needs a `ref: values` source + per-child annotations on the
ApplicationSet `template.metadata.annotations`.

## Per-app onboarding recipe (the repeatable pattern)

On the app's entry in `charts/apps/values.yaml`, (1) set `chart:` (activates OCI mode +
the `$values` source), and (2) add the image-updater annotations. Model on
`lightbridge-code-intelligence`:

```yaml
  - name: <app>
    chart: <oci-chart-name>          # ← activates OCI Source A + $values Source B
    # releaseName: <app>             # optional; defaults to .name
    # valuesObject: { … }            # optional static config (image tags go to $values, not here)
    additionalAnnotations:
      argocd-image-updater.argoproj.io/image-list: main=ghcr.io/adorsys-gis/<image>
      argocd-image-updater.argoproj.io/main.update-strategy: newest-build      # first-party sha
      argocd-image-updater.argoproj.io/main.allow-tags: regexp:^sha-[0-9a-f]+$
      argocd-image-updater.argoproj.io/main.helm.image-name: <values path>.image.repository
      argocd-image-updater.argoproj.io/main.helm.image-tag: <values path>.image.tag
      argocd-image-updater.argoproj.io/main.signature-type: cosign             # first-party only
      argocd-image-updater.argoproj.io/main.cosign.certificate-oidc-issuer: https://token.actions.githubusercontent.com
      argocd-image-updater.argoproj.io/main.cosign.certificate-identity-regexp: ^https://github\.com/adorsys-gis/<repo>/\.github/workflows/.*$
      argocd-image-updater.argoproj.io/write-back-method: git
      argocd-image-updater.argoproj.io/git-repository: https://github.com/adorsys-gis/ai-helm-values.git
      argocd-image-updater.argoproj.io/git-branch: main
      argocd-image-updater.argoproj.io/write-back-target: helmvalues:/environments/prod/values/<app>.yaml
      argocd-image-updater.argoproj.io/git-credentials: secret:argocd/github-app-creds--adorsys-gis
    destination:
      namespace: <ns>
```

Then add the matching `imageUpdaters[]` entry in `charts/imageupdater` and seed
`ai-helm-values:/environments/prod/values/<app>.yaml`.

**Strategy by image kind:**
| Image kind | `update-strategy` | `allow-tags` | signature |
|---|---|---|---|
| First-party `sha-*` build | `newest-build` | `regexp:^sha-[0-9a-f]+$` | cosign (verified) |
| Upstream semver | `semver` | `regexp:^v?\d+\.\d+\.\d+$` | none (unsigned auto-lands — keep tight) |
| Mutable ref (`:latest`,`:main`) | `digest` | — | none |

> **`write-back-target` leading slash:** keep the `/` (`helmvalues:/environments/...`). With
> an OCI Source A there is no chart source path so it resolves cleanly against the values-repo
> root, but the slash is still the correct, unambiguous form.

## Moving workload values into `ai-helm-values` (ADR-0056)

Beyond image tags, a singular-`source:` app can keep its whole Helm `valuesObject` in
the values repo instead of inline in `charts/apps/values.yaml`:

1. **Seed the file FIRST** at `ai-helm-values:/environments/<env>/values/<app>.yaml`
   (the dedented `valuesObject` content), commit to `main`. The `render-check.yml`
   workflow there YAML-validates it and (for OCI-sourced charts) `helm template`s it.
2. **Then** in `charts/apps/values.yaml`: add `valuesFromRepo: true` to the app entry
   and **delete** its inline `valuesObject`. The template injects the `$values`
   valueFiles ref (+ `ignoreMissingValueFiles` + the `ref: values` source).

```yaml
  - name: <app>
    valuesFromRepo: true             # ← inject $values/environments/<env>/values/<app>.yaml
    depsOverlay: environments/<env>/deps/<app>   # optional, still works
    source:
      repoURL: oci://…/charts/<chart>   # or upstream OCI / git
      chart: "."
      targetRevision: ">=0.0.0"
      helm:
        releaseName: <app>           # keep; valuesObject is gone
```

> ⚠️ **Ordering is load-bearing.** Because of `ignoreMissingValueFiles`, if the
> `charts/apps` change merges *before* the values file exists on `ai-helm-values`
> `main`, the app renders on **chart defaults** — for `security-policies` that drops
> the entire Authorino AuthConfig. Always: values-repo PR/commit first, `charts/apps`
> PR second. Migrated so far: `security-policies`, `eg`, `opencode-k8s-agent`.

## Rollback

- **A bad image tag:** `git revert` the image-updater commit in `ai-helm-values` (or set the
  tag back manually). ArgoCD syncs the prior tag on the next reconcile.
- **A bad chart version:** pin the offending app's `chartVersionRange` to a known-good exact
  version (or a `< badversion` range) in `charts/apps`, or republish a higher patch with the
  fix. There is **no immutable fleet snapshot** — reproducing a past state means a values-repo
  commit *plus* knowing which chart versions the ranges resolved to then.

## Gotchas (full list in ADR-0055 / the plan)

1. **Private values repo creds** (write + ArgoCD read) — both already provided by the org-wide `github-app-creds--adorsys-gis` repo-creds (prefix `https://github.com/adorsys-gis`, `repos=all`, `contents=write`). Nothing to provision; if that App were ever scoped to *selected* repos, add `ai-helm-values` to its installation or apps go `ComparisonError`.
2. **`file://` library change fans out** — the OCI workflow republishes all dependents of `common`/`bjw-common`/`bjw-template`; a consumer pulling a chart that wasn't republished keeps the old vendored library.
3. **Semver ranges skip pre-releases** unless written `-0` — the publish workflow emits clean `X.Y.Z`, so `>=0.0.0` matches.
4. **`$values` requires plural `sources:` + exactly one `ref`** — the template owns the single `ref: values` source; never add another `ref`.
5. **Renaming the imageupdater app prunes+recreates the control object** at cutover (brief CR gap; image-updater resumes).
6. **Upstream/model images opted into write-back auto-land unsigned in-range tags** — a bad upstream tag reaches prod in one reconcile; keep `allow-tags` tight.
