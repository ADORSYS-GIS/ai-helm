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
Every Dataset Build form has **no inputs**. Its target repository, `main`
branch, reviewed storage namespace, and closed source strategy come only from
`ai-helm-values`; the dashboard cannot choose a LakeFS reference, source
archive, URL, or destination.

Document detector, document recognizer, and face detector run their bundled
offline Python builders. Recognizer and face-detector output then passes
through the typed `materialize-synthetic-source` adapter before the complete
training directory is packed. Document detector's builder already emits the
fixed bundle contract. All three publish only through `fixed-dataset publish`
to their configured `ds-<model>/main` target.

SFace and PAD use a distinct, fixed governed LakeFS source repository. The
workflow resolves its configured `main` branch to an immutable commit, checks
out only the sealed source bundle, proves the embedded source commit matches,
materializes the model-specific trainer contract, then packs and publishes the
derived bundle. A missing or unapproved source fails closed. No workflow
invents identity labels, consent, or physical-attack labels.

Every target repository may be created only with its reviewed storage
namespace. An existing repository is never reset or reconfigured. The
synthetic builders create starter training data, never real-world evaluation
or promotion evidence.

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
