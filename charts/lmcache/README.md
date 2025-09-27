# LMCache Helm Chart

This Helm chart deploys [LMCache](https://github.com/lm-cache/lm-cache), a high-performance KV cache management system for LLMs.

## Prerequisites

- Kubernetes 1.19+
- Helm 3.2.0+

## Installing the Chart

To install the chart with the release name `my-release`:

```bash
helm repo add adorsys https://adorsys.github.io/ai-helm
helm install my-release adorsys/lmcache
```

## Uninstalling the Chart

To uninstall/delete the `my-release` deployment:

```bash
helm delete my-release
```

## Configuration

The following table lists the configurable parameters of the LMCache chart and their default values.

| Parameter | Description | Default |
| --- | --- | --- |
| `global.nameOverride` | Name to override the release name. | `""` |
| `global.fullnameOverride` | Name to override the full name of the chart. | `""` |
| `controllers.main.strategy` | Controller deployment strategy. | `RollingUpdate` |
| `controllers.main.annotations` | Annotations for the controller pods. | `{}` |
| `controllers.main.podSecurityContext` | Pod security context. | `{}` |
| `controllers.main.containers.main.image.repository` | Container image repository. | `"lmcache/vllm-openai"` |
| `controllers.main.containers.main.image.tag` | Container image tag. | `"2025-03-10"` |
| `controllers.main.containers.main.image.pullPolicy` | Container image pull policy. | `IfNotPresent` |
| `controllers.main.containers.main.env` | Environment variables for the container. | `see values.yaml` |
| `controllers.main.containers.main.probes.liveness.enabled` | Enable liveness probe. | `true` |
| `controllers.main.containers.main.probes.readiness.enabled` | Enable readiness probe. | `true` |
| `controllers.main.containers.main.resources` | Resource requests and limits for the container. | `see values.yaml` |
| `service.main.type` | Service type. | `ClusterIP` |
| `service.main.ports.http.port` | Service port. | `80` |
| `service.main.ports.http.targetPort` | Service target port. | `8000` |
| `ingress.main.enabled` | Enable ingress. | `false` |
| `ingress.main.className` | Ingress class name. | `""` |
| `ingress.main.annotations` | Ingress annotations. | `{}` |
| `ingress.main.hosts` | Ingress hosts. | `[]` |
| `ingress.main.tls` | Ingress TLS configuration. | `[]` |
| `persistence.enabled` | Enable persistence. | `false` |
| `persistence.storageClass` | Persistence storage class. | `""` |
| `persistence.accessMode` | Persistence access mode. | `ReadWriteOnce` |
| `persistence.size` | Persistence size. | `1Gi` |
| `persistence.mountPath` | Persistence mount path. | `/data` |
| `nodeSelector` | Node selector configuration. | `{}` |
| `tolerations` | Tolerations configuration. | `[]` |
| `affinity` | Affinity configuration. | `{}` |
| `rbac.roles` | RBAC roles. | `{}` |
| `redis.host` | Redis host. | `"redis-master.redis.svc.cluster.local"` |
| `redis.port` | Redis port. | `6379` |
