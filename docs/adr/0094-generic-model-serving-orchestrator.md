# ADR-0094: Replace the per-model serving charts with one orchestrator plus a generic leaf

**Status:** Accepted
**Date:** 2026-07-26
**Deciders:** @stephane-segning

## Context

Self-hosted model serving grew by copying a chart. `charts/model-serving-qwen3-4b`
was cloned into `-qwen3-5`, `-qwen3-8b`, `-qwen25-3b-awq`, `-deepseek-r1-1-5b`,
`-ministral-3b`, `-qwen2-vl-2b` and `-zimage-turbo`: eight charts of ~300 values
lines each, differing in a model id, a HuggingFace repo, a handful of engine
flags, and nothing else. Each also needed its own `charts/apps` Application entry
and its own `charts/ai-models` backend, and because there was exactly one GPU,
every one of them carried an `enabled: false` and a comment naming which model
had displaced it. Adding a model meant touching four files across two catalogs,
copying ~300 lines nobody re-read, and cutting a release.

[`docs/patterns/self-hosted-model-serving.md`](../patterns/self-hosted-model-serving.md)
§9 recognised this at the time and committed to generalising "at model #3+". We
reached model #8 without doing it.

Two facts now force the issue. Two GPU nodes joined `home-remote`
([ADR-0092](0092-longhorn-for-hetzner-gpu-nodes.md)), so "one GPU, one model,
swap forever" — the constraint the copy-paste shape was built around — no longer
holds. And the copies had begun to diverge in ways that matter: the seed Job's
download command is hardcoded in each chart's bjw-template values under a
`⚠️ keep in sync with model.hfRepo` comment, because a Helm parent cannot compute
**subchart** values at render time. A chart that serves one set of weights while
downloading another is a live possibility in that design, not a hypothetical.

## Decision

Adopt the orchestrator-plus-leaves pattern already used for `ai-models` and
`librechart` ([ADR-0012](0012-split-ai-models-applicationset.md) /
[ADR-0014](0014-split-librechart-and-opencode-wellknown.md)):

- **`charts/model-serving`** — the orchestrator. Emits one `ApplicationSet` whose
  List generator produces one child per enabled entry in its `models:` catalog.
  `controlPlane: true` in `charts/apps`, so the ApplicationSet lands
  in-cluster/argocd while its children deploy to `home-remote`.
- **`charts/model-server`** — the generic leaf. One model's worth of resources,
  keeping the [ADR-0030](0030-merge-model-and-proxy-into-one-statefulset-bjw.md)
  hybrid shape: `bjw-template` renders the StatefulSet, seed Job and Service; the
  chart's own templates render the PVC, ExternalSecrets, CiliumNetworkPolicy and
  ServiceMonitor.

**Engine expansion lives in the orchestrator**, not the leaf. `_helpers.tpl`
expands a compact catalog entry into the complete `modelServing:` block — engine
image, server args, seed script, probes, GPU scheduling, mounts. This is the
crux: the orchestrator writes each child's values as a YAML string, so it *can*
derive subchart values from one source of truth, which the leaf cannot. The
hardcoded-seed-args hazard is designed out rather than documented.

Two engine profiles ship: **`llamacpp`** (GGUF) and **`vllm`** (safetensors, with
opt-in LMCache). GPU placement is expressed as a `nvidia.com/gpu: 1` resource
request with the fleet's toleration and nodeSelector, so the scheduler assigns
cards and an over-subscribed fleet produces a `Pending` pod with a legible event
instead of a human swap procedure.

Adding, replacing or removing a model is **one entry in
`charts/model-serving/values.yaml`**, plus its `charts/ai-models` catalog entry
when it should be user-reachable. `tools/check-model-catalogs.sh` fails CI if a
cluster-local gateway backend has no server behind it.

The existing `charts/model-serving-*` charts are **retained, not deleted**:
`zimage-turbo` is live on `admin@homeos` and the rest are its rollback set.
Retiring them is a decommissioning exercise on that cluster. They are marked
legacy in `charts/apps/values.yaml`; no new model may use that shape.

## Consequences

**Positive**

- Adding a model goes from ~300 copied lines across four files to ~15 lines in
  one, reviewable by someone who has never opened a Helm template.
- The seed script is derived from the same values as the server args, so the
  "downloads one model, serves another" failure mode is structurally impossible.
- Both engines are exercised by CI fixtures (`ci/llamacpp-values.yaml`,
  `ci/vllm-values.yaml`), which the per-model charts never were.
- Fleet-wide changes — a security context, a probe budget, a seed image — are one
  edit instead of eight.
- Multiple concurrent models become ordinary scheduling rather than a manual
  enable/disable dance across charts.

**Negative**

- Indirection: reading a rendered StatefulSet now means reading the orchestrator's
  helper, not a values file. Mitigated by the documented render command in
  `charts/model-serving/README.md`, which prints exactly what a child receives.
- A bug in `_helpers.tpl` affects every model at once, where a bug in a copied
  chart affected one. The CI fixtures and the render check are the counterweight.
- Two chart generations coexist until `admin@homeos` is decommissioned, and the
  legacy charts are a tempting (wrong) template for a newcomer.

**Neutral / follow-ups**

- The catalog stays in `charts/model-serving/values.yaml` rather than moving to
  `ai-helm-values`, matching the deliberate [ADR-0056](0056-workload-values-in-ai-helm-values.md)
  carve-out that left the `ai-models`/`librechart`/`mcps` orchestrator catalogs in
  chart values. A junior therefore edits two adjacent files in one repo.
- Both engines currently run as root with all capabilities dropped. Tightening to
  non-root is a per-engine follow-up gated on a real GPU rollout — a previous
  attempt to pin `runAsUser: 1000` was written but never verified.
- Decommissioning the legacy charts, once `admin@homeos` retires.

## Alternatives considered

- **Keep copying the chart** — rejected. It was already the wrong shape at model
  #3 by our own written standard, and the divergence it produces is not cosmetic:
  the hardcoded seed args are a correctness hazard, not a style one.
- **One chart, model selected by values, no orchestrator** — rejected. It gives a
  single Application for all models, so one model's failed sync or rollback drags
  every other model with it, and the per-model ArgoCD UI surface disappears.
- **Put the engine expansion in the leaf** — rejected because it is not possible:
  a parent chart cannot compute subchart values at render time. This constraint is
  precisely what shaped the decision.
- **Move the catalog to `ai-helm-values`** — rejected for now. It would split a
  model's definition across two repositories while the gateway catalog it must
  agree with stays here, making the cross-check harder and the junior workflow
  worse. Revisit if per-environment model sets ever diverge.

## Related

- Docs: [`docs/patterns/self-hosted-model-serving.md`](../patterns/self-hosted-model-serving.md)
  (the *how*), and the team's `inference-ops` repo `docs/how-to/add-a-model.md`
- Charts: `charts/model-serving/`, `charts/model-server/`, `charts/apps/values.yaml`
- Tools: `tools/check-model-catalogs.sh`, `.github/workflows/helm-lint.yaml`
- Related: [ADR-0095](0095-cluster-local-model-federation.md) (exposure),
  [ADR-0012](0012-split-ai-models-applicationset.md) (the pattern),
  [ADR-0030](0030-merge-model-and-proxy-into-one-statefulset-bjw.md) (chart shape),
  [ADR-0092](0092-longhorn-for-hetzner-gpu-nodes.md) (the storage this depends on)
