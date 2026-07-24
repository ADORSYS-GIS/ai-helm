# ADR-0087: Move librechat-app workload config to ai-helm-values

**Status:** Proposed
**Date:** 2026-07-24
**Deciders:** @stephane-segning

## Context

[ADR-0056](0056-workload-values-in-ai-helm-values.md) moved every flat
`charts/apps` `valuesObject` — and the `observability`/`lightbridge`
**App-of-Apps** orchestrator children — into the private `ai-helm-values` repo,
so *how to render* stays in `ai-helm` and *what is deployed* lives in
`ai-helm-values`. The **`librechart` leaves** (`librechat-app`,
`librechat-search`, `librechat-opencode-wellknown`) were deliberately left out:
they are an **ApplicationSet** orchestrator (ADR-0014), and its children "carry
their own values" — the ApplicationSet injects no `$values` source today.

The result is that `charts/librechat-app/values.yaml` still holds the entire
LibreChat workload config inline — the ~900-line `config:` block (models, MCP
servers, model-specs, token config, skill sync, interface) plus the OIDC/env
knobs. That is exactly the *deployed state* ADR-0055/0056 want in the values
repo, and it now changes often (models, personas, MCPs). We choose to finish the
migration for this leaf.

## Decision

Extend the ADR-0056 split to the `librechart` leaves, starting with
`librechat-app`:

1. **`ai-helm-values`** — add `environments/prod/values/librechat-app.yaml`
   holding the LibreChat `config:` block (the `librechat.yaml` content). This is
   the workload-config boundary; deployment structure (image, volumes, env,
   ExternalSecrets, ingress) stays in the chart.
2. **`charts/librechart`** — teach the ApplicationSet per-child
   `valuesFromRepo`: when a child sets it, the generated Application gets a
   second `$values` source (`argocd.valuesRepoURL` @ `main`) and
   `helm.valueFiles: [$values/environments/<env>/values/<child>.yaml]` +
   `ignoreMissingValueFiles`, mirroring what ADR-0056 phase 3 did for the
   `observability`/`lightbridge` App-of-Apps. Set it on the `librechat-app`
   child.
3. **`charts/librechat-app`** — remove the inline `config:` block (keep only the
   structural defaults + the deployment/secret/ingress scaffolding).

`config:` is the only thing that moves; `librechatSecrets`, the `env` block
(incl. `OPENID_SCOPE`), and every ExternalSecret stay in the chart.

### Sequencing (load-bearing)

- **Values-repo-FIRST.** `librechat-app.yaml` must be on `ai-helm-values` `main`
  **before** the chart drops its inline `config:` — otherwise
  `ignoreMissingValueFiles` silently falls the chart back to defaults, which for
  LibreChat means **no endpoints/models = broken chat**.
- **After the in-flight config PRs land.** Because the split relocates the whole
  `config:` block, it must be built on a `main` that already includes the open
  LibreChat config PRs (skill sync #724, icon URLs #725) — otherwise merging the
  split would revert them. Merge those, then snapshot the final `config:` into
  the values file.

## Consequences

**Positive**
- LibreChat's deployed behavior lives with the rest of the deployed state; model/
  persona/MCP edits are `ai-helm-values` commits, not chart releases.
- The `librechart` ApplicationSet gains the same `valuesFromRepo` capability the
  other orchestrators already have — reusable for the other two leaves later.

**Negative**
- A new cross-repo coupling + the unforgiving values-repo-first hazard (a
  mis-ordered merge breaks chat, not just a render).
- Cannot be verified from the chart repo — needs a live smoke test post-cutover.

**Neutral / follow-ups**
- `librechat-search` + `librechat-opencode-wellknown` can follow the same shape
  when their config is worth externalizing; not done here.
- Whether to also externalize the `env`/OIDC knobs is left open — the boundary
  chosen here is "the `librechat.yaml` config object", matching ADR-0056.

## Alternatives considered

- **Keep it inline (status quo)** — rejected: it's deployed state that changes
  often; ADR-0055/0056 doctrine says it belongs in `ai-helm-values`.
- **Move env/secrets too** — deferred: ExternalSecrets are chart-owned by
  design, and the env block is deployment structure; moving only the `config:`
  object keeps a clean, ADR-0056-consistent boundary.
- **A single big-bang across all three librechart leaves** — rejected: start
  with the one leaf whose config actually churns; prove the ApplicationSet
  `valuesFromRepo` path once.

## Related

- [ADR-0056](0056-workload-values-in-ai-helm-values.md) — the split this extends.
- [ADR-0055](0055-oci-charts-and-image-updater-writeback-to-values-repo.md) — OCI float + values-repo model.
- [ADR-0014](0014-split-librechart-and-opencode-wellknown.md) — the librechart orchestrator/leaf pattern.
- PRs #724 (skill sync) + #725 (icon URLs) — must merge before the config snapshot.
