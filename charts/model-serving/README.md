# model-serving

Deploys a vLLM model via KServe + Knative. The chart provisions model-scoped
resources (ServingRuntime, InferenceService) and exposes optional adapters for
observability (Prometheus ServiceMonitor).

## Prerequisites

Operators assumed present in the cluster (not installed by this chart):

| Operator | Required | Condition |
|---|---|---|
| KServe controller (`serving.kserve.io` CRDs) | Always | - |
| Knative Serving (`serving.knative.dev` CRDs) | When `deploymentMode: Serverless` | - |
| Prometheus Operator (`monitoring.coreos.com` CRDs) | When `adapters.metrics.enabled` | - |

## Values Reference

### `model`

| Key | Default | Description |
|---|---|---|
| `model.name` | `"my-model"` | InferenceService name and `--served-model-name` in vLLM |
| `model.storageUri` | `""` | Model location. Supports `hf://`, `s3://`, `gs://`, `pvc://`. Required when `model.storage.pvc.enabled` is false; used as the download source when true |
| `model.format.name` | `"vllm"` | Model format for ServingRuntime autoSelect matching |
| `model.huggingFaceToken.secretName` | `""` | Secret containing a HuggingFace token for gated models |
| `model.huggingFaceToken.secretKey` | `"token"` | Key within the secret |

### `model.storage.pvc`

Creates a PVC to cache downloaded model weights. The PVC is annotated with
`helm.sh/resource-policy: keep` so it survives `helm uninstall` and upgrades.

| Key | Default | Description |
|---|---|---|
| `pvc.enabled` | `false` | Create a PVC for cached model weights |
| `pvc.nameOverride` | `""` | Override PVC name (default: `<model.name>-model-store`) |
| `pvc.accessModes` | `[ReadWriteOnce]` | PVC access modes |
| `pvc.size` | `"50Gi"` | Storage size. Rule of thumb: 7B fp16 ~14Gi, 13B ~26Gi, 70B ~140Gi |
| `pvc.storageClassName` | `""` | Leave empty for the cluster default StorageClass |
| `pvc.subPath` | `""` | Sub-directory within the PVC. Useful for sharing one PVC across releases. Produces `pvc://<name>/<subPath>` |

### `model.storage.downloader`

One-shot Helm hook Job that pre-downloads the model into the PVC. Only active
when both `pvc.enabled` and `downloader.enabled` are true.

- Runs as a `post-install` / `post-upgrade` hook
- Idempotent: skips download if the destination directory is already non-empty
- Hook delete policy: `before-hook-creation`

| Key | Default | Description |
|---|---|---|
| `downloader.enabled` | `false` | Run the download Job |
| `downloader.image.repository` | `kserve/storage-initializer` | Image that handles `hf://`, `s3://`, `gs://` etc. |
| `downloader.image.tag` | `v0.14.1` | Match to the KServe version in your cluster |
| `downloader.resources` | 1-2 CPU, 4-8Gi | Job resource requests/limits |
| `downloader.backoffLimit` | `3` | Kubernetes Job retry budget |
| `downloader.activeDeadlineSeconds` | `7200` | Hard deadline (default 2 hours) |

### `servingRuntime`

Creates a namespace-scoped ServingRuntime describing the vLLM container.
Set `enabled: false` to reference a pre-existing runtime via
`inferenceService.runtime` instead.

| Key | Default | Description |
|---|---|---|
| `servingRuntime.enabled` | `true` | Create a chart-managed ServingRuntime |
| `servingRuntime.nameOverride` | `""` | Override runtime name (default: `<model.name>-runtime`) |
| `servingRuntime.image.repository` | `vllm/vllm-openai` | vLLM image |
| `servingRuntime.image.tag` | `v0.6.4.post1` | vLLM version |
| `servingRuntime.port` | `8080` | HTTP port inside the container |
| `servingRuntime.args` | `[--tensor-parallel-size=1, --dtype=auto, --max-model-len=4096]` | Extra CLI flags appended after the mandatory `--port`, `--model`, `--served-model-name` |
| `servingRuntime.env` | `{}` | Extra environment variables (e.g. `VLLM_ATTENTION_BACKEND: FLASHINFER`) |
| `servingRuntime.resources` | 1 GPU, 4-8 CPU, 16-32Gi | Container resource requests/limits |
| `servingRuntime.probes` | see values.yaml | Liveness and readiness probe tuning |

### `inferenceService`

| Key | Default | Description |
|---|---|---|
| `inferenceService.deploymentMode` | `Serverless` | `Serverless` (Knative, supports scale-to-zero) or `RawDeployment` (plain Deployment, no Knative required) |
| `inferenceService.minReplicas` | `1` | Minimum replica count |
| `inferenceService.maxReplicas` | `3` | Maximum replica count |
| `inferenceService.scaleMetric` | `concurrency` | KPA metric: `concurrency`, `rps`, `cpu`, or `memory`. Ignored in RawDeployment mode |
| `inferenceService.scaleTarget` | `1` | KPA target value per replica. Ignored in RawDeployment mode |
| `inferenceService.scaleDownDelay` | `"0s"` | Grace period before Knative scales to zero. Ignored in RawDeployment mode |
| `inferenceService.timeout` | `300` | Request deadline in seconds |
| `inferenceService.runtime` | `""` | Reference an existing ServingRuntime/ClusterServingRuntime by name. Defaults to the chart-managed runtime |
| `inferenceService.resources` | `{}` | Predictor-level resource overrides (take precedence over ServingRuntime defaults) |
| `inferenceService.nodeSelector` | `{}` | Node selector for GPU / spot scheduling |
| `inferenceService.tolerations` | `[]` | Pod tolerations |

### `adapters.metrics`

Emits a Prometheus `ServiceMonitor` that scrapes vLLM's `/metrics` endpoint.

| Key | Default | Description |
|---|---|---|
| `metrics.enabled` | `false` | Create the ServiceMonitor |
| `metrics.serviceMonitor.labels` | `{}` | Labels to match your Prometheus `serviceMonitorSelector` |
| `metrics.serviceMonitor.portName` | `"http-userport"` | Port name on the KServe Service. Serverless uses `http-userport`; RawDeployment uses `http1` |
| `metrics.serviceMonitor.path` | `/metrics` | Metrics endpoint path |
| `metrics.serviceMonitor.interval` | `"30s"` | Scrape interval |
| `metrics.serviceMonitor.scrapeTimeout` | `"10s"` | Scrape timeout |

### `serving`

Extension point backed by the
[bjw-s app-template v4.x](https://bjw-s-labs.github.io/helm-charts/docs/app-template/).
Set `serving.enabled: true` to bolt on supplementary workloads (ServiceAccounts,
ConfigMaps, Jobs, rawResources) alongside the KServe CRDs.

Disabled by default.

## TLS

There is intentionally no TLS adapter in this chart. Certificate provisioning
is handled at the infrastructure level:

- **Ingress shim**: cert-manager watches Ingress objects annotated with
  `cert-manager.io/cluster-issuer`
- **Gateway shim**: cert-manager watches Gateway API objects with the same
  annotation (requires `enableGatewayAPI: true` in cert-manager)
- **Knative Serverless**: the `net-certmanager` integration handles per-model
  certificates cluster-wide automatically
