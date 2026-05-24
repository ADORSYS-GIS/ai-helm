# ADR-0006: Migrate `charts/apps` to a multi-source ApplicationSet (List generator, no-dup)

**Status:** Proposed
**Date:** 2026-05-24
**Deciders:** repo maintainers via `claude/magical-bohr-390242`

## Context

`charts/apps` is the GitOps root: a single chart whose only job is to render
~35 `argoproj.io/v1alpha1` Application manifests from `values.yaml`. Today
it does this with a Helm `range` over `.Values.apps`. The audit surfaced
several issues with the current shape:

- Destination cluster name (`lke560142-ctx`) is hardcoded in the template,
  not parameterized.
- Default `syncPolicy` injects both `Replace=true` and `ServerSideApply=true`,
  which conflict on CRDs and produce field-manager loops.
- Most apps that need secrets pull them from a separate
  `ai-ops-secrets.git` repo via a parallel `secrets` Application — secrets
  and the workloads they support are managed by two different Apps that
  must succeed in the right order.
- The values block carries `valuesObject:` inline, which is verbose and
  makes diff review noisy for unrelated changes.

ArgoCD has supported ApplicationSet for years and multi-source per
Application since 2.8. Both are mature enough to adopt.

## Decision

Replace the `range` Application template with a single ApplicationSet
using a **List generator**. Each entry in `generators[0].list.elements`
corresponds to one current Application; the template renders an
`Application` per element.

Each rendered Application uses **multi-source** (`spec.sources[]`):
- **Source A** — the upstream chart (workloads, Services, default ConfigMaps).
- **Source B** — the secrets repo (`ai-ops-secrets.git`) or local
  ExternalSecret manifests. Owns **only** ExternalSecret / SealedSecret
  resources; never workloads.
- **Source C (optional)** — a `bjw-s/app-template` wrapper that ships
  chart-extension manifests the upstream doesn't (NetworkPolicy, PDB,
  GrafanaDashboard CRs, ResourceQuota).
- One source provides values for another via the
  `helm.valueFiles: [$values/path]` pattern so the values block isn't
  duplicated either.

**No-dup invariant:** every rendered Kubernetes resource is produced by
exactly one source. Validated in the pilot phase with `argocd app diff`
and `helm template` side-by-side.

Also in this migration:
- Parameterize `destination.name` (top-level value, drop `lke560142-ctx`).
- Default `syncPolicy` drops `Replace=true`, keeps `ServerSideApply=true`.
- Preserve sync-wave annotations, finalizers, syncOptions per element.
- ApplicationSet `goTemplate: true` so we can use sprig.

Approach: pilot 2–3 apps first (`librechat`, `models-proxy`, `mimir`),
validate the no-dup invariant on a real cluster, then roll out to all
entries.

## Consequences

**Positive**
- One ApplicationSet to read, version, and review — instead of a `range`
  inside a template that hides the per-app shape.
- Secrets stop being a parallel App with implicit ordering — each App owns
  its secret source explicitly.
- Multi-cluster becomes a small change: swap List generator for a Matrix
  (Cluster × App) when a second cluster appears.
- Two audit findings fixed in the same pass (Replace conflict, hardcoded
  cluster).

**Negative**
- Bigger blast radius than per-app edits. Pilot phase mitigates by
  validating on a subset before rolling out.
- ApplicationSet templating quirks (escaping, `goTemplate` semantics)
  will bite during conversion. Documented in the how-to as they emerge.
- Multi-source `$values` rendering requires both sources to be reachable
  at sync time. Both already are, but adds a coupling worth naming.

**Neutral / follow-ups**
- After the pilot, the audit's "`HEAD` and `main` revisions everywhere"
  finding (11 apps pin to `HEAD`) is best fixed in the same migration —
  cleaner if we add the pin convention to every new element rather than
  remember to retrofit later.
- Successor ADR likely needed when a second cluster lands (Matrix
  generator shape decision).

## Alternatives considered

- **Status quo (helm `range`)** — works today; doesn't solve any of the
  problems above. Rejected.
- **Multi-source first, AppSet later** — convert the existing `Application`
  template to multi-source, leave the `range`. Smaller per-step diff but
  the AppSet pass would re-touch every entry. Rejected as more total churn.
- **AppSet first, multi-source later** — single-source AppSet 1:1 with
  today; convert each entry to multi-source in a follow-up. Smaller
  per-step diff but doesn't address the secrets-as-parallel-App problem
  immediately. Considered; rejected because the user's "deduplicate
  resources" constraint argues for designing the source split correctly
  on day one.
- **Git directory generator** — adding a chart becomes "drop a file" with
  no `values.yaml` edit. More invasive structural change. Could be a
  successor ADR once the List generator is in steady state.

## Related

- Task: #2 (implementation pending)
- Doc to be written: `docs/argocd-multi-source-pattern.md`
- Charts touched (planned): `charts/apps/templates/applications.yaml`,
  `charts/apps/values.yaml`
