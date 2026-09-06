# `ai-model` — leaf

One AI model on the Envoy AI Gateway. Renders an `AIGatewayRoute`
(routing + cost CEL) and a `BackendTrafficPolicy` (rate limits per
billing plan). Instantiated N times by the [`ai-models`](../ai-models/)
orchestrator.

**ADR:** [`0012`](../../docs/adr/0012-split-ai-models-applicationset.md)

## What it renders

- `aigateway.envoyproxy.io/v1beta1` **`AIGatewayRoute`** — header-match
  on `x-ai-eg-model: <modelName>`, backend refs with priorities, and an
  `llmRequestCosts[]` CEL expression computing per-request cost in
  micro-USD.
- `gateway.envoyproxy.io/v1alpha1` **`BackendTrafficPolicy`** — this model's
  upstream timeout, and up to six global rate-limit rule families. Only one of
  them renders on the live fleet: **`rpmPerKey`**, the request-rate ceiling
  below. The five plan/tier/budget families are intact but produce nothing —
  every `burst:` block has been commented out fleet-wide since 2026-08-01, and
  the cost buckets were deleted on 2026-09-05 (ai-helm-values#427).

## The request-rate ceiling (`rpmPerKey`)

Owner ruling **2026-09-06**: *"a rate limit per api-key id and per model would
be enough, so that spamming is avoided — no cost hit, no tier."* Amended the
same day to make the number **per model**, because N req/min against a small
model on a SaaS provider and N req/min against a self-hosted vLLM on two GPUs
are not the same event.

`rpmPerKey: N` renders two rules on **this model's own** policy:

| rule | key | limit |
|---|---|---|
| `rpm-rule/0` | `x-api-key-id` (Distinct) × `x-ai-eg-model` (Exact = this model) | `N` / `Minute` |
| `rpm-rule/1` | `x-account-id` (Distinct) × `x-ai-eg-model` (Exact = this model) | `N` / `Minute` |

Neither carries a `cost:` block, so the counter counts **requests** (+1 each),
never micro-USD — this is a rate cap and can never become a second cap on money.
Neither carries a plan or tier descriptor. `rpmPerKey: 0` renders neither rule
and is both the per-model opt-out and the rollback.

**Two rules, not one**, because `x-api-key-id` is stamped from the `api_key_id`
claim only on the public API-key plane; it is a constant `""` on the internal
AuthConfig (LibreChat, LCI, k8s SAs) and empty for GitHub-Actions repobinding
and Keycloak-human tokens. Envoy generates no descriptor for an absent-or-empty
header, so a key-only rule would leave those planes unlimited. `x-account-id` is
stamped on every plane.

**Why here and not on the gateway-wide policy — the ADR-0084 argument.** A
gateway-scoped shape would put every model's rule into one ordered `global.rules`
list on one policy, and a rule's *index* is part of the Lyft counter key. Adding
or removing a model — routine in the catalog, several times a month — would
renumber every rule after it and orphan those models' counters: the 2026-07-16
incident, exactly. Here each model owns its own `BackendTrafficPolicy`, so its
rules are always indices 0 and 1 and **editing, adding or deleting model X cannot
renumber model Y**. The per-model shape is the one where the hazard cannot occur.

`unit: Minute` is the plain, correct unit. [ADR-0111](../../docs/adr/0111-calendar-aligned-billing-period.md)/[ADR-0112](../../docs/adr/0112-year-unit-so-the-billing-period-is-the-only-rotation.md)'s
`x-billing-period` + `unit: Year` trick exists only because a *calendar* month
cannot be expressed by Lyft's window epoch. Do not copy it here.

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
| `rpmPerKey` | `0` | Requests/min per (API-key id × this model) **and** per (account id × this model). `0` renders no rule. Set from the model's own catalog entry in `ai-helm-values` `models.yaml`; the orchestrator falls back to `requestRate.defaultRpmPerKey`. See the section above. |
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
