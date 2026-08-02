# Webank model workflows

Use this playbook when preparing a governed dataset or starting a candidate
training run from the Argo Workflows dashboard. Do not use it to upload source
records, bypass the readiness gate, or promote a candidate.

## Choose the right template

Start with the model-specific operation you actually need:

| Need | Template pattern | Compute |
| --- | --- | --- |
| Materialize and publish a governed descriptor | `webank-<model>-dataset-build` | CPU |
| Train a governed candidate | `webank-<model>-train` | one GPU |

There is one template of each kind for document detector, document recognizer,
face detector, SFace, and PAD liveness. Do not choose a different entrypoint:
the displayed `build` or `train` entrypoint is fixed by the selected template.

Each template's LakeFS destinations are fixed in reviewed `ai-helm-values`, not
in the Argo form. Dataset builds use `ds-<model>/main`; training candidates use
`model-<model>/main`. The document-detector Dataset Build template is allowed
to create its own fixed empty repository from its reviewed storage namespace;
every other repository and `main` branch must exist before its first run.

## Build a dataset descriptor

For **document detector**, open
`webank-document-detector-dataset-build` and select **Submit** with no fields.
Its fixed entrypoint builds the reviewed hermetic synthetic starter set from
the image-bundled policy, reports the LakeFS commit in its logs, and accepts no
source artifact, repository, branch, prompt, or transform. It must not be used
as real-world evaluation data.

For every other model:

1. In Argo, open the model's `*-dataset-build` template and select **Submit**.
2. Set `lakefs_ref` to the 64-character immutable commit recorded by the
   approved source manifest. A branch name is rejected.
3. Provide the three restricted artifacts: `source`, `manifest`, and
   `readiness`. They must be the model-specific source metadata, RFC-0006
   manifest, and matching readiness attestation from the data repository.
4. Submit and inspect the `build` pod. A successful run writes only the
   generated descriptor through the LakeFS training-data boundary into that
   model's fixed `ds-<model>/main` repository.

If a non-document-detector LakeFS repository is empty, this operation still
cannot begin without an approved source artifact and its manifest/attestation.
Do not use fixtures or a blank reference as a substitute.

## Start candidate training

1. Confirm the dataset and its governance evidence are already approved.
2. Select the model's `*-train` template.
3. For document detector, enter `dataset_ref` (the 64-character commit) and
   `dataset_version`. The template composes the URI against its fixed
   `ds-document-detector` repository; the form never accepts a repository or
   branch. For document recognizer, face detector, and SFace, provide the
   governed `dataset`, `manifest`, and `readiness` artifacts and the matching
   `lakefs_ref`.
4. Leave `run_name` empty unless a named experiment is needed. Its default is
   `<model>-<Argo workflow name>` and is the preferred unique correlation key.
5. Submit. The pod must show `role=gpu`, the `role=gpu:NoSchedule` toleration,
   and a one-GPU request before it begins candidate training.

The run can only publish a candidate. Evaluation and governed promotion remain
separate procedures.

## Known blocked path

`webank-pad-liveness-train` is intentionally fail-closed. The PAD data
descriptor exists but the Rust PAD optimizer/trainer does not. Record the
missing trainer as implementation work; do not treat a parity or smoke command
as PAD training and do not create a candidate manually.

## Troubleshooting

| Symptom | Meaning | Action |
| --- | --- | --- |
| Argo rejects a missing dataset field | The data contract is intentionally required. | Supply the approved ref/version or artifacts; never fake a value. |
| `readiness-gate` fails | Source manifest, readiness attestation, and pinned commit disagree or are not eligible. | Repair/reapprove data in its source repository. |
| Pod remains Pending | GPU placement requirements cannot currently be met. | Check a `role=gpu` node and its allocatable GPU; do not remove placement constraints. |
| PAD train exits immediately | There is no PAD trainer. | Keep it blocked until a model-specific trainer lands. |
