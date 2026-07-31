# Webank governed dataset and training deployment

The `webank-training` chart installs a deliberately small, public Argo
WorkflowTemplate catalogue in `mlops`. Each governed model has two separate
templates in the dashboard: one for restricted dataset materialization and one
for GPU candidate training. This is the deployment boundary for
[Webank ADR-0034](https://github.com/ADORSYS-GIS/webank-models/blob/main/docs/adr/0034-training-job-orchestration-argo-workflows.md);
it is neither a scheduler nor a model-serving deployment.

| Model | Dataset template | Training template |
| --- | --- | --- |
| Document detector | `webank-document-detector-dataset-build` | `webank-document-detector-train` |
| Document recognizer | `webank-document-recognizer-dataset-build` | `webank-document-recognizer-train` |
| Face detector | `webank-face-detector-dataset-build` | `webank-face-detector-train` |
| SFace | `webank-sface-dataset-build` | `webank-sface-train` |
| PAD liveness | `webank-pad-liveness-dataset-build` | `webank-pad-liveness-train` |

Each object has exactly one named template and fixes its own `entrypoint`
(`build` or `train`). The Argo UI therefore cannot turn an implementation
stage into an alternative public operation.

## Dataset-build templates

`*-dataset-build` templates are CPU-only restricted-plane operations. The
Argo submission form requires three governed artifacts:

- `source` — the model-specific source metadata;
- `manifest` — the RFC-0006 source manifest; and
- `readiness` — the matching attestation.

It also requires `lakefs_ref`, the immutable commit declared by those two
governance documents. The container materializes the model-specific descriptor
and calls the narrow `training-data push` LakeFS boundary. It never accepts a
dataset path or arbitrary shell command from the dashboard.

The current materializers deliberately produce metadata descriptors. They do
not invent document, biometric, identity, or PAD bytes. A data repository must
provide an approved model-specific source and its governed artifact contract
before an operator starts one of these templates.

## Training templates

All `*-train` templates select `role=gpu`, tolerate
`role=gpu:NoSchedule`, and request one `nvidia.com/gpu`. A submitted training
workflow therefore cannot land on a CPU-only node.

The document detector accepts one `dataset_uri` in the immutable form
`lakefs://repository/64-character-commit/dataset-version`; its runtime checks
out and gates the archive itself. The recognizer, face-detector, and SFace
templates take a governed `dataset`, `manifest`, and `readiness` artifact plus
the matching `lakefs_ref`; they run their closed, model-specific Rust trainer
only after the readiness gate passes. All successful trainers write candidates
back only through `training-data push`, never to the model registry.

`run_name` is optional on every training template. Its default includes the
generated Argo workflow name, so it is unique even when the operator leaves
the form untouched. Use an override only for an intentional experiment and
never include source-record or personal data.

The PAD liveness template is visible intentionally but **fails closed**: PAD
has a governed descriptor materializer, while a PAD optimizer/trainer has not
landed. It emits no checkpoint and cannot fabricate a candidate. That gap must
be closed in `webank-models` before a real PAD training submission is possible.

Use the [model workflow playbook](../playbooks/webank-model-workflows.md) for
the dashboard submission sequence and failure handling.

## Credentials and delivery

LakeFS credentials are mounted only into the restricted workflow pods from the
platform-managed `mlops` Secret. They are never dashboard parameters or Git
values. The immutable GPU training image and all endpoint/placement literals
live in the private `ai-helm-values` repository. Argo CD renders the public
catalogue from the OCI chart plus those values.
