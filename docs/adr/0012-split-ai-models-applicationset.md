# ADR-0012: Split `charts/ai-models` into three sub-charts + ApplicationSet

**Status:** Accepted
**Date:** 2026-05-24
**Deciders:** @stephane-segning

## Context

`charts/ai-models` was a single chart that rendered six K8s resource types
(`Backend`, `AIServiceBackend`, `BackendSecurityPolicy`, `BackendTLSPolicy`,
`AIGatewayRoute`, `BackendTrafficPolicy`) for ~15 models against 6 shared
upstream backends (fw-01, fw-02, deepinfra-01, deepinfra-02,
google-ai-studio-01, google-ai-studio-02). One ArgoCD Application owned
all of it.

Three problems with that shape:

1. **No per-model sync isolation.** Adding/removing/breaking one model
   re-renders and re-applies all of them. A bad pricing CEL on `gemma-4`
   destabilises every other route's `BackendTrafficPolicy` in the same
   sync.
2. **No per-model lifecycle.** "Roll out `glm-5p1` in canary first" or
   "pause `kimi-k2.6` while the provider stabilises" requires editing the
   monolithic values block — there's no Application boundary to wrap.
3. **Sync-wave granularity stops at the model layer.** Backends and models
   share the same Application, so backend changes always rebuild model
   resources too.

ADR-0006 introduced the multi-source ApplicationSet pattern for
`charts/apps`; ArgoCD ApplicationSet is also the right answer here, at
the lower granularity of "one Application per model".

## Decision

Split `charts/ai-models` into **three charts**:

| Chart | Role | What it renders | Sync-wave |
|---|---|---|---|
| `ai-models-backends` | Leaf — shared infra | `Backend` + `AIServiceBackend` + `BackendSecurityPolicy` + `BackendTLSPolicy` per upstream backend | `-1` |
| `ai-model` | Leaf — per-model | `AIGatewayRoute` + `BackendTrafficPolicy` for ONE model | `0` |
| `ai-models` | Orchestrator | One `ApplicationSet` (List generator) that emits 1 backends-App + N model-Apps | n/a (the AppSet itself, deployed by the existing `models` Application) |

The orchestrator's `templates/applicationset.yaml` iterates `.Values.models`
at Helm render time, producing one element per enabled model plus a
fixed element for backends. The ApplicationSet controller then creates
the child Applications. Each child's `helm.values` is the per-app YAML
inlined into the element (pre-rendered by Helm; substituted into the
template at AppSet-controller time via `goTemplate: true`).

**Data flow:**

```
charts/apps/values.yaml
  └─ "models" Application ──► charts/ai-models (orchestrator)
                                └─ renders 1× ApplicationSet
                                    ├─ child App: ai-models-backends   (wave -1)
                                    │   └─ charts/ai-models-backends
                                    │       └─ Backend × 6, AIServiceBackend × 6,
                                    │          BackendSecurityPolicy × 6,
                                    │          BackendTLSPolicy × 6
                                    └─ child App: ai-models-<modelName> (wave 0)
                                        └─ charts/ai-model
                                            └─ AIGatewayRoute × 1,
                                               BackendTrafficPolicy × 1
                                        × N enabled models
```

The existing `models` Application entry in `charts/apps/values.yaml` is
**unchanged** — it still points at `path: charts/ai-models`, which now
emits the ApplicationSet rather than the K8s resources directly.

The orchestrator's `argocd.targetRevision` value is pinned to
**`claude/magical-bohr-390242`** while this PR is under review, so the
children sync the leaf charts from this branch. On merge, flip the
default to `main` in a follow-up commit; the value is parameterised.

## Consequences

**Positive**
- **Per-model ArgoCD Applications.** Each model has its own
  `Application` resource with its own sync status, health, history,
  and revert button in the UI. Operating a single model — pause,
  reorder sync-wave, redeploy — is a one-Application change, not a
  values diff that touches the whole map.
- **Failure isolation.** A pricing-CEL syntax error in `gemma-4` fails
  only `ai-models-gemma-4`; every other model continues to sync.
- **Backend lifecycle decoupled.** `ai-models-backends` syncs at wave
  -1 and is rarely touched. Model-level config changes don't trigger
  Backend / AIServiceBackend / BackendSecurityPolicy reconciliation.
- **Cost-helper logic consolidated** into the `ai-model` chart's
  `_helpers.tpl`. The pre-split chart had it in `ai-models`; same code,
  closer to where it's used.
- **Disabled models are gone, not greyed-out.** A model with
  `enabled: false` is not emitted into the AppSet element list, so the
  AppSet controller deletes any previously-generated child Application
  for it. The pre-split chart `range`-skipped them but left no audit
  trail.
- **Per-model claim-based annotations become trivial** for ADR-0010's
  image-updater (once any image lives on the model layer; today no
  model uses cluster-internal images, but the pattern is in place for
  future model-server self-hosting).

**Negative**
- **More moving parts.** Three charts where there was one. The AppSet
  manifest is non-trivial — pre-rendering element values as YAML
  strings + AppSet-side `goTemplate` substitution has a learning curve
  documented in the chart comments.
- **AppSet templating quirks.** `nindent`, the literal `{{ "{{.field}}" }}`
  escape, and the `values: |  {{ .valuesYaml | nindent 12 }}` pattern
  must stay in sync with the per-element YAML format. Validated by
  helm-template before commit.
- **Two-layer rendering.** `helm template charts/ai-models` shows the
  ApplicationSet, NOT the final K8s resources. Verifying a model's
  output requires `helm template charts/ai-model -f <child-values>`.
  Documented in the chart README (to-be-written).
- **`targetRevision` of leaf charts is set in values, not on the parent
  Application.** Forgetting to flip back to `main` on PR merge would
  leave the cluster pulling leaf charts from a closed branch. Mitigated
  by a TODO comment in the orchestrator's `values.yaml` and by the
  follow-up task to flip on merge.

**Neutral / follow-ups**
- Once stable, consider promoting `models` (the existing umbrella
  ArgoCD Application) from a Helm-rendered ApplicationSet to a direct
  ApplicationSet resource managed by `charts/apps` — saves one
  indirection. Defer until the pattern proves itself.
- The orchestrator's `_helpers.tpl` could share cost-expression logic
  with `ai-model/_helpers.tpl` via the `common` library, but they're
  not used by both today (only `ai-model` renders cost expressions —
  the orchestrator just inlines pricing config as values data).
  Single-owner today; revisit if a second renderer needs the same
  helpers.

## Alternatives considered

- **Helm `dependencies:` composition (parent → 2 sub-charts).** The
  old chart consumed via Helm aliases. Doesn't get us per-model
  Applications — everything still syncs as one unit. Rejected.
- **Per-model file under `charts/ai-models/values/<model>.yaml` + AppSet
  Files generator.** Different shape: each model becomes a Git file
  the AppSet discovers. Cleaner in some ways (adding a model = drop
  a file), but loses the shared-defaults YAML-anchor pattern the
  current values use, and the per-model files would duplicate
  `gatewayRef` / `plans` / `backendsInventory` everywhere. The List-
  generator-with-Helm-templating shape preserves DRY. Could be a
  successor ADR.
- **Drop the orchestrator chart entirely** — have `charts/apps`
  iterate `.Values.aiModels` directly and emit Applications. Couples
  the apps chart to AI-model knowledge it doesn't need. Rejected.

## Migration verification

`helm template charts/ai-model -f <per-model-values.yaml>` and
`helm template charts/ai-models-backends` both produce the **same
K8s resources as the pre-split chart**. The orchestrator emits one
ApplicationSet that resolves to identical Applications post-split.
Cluster-side, the existing `Backend`, `AIServiceBackend`, etc. resources
will be re-adopted by the new child Applications via ArgoCD's tracking
labels — coordinate the merge with a brief sync pause to avoid duplicate
ownership in flight.

## Related

- ADR-0006 — multi-source ApplicationSet pattern for `charts/apps` (same
  fundamental tool, different granularity)
- ADR-0010 — image-updater write-back (per-model Applications make this
  cleaner in the future)
- 2026 audit punch-list item 2 — Envoy AI Gateway v0.6 + `v1beta1` CRD
  migration; touches every `aigateway.envoyproxy.io/v1alpha1` reference in
  the new leaf charts. Worth doing in the same pass as the v0.6 bump.

## Related files

- `charts/ai-models/` — orchestrator (Chart.yaml + values.yaml + ApplicationSet template)
- `charts/ai-models-backends/` — shared backends leaf
- `charts/ai-model/` — per-model leaf
- `charts/apps/values.yaml` — `models` Application entry unchanged (still
  points at `charts/ai-models`); 10 other self-referencing `targetRevision`
  fields flipped to `claude/magical-bohr-390242` for end-to-end branch
  testing — flip back to `main` on PR merge
