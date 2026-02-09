# AI Gateway Core

A Helm chart for deploying the core AI Gateway infrastructure on Kubernetes using Envoy Gateway.

## Description

This chart deploys the foundational infrastructure components required for an AI Gateway:

- **GatewayClass** - Defines the Envoy Gateway controller
- **Gateway** - The main gateway resource that handles incoming traffic
- **EnvoyProxy** - Configuration for the Envoy proxy deployment
- **ClientTrafficPolicy** - Traffic policies for client connections
- **GatewayConfig** - AI Gateway extension configuration (tracing, processing)

This chart should be installed **before** the `models` chart, which deploys the actual AI model backends and routing rules.

## Prerequisites

- Kubernetes 1.24+
- Helm 3.0+
- [Envoy Gateway](https://gateway.envoyproxy.io/) installed in the cluster

## Installation

```bash
# Install the chart with default values
helm install ai-gateway-core ./charts/ai-gateway-core

# Install with custom values
helm install ai-gateway-core ./charts/ai-gateway-core -f my-values.yaml

# Install with EnvoyProxy disabled
helm install ai-gateway-core ./charts/ai-gateway-core --set envoyProxy.enabled=false
```

## Configuration

### GatewayClass

| Parameter | Description | Default |
|-----------|-------------|---------|
| `gatewayClass.enabled` | Enable/disable GatewayClass | `true` |
| `gatewayClass.name` | Name of the GatewayClass | `ai-gateway` |
| `gatewayClass.controllerName` | Controller name | `gateway.envoyproxy.io/gatewayclass-controller` |
| `gatewayClass.labels` | Additional labels | `{}` |
| `gatewayClass.annotations` | Additional annotations | `{}` |

### Gateway

| Parameter | Description | Default |
|-----------|-------------|---------|
| `gateway.enabled` | Enable/disable Gateway | `true` |
| `gateway.name` | Name of the Gateway | `ai-gateway` |
| `gateway.className` | GatewayClass reference (defaults to gatewayClass.name) | `""` |
| `gateway.labels` | Additional labels | `{}` |
| `gateway.annotations` | Additional annotations | `{}` |
| `gateway.listeners` | List of gateway listeners | See below |
| `gateway.infrastructure.enabled` | Enable EnvoyProxy reference | `true` |

#### Default Listeners

```yaml
listeners:
  - name: http
    protocol: HTTP
    port: 80
```

### GatewayConfig

| Parameter | Description | Default |
|-----------|-------------|---------|
| `gatewayConfig.enabled` | Enable/disable GatewayConfig | `true` |
| `gatewayConfig.name` | Name of the GatewayConfig | `ai-gateway-tracing` |
| `gatewayConfig.labels` | Additional labels | `{}` |
| `gatewayConfig.annotations` | Additional annotations | `{}` |
| `gatewayConfig.extProc.kubernetes.env` | Environment variables for extProc | `[]` |

#### Tracing Configuration

Tracing is configured via the `GatewayConfig` resource using OTLP environment variables:

```yaml
gatewayConfig:
  enabled: true
  name: ai-gateway-tracing
  spec:
    extProc:
      kubernetes:
        env:
          - name: OTEL_EXPORTER_OTLP_ENDPOINT
            value: "https://tempo-prod-10-prod-eu-west-2.grafana.net/tempo"
          - name: OTEL_SERVICE_NAME
            value: "ai-gateway"
          - name: OTEL_EXPORTER_OTLP_PROTOCOL
            value: "http/protobuf"
```

For Grafana Cloud Tempo with authentication, you can add basic auth credentials:

```yaml
gatewayConfig:
  enabled: true
  name: ai-gateway-tracing
  spec:
    extProc:
      kubernetes:
        env:
          - name: OTEL_EXPORTER_OTLP_ENDPOINT
            value: "https://username:api-key@tempo-prod-10-prod-eu-west-2.grafana.net/tempo"
          - name: OTEL_SERVICE_NAME
            value: "ai-gateway"
```

### EnvoyProxy

| Parameter | Description | Default |
|-----------|-------------|---------|
| `envoyProxy.enabled` | Enable/disable EnvoyProxy | `true` |
| `envoyProxy.name` | Name of the EnvoyProxy | `ai-gateway` |
| `envoyProxy.labels` | Additional labels | `{}` |
| `envoyProxy.annotations` | Additional annotations | `{}` |

#### Provider Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `envoyProxy.provider.type` | Provider type | `Kubernetes` |
| `envoyProxy.provider.kubernetes.envoyDeployment.replicas` | Number of replicas | `1` |
| `envoyProxy.provider.kubernetes.envoyDeployment.pod.labels` | Pod labels | `{}` |
| `envoyProxy.provider.kubernetes.envoyDeployment.pod.annotations` | Pod annotations | `{}` |
| `envoyProxy.provider.kubernetes.envoyDeployment.pod.securityContext` | Pod security context | `{}` |
| `envoyProxy.provider.kubernetes.envoyDeployment.pod.tolerations` | Pod tolerations | `[]` |
| `envoyProxy.provider.kubernetes.envoyDeployment.pod.nodeSelector` | Pod node selector | `{}` |
| `envoyProxy.provider.kubernetes.envoyDeployment.pod.affinity` | Pod affinity rules | `{}` |
| `envoyProxy.provider.kubernetes.envoyDeployment.container.resources` | Container resources | `{}` |
| `envoyProxy.provider.kubernetes.envoyDeployment.container.securityContext` | Container security context | `{}` |
| `envoyProxy.provider.kubernetes.envoyDeployment.container.env` | Environment variables | `[]` |
| `envoyProxy.provider.kubernetes.envoyDeployment.container.volumeMounts` | Volume mounts | `[]` |
| `envoyProxy.provider.kubernetes.envoyDeployment.volumes` | Volumes | `[]` |

#### Service Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `envoyProxy.provider.kubernetes.envoyService.type` | Service type | `LoadBalancer` |
| `envoyProxy.provider.kubernetes.envoyService.annotations` | Service annotations | `{}` |
| `envoyProxy.provider.kubernetes.envoyService.loadBalancerIP` | Load balancer IP | `""` |
| `envoyProxy.provider.kubernetes.envoyService.externalTrafficPolicy` | External traffic policy | `""` |

#### Logging & Telemetry

| Parameter | Description | Default |
|-----------|-------------|---------|
| `envoyProxy.logging.level.default` | Default log level | `info` |
| `envoyProxy.telemetry.accessLog` | Access log configuration | `{}` |
| `envoyProxy.telemetry.metrics` | Metrics configuration | `{}` |
| `envoyProxy.telemetry.tracing` | Tracing configuration | `{}` |

#### Shutdown Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `envoyProxy.shutdown.drainTimeout` | Drain timeout | `30s` |
| `envoyProxy.shutdown.minDrainDuration` | Minimum drain duration | `5s` |

### ClientTrafficPolicy

| Parameter | Description | Default |
|-----------|-------------|---------|
| `clientTrafficPolicy.enabled` | Enable/disable ClientTrafficPolicy | `true` |
| `clientTrafficPolicy.name` | Name of the policy | `client-buffer-limit` |
| `clientTrafficPolicy.labels` | Additional labels | `{}` |
| `clientTrafficPolicy.annotations` | Additional annotations | `{}` |
| `clientTrafficPolicy.targetRefs` | Custom target refs (defaults to Gateway) | `[]` |
| `clientTrafficPolicy.connection.bufferLimit` | Connection buffer limit | `50Mi` |
| `clientTrafficPolicy.connection.connectionTimeout` | Connection timeout | `""` |
| `clientTrafficPolicy.http` | HTTP configuration | `{}` |
| `clientTrafficPolicy.timeout` | Timeout configuration | `{}` |
| `clientTrafficPolicy.tls` | TLS configuration | `{}` |
| `clientTrafficPolicy.path` | Path configuration | `{}` |
| `clientTrafficPolicy.headers` | Headers configuration | `{}` |
| `clientTrafficPolicy.healthCheck` | Health check configuration | `{}` |

## Example Values

### Basic Configuration

```yaml
gatewayClass:
  enabled: true
  name: ai-gateway

gateway:
  enabled: true
  name: ai-gateway
  listeners:
    - name: http
      protocol: HTTP
      port: 80

envoyProxy:
  enabled: true
  name: ai-gateway

clientTrafficPolicy:
  enabled: true
  connection:
    bufferLimit: 50Mi
```

### Production Configuration

```yaml
gatewayClass:
  enabled: true
  name: ai-gateway
  annotations:
    description: "Production AI Gateway"

gateway:
  enabled: true
  name: ai-gateway
  listeners:
    - name: http
      protocol: HTTP
      port: 80
    - name: https
      protocol: HTTPS
      port: 443
      tls:
        mode: Terminate
        certificateRefs:
          - name: ai-gateway-tls
            kind: Secret

gatewayConfig:
  enabled: true
  name: ai-gateway-tracing
  spec:
    extProc:
      kubernetes:
        env:
          - name: OTEL_EXPORTER_OTLP_ENDPOINT
            value: "https://tempo-prod-10-prod-eu-west-2.grafana.net/tempo"
          - name: OTEL_SERVICE_NAME
            value: "ai-gateway-production"

envoyProxy:
  enabled: true
  name: ai-gateway
  provider:
    type: Kubernetes
    kubernetes:
      envoyDeployment:
        replicas: 3
        pod:
          annotations:
            prometheus.io/scrape: "true"
          tolerations:
            - key: "dedicated"
              operator: "Equal"
              value: "gateway"
              effect: "NoSchedule"
          affinity:
            podAntiAffinity:
              preferredDuringSchedulingIgnoredDuringExecution:
                - weight: 100
                  podAffinityTerm:
                    labelSelector:
                      matchLabels:
                        app: envoy
                    topologyKey: kubernetes.io/hostname
        container:
          resources:
            limits:
              cpu: "2"
              memory: "4Gi"
            requests:
              cpu: "500m"
              memory: "1Gi"
      envoyService:
        type: LoadBalancer
        annotations:
          service.beta.kubernetes.io/aws-load-balancer-type: "nlb"
  logging:
    level:
      default: warn
  shutdown:
    drainTimeout: 60s
    minDrainDuration: 10s

clientTrafficPolicy:
  enabled: true
  connection:
    bufferLimit: 100Mi
    connectionTimeout: 60s
  timeout:
    http:
      requestTimeout: 300s
  tls:
    minVersion: "1.2"
    maxVersion: "1.3"
```

### Minimal Configuration (No EnvoyProxy)

```yaml
gatewayClass:
  enabled: true
  name: ai-gateway

gateway:
  enabled: true
  name: ai-gateway
  infrastructure:
    enabled: false

envoyProxy:
  enabled: false

clientTrafficPolicy:
  enabled: true
  connection:
    bufferLimit: 50Mi
```

## Related Charts

- **models** - Deploy AI model backends and routing rules that connect to this gateway

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    ai-gateway-core                          │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────┐ │
│  │ GatewayClass│  │   Gateway   │  │ ClientTrafficPolicy  │ │
│  └─────────────┘  └─────────────┘  └──────────────────────┘ │
│         ┌────────────────┴────────────────┐                 │
│         │       GatewayConfig             │                 │
│         │ (tracing, extProc settings)     │                 │
│         └──────────────────────────────────┘                 │
│                          │                                   │
│                   ┌──────┴──────┐                           │
│                   │ EnvoyProxy  │ (optional)                  │
│                   └─────────────┘                            │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                      models chart                           │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────┐ │
│  │   Backend   │  │AIServiceBknd│  │   AIGatewayRoute     │ │
│  └─────────────┘  └─────────────┘  └──────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```
