# Webank governed dataset and training deployment

The `webank-training` chart installs a deliberately small, public Argo
WorkflowTemplate catalogue in `mlops`. Each governed model has two separate
templates in the dashboard: one for restricted dataset materialization and one
for GPU candidate training. This is the deployment boundary for
[Webank ADR-0034](https://github.com/ADORSYS-GIS/webank-models/blob/main/docs/adr/0034-training-job-orchestration-argo-workflows.md);
it is neither a scheduler nor a model-serving deployment.

| Model | Dataset template → LakeFS destination | Training template → LakeFS destination |
| --- | --- | --- |
| Document detector | `webank-document-detector-dataset-build` → `ds-document-detector/main` | `webank-document-detector-train` → `model-document-detector/main` |
| Document recognizer | `webank-document-recognizer-dataset-build` → `ds-document-recognizer/main` | `webank-document-recognizer-train` → `model-document-recognizer/main` |
| Face detector | `webank-face-detector-dataset-build` → `ds-face-detector/main` | `webank-face-detector-train` → `model-face-detector/main` |
| SFace | `webank-sface-dataset-build` → `ds-sface/main` | `webank-sface-train` → `model-sface/main` |
| PAD liveness | `webank-pad-liveness-dataset-build` → `ds-pad-liveness/main` | `webank-pad-liveness-train` → `model-pad-liveness/main` |

Each object has exactly one named template and fixes its own `entrypoint`
(`build` or `train`). The Argo UI therefore cannot turn an implementation
stage into an alternative public operation.

## Dataset-build templates

`*-dataset-build` templates are restricted-plane operations placed on
`nvidia.com/gpu.present=true` nodes (the live GPU node label, matching
`charts/inference`), tolerating `nvidia.com/gpu:NoSchedule` (Exists), and
using `runtimeClassName: nvidia` so the host CUDA driver libraries are mounted.
They request the same reviewed CPU, memory, and one-GPU resource profile as
candidate training (ADR-0114).
Document detector is the one special case: its form has **no inputs**. It
creates the fixed `ds-document-detector/main` repository if necessary, obtains
LakeFS's initial immutable commit, then runs the in-image Python builder to
create the reviewed hermetic synthetic starter set. It fetches no source
dataset from the network and passes the resulting manifest/readiness pair
through the normal Rust gate and LakeFS write boundary.

The other dataset-build forms require three governed artifacts:

- `source` — the model-specific source metadata;
- `manifest` — the RFC-0006 source manifest; and
- `readiness` — the matching attestation.

It also requires `lakefs_ref`, the immutable commit declared by those two
governance documents. The container materializes the model-specific descriptor
and calls the narrow `training-data push` LakeFS boundary. It never accepts a
dataset path, LakeFS destination, or arbitrary shell command from the
dashboard. The destination repository and `main` branch come only from the
model's reviewed `ai-helm-values` entry. Document detector's reviewed storage
namespace is used only if that fixed repository must be created; an existing
repository is never reset or reconfigured.

The current materializers deliberately produce metadata descriptors. They do
not invent biometric, identity, or PAD bytes. The document-detector bootstrap
creates only generic synthetic scenes and exact programmatic labels; it is
training input, never real-world evaluation or promotion evidence. Every other
model still needs an approved model-specific source and governed artifact
contract before an operator starts its template.

## Training templates

All `*-train` templates select `nvidia.com/gpu.present=true`, tolerate
`nvidia.com/gpu:NoSchedule` (Exists), use `runtimeClassName: nvidia`, and request
one `nvidia.com/gpu`. A submitted training workflow therefore cannot land on a
CPU-only node or start without the NVIDIA runtime injecting `libcuda.so.1`.

The document detector accepts `dataset_ref` and `dataset_version`; its runtime
combines them with the fixed `ds-document-detector` repository to check out and
gate `lakefs://ds-document-detector/64-character-commit/dataset-version`.
The recognizer, face-detector, and SFace
templates take a governed `dataset`, `manifest`, and `readiness` artifact plus
the matching `lakefs_ref`; they run their closed, model-specific Rust trainer
only after the readiness gate passes. All successful trainers write candidates
back only through `training-data push` into the fixed per-model `model-*`
repository, never to the model registry.

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
