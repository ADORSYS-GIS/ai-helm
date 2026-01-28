# Models

A Helm chart for deploying AI model backends and routing configuration on Kubernetes using Envoy Gateway.

## Description

This chart deploys the model-specific components for an AI Gateway:

- **Backend** - Envoy backend endpoints (FQDN-based)
- **AIServiceBackend** - AI service backend definitions with schema configuration
- **AIGatewayRoute** - Model routing rules with load balancing and failover
- **BackendSecurityPolicy** - API key authentication policies
- **BackendTLSPolicy** - TLS configuration for backend connections
- **BackendTrafficPolicy** - Retry, fallback, and token-based rate limiting policies for backend connections
- **Secret** - API key secrets for backend authentication

This chart requires the `ai-gateway-core` chart to be installed first, which provides the Gateway infrastructure.

## Prerequisites

- Kubernetes 1.24+
- Helm 3.0+
- [Envoy Gateway](https://aigateway.envoyproxy.io/docs/getting-started/prerequisites) installed in the cluster with rate limiting enabled
- [Envoy Ai Gateway](https://aigateway.envoyproxy.io/docs/getting-started/installation) installed too
- `ai-gateway-core` chart installed
- `redis` installed

## Installation

### Prepare Secrets

Before installing, prepare your API key secrets:

```bash
# Copy the example secret file
cp secret.example.yaml secret.yaml

# Edit secret.yaml with your actual API keys
# Update the apiKey values and service account JSON as needed

# Apply the secrets to Kubernetes
kubectl apply -f secret.yaml
```

### Install the Charts

```bash
# First, install the core gateway infrastructure
helm install ai-gateway-core ./charts/ai-gateway-core

# Then install the models chart
helm install models ./charts/models

# Install with custom values
helm install models ./charts/models -f my-values.yaml

# Install without rate limiting
helm install models ./charts/models --set rateLimitPolicy.enabled=false
```

## Testing

After installing the chart, you can test the AI Gateway locally using curl requests. First, ensure the Gateway is accessible (e.g., via port-forwarding or LoadBalancer IP).

### Port Forwarding (for local testing)

```bash
# Get the Envoy service name dynamically
export ENVOY_SERVICE=$(kubectl get svc -n envoy-gateway-system \
  --selector=gateway.envoyproxy.io/owning-gateway-namespace=default,gateway.envoyproxy.io/owning-gateway-name=ai-gateway \
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
  -H "x-user-id: user1" \
  -d '{
    "model": "fireworks-instruct",
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

### Screenshots

Placeholder for testing screenshots:

- ![Gateway Installation](screenshots/gateway-install.png)
- ![Successful API Response](screenshots/api-response.png)
- ![Rate Limiting Test](screenshots/rate-limit.png)

## Configuration

### Gateway Reference

| Parameter | Description | Default |
|-----------|-------------|---------|
| `gatewayRef.name` | Name of the Gateway resource (from ai-gateway-core) | `ai-gateway` |

### Envoy Rate Limiting

| Parameter | Description | Default |
|-----------|-------------|---------|
| `envoyRateLimit.enabled` | Enable/disable Envoy rate limiting | `true` |
| `models.<name>.envoyRateLimit.requests` | Token limit per user per model | `30` |
| `models.<name>.envoyRateLimit.unit` | Time unit for rate limiting | `Minute` |

Rate limiting is implemented using Envoy Gateway's built-in global rate limiting. Limits are applied per user per model based on actual token consumption, using metadata from AI Gateway responses.

### Backend Traffic Policy

| Parameter | Description | Default |
|-----------|-------------|---------|
| `backendTrafficPolicy.enabled` | Enable/disable backend traffic policies | `true` |
| `backendTrafficPolicy.name` | Name of the BackendTrafficPolicy | `backend-retry-policy` |
| `backendTrafficPolicy.labels` | Additional labels | `{}` |
| `backendTrafficPolicy.annotations` | Additional annotations | `{}` |
| `backendTrafficPolicy.targetRefs` | Target resources for the policy | See below |
| `backendTrafficPolicy.retry` | Retry configuration | See below |
| `envoyRateLimit.enabled` | Enable Envoy rate limiting (when true, adds rateLimit to policy) | `true` |

Default backend traffic policy:
```yaml
backendTrafficPolicy:
  enabled: true
  targetRefs:
    - group: gateway.networking.k8s.io
      kind: Gateway
      name: ai-gateway
  retry:
    numRetries: 3
    perRetry:
      backOff:
        baseInterval: 100ms
        maxInterval: 10s
      timeout: 30s
    retryOn:
      httpStatusCodes:
        - 500
        - 502
        - 503
        - 504
        - 404
      triggers:
        - connect-failure
        - retriable-status-codes
```

### Backends

Backends define the upstream AI service endpoints:

| Parameter | Description | Example |
|-----------|-------------|---------|
| `backends.<name>.resourceName` | Kubernetes resource name | `gcp-backend-svc` |
| `backends.<name>.schema` | AI service schema (OpenAI, etc.) | `OpenAI` |
| `backends.<name>.prefix` | Optional URL prefix | `/inference/v1` |
| `backends.<name>.fqdn.hostname` | Backend hostname | `api.openai.com` |
| `backends.<name>.fqdn.port` | Backend port | `443` |
| `backends.<name>.apiKeySecretRef.name` | Secret name for API key | `openai-apikey` |
| `backends.<name>.apiKeySecretRef.key` | Key in secret | `apiKey` |
| `backends.<name>.tlsHostname` | TLS hostname for validation | `api.openai.com` |

### Models

Models define routing rules for AI model requests:

| Parameter | Description | Example |
|-----------|-------------|---------|
| `models.<name>.enabled` | Enable this model route | `true` |
| `models.<name>.modelMatch` | Model name to match in requests | `gpt-4` |
| `models.<name>.rateLimit` | Per-model rate limit override | See below |
| `models.<name>.backends.<ref>.enabled` | Enable this backend for the model | `true` |
| `models.<name>.backends.<ref>.ref` | Reference to backend definition | `gcp-primary` |
| `models.<name>.backends.<ref>.modelNameOverride` | Override model name sent to backend | `gpt-4-turbo` |
| `models.<name>.backends.<ref>.priority` | Failover priority (0 = primary) | `0` |
| `models.<name>.backends.<ref>.weight` | Load balancing weight | `50` |

## Example Values

```yaml
gatewayRef:
  name: ai-gateway

rateLimitPolicy:
  enabled: true

backendTrafficPolicy:
  enabled: true
  targetRefs:
    - group: gateway.networking.k8s.io
      kind: Gateway
      name: ai-gateway
  retry:
    numRetries: 3
    perRetry:
      backOff:
        baseInterval: 100ms
        maxInterval: 10s
      timeout: 30s
    retryOn:
      httpStatusCodes:
        - 500
        - 502
        - 503
        - 504
        - 404
      triggers:
        - connect-failure
        - retriable-status-codes

backends:
  gpt-01:
    resourceName: gpt-backend-01-svc
    schema: OpenAI
    fqdn:
      hostname: api.ai.kivoyo.com
      port: 443
    securityType: APIKey
    useEnvVars: true
    envSecretRef:
      name: openai-api-key-01
    tlsHostname: api.ai.kivoyo.com
  gpt-02:
    resourceName: gpt-backend-02-svc
    schema: OpenAI
    fqdn:
      hostname: api.ai.kivoyo.com
      port: 443
    securityType: APIKey
    useEnvVars: true
    envSecretRef:
      name: openai-api-key-02
    tlsHostname: api.ai.kivoyo.com

models:
  gpt-04:
    enabled: true

    rateLimit:
      scope:
        - user
        - model
        - tokens

      limits:
        requests:
          rates:
            - limit: 3
              window: 1m
        tokens:
          rates:
            - limit: 50
              window: 1m
        
    backends:
      aws-01:
        enabled: true
        ref: gpt-01
        modelNameOverride: "gpt-4o-mini"
        priority: 0
      aws-02:
        enabled: true
        ref: gpt-02
        modelNameOverride: "gpt-4o-mini"
        priority: 1
```

## Rate Limiting

Rate limiting is implemented using Envoy Gateway's built-in global rate limiting. The chart supports token-based rate limiting per user per model, using AI Gateway metadata to count actual token consumption.

### Rate Limit Configuration

Rate limits are configured per model in the values.yaml file. Each model can have its own token limit per user. The limits are enforced globally across all backends for that model.

Example configuration:
```yaml
models:
  gpt-5:
    enabled: true
    envoyRateLimit:
      requests: 30  # Max 30 tokens per minute per user
      unit: Minute
```

## Backend Traffic Policies

Backend traffic policies provide retry and fallback logic for backend connections. The BackendTrafficPolicy applies to the Gateway and configures retry behavior for failed requests, including exponential backoff and specific HTTP status codes to retry on.

### Disabling Rate Limiting

To disable Envoy rate limiting:

```bash
helm install models ./charts/models --set envoyRateLimit.enabled=false
```

## Model Routing Requirements

Each enabled model route must have **at least 2 enabled backends**. This is enforced by the chart to ensure high availability.

## Related Charts

- **ai-gateway-core** - Core gateway infrastructure (must be installed first)

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    ai-gateway-core                          │
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
