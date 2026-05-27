# `librechat-search` — leaf

Meilisearch instance for LibreChat full-text search. Independent
Application (sync-wave -1) so it's up before LibreChat hits the search
code path.

**ADR:** [`0014`](../../docs/adr/0014-split-librechart-and-opencode-wellknown.md)
**Orchestrator:** [`librechart`](../librechart/)

## What it renders

Entirely via the upstream `meilisearch@0.25.1` chart from
<https://meilisearch.github.io/meilisearch-kubernetes>. This chart adds
no templates of its own — just values overrides.

Resources rendered:

- `StatefulSet` (1 replica, PVC for persistence)
- `Service` (ClusterIP, named `{{ .Release.Name }}` — i.e. `librechat-search`
  per the AppSet's child name; `librechat-app` references this as
  `MEILI_HOST: http://librechat-search:7700`)
- `PersistentVolumeClaim`
- `ConfigMap` (Meilisearch env)
- `ServiceAccount`
- (Optional test connection Pod)

## Required Secret

- **`librechat-meili-config`** with key `MEILI_MASTER_KEY`. Same Secret
  is consumed by `librechat-app` (which uses the master key to
  authenticate Meilisearch admin operations).

## Verifying

```bash
helm dep build .
helm template librechat-search . -n converse | grep -E "^kind:"
# → ServiceAccount, ConfigMap, PVC, Service, StatefulSet, [test Pod]
```

The Service name is `librechat-search` (matches the orchestrator's
child name + the `MEILI_HOST` env in librechat-app).
