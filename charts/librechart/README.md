# `librechart` — orchestrator

ArgoCD `ApplicationSet` orchestrator for the LibreChat stack. Emits one
Application per leaf chart.

**ADR:** [`0014`](../../docs/adr/0014-split-librechart-and-opencode-wellknown.md)
**Leaves:** [`librechat-app`](../librechat-app/), [`librechat-search`](../librechat-search/), [`librechat-opencode-wellknown`](../librechat-opencode-wellknown/)

## What it renders

A single `ApplicationSet`. The List generator emits one element per
enabled `children[]` entry:

```yaml
children:
  - { name: librechat-search,             chartPath: charts/librechat-search,             syncWave: "-1" }
  - { name: librechat-app,                chartPath: charts/librechat-app,                syncWave: "0"  }
  - { name: librechat-opencode-wellknown, chartPath: charts/librechat-opencode-wellknown, syncWave: "1"  }
```

The ArgoCD AppSet controller then creates one `Application` per element,
each pointing at a leaf chart in this repo.

## Values

| Key | What |
|---|---|
| `argocd.targetRevision` | Branch / SHA / tag the children pull leaf charts from. Deploys run from the branch now; pins to a release **tag** next. **Never `main`.** |
| `argocd.{project, namespace, destination.{name, namespace}, syncPolicy}` | ArgoCD wiring inherited by every child |
| `children[]` | List of leaves. Each: `{ name, chartPath, syncWave, enabled }`. Set `enabled: false` to omit a child. |

## Why an orchestrator vs a Helm subchart composition

The three leaves have different lifecycles — Meilisearch can be
restarted without rebuilding LibreChat's Deployment; the well-known
endpoint is utterly independent of either. Separating into per-leaf
Applications gives per-leaf sync status, per-leaf rollback, and per-leaf
sync waves. See ADR-0014.

## Adding a new component

1. Create the leaf chart at `charts/librechat-<name>/`.
2. Add an entry to `children:` here.
3. Push. AppSet picks it up.

## Verifying

```bash
helm dep build .
helm template librechart .
# → exactly one ApplicationSet with one element per enabled child
```
