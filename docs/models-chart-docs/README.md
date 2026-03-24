# Models

A Helm chart for deploying AI model backends and routing configuration on Kubernetes using Envoy Gateway.

## Description

This chart deploys the model-specific components for an AI Gateway:

- **Backend** - Envoy backend endpoints (FQDN-based)
- **AIServiceBackend** - AI service backend definitions with schema configuration
- **AIGatewayRoute** - Model routing rules with load balancing and failover
- **BackendSecurityPolicy** - API key authentication policies
- **BackendTLSPolicy** - TLS configuration for backend connections
- **BackendTrafficPolicy** - Retry and cost-based rate limiting policies for backend connections
- **Secret** - API key secrets for backend authentication

This chart requires the `core-gateway` chart to be installed first, which provides the Gateway infrastructure.

## Prerequisites

- Kubernetes 1.24+
- Helm 3.0+
- [Envoy Gateway](https://gateway.envoyproxy.io/docs/tasks/quickstart/) installed in the cluster with rate limiting enabled
- [Envoy AI Gateway](https://aigateway.envoyproxy.io/docs/getting-started/installation/) installed too
- `core-gateway` chart installed
- `redis` installed

## Installation

### Prepare Secrets

Before installing, prepare your API key secrets. The example file in this repo is
[`secret.example.yaml`](./secret.example.yaml).

```bash
# Copy the example secret file from the repo root
cp ./docs/models-chart-docs/secret.example.yaml ./secret.yaml

# Edit secret.yaml with your actual API keys
# Update the apiKey values and service account JSON as needed

# Apply the secrets to Kubernetes
kubectl apply -f secret.yaml
```

### Install the Charts

```bash
# First, install the core gateway infrastructure
helm install core-gateway ./charts/core-gateway -n converse-gateway --create-namespace

# Then install the models chart
helm install ai-models ./charts/ai-models -n converse-gateway

# Install with custom values
helm install ai-models ./charts/ai-models -n converse-gateway -f my-values.yaml
```

## Testing

After installing the chart, you can test the AI Gateway locally using curl requests. First, ensure the Gateway is accessible (e.g., via port-forwarding or LoadBalancer IP).

### Port Forwarding (for local testing)

```bash
# Get the Envoy service name dynamically
export ENVOY_SERVICE=$(kubectl get svc -n envoy-gateway-system \
  --selector=gateway.envoyproxy.io/owning-gateway-namespace=converse-gateway,gateway.envoyproxy.io/owning-gateway-name=core-gateway \
  -o jsonpath='{.items[0].metadata.name}')

# Port forward the Envoy Gateway service
kubectl port-forward -n envoy-gateway-system svc/$ENVOY_SERVICE 8080:80

# Set the gateway URL
export GATEWAY_URL=http://localhost:8080
```

### Example Curl Requests

Test a chat completion request:

```bash
curl -v -H "Content-Type: application/json" \
  -H "Authorization: Bearer <your-api-key>" \
  -H "x-ai-eg-model: gpt-5-mini" \
  -d '{
    "messages": [
      {
        "role": "user",
        "content": "hi"
      }
    ]
  }' \
  $GATEWAY_URL/v1/chat/completions
```

**Update model name in respect to the configurations made in the values.yaml file**

## Configuration

## Cost Tracking And Budgeting

Start with the plain-English guide:

Docs: [cost-tracking.md](./cost-tracking.md)

That guide explains:

- what `weighted`, `flat`, and `tieredWeighted` mean
- the difference between input, cached input, and output tokens
- how `standard` and `longContext` pricing work
- how the math turns token usage into `llm_custom_total_cost`
- when a request is blocked before upstream and when it is not

For the ticket-focused investigation of the full pipeline, deployed versions, and proposed improvements, see:

Docs: [rate-limit-investigation.md](./rate-limit-investigation.md)

That guide explains:

- what `weighted`, `flat`, and `tieredWeighted` mean
- the difference between input, cached input, and output tokens
- how `standard` and `longContext` pricing work
- how the math turns token usage into `llm_custom_total_cost`
- how monthly budgets interact with the fallback requests-per-minute rule

### Gateway Reference

| Parameter | Description | Default |
|-----------|-------------|---------|
| `gatewayRef.name` | Name of the shared gateway resource | `core-gateway` |
| `gatewayRef.namespace` | Namespace of the shared gateway resource | `converse-gateway` |

### Rate Limiting And Budgeting

| Parameter | Description | Default |
|-----------|-------------|---------|
| `rateLimitBudgeting.plans.<plan>.monthlyBudgetUsd` | Monthly estimated spend guard per account, plan, and model | `free=30`, `pro=200` |
| `rateLimitBudgeting.plans.<plan>.modelBudgets.overrides.<model>` | Per-model budget override (USD) | none (uses `monthlyBudgetUsd`) |
| `rateLimitFallback.enabled` | Enable the coarse burst guard | `true` |
| `rateLimitFallback.requests` | Max fallback requests per API key and per model in the fallback window | `30` |
| `rateLimitFallback.unit` | Fallback window unit | `Minute` |
| `models.<name>.pricing.strategy` | Cost model used to compute `llm_custom_total_cost` | `weighted`, `flat`, `tieredWeighted` |

The chart uses two complementary controls:

1. A monthly budget rule based on estimated request cost.
2. A fallback request-rate rule for burst protection.

The budget rule matches `x-account-id + x-billing-plan + x-ai-eg-model`.
The fallback rule matches `x-api-key-id + x-ai-eg-model`.

The budget is decremented from response metadata, so the request that crosses the budget can still succeed. The fallback rule exists to keep that delayed budget enforcement from becoming an abuse gap.

Budget resolution: `modelBudgets.overrides.<model>` if defined, else `monthlyBudgetUsd`.

Example with per-model budgets:

```yaml
rateLimitBudgeting:
  plans:
    free:
      monthlyBudgetUsd: 30           # Default: $30 per month for all models
      modelBudgets:
        overrides:
          gpt-5-mini: 10             # Override: $10 for this specific model
          gemini-2.5-pro: 50         # Override: $50 for this specific model
```

### Backend Traffic Policy

| Parameter | Description | Default |
|-----------|-------------|---------|
| `BackendTrafficPolicy` target | One `BackendTrafficPolicy` is rendered per model route | each `HTTPRoute` |
| Monthly budget selector | `x-account-id`, `x-billing-plan`, `x-ai-eg-model` | generated |
| Budget limit unit | Same unit as `llm_custom_total_cost` | micro-USD |
| Fallback selector | `x-api-key-id`, `x-ai-eg-model` | generated |

`BackendTrafficPolicy` does not calculate cost by itself. It reads the `llm_custom_total_cost` value produced by `AIGatewayRoute` and uses that response metadata as the cost of the request.

### Pricing Strategies

| Strategy | When to use it | Required fields |
|-----------|-------------|---------|
| `weighted` | Provider publishes separate prices for input, cached input, and output tokens | `standard.inputPer1M`, `standard.cachedInputPer1M`, `standard.outputPer1M` |
| `flat` | Provider publishes one blended price for total tokens | `standard.effectivePer1M` |
| `tieredWeighted` | Provider publishes weighted prices and a more expensive long-context tier | `thresholdTokens`, `standard.*`, `longContext.*` |

### Backends

Backends define the upstream AI service endpoints:

| Parameter | Description | Example |
|-----------|-------------|---------|
| `backends.<name>.resourceName` | Kubernetes resource name | `gcp-backend-svc` |
| `backends.<name>.schema` | AI service schema (OpenAI, etc.) | `OpenAI` |
| `backends.<name>.prefix` | Optional URL prefix | `/inference/v1` |
| `backends.<name>.fqdn.hostname` | Backend hostname | `api.openai.com` |
| `backends.<name>.fqdn.port` | Backend port | `443` |
| `backends.<name>.secretRef.name` | Secret name for API key | `openai-apikey` |
| `backends.<name>.tlsHostname` | TLS hostname for validation | `api.openai.com` |

### Models

Models define routing rules for AI model requests:

| Parameter | Description | Example |
|-----------|-------------|---------|
| `models.<name>.enabled` | Enable this model route | `true` |
| `models.<name>.kind` | Model family used for routing and telemetry expectations | `text` |
| `models.<name>.pricing` | Cost formula inputs for `llm_custom_total_cost` | See [cost-tracking.md](./cost-tracking.md) |
| `models.<name>.backends.<ref>.enabled` | Enable this backend for the model | `true` |
| `models.<name>.backends.<ref>.ref` | Reference to backend definition | `gcp-primary` |
| `models.<name>.backends.<ref>.modelNameOverride` | Override model name sent to backend | `gpt-4-turbo` |
| `models.<name>.backends.<ref>.priority` | Failover priority (0 = primary) | `0` |
| `models.<name>.backends.<ref>.weight` | Load balancing weight | `50` |

## Example Values

```yaml
gatewayRef:
  name: core-gateway
  namespace: converse-gateway

rateLimitBudgeting:
  plans:
    free:
      monthlyBudgetUsd: 30
      modelBudgets:
        overrides: {}
    pro:
      monthlyBudgetUsd: 200
      modelBudgets:
        overrides: {}
rateLimitFallback:
  enabled: true
  requests: 30
  unit: Minute

backends:
  gpt-01:
    resourceName: gpt-backend-01-svc
    schema: OpenAI
    fqdn:
      hostname: api.ai.kivoyo.com
      port: 443
    securityType: APIKey
    secretRef:
      name: openai-api-key-01
    tlsHostname: api.ai.kivoyo.com
  gpt-02:
    resourceName: gpt-backend-02-svc
    schema: OpenAI
    fqdn:
      hostname: api.ai.kivoyo.com
      port: 443
    securityType: APIKey
    secretRef:
      name: openai-api-key-02
    tlsHostname: api.ai.kivoyo.com

models:
  gpt-5-mini:
    enabled: true
    kind: text
    pricing:
      strategy: weighted
      standard:
        inputPer1M: 0.75
        cachedInputPer1M: 0.075
        outputPer1M: 4.50
    backends:
      primary:
        enabled: true
        ref: gpt-01
        modelNameOverride: "gpt-5-mini"
        priority: 0
      secondary:
        enabled: true
        ref: gpt-02
        modelNameOverride: "gpt-5-mini"
        priority: 1

  text-embedding-3-small:
    enabled: true
    kind: embedding
    pricing:
      strategy: flat
      standard:
        effectivePer1M: 0.02
    backends:
      primary:
        enabled: true
        ref: gpt-01
        modelNameOverride: "text-embedding-3-small"
        priority: 0
      secondary:
        enabled: true
        ref: gpt-02
        modelNameOverride: "text-embedding-3-small"
        priority: 1
```

## Rate Limiting

The current chart does not use a per-model `envoyRateLimit` block anymore.

Instead, rate limiting works like this:

1. `AIGatewayRoute` computes `llm_custom_total_cost` from token usage and the model's pricing block.
2. `BackendTrafficPolicy` charges that value against the monthly budget for the account, billing plan, and model.
3. A separate fallback requests-per-minute rule protects against bursts.

The budget is decremented from response metadata, so the request that crosses the budget can still succeed. Once Redis already contains an exhausted bucket from earlier responses, the next matching request is rejected before it reaches the upstream provider.

If you need to tune behavior, update:

1. `rateLimitBudgeting.plans` for monthly budget limits
2. `rateLimitFallback` for the burst guard
3. `models.<name>.pricing` for the cost formula

## Backend Traffic Policies

In this chart, `BackendTrafficPolicy` is responsible for:

1. enforcing the monthly estimated-spend budget
2. enforcing the fallback burst rule

The policy does not contain provider pricing. Provider pricing lives in `values.yaml` and is rendered into `AIGatewayRoute`.

## Model Routing Requirements

Each enabled model route must have **at least 2 enabled backends**. This is enforced by the chart to ensure high availability.

## Related Charts

- **core-gateway** - Core gateway infrastructure (must be installed first)

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     core-gateway                            │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────┐ │
│  │ GatewayClass│  │   Gateway   │  │ ClientTrafficPolicy  │ │
│  └─────────────┘  └─────────────┘  └──────────────────────┘ │
│                          │                                   │
│                   ┌──────┴──────┐                           │
│                   │ EnvoyProxy  │                           │
│                   └─────────────┘                           │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                      models chart                           │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────┐ │
│  │   Backend   │  │AIServiceBknd│  │   AIGatewayRoute     │ │
│  └─────────────┘  └─────────────┘  └──────────────────────┘ │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────┐ │
│  │BackendSecPol│  │BackendTLSPol│  │       Secret         │ │
│  └─────────────┘  └─────────────┘  └──────────────────────┘ │
│  ┌──────────────────────────────────────────────────────────┐│
│  │          BackendTrafficPolicy (Retry + Rate Limit)      ││
│  └──────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```
