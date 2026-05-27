# `ai-model` — leaf

One AI model on the Envoy AI Gateway. Renders an `AIGatewayRoute`
(routing + cost CEL) and a `BackendTrafficPolicy` (rate limits per
billing plan). Instantiated N times by the [`ai-models`](../ai-models/)
orchestrator.

**ADR:** [`0012`](../../docs/adr/0012-split-ai-models-applicationset.md)

## What it renders

- `aigateway.envoyproxy.io/v1alpha1` **`AIGatewayRoute`** — header-match
  on `x-ai-eg-model: <modelName>`, backend refs with priorities, and an
  `llmRequestCosts[]` CEL expression computing per-request cost in
  micro-USD.
- `gateway.envoyproxy.io/v1alpha1` **`BackendTrafficPolicy`** — global
  rate limit gated by `(x-account-id, x-billing-plan, x-ai-eg-model)`.

## Required values

| Key | Notes |
|---|---|
| `modelName` | Used as the AIGatewayRoute name AND as the `x-ai-eg-model` header match. |
| `gatewayRef.{name, namespace}` | The Envoy AI Gateway to attach to. |
| `backendsInventory` | Map of backend `ref` → `{ resourceName }`. Lets this leaf resolve a backend's Service name without re-declaring the backend. Comes from the orchestrator's `backends:` value. |
| `backends` | This model's backend refs + priorities + `modelNameOverride`. Minimum 2 backends for HA (configurable via `minBackends`). |
| `pricing` | `strategy: weighted` (input/output/cached prices) or `flat` (single effective price) or `tieredWeighted`. Drives the cost CEL. |
| `plans` | The orchestrator's `rateLimitBudgeting.plans` map; provides default per-plan monthly budgets. |

## Optional values

| Key | Default | Notes |
|---|---|---|
| `minBackends` | 2 | Render fails if fewer enabled backends present (HA safety) |
| `rateLimitBudgeting` | (uses `plans`) | Per-model overrides: `{ free: 10, pro: 50 }` |
| `kind` | `text` | Informational tag |

## Cost CEL

Three pricing strategies in [`templates/_helpers.tpl`](templates/_helpers.tpl):

- `weighted`: `(input - cached) * inputPer1M + cached * cachedInputPer1M + output * outputPer1M`
- `tieredWeighted`: same, but switch to `longContext` prices above `thresholdTokens`
- `flat`: `total_tokens * effectivePer1M`

All wrap with `int(... > 0.0 ? ... : 0.0)` to return a non-negative
integer in micro-USD (the unit `llm_custom_total_cost` expects).

## Verifying with sample values

```bash
helm template ai-model . -f /tmp/sample.yaml
```

Where `/tmp/sample.yaml`:

```yaml
modelName: glm-5
gatewayRef: { name: core-gateway, namespace: converse-gateway }
pricing:
  strategy: weighted
  standard: { inputPer1M: 0.60, cachedInputPer1M: 0.12, outputPer1M: 2.08 }
backends:
  deepinfra-01: { ref: deepinfra-01, priority: 0, modelNameOverride: "zai-org/GLM-5" }
  deepinfra-02: { ref: deepinfra-02, priority: 1, modelNameOverride: "zai-org/GLM-5" }
backendsInventory:
  deepinfra-01: { resourceName: deepinfra-backend-01-svc }
  deepinfra-02: { resourceName: deepinfra-backend-02-svc }
plans:
  free: { monthlyBudgetUsd: 30 }
  pro:  { monthlyBudgetUsd: 200 }
```
