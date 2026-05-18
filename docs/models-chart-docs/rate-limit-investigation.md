# AI Model Rate-Limit Investigation

This note documents the current rate-limit implementation in this repo, the exact point where
`llm_custom_total_cost` is computed, the accuracy limits of the current approach, and the changes
made in this branch to make the chart easier to reason about.

If you need the operator guide rather than the ticket detail, start with
`docs/models-chart-docs/cost-tracking.md`. That file explains the pricing strategies, token types,
and formulas in plain language.

## Scope And Deployed Stack

`charts/apps/templates/applications.yaml` is only the Argo CD app-of-apps renderer. The pinned
versions for the deployed gateway stack live in `charts/apps/values.yaml`.

Current pinned versions in this repo:

| Component | Version | Source in repo |
| --- | --- | --- |
| Envoy Gateway CRDs / controller (`eg`) | `v1.7.0` | `charts/apps/values.yaml` |
| Envoy AI Gateway CRDs (`aieg-crd`) | `v0.5.0` | `charts/apps/values.yaml` |
| Envoy AI Gateway controller (`aieg`) | `v0.5.0` | `charts/apps/values.yaml` |
| Rate-limit backend | Redis | `charts/apps/values.yaml` |

That matters because the investigation below is about the behavior of the versions this repo
actually deploys, not `latest`.

## Executive Summary

1. `llm_custom_total_cost` is not computed by `BackendTrafficPolicy`. It is rendered into each
   `AIGatewayRoute` via CEL in `charts/ai-models/templates/aigatewayroute.yaml`.
2. Envoy AI Gateway extracts token usage in its external processor, stores it as dynamic metadata
   in the `io.envoy.ai_gateway` namespace, and Envoy Gateway later consumes that metadata in
   `BackendTrafficPolicy`.
3. The estimation happens in our Helm chart, not in provider billing data. Envoy AI Gateway only
   supplies token counts; the repo turns those counts into an estimated micro-USD cost.
4. The current approach is directionally better than raw token counting because it differentiates
   uncached input, cached input, and output tokens per model. It is still not identical to real
   provider billing.
5. The repo now uses only the monthly cost-based rule. There is no separate request-rate rule in
   `BackendTrafficPolicy`.
6. I could not find `tokenBudget` in the public Envoy Gateway `v1.7.x` or Envoy AI Gateway
   `v0.5.0` documentation queried through Context7/Tavily. For this repo, that feature should be
   treated as unverified and unavailable until proven against the installed CRDs.

## Full Lifecycle Of `llm_custom_total_cost`

### 1. Authn/Authz injects the selector headers

Authorino adds several headers after a successful LightBridge validation, including:

- `x-account-id`
- `x-api-key-id`
- `x-billing-plan`

Those headers are configured in `charts/apps/values.yaml` under the `AuthConfig` response block.
The `SecurityPolicy` in `charts/kuadrant-policies/templates/securitypolicy.yaml` attaches ext auth
to the `core-gateway` `api-https` and `service-https` listeners.

For the current budget rule, the rate-limit selectors specifically rely on:

- `x-account-id`
- `x-billing-plan`
- `x-ai-eg-model`

Implication: if traffic reaches the generated model routes without passing through this auth path,
the budget rule will not match.

### 2. Envoy AI Gateway resolves the model and extracts token usage

The generated `AIGatewayRoute` resources in
`charts/ai-models/templates/aigatewayroute.yaml` match on `x-ai-eg-model`.

Per Envoy AI Gateway docs, the model header can be derived from the request content before routing,
and the external processor extracts token usage from the provider response and stores it in Envoy
dynamic metadata under `io.envoy.ai_gateway`.

This chart asks AI Gateway to emit:

- `llm_input_token`
- `llm_cached_input_token`
- `llm_output_token`
- `llm_total_token`
- `llm_custom_total_cost`

### 3. This repo computes `llm_custom_total_cost`

This is the key point of the ticket.

The cost estimation happens in `charts/ai-models/templates/aigatewayroute.yaml` inside
`spec.llmRequestCosts`. The chart renders a CEL expression per model using the pricing strategy from
`charts/ai-models/values.yaml`.

For `pricing.strategy: weighted`, the rendered CEL is:

```cel
((max((int(input_tokens) - int(cached_input_tokens)), 0) * inputPer1MScaled) +
 (int(cached_input_tokens) * cachedInputPer1MScaled) +
 (int(output_tokens) * outputPer1MScaled)) / 1000
```

For `pricing.strategy: flat`, the rendered CEL is:

```cel
(int(total_tokens) * effectivePer1MScaled) / 1000
```

For `pricing.strategy: tieredWeighted`, the chart switches between two weighted branches based on
`input_tokens > thresholdTokens`.

All outputs are integers in micro-USD.

### 4. Envoy Gateway consumes the metadata as budget cost

`charts/ai-models/templates/backendtrafficpolicy.yaml` defines one budget rule per billing plan and
per model. The rule uses:

- request cost: `0`
- response cost: `io.envoy.ai_gateway/llm_custom_total_cost`

Per Envoy Gateway docs, response-path cost reduction only happens after the response is sent back
or the stream is closed. That means the request that crosses the limit still succeeds; the next
matching request is the one that sees the exhausted bucket.

### 5. Access logs export the same metadata

`charts/core-gateway/templates/envoy-proxy.yaml` exports:

- `gen_ai.usage.total_tokens`
- `gen_ai.usage.input_tokens`
- `gen_ai.usage.output_tokens`
- `gen_ai.usage.custom_total_cost`

So the same metadata used for rate limiting is already available in telemetry.

## Accuracy Assessment

### What Is Accurate

### Per-model pricing is model-specific

The pricing constants are rendered per route from `charts/ai-models/values.yaml`. This is not a
single shared multiplier across all models.

For example:

- `deepseek-v3p2` uses `weighted` pricing: `0.56 / 0.28 / 1.68`
- `qwen3-8b` uses `flat` pricing: `0.20`
- `gemini-2.5-pro` uses `tieredWeighted` pricing:
  - short context: `1.25 / 0.125 / 10.0`
  - long context: `2.50 / 0.25 / 15.0`

So the chart already does the right thing at the model granularity.

### Weighted tokens are better than flat token budgets

This repo does not treat all tokens equally for text-like models. Output tokens are charged using a
higher multiplier, and cached input tokens use a discounted multiplier when `cached_input_tokens`
is available.

That is materially better than a naive `total_tokens` budget.

### What Is Inaccurate Or Incomplete

### The current request is never blocked by the monthly budget rule

Because cost is consumed from response metadata, budget enforcement is delayed by one request.

Concrete example:

- Remaining monthly budget bucket: `1000` micro-USD
- Response cost for the current request: `1500` micro-USD

Outcome:

- current request succeeds
- next matching request is the one that is rejected

That does not mean the budget rule is ignored on the request path. It means the request that causes
the overage is allowed, while later matching requests are blocked once Redis already contains the
exhausted bucket state.

### Integer math truncates small costs to zero

The CEL expressions intentionally use integer math. That avoids type issues, but tiny requests can
round down to zero budget usage.

Concrete example for `gemini-2.5-flash-lite`:

- `inputPer1M = 0.10`
- one uncached input token

Budget cost:

- true arithmetic: `0.10` micro-USD
- CEL integer result: `0`

So extremely small requests can consume no monthly budget at all.

### Cached-input accuracy depends on provider metadata support

The public Envoy AI Gateway docs I found explicitly document extracting input, output, and total
tokens from OpenAI-style usage fields. They do not clearly document the exact provider-specific
behavior for cached input tokens in the deployed versions.

That means cached-input discounting should be treated as best-effort unless validated against live
telemetry for every provider behind this chart.

Concrete example for `gpt-5-mini`:

- `inputPer1M = 0.75`
- `cachedInputPer1M = 0.075`
- `outputPer1M = 4.5`
- request usage: `10000` input, `9000` cached input, `100` output

If cached input is correctly reported:

- cost = `1875` micro-USD

If cached input is missing and treated as `0`:

- cost = `7950` micro-USD

That is a `4.24x` overestimate.

### Image-generation models still require approximation

Some provider price sheets split image workloads into different token classes that AI Gateway does
not expose separately in CEL.

Concrete example for `gpt-image-1.5`:

- published text input: `$5.00 / 1M`
- published image input: `$8.00 / 1M`
- published image output: `$32.00 / 1M`

The OpenAI image APIs do expose `input_tokens_details` and `output_tokens_details`, but the Envoy
AI Gateway token-cost examples only document aggregate `input_tokens`, `output_tokens`, and
`total_tokens`.

Current implication in this repo:

- `gpt-image-1` is rendered as a weighted model so output tokens cost more than input tokens
- the input side still uses one published rate, not separate text-input vs image-input rates

That is directionally much better than a flat token budget, but it is still not equivalent to exact
provider billing for edit-heavy image workflows.

### Header-based matching assumes all traffic uses the secured gateway path

The budget rules match on:

- `x-account-id`
- `x-billing-plan`
- `x-ai-eg-model`

If a request bypasses the `core-gateway` auth path, these headers may be missing. In that case the
budget rule does not apply.

## Review Of The Previous `30 req/min` Rule

This repo previously had a second rule:

- per `x-api-key-id`
- per `x-ai-eg-model`
- default `30` requests per minute

That rule was not a true fallback in protocol terms. It was an always-on second limiter that
applied independently whenever the request matched its headers.

### Why it was removed

- it was not cost-aware
- it was plan-agnostic
- it could reject requests even when the account still had monthly budget remaining
- it made the runtime behavior harder to explain because two independent rules were active at once

### What remains true after removing it

- the request that crosses the monthly budget is still allowed
- later matching requests are rejected once Redis already contains the exhausted budget bucket
- there is no longer a separate request-count guardrail in this chart

## Changes Made In This Branch

Besides documenting the current behavior, this branch makes four chart changes:

1. Model pricing now lives under an explicit `pricing.strategy` block in `charts/ai-models/values.yaml`.
2. Vendor prices were refreshed from the current Fireworks, OpenAI, and Gemini pricing pages.
3. Gemini long-context tiers are now represented explicitly with `tieredWeighted` pricing.
4. The separate request-rate rule was removed so only the monthly cost-based rule remains.

Rationale:

- before this branch, the chart mixed weighted and flat prices directly into each model entry, which
  made stale pricing harder to spot and long-context Gemini pricing impossible to represent cleanly
- vendor-published pricing now maps directly to one of three strategies: `weighted`, `flat`, or
  `tieredWeighted`
- `BackendTrafficPolicy` still consumes a single `llm_custom_total_cost` metadata key, so this keeps
  the enforcement path stable while improving the estimate
- removing the extra request-rate rule makes the behavior easier to reason about, at the cost of no
  longer having a coarse burst guard in this chart

## Proposed Improvements

| Proposal | Rationale | Complexity |
| --- | --- | --- |
| Keep cost-based limiting in CEL, but treat it as an estimate | This repo now has explicit `weighted`, `flat`, and `tieredWeighted` pricing strategies, which is better than raw token limits. The right framing is “estimated spend guardrail”, not “exact billing.” | Low |
| Add a separate gateway-level abuse-control policy only if production traffic shows a real burst problem | The current chart now has one budget rule, which is easier to reason about. If a burst guard is needed later, make it explicit and separate from billing logic. | Medium |
| Build budget observability from existing access logs | The access log already exports `gen_ai.usage.custom_total_cost`, `account_id`, `billing_plan`, and `api_key_id`. A dashboard can show budget burn before users hit `429`. | Medium |
| Validate cached-token telemetry per provider | Cached pricing is where the estimate can diverge the most. This should be verified against live responses from OpenAI, Gemini proxy paths, Fireworks, and Vertex/OpenAI-compatible backends. | Medium |
| Do not plan around `tokenBudget` yet | I could not find `tokenBudget` in the Envoy Gateway `v1.7.x` or Envoy AI Gateway `v0.5.0` docs queried via Context7/Tavily. Upgrade exploration is needed before treating it as a viable option. | Medium |
| Validate image-model usage breakdown before tightening budgets further | OpenAI and Gemini publish image-specific token rates, but the current CEL path still consumes aggregate input/output counters. | Medium |

## Suggested Follow-up Validation

1. Send one request per provider/model family and confirm that access logs contain:
   `llm_input_token`, `llm_cached_input_token`, `llm_output_token`, `llm_total_token`,
   `llm_custom_total_cost`.
2. Compare logged `llm_custom_total_cost` against provider invoices or provider response usage for a
   small sample.
3. Confirm that missing header paths are impossible in production, or reject them explicitly.
4. Decide explicitly whether a separate gateway-level abuse guard is still needed, rather than reintroducing a hidden second limiter in the model chart.

## External Sources

- Envoy AI Gateway usage-based rate limiting and `llmRequestCosts` docs:
  `https://github.com/envoyproxy/ai-gateway/blob/main/site/docs/capabilities/usage-based-ratelimiting.md`
- Envoy AI Gateway API reference:
  `https://github.com/envoyproxy/ai-gateway/blob/main/site/docs/api/api.mdx`
- Envoy AI Gateway architecture docs:
  `https://github.com/envoyproxy/ai-gateway/blob/main/site/docs/concepts/architecture/system-architecture.md`
- Envoy Gateway `BackendTrafficPolicy` concept docs:
  `https://gateway.envoyproxy.io/docs/concepts/gateway_api_extensions/backend-traffic-policy/`
- Envoy Gateway API reference for rate-limit response cost semantics:
  `https://gateway.envoyproxy.io/docs/api/extension_types/`
- Envoy AI Gateway maintainer clarification that AI Gateway computes request cost while Envoy
  Gateway owns the static rate-limit policy:
  `https://github.com/envoyproxy/ai-gateway/discussions/557`
- Fireworks pricing:
  `https://fireworks.ai/pricing`
- OpenAI pricing:
  `https://developers.openai.com/api/docs/pricing/`
- OpenAI embeddings guide:
  `https://developers.openai.com/api/docs/guides/embeddings/`
- OpenAI GPT Image 1.5 model page:
  `https://developers.openai.com/api/docs/models/gpt-image-1.5`
- Gemini Developer API pricing:
  `https://ai.google.dev/gemini-api/docs/pricing`
