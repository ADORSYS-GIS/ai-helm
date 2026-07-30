# Webank governed training deployment

The `webank-training` chart installs a single namespaced Argo
`WorkflowTemplate`, `webank-weak-training-pass`, in `mlops`. It is the live,
manual GPU-training route for `ADORSYS-GIS/webank-models` — not a scheduler and
not a model-serving deployment. It implements Webank
[ADR-0034](https://github.com/ADORSYS-GIS/webank-models/blob/main/docs/adr/0034-training-job-orchestration-argo-workflows.md)
and [ADR-0035](https://github.com/ADORSYS-GIS/webank-models/blob/main/docs/adr/0035-training-observability-on-mlflow.md).

## Deployment shape

`charts/apps` creates `aii-webank-training` as a normal OCI Application. Its
deployment values are read from the private `ai-helm-values` repository and its
one dependency overlay materialises `mlops/mlflow-automation` from the existing
AWS Secrets Manager property. This order is intentional: merge the values-repo
change before the chart Application so `ignoreMissingValueFiles` can never
install an incomplete template.

The template runs as the existing `argo-workflow` ServiceAccount. That identity
has Argo executor permissions only; it does not grant data or experiment access.
The GPU and candidate-push steps receive the minimum extra credentials they
need:

| Boundary | Mechanism |
|---|---|
| LakeFS data plane | Existing `mlops/lakefs-proxy-admin` Secret, mounted only into GPU/push steps; direct in-cluster Service endpoint |
| MLflow experiment plane | `mlops/mlflow-automation` client secret; the Webank command must exchange it for an `aud=mlflow` bearer token |
| Operational telemetry | OTLP/HTTP to `alloy.observability.svc.cluster.local:4318` |
| GPU placement | `role=gpu` selector + `role=gpu:NoSchedule` toleration + exactly `nvidia.com/gpu: 1` |

No credential material is held in either Git repository. The LakeFS key is the
platform's single root credential and must not be duplicated; the MLflow client
secret is synchronised by ESO from
`ai/camer/digital/prod/env#mlflow_automation_client_secret`. The MLflow identity
`service-account-mlflow-automation` needs `EDIT` on the intended experiment.

## Submitting a candidate run

The chart deliberately creates no `Workflow`, `CronWorkflow`, `EventSource`, or
`Sensor`. A model owner submits a reviewed run against the template, supplying:

- one of the five model names;
- a pinned 64-character lowercase-hex LakeFS commit;
- a governed readiness manifest and attestation;
- the model-specific `cargo xtask ...` training command; and
- a candidate output path in the training-data plane.

The DAG is fixed: pinned-ref validation → readiness gate → GPU training →
candidate push. A failed validation or readiness gate cannot claim a GPU. The
template defaults to the published immutable training image
`webank-train-gpu@sha256:c177…`, has a six-hour active deadline, and retains
completed workflow records for three days.

The template supplies `MLFLOW_TOKEN_URL`, `MLFLOW_AUTOMATION_CLIENT_ID`, and
`MLFLOW_AUTOMATION_CLIENT_SECRET` to the GPU command but does not put a bearer
token into a Workflow parameter or status field. The current training image
does not mint that token itself yet, so this makes the credential boundary
available without claiming an end-to-end MLflow write. The Webank command must
exchange the secret at runtime, keep the token in process memory, and never log
it or write it as an Argo output/artifact.

The source-of-truth request is
[webank-models#48](https://github.com/ADORSYS-GIS/webank-models/issues/48).
