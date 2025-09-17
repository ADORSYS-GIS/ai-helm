# LMCache KServe Inference

A Helm chart to deploy an LMCache-enabled KServe InferenceService.

## Installation

```bash
helm install lmcache-inference ./lmcache-kserve-inference
```

## Configuration

Key configuration options:

- `inferenceService.model.image`: Container image for the inference service
- `inferenceService.model.storageUri`: Model storage location
- `inferenceService.resources`: CPU and memory resource limits
- `lmcache.chunkSize`: LMCache chunk size configuration
- `ingress.enabled`: Enable ingress for external access

## Values

See `values.yaml` for all available configuration options.
