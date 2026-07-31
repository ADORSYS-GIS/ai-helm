# Document-detector governed training deployment

The `webank-training` chart installs the namespaced Argo
`WorkflowTemplate` `webank-document-detector-train` in `mlops`. It is a
manual candidate-training route for the document detector, not a scheduler,
dataset builder, or model-serving deployment.

It implements Webank
[ADR-0034](https://github.com/ADORSYS-GIS/webank-models/blob/main/docs/adr/0034-training-job-orchestration-argo-workflows.md).
The deployment values, including the immutable GPU-training image digest, live
in the private `ai-helm-values` repository.

## Dashboard submission

In the Argo UI, select the `webank-document-detector-train` WorkflowTemplate
and leave **Entrypoint** set to `train`.

The UI also lists `readiness-gate` and `gpu-train-and-publish-candidate` because
they are Argo implementation templates. They are not alternate public
workflows. `train` is the only supported entrypoint and fixes the ordering:

```text
train
  -> readiness-gate (CPU only)
  -> gpu-train-and-publish-candidate (one GPU)
```

The submission fields are:

| Field | Value |
| --- | --- |
| `dataset_uri` | Required immutable URI: `lakefs://repository/64-character-commit/dataset-version`. It must name an approved, published document-detector training archive. Branches, local paths, raw source data, and moving refs are rejected. |
| `run_name` | Optional correlation name. It defaults to `document-detector-<Argo workflow name>` so every submission has a unique identity. Override it only for a deliberately named experiment; never include personal or source-record data. |

Do not submit this template while LakeFS has no approved document-detector
dataset. A missing `dataset_uri` is intentionally rejected by Argo before a
Workflow is created; it must not be replaced with a fake or blank default.

## Producing the required dataset URI

Dataset publication is a distinct, restricted-plane operation. The Python
builder in
[webank-models](https://github.com/ADORSYS-GIS/webank-models/tree/main/tools/document-detector-dataset)
creates the typed archive from approved source records. A governed LakeFS push
then returns the immutable commit used in `dataset_uri`.

1. Build and review the archive, source manifest, and readiness attestation in
   the restricted plane.
2. Push the reviewed archive through `cargo xtask training-data push` to the
   repository named by the governed manifest.
3. Record the returned LakeFS commit and the manifest `dataset_version`.
4. Submit `train` with
   `lakefs://<repository>/<returned-commit>/<dataset-version>`.

The workflow downloads that exact archive, verifies its embedded governance
files on CPU, and only then requests the GPU. A successful run publishes a
candidate; it is not production promotion evidence.

## Model-specific workflow surface

Each model gets its own public WorkflowTemplate when its dataset contract and
trainer exist. The document detector is the first deployed template. Do not add
new model behaviour as an extra entrypoint or optional parameter to this
template: that obscures the governed data contract and makes the dashboard form
unsafe.

## Placement and credentials

The GPU task is constrained to `role=gpu`, tolerates the matching
`role=gpu:NoSchedule` taint, and requests exactly `nvidia.com/gpu: 1`. The
readiness gate is CPU-only. LakeFS credentials are mounted from the
platform-managed `mlops` Secret only inside workflow pods and are never passed
through dashboard parameters or committed to Git.
