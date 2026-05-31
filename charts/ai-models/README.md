# `ai-models` — orchestrator

ArgoCD `ApplicationSet` orchestrator for the AI gateway model fleet. Emits
one Application per enabled model + one for the shared backends.

**ADR:** [`0012`](../../docs/adr/0012-split-ai-models-applicationset.md)
**Leaves:** [`ai-model`](../ai-model/), [`ai-models-backends`](../ai-models-backends/)

## What it renders

A single `ApplicationSet` (one `kind: ApplicationSet`, zero `Backend` /
`AIServiceBackend` / `AIGatewayRoute` resources directly). The
`ApplicationSet`'s List generator has one element per child:

```yaml
generators:
  - list:
      elements:
        - appName: ai-models-backends                 # syncWave -1
          chartPath: charts/ai-models-backends
        - appName: ai-models-deepseek-v4-flash        # syncWave 0
          chartPath: charts/ai-model
        - appName: ai-models-glm-5                    # syncWave 0
          chartPath: charts/ai-model
        # … one per enabled model …
```

The ArgoCD `ApplicationSet` controller then materialises one `Application`
per element. Each child Application's `helm.values` is the inlined
per-model YAML.

## Values

| Key | What |
|---|---|
| `argocd.targetRevision` | Branch / SHA the children pull leaf charts from. **Must flip to `main` on PR merge.** |
| `argocd.project`, `argocd.destination.{name,namespace}` | ArgoCD wiring inherited by every child |
| `argocd.destination.name` / `.server` | Home-remote cluster every child targets (default `home-remote`). Render **hard-fails** if this resolves to in-cluster — see ADR-0017. |
| `argocd.destination.allowInCluster` | Escape hatch (default `false`). Set `true` only to deliberately permit an in-cluster destination. |
| `gatewayRef` | Reference to the `core-gateway` Gateway each model's HTTPRoute attaches to |
| `backendDefaults` (YAML anchors) | Provider-level shape: schema, prefix, fqdn, security type |
| `backends` | Map of provider accounts (fw-01, deepinfra-01, …). Flows into `ai-models-backends` and to each model's `backendsInventory`. |
| `models` | The model fleet. Each entry → one child Application. Set `enabled: false` to omit. |
| `rateLimitBudgeting.plans` | Default monthly-budget tiers (free, pro) — models inherit unless they override per-entry |

## Adding a model

1. Add an entry under `models:` in `values.yaml` with `kind`, `pricing`,
   `backends`, optional `rateLimitBudgeting`.
2. (If new backend) Add to `backends:`.
3. Push — the `ApplicationSet` controller picks up the new element and
   creates a child Application within a reconcile cycle.

To remove: set `enabled: false` (the AppSet deletes the child Application;
ArgoCD `prune: true` removes the K8s resources). Hard-deleting the entry
also works.

## Why an orchestrator vs a single chart

Per-model lifecycle (rollback one bad pricing CEL without touching others),
per-model sync isolation, per-model ArgoCD UI surface. See ADR-0012.

## The third element type: models-info

Beyond the per-model children and the shared backends element, the
orchestrator also emits one child for [`ai-models-info`](../ai-models-info/)
when `modelsInfo.enabled` (default `true`). This serves an
OpenRouter-shape JSON catalog at `api.ai.camer.digital/v1/models/info`
so opencode's models-info plugin can enrich each model with context
length, pricing, modalities, and capability flags. See ADR-0015.

## Verifying

```bash
helm dep build .
helm template ai-models .
# → exactly one ApplicationSet manifest with one element per enabled model
```
