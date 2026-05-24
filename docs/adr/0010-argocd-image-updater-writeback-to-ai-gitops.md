# ADR-0010: ArgoCD Image Updater with git write-back to `ai-gitops`

**Status:** Accepted
**Date:** 2026-05-24
**Deciders:** @stephane-segning

## Context

We operate two repos in the GitOps system:

- **`ai-helm`** (this repo) — the Helm charts: chart logic, default values,
  templates, helpers.
- **`ai-gitops`** (separate) — the ArgoCD `Application` / `ApplicationSet`
  manifests that *reference* `ai-helm`'s charts and provide
  environment-specific overrides (including image tags). This is what
  ArgoCD actually syncs into the cluster.

Upstream container registries publish new tags continuously — LiteLLM,
OpenCode, Lightbridge `sha-*` builds, model-serving images, grafana,
operators. Today bumping a deployment to a new image tag means a human
opens a PR against `ai-gitops` with an edited values override. The
result: bumps batch into infrequent multi-change PRs, lag behind upstream
by weeks, and routine-vs-meaningful changes get mixed together.

**`argocd-image-updater` is already installed in the cluster.** What's
missing is the per-application configuration that opts each one in.

## Decision

Use `argocd-image-updater` configured **per-Application via annotations**
(one annotation block per app, the "once each per application" pattern).
On every poll, image-updater monitors each app's image(s), and when a
new tag matches the update strategy, it **opens a PR against
`ai-gitops`** (not against this repo). Branch-protection rules on
`ai-gitops/main` require the standard CI checks (`helm-lint`,
`dashboards-drift`, the planned `kubeconform`); **auto-merge** is enabled,
so a green CI flips the PR to `main`. ArgoCD reconciles within its
refresh interval.

**Auth:** image-updater uses the **existing GitHub App** with
`contents: write` + `pull-requests: write` scopes scoped to `ai-gitops`.
No new credential surface; same App that the rest of the GitOps
automation already operates with.

**Per-Application annotations** (in `ai-gitops`, not here):

```yaml
metadata:
  annotations:
    argocd-image-updater.argoproj.io/image-list: |
      gw=docker.io/envoyproxy/envoy
    argocd-image-updater.argoproj.io/gw.update-strategy: semver
    argocd-image-updater.argoproj.io/gw.allow-tags: regexp:^v1\.\d+\.\d+$
    argocd-image-updater.argoproj.io/write-back-method: git
    argocd-image-updater.argoproj.io/write-back-target: helmvalues:./apps/<app>/values.yaml
    argocd-image-updater.argoproj.io/git-branch: image-updater/<app>-gw
```

**Update strategies match the tag style:**

| Tag style | Strategy | Example consumer |
|---|---|---|
| Upstream semver releases | `semver` (with `allow-tags`) | grafana-operator, envoy-gateway, LiteLLM |
| Mutable refs (`:main`, `:latest`) | `digest` (pin to digest, refresh on digest change) | mcpo, mcps `:latest` |
| Sortable date / SHA tags | `name` (alphabetical newest) | lightbridge `sha-*` builds |
| Newest by registry timestamp | `latest` | use sparingly — last-resort |

**`ai-helm` side** (this repo) responsibilities are narrow but real:
- Chart values expose image fields in a canonical structure
  (`image: { repository, tag }`) that image-updater knows how to write to.
- Avoid composite tag strings (e.g. `tag: "{{ .Values.global.version }}"`)
  — image-updater can't resolve template strings at write-time.
- Document image-updater compatibility per chart so `ai-gitops` knows
  which apps are wire-up-ready and which need a chart-side fix first.

## Consequences

**Positive**
- Upstream releases land within minutes of registry publication
  (PR open → CI → auto-merge → ArgoCD sync). Aligns the cluster with
  what's actually current upstream.
- Each PR is one bump → trivial review (when needed) and trivial revert.
- The `ai-gitops` git log becomes a precise audit trail: every
  production-affecting image change, who/what bumped it, when CI passed.
- No human toil for routine bumps. Humans only touch chart-level decisions
  (`targetRevision` of the chart itself, value overrides that change
  behaviour).
- Repos stay cleanly separated: `ai-helm` for chart logic,
  `ai-gitops` for what's deployed. Image-updater never touches this repo.

**Negative**
- Dependency: a compromised registry or a bad upstream tag becomes
  one green CI away from prod. Mitigated by strict `allow-tags` regexes,
  the Trivy scan already running in `release-helm-charts.yml`, and
  (in `ai-gitops`) optional human-approval bypass for the highest-trust
  Applications.
- Two repos to keep in sync mentally. `ai-helm` evolves chart logic;
  `ai-gitops` mostly evolves image pins. Cross-references in commit
  messages help.
- Image-updater needs read credentials for every monitored registry.
  Credentials proliferate (one secret per registry).

**Neutral / follow-ups**
- ADR-0006 (multi-source ApplicationSet) becomes simpler when each
  Application has its own values file — that's a clean write-back target.
- Inventory `ai-helm` chart values for image-updater-hostile shapes
  (audit task). Most charts are already clean; `mcpo` and `mcps` have
  flagged anti-patterns from the 2026 currency audit (composite tag
  template / `:latest`) that should be tidied as we opt them in.
- Image-updater's notion of "auto" doesn't include chart-version bumps
  (`targetRevision`) — those stay a human PR action.
- Once stable, consider promoting image-updater to also watch chart-OCI
  repositories for `targetRevision` bumps (a different update mode, more
  invasive — defer).

## Alternatives considered

- **Renovate Bot for image bumps** — broader scope (also dep files,
  Helm chart versions, Go modules). Heavier configuration; one more
  bot identity. Rejected for the image-only use case since
  `argocd-image-updater` is purpose-built and we already operate it.
  May revisit Renovate later for *chart-version* bumps (which
  image-updater doesn't do).
- **Direct commit to `ai-gitops/main`** — no CI gate, fastest. Rejected
  per the agreed PR + auto-merge flow.
- **Write-back to `ai-helm` chart values** — would mix chart-source-of-
  truth with deployment-state. Conflates the two repos. Rejected.
- **Per-Application Renovate config in `ai-gitops`** — same outcome as
  image-updater, more weight. Rejected on installed-tool grounds.
- **Manual-merge PRs only** — maximum control, merge fatigue at the
  volume of upstream releases the AI/observability stack emits.
  Rejected as the default; available per-app for the few that warrant it.

## Related

- ADR-0006 (multi-source ApplicationSet) — image-updater works cleanest
  when each app has its own values file → natural write-back target
- ADR-0009 (GitHub App reuse pattern) — same App scoped to `ai-gitops`
- 2026 currency audit (`docs/2026-currency-audit.md`) — flagged
  `mcpo` / `mcps` `:latest` and composite-tag patterns that image-updater
  needs cleaned up before opting in those charts
- `ai-gitops` repo (where the annotations actually land — out of scope
  for `ai-helm`)
