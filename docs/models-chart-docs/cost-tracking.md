# Cost Tracking And Budgeting

This repo tracks token usage and an estimated per-request cost via Envoy AI Gateway dynamic metadata.
That metadata is:

- Exported to access logs by the core gateway (`gen_ai.usage.*` fields).
- Used for budget-style rate limiting in `BackendTrafficPolicy` (token-cost budgeting).

## Data Flow

1. `AIGatewayRoute.spec.llmRequestCosts` defines which token counters/cost keys the AI Gateway should emit as dynamic metadata.
2. The AI Gateway extproc filter attaches dynamic metadata under the namespace `io.envoy.ai_gateway`.
3. The core gateway access log config reads those metadata keys and logs them, for example:
   - `gen_ai.usage.total_tokens` from `io.envoy.ai_gateway:llm_total_token`
   - `gen_ai.usage.custom_total_cost` from `io.envoy.ai_gateway:llm_custom_total_cost`
4. `BackendTrafficPolicy.spec.rateLimit.global.rules[].cost.response.from: Metadata` reads
   `io.envoy.ai_gateway/llm_custom_total_cost` and treats it as the per-request "cost" against the budget limit.

## Units (Important)

### Model Price Inputs (values.yaml)

These values are expressed as **USD per 1,000,000 tokens** (a common pricing unit):

- Text models:
  - `inputPer1M`
  - `cachedInputPer1M`
  - `outputPer1M`
- Image / embedding models:
  - `effectivePer1M`

### `llm_custom_total_cost` output

`llm_custom_total_cost` is emitted as an **integer in micro-USD**:

- Unit: `microUSD = USD * 1,000,000`
- Conversion: `usd = llm_custom_total_cost / 1_000_000`

Why micro-USD?

- The AI Gateway CEL cost expressions must evaluate to an **integer** (not a double).
- Micro-USD keeps values reasonably sized while still representing common per-token pricing.

Example:

- `inputPer1M: 0.56` (=$0.56 / 1M tokens)
- 75 input tokens (and no cached / output tokens)
- `microUSD = 75 * 0.56 = 42`
- `USD = 42 / 1_000_000 = 0.000042`

## How the CEL expressions work

The models chart renders integer-safe CEL expressions to avoid type errors (tokens are `uint`) and to
avoid returning non-integers.

### Text models

The chart computes scaled integers in Helm:

- `inputPer1MScaled = round(inputPer1M * 1000)`
- same for cached input and output

Then CEL does integer math:

- `(((int(input_tokens) - int(cached_input_tokens)) * inputPer1MScaled) + ...) / 1000`

This yields an integer approximation of `tokens * pricePer1M` (micro-USD) with 3-decimal precision on
the `*Per1M` prices.

### Image / embedding models

- `effectivePer1MScaled = round(effectivePer1M * 1000)`
- CEL: `(int(total_tokens) * effectivePer1MScaled) / 1000`

## Budgeting (BackendTrafficPolicy)

The `BackendTrafficPolicy` rules treat the budget limit and the per-request cost as the same unit.

Because `llm_custom_total_cost` is micro-USD, `rateLimitBudgeting.plans.<plan>.monthlyBudgetUsd`
is converted to micro-USD at render time:

- `budgetMicroUsd = monthlyBudgetUsd * 1_000_000`

If you see a logged `gen_ai.usage.custom_total_cost: "42"`, that consumes 42 micro-USD from the monthly
budget for that account/plan/model selector.

## Gotchas

- Integer truncation: very small requests can cost 0 micro-USD for low-priced models due to integer math.
  This is usually acceptable for budgeting at larger scales, but you can switch to a smaller unit
  (e.g., nano-USD) if you need more precision.
- The metadata namespace/key must match exactly:
  - namespace: `io.envoy.ai_gateway`
  - key: `llm_custom_total_cost`

