# Models

A Helm chart for deploying AI model backends and routing configuration on Kubernetes using Envoy Gateway.

## Description

This chart deploys the model-specific components for an AI Gateway:

- **Backend** - Envoy backend endpoints (FQDN-based)
- **AIServiceBackend** - AI service backend definitions with schema configuration
- **AIGatewayRoute** - Model routing rules with load balancing and failover
- **BackendSecurityPolicy** - API key authentication policies
- **BackendTLSPolicy** - TLS configuration for backend connections
- **Secret** - API key secrets for backend authentication
- **RateLimitPolicy** - Kuadrant rate limiting per model route

This chart requires the `ai-gateway-core` chart to be installed first, which provides the Gateway infrastructure.

## Prerequisites

- Kubernetes 1.24+
- Helm 3.0+
- [Envoy Gateway](https://gateway.envoyproxy.io/) installed in the cluster
- `ai-gateway-core` chart installed
- [Kuadrant Operator](https://kuadrant.io/) installed (for rate limiting)
- Redis (for Kuadrant rate limiting backend)

## Installation

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

## Configuration

### Gateway Reference

| Parameter | Description | Default |
|-----------|-------------|---------|
| `gatewayRef.name` | Name of the Gateway resource (from ai-gateway-core) | `ai-gateway` |

### Rate Limit Policy

| Parameter | Description | Default |
|-----------|-------------|---------|
| `rateLimitPolicy.enabled` | Enable/disable rate limiting | `true` |
| `rateLimitPolicy.labels` | Additional labels for RateLimitPolicy | `{}` |
| `rateLimitPolicy.annotations` | Additional annotations for RateLimitPolicy | `{}` |
| `rateLimitPolicy.defaults.limits` | Default rate limits applied to all models | See below |

Default rate limits:
```yaml
rateLimitPolicy:
  defaults:
    limits:
      default:
        rates:
          - limit: 100
            window: 1m
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
  defaults:
    limits:
      default:
        rates:
          - limit: 100
            window: 1m

backends:
  openai-primary:
    resourceName: openai-backend-svc
    schema: OpenAI
    fqdn:
      hostname: api.openai.com
      port: 443
    apiKeySecretRef:
      name: openai-apikey
      key: apiKey
    tlsHostname: api.openai.com

  anthropic-primary:
    resourceName: anthropic-backend-svc
    schema: OpenAI
    fqdn:
      hostname: api.anthropic.com
      port: 443
    apiKeySecretRef:
      name: anthropic-apikey
      key: apiKey
    tlsHostname: api.anthropic.com

models:
  gpt-4:
    enabled: true
    modelMatch: "gpt-4"
    rateLimit:
      limits:
        gpt4-limit:
          rates:
            - limit: 50
              window: 1m
    backends:
      primary:
        enabled: true
        ref: openai-primary
        priority: 0
        weight: 100
      failover:
        enabled: true
        ref: anthropic-primary
        modelNameOverride: "claude-3-opus"
        priority: 1

  claude-3:
    enabled: true
    modelMatch: "claude-3"
    backends:
      primary:
        enabled: true
        ref: anthropic-primary
        priority: 0
        weight: 50
      secondary:
        enabled: true
        ref: anthropic-primary
        modelNameOverride: "claude-3-sonnet"
        priority: 0
        weight: 50
```

## Rate Limiting

Rate limiting is implemented using [Kuadrant](https://kuadrant.io/) RateLimitPolicy resources. Each enabled model route gets its own RateLimitPolicy that targets the AIGatewayRoute.

### Per-Model Rate Limits

You can override the default rate limits for specific models:

```yaml
models:
  expensive-model:
    enabled: true
    rateLimit:
      limits:
        strict-limit:
          rates:
            - limit: 10
              window: 1m
    backends:
      # ...
```

### Disabling Rate Limiting

To disable rate limiting entirely:

```bash
helm install models ./charts/models --set rateLimitPolicy.enabled=false
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
│  │                   RateLimitPolicy                        ││
│  └──────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```
