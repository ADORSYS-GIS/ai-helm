# ADR-0057: Genericize a workload chart's own `values.yaml`; deployment specifics live in `ai-helm-values`

**Status:** Accepted
**Date:** 2026-06-23
**Deciders:** @stephane-segning
**Amends:** [ADR-0056](./0056-workload-values-in-ai-helm-values.md)

## Context

[ADR-0056](./0056-workload-values-in-ai-helm-values.md) moved each app's
`charts/apps` `valuesObject` (the orchestrator-level override) into
`ai-helm-values`. But a *leaf* workload chart's **own** `charts/<chart>/values.yaml`
was untouched, and `lightbridge-code-intelligence`'s baked a large set of
**deployment-specific literals as chart "defaults"**: the Keycloak OIDC issuer /
audience / client + public redirect URIs, the public ingress hostnames + ingress
class + cert-manager cluster-issuer + TLS secret names, the `ssegning-aws`
ClusterSecretStore + its SM bucket paths and property names, the CNPG
`DATABASE_URL` connection string (host/namespace/db), the in-cluster inference
gateway URLs + the embeddings/LLM model names, the registered GitHub App handle,
and the **full ~150-line reviewer system prompt**.

Two problems. First, this conflated chart *structure* with *this one deployment* —
the chart only ever renders correctly for `*.ai.camer.digital` on `auth.verif.fyi`,
so it is not reusable and "default" is a misnomer. Second, the reviewer prompt was
**duplicated** in both the chart and the `$values` override and had already
**diverged** (chart carried the old copy, the override the richer eng-practices
one). The `lightbridge-code-intelligence` app repo's **ADR-0037** (native agent has
no built-in prompt) already declares the runner has no baked-in prompt and
`ai-helm-values` is its source of truth, so the chart's copy was dead weight that
silently drifted.

## Decision

- **A workload chart's `values.yaml` ships only environment-agnostic base/default
  values** — controller topology, resources, probes, security contexts, ports,
  sync waves, product-level names (namespace / service account / image
  repositories / ConfigMap names), feature flags, and safety guards. **Every
  deployment-specific literal is empty/neutral in the chart** and supplied
  per-environment from `ai-helm-values` `environments/<env>/values/<app>.yaml` via
  the existing `$values` valueFiles ref (ADR-0056). Defaults-only renders are a
  deliberately non-deployable skeleton.
- **For `lightbridge-code-intelligence` specifically**, moved to the prod values
  file: the secret-store coordinates + SM property names, all OIDC settings, the
  public hostnames + the **entire ingress** (the chart now ships ingress
  `enabled: false` by default — no broken empty-host render), the `DATABASE_URL`
  `value` on all three control-plane roles (`dependsOn: DB_PASSWORD` stays in the
  chart, since only the URL string is env-specific and it must keep the
  `$(DB_PASSWORD)` ref), the gateway base URLs + the embeddings/LLM model names,
  the GitHub App handle (`config.appHandle` + the `GITHUB_APP_HANDLE` /
  `GITHUB_APP_INSTALL_URL` env literals), and the reviewer system prompt — whose
  stale chart copy is **deleted**, leaving `ai-helm-values` as the sole source per
  the app repo's ADR-0037.
- **Render-neutrality is the acceptance test.** Genericization must change *where*
  a literal is declared, never the rendered output. Verified by `helm template`ing
  the merged chart + prod override before and after, then diffing **normalized
  per-resource** (keyed by `kind`/`namespace`/`name`, keys sorted): all 26
  resources byte-identical, only document emission order differs (irrelevant to
  ArgoCD, which reconciles by resource identity). A naive line-diff is misleading
  here — deep-merging the moved ingress/env maps reorders the emitted documents.

## Consequences

**Positive**
- The chart is environment-agnostic and reusable; "default" now means default, not
  "Stephane's prod".
- The diverged ~150-line reviewer prompt is single-source again (the chart no
  longer carries a copy that drifts from the live one).
- Editing deployment config (hosts, OIDC, model, prompt) is a commit to
  `ai-helm-values` — decoupled from chart-logic changes and the chart governance
  flow — exactly where image tags + the orchestrator overrides already live.

**Negative / trade-offs**
- A defaults-only render is non-deployable. This is intentional and **fail-closed**:
  an empty `reviewSystemPrompt` emits no `review-system.md`, so review fails closed
  rather than running a weak baked-in prompt (app repo's ADR-0037).
- Verifying the real render needs both repos
  (`helm template charts/lightbridge-code-intelligence -f <values>/.../lightbridge-code-intelligence.yaml`).
- The override is not schema-validated against the chart, so a *missing* env-specific
  key would render silently on an empty default. Mitigated: ArgoCD always layers the
  prod override, and the highest-stakes value (the prompt) is fail-closed.

**Neutral / follow-ups**
- Resource emission order in the rendered manifest changes (cosmetic; no ArgoCD churn).
- `argocd-image-updater` still owns the `tag` fields in the values file; its
  helm-values write-back rewrites only those paths and preserves the new
  env/ingress/secrets/agents/config blocks (already proven across a tag bump).
- The same treatment could be applied to other single-tenant leaf charts later; this
  ADR establishes the convention, `lightbridge-code-intelligence` is the first.

## Alternatives considered

- **Leave env specifics as chart "defaults" (status quo)** — rejected: conflates
  chart structure with one deployment, and kept the reviewer prompt duplicated and
  silently drifting between the chart and the override.
- **Move only the duplicated prompt (minimal cleanup)** — rejected: fixes the worst
  drift but leaves the chart half-specialized (hostnames, OIDC, secrets still
  baked); the maintainer chose full genericization.
- **Parameterize `DATABASE_URL` into host/db/user sub-values rather than moving the
  whole string** — rejected: bjw-s app-template renders `env` literals against the
  sub-chart scope where top-level `.Values` aren't visible, so the connection string
  can't cleanly interpolate other chart values. Moving the opaque literal is simpler
  and provably render-neutral.

## Related

- Charts/files touched: `charts/lightbridge-code-intelligence/values.yaml`,
  `ai-helm-values:environments/prod/values/lightbridge-code-intelligence.yaml`
- Amends: [ADR-0056](./0056-workload-values-in-ai-helm-values.md)
- Relates to: the `lightbridge-code-intelligence` app repo's **ADR-0037** (native
  agent has no built-in prompt; the values repo is the prompt's source of truth),
  and [ADR-0055](./0055-oci-charts-and-image-updater-writeback-to-values-repo.md)
  ($values mechanism + image-tag write-back)
