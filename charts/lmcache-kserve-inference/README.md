# LMCache KServe Inference

A Helm chart to deploy an LMCache-enabled KServe InferenceService.

## Overview

LMCache is an LLM serving engine extension that reduces Time to First Token (TTFT) and increases throughput by storing and reusing KV caches across multiple storage locations (GPU, CPU DRAM, Local Disk). This chart deploys LMCache with KServe for high-performance LLM inference.

## Infrastructure Requirements

### Platform Support
- **Linux NVIDIA GPU platform** (required)
- **Kubernetes cluster** with KServe installed
- **Docker Engine 27.0+** (for container deployment)

### LMCache Infrastructure Components

1. **Storage Backends**:
   - CPU memory caching (enabled by default)
   - Optional disk caching
   - Optional remote storage (Redis, etc.)

2. **Optional Components**:
   - **P2P Sharing**: For distributed KV cache sharing across instances
   - **Lookup Server**: For global KV cache coordination
   - **Controller**: For advanced cache management

### Resource Requirements
- **Memory**: Minimum 2Gi (configurable via `inferenceService.resources`)
- **CPU**: Minimum 1000m (1 CPU core)
- **GPU**: NVIDIA GPU required for inference
- **Storage**: Additional disk space if local disk caching is enabled

## Installation

```bash
helm install lmcache-inference ./lmcache-kserve-inference
```

## Configuration

### Key Configuration Options

- `inferenceService.model.image`: Container image (default: `lmcache/vllm-openai:latest`)
- `inferenceService.model.storageUri`: Model storage location (GCS, S3, etc.)
- `inferenceService.resources`: CPU and memory resource limits
- `lmcache.chunkSize`: LMCache chunk size (default: "256")
- `lmcache.localCpu`: Enable CPU caching (default: "True")
- `ingress.enabled`: Enable ingress for external access

### LMCache Environment Variables

The chart configures LMCache through environment variables:
- `LMCACHE_CHUNK_SIZE`: Size of cache chunks
- `LMCACHE_LOCAL_CPU`: Enable/disable CPU caching

For advanced configurations, you can extend the environment variables in the InferenceService template.

### Example Configuration

```yaml
inferenceService:
  model:
    image: "lmcache/vllm-openai:latest"
    storageUri: "gs://my-bucket/my-model"
  resources:
    requests:
      memory: "4Gi"
      cpu: "2000m"
    limits:
      memory: "8Gi"
      cpu: "4000m"

lmcache:
  chunkSize: "512"
  localCpu: "True"
```

## Deployment Notes

1. **Model Storage**: Ensure your model is accessible from the Kubernetes cluster
2. **GPU Resources**: The chart assumes GPU resources are managed by KServe
3. **Networking**: KServe handles service exposure and load balancing
4. **Scaling**: Use KServe's built-in autoscaling features

## Troubleshooting

- **Undefined Symbol Errors**: Ensure torch versions match between LMCache and vLLM
- **GPU Access**: Verify NVIDIA GPU operator is installed in the cluster
- **Model Loading**: Check that `storageUri` is accessible and contains a valid model

## Values

See `values.yaml` for all available configuration options.
