# LMCache Helm Chart

A Helm chart to deploy LMCache, a high-performance KV cache management system for LLMs.

This chart uses the [bjw-s/app-template](https://github.com/bjw-s/helm-charts/tree/main/charts/library/app-template) chart as a library to deploy a pre-configured LMCache instance.

## Prerequisites

- Kubernetes 1.16+
- Helm 3.2.0+
- NVIDIA GPU resources available in the cluster.

## Installation

1.  **Add the bjw-s Helm repository:**

    ```sh
    helm repo add bjw-s https://bjw-s.github.io/helm-charts
    ```

2.  **Update your local Helm chart repository cache:**

    ```sh
    helm repo update
    ```

3.  **Install the LMCache chart:**

    Navigate to the root of the `ai-helm` repository and run:

    ```sh
    helm install my-lmcache ./charts/lmcache
    ```

## Configuration

This chart acts as a configuration wrapper for the `app-template` chart. All configuration parameters are set under the `app-template` key in the `values.yaml` file.

For a complete list of all available configuration options, please see the official [app-template documentation](https://bjw-s.github.io/helm-charts/docs/app-template).

### Key LMCache Parameters

The following table shows the most important parameters for configuring the LMCache application, located within the `app-template` object in `values.yaml`.

| Parameter | Description | Default |
| :--- | :--- | :--- |
| `app-template.controllers.main.containers.main.image.repository` | The container image repository. | `lmcache/vllm-openai` |
| `app-template.controllers.main.containers.main.image.tag` | The container image tag. | `2025-03-10` |
| `app-template.controllers.main.containers.main.env.LMCACHE_CHUNK_SIZE` | Size of the KV cache chunks. | `256` |
| `app-template.controllers.main.containers.main.env.LMCACHE_LOCAL_CPU` | Enable or disable local CPU caching. | `True` |
| `app-template.controllers.main.containers.main.resources` | Container resource requests and limits. | See `values.yaml` |
| `app-template.service.main.ports.http.port` | The port for the Kubernetes service. | `80` |
| `app-template.ingress.main.enabled` | Enable or disable the Kubernetes ingress. | `false` |
| `app-template.redis.host` | The hostname of the Redis backend. | `redis-master.redis.svc.cluster.local` |
| `app-template.redis.port` | The port for the Redis backend. | `6379` |

### Example `values.yaml`

Here is an example of a minimal `values.yaml` configuration:

```yaml
app-template:
  controllers:
    main:
      containers:
        main:
          image:
            repository: "lmcache/vllm-openai"
            tag: "2025-03-10"
          env:
            LMCACHE_CHUNK_SIZE: "512"
            LMCACHE_REMOTE_BACKEND: "redis"
            LMCACHE_REDIS_HOST: "{{ .Values.redis.host }}"
            LMCACHE_REDIS_PORT: "{{ .Values.redis.port }}"
          resources:
            requests:
              memory: "8Gi"
              cpu: "4000m"
              nvidia.com/gpu: "1"
            limits:
              nvidia.com/gpu: "1"

  service:
    main:
      ports:
        http:
          port: 8080

  ingress:
    main:
      enabled: true
      hosts:
        - host: lmcache.example.com
          paths:
            - path: /

  redis:
    host: "my-redis-host.example.com"
    port: 6379
```

## Values

For a full list of configurable values, see the `values.yaml` file and the [app-template documentation](https://bjw-s.github.io/helm-charts/docs/app-template).
