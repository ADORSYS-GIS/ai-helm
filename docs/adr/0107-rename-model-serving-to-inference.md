# ADR-0107: Rename `model-serving`/`model-server` to `inference`/`inference-server`

**Status:** Accepted
**Date:** 2026-07-29
**Deciders:** @stephane-segning

## Context

The GPU-serving charts sit in a namespace of near-homonyms that nothing
distinguishes at a glance:

| Chart | What it is |
|---|---|
| `charts/model-serving` | the ADR-0094 orchestrator — emits the ApplicationSet |
| `charts/model-server` | the generic leaf — runs **one** model |
| `charts/model-serving-<model>` × 7 | the **legacy** per-model charts on the other cluster |
| `charts/ai-models` | gateway **federation** orchestrator (routes + budgets) |
| `charts/ai-model` | gateway federation leaf |
| `charts/model-deployment` | unrelated |

Three of those differ by two characters (`model-serving` / `model-server`) or by
a suffix that reads as a variant rather than a different generation
(`model-serving` / `model-serving-qwen3-4b`). In review and in the ArgoCD UI they
are routinely confused, and the confusion is not cosmetic: `model-serving` (new,
fleet, catalog-driven) and `model-serving-<model>` (legacy, other cluster,
per-model chart) are opposites that a reader is invited to treat as siblings.

This is also the naming that PR #790's regression hid behind — a merge that
re-enabled a `model-serving-*` chart while deleting the `model-serving` catalog
entry that replaced it read, in the diff, like two edits to the same thing.

## Decision

**Rename the two current-generation charts:**

| Before | After |
|---|---|
| `charts/model-serving` | **`charts/inference`** |
| `charts/model-server` | **`charts/inference-server`** |

`inference` is what the thing does, matches the namespace the workloads already
live in (`inference`), and matches the team repo that documents them
(`inference-ops`). It also breaks the homonym: `inference` and `inference-server`
differ by a whole word, and neither can be confused with `model-serving-<model>`.

Renamed with them: the Helm template namespaces (`model-serving.*` →
`inference.*`, `model-server.*` → `inference-server.*`), the leaf's OCI path in
the orchestrator's ApplicationSet, the `charts/apps` Application name and release
name, the `.trivyignore.yaml` path, `tools/check-model-catalogs.sh`, and every
mutable doc reference.

**Deliberately NOT renamed:**

- **The seven legacy `charts/model-serving-<model>` charts.** They keep the old
  name, which is now unambiguously the *legacy* marker. They are disabled and
  awaiting decommissioning; renaming dead code buys nothing.
- **Accepted ADRs 0010–0106.** They are immutable and refer to
  `charts/model-serving` / `charts/model-server` by their names at the time. This
  ADR is the mapping. `docs/adr/README.md` rows likewise keep the historical
  names.
- **`docs/patterns/self-hosted-model-serving.md`** and
  **`docs/architecture/09-model-serving.md`.** Both are linked from immutable
  ADRs; renaming the files would break those links to no benefit. They document a
  pattern, not the chart.
- **The Grafana folder `model-serving` and the `team: model-serving` alert
  label.** These are a display and alert-routing taxonomy, not chart identity.
  Renaming the folder moves every dashboard in it and changes notification-policy
  matchers — a separate change with its own blast radius. Follow-up, not this.

## Consequences

**Positive**

- The two charts that are easy to confuse now differ by a word, not two letters.
- The legacy generation is identifiable from its name alone.
- Chart name, workload namespace and the `inference-ops` docs repo all agree.

**Negative**

- **The live child Applications are recreated, and the qwen3-vl weights
  re-download.** Child app names are `{{ .Release.Name }}-<model>`, so
  `model-serving-qwen3-vl-4b-thinking` becomes `inference-qwen3-vl-4b-thinking`.
  ArgoCD prunes the old child — which cascades to its PVC — and creates the new
  one, so ~9 GB re-seeds and the model is down for that window. Accepted
  deliberately as a one-time cost. `z-image-turbo` loses nothing: ADR-0106 is
  provisioning it fresh anyway.
- **`oci://ghcr.io/adorsys-gis/charts/inference` does not exist until this
  merges.** `publish-charts-oci` creates it on merge to `main`, so between the
  `charts/apps` change syncing and that workflow finishing, the new Application
  cannot resolve its chart. Transient and self-healing, but it will be red for a
  few minutes.
- The old `model-serving` / `model-server` OCI charts remain in the registry as
  orphans. Nothing references them; they are not worth deleting.
- Every ADR before this one names the old paths.

**Neutral / follow-ups**

- Neither chart was ever registered in `release-please-config.json` — a
  pre-existing gap from when ADR-0094 added them, not something this rename
  changed. They still are not, so behaviour is unchanged; adding them is a
  separate call about whether these charts want managed versions.
- Renaming the Grafana folder + `team:` alert label to match is open.

## Alternatives considered

- **Rename only the orchestrator.** Rejected: it leaves `model-server` sitting
  next to `model-serving-<model>`, which is most of the confusion.
- **Keep the ArgoCD Application and release name as `model-serving`.** Would have
  avoided the child recreation and the re-seed entirely, but leaves the old name
  on every child app and in the ArgoCD UI — exactly where the confusion is read.
  Weighed and declined; the re-seed is a one-time cost against a permanent one.
- **`gpu-serving` / `model-runtime` / `serving`.** `inference` won for agreeing
  with the namespace and the `inference-ops` repo already in use.
- **Do nothing.** The names are survivable, but they actively mislead about which
  generation a chart belongs to, and that has now cost a regression's worth of
  review attention.

## Related

- Renames the charts introduced by [0094](./0094-generic-model-serving-orchestrator.md)
- Landed alongside [0106](./0106-restore-the-localai-image-tier.md), whose
  regression the old naming helped obscure
- Charts: `charts/inference`, `charts/inference-server`, `charts/apps/values.yaml`
- Tooling: `tools/check-model-catalogs.sh`, `.trivyignore.yaml`
