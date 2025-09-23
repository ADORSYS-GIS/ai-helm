# LMCache

A Helm chart to deploy LMCache - a high-performance KV cache management system for LLMs.

## Overview

LMCache is an LLM serving engine extension that reduces Time to First Token (TTFT) and increases throughput by storing and reusing KV caches across multiple storage locations (GPU, CPU DRAM, Local Disk). This chart deploys LMCache as a standalone service that can be integrated with various LLM serving engines like vLLM.

## Infrastructure Requirements

### Platform Support
- **Linux NVIDIA GPU platform** (required)
- **Kubernetes cluster**
- **Docker Engine 27.0+** (for container deployment)

### LMCache Infrastructure Components

1. **Storage Backends**:
   - CPU memory caching (enabled by default)
   - Optional disk caching
   - Optional remote storage (Redis, S3, etc.)

2. **Optional Components**:
   - **P2P Sharing**: For distributed KV cache sharing across instances
   - **Lookup Server**: For global KV cache coordination
   - **Remote Storage**: Redis, S3, or other backends for persistent caching

### Resource Requirements
- **Memory**: Minimum 4Gi (configurable via `deployment.resources`)
- **CPU**: Minimum 2000m (2 CPU cores)
- **GPU**: NVIDIA GPU required for inference workloads
- **Storage**: Additional disk space if local disk caching is enabled

## Installation

```bash
helm install lmcache ./lmcache
```

## Configuration

### Key Configuration Options

- `deployment.image.repository`: Container image (default: `lmcache/vllm-openai`)
- `deployment.image.tag`: Image tag (default: `latest`)
- `deployment.resources`: CPU, memory, and GPU resource limits
- `lmcache.chunkSize`: LMCache chunk size (default: "256")
- `lmcache.localCpu`: Enable CPU caching (default: "True")
- `service.type`: Kubernetes service type (default: `ClusterIP`)
- `ingress.enabled`: Enable ingress for external access

### LMCache Environment Variables

The chart configures LMCache through environment variables:
- `LMCACHE_CHUNK_SIZE`: Size of cache chunks
- `LMCACHE_LOCAL_CPU`: Enable/disable CPU caching
- `LMCACHE_LOCAL_DISK`: Path for local disk caching
- `LMCACHE_MAX_LOCAL_DISK_SIZE`: Maximum disk cache size in GB
- `LMCACHE_REMOTE_URL`: Remote storage backend URL
- `LMCACHE_ENABLE_P2P`: Enable peer-to-peer cache sharing
- `LMCACHE_LOOKUP_URL`: P2P lookup server URL
- `LMCACHE_DISTRIBUTED_URL`: P2P distributed coordination URL

### Example Configuration

```yaml
deployment:
  image:
    repository: "lmcache/vllm-openai"
    tag: "latest"
  resources:
    requests:
      memory: "4Gi"
      cpu: "2000m"
      nvidia.com/gpu: "1"
    limits:
      memory: "8Gi"
      cpu: "4000m"
      nvidia.com/gpu: "1"

lmcache:
  chunkSize: "512"
  localCpu: "True"
  localDisk: "file:///tmp/lmcache"
  maxLocalDiskSize: "10.0"

service:
  type: LoadBalancer
  port: 80
```

## Advanced Configuration

### Storage Backends

LMCache supports multiple storage backends:

1. **CPU RAM** (default): Fast access, limited by system memory
2. **Local Disk**: Persistent storage, configurable size limit
3. **Remote Storage**: Redis, S3, or other external backends
4. **P2P Sharing**: Distributed cache sharing across multiple instances

### Health Checks

The chart includes configurable health checks:
- **Liveness Probe**: Ensures the container is running
- **Readiness Probe**: Ensures the service is ready to accept traffic

### Autoscaling

Enable horizontal pod autoscaling:

```yaml
autoscaling:
  enabled: true
  minReplicas: 1
  maxReplicas: 10
  targetCPUUtilizationPercentage: 80
```

## Deployment Notes

1. **GPU Resources**: Ensure NVIDIA GPU operator is installed for GPU access
2. **Storage**: Configure persistent volumes if using local disk caching
3. **Networking**: Use ingress or LoadBalancer for external access
4. **Security**: Configure security contexts and RBAC as needed

## Integration with LLM Serving Engines

LMCache can be integrated with various LLM serving engines:
- **vLLM**: Use the `lmcache/vllm-openai` image
- **KServe**: Deploy alongside KServe InferenceServices
- **Custom Engines**: Configure environment variables for integration

## Troubleshooting

- **Undefined Symbol Errors**: Ensure torch versions match between LMCache and serving engine
- **GPU Access**: Verify NVIDIA GPU operator is installed in the cluster
- **Cache Performance**: Monitor cache hit rates and adjust chunk size accordingly
- **Storage Issues**: Check disk space and permissions for local disk caching

## Values

See `values.yaml` for all available configuration options.
