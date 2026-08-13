# Webank model workflows

Use this playbook when preparing a governed dataset or starting a candidate
training run from the Argo Workflows dashboard. Do not use it to upload source
records, bypass the readiness gate, or promote a candidate.

## Choose the right template

Start with the model-specific operation you actually need:

| Need | Template pattern | Compute |
| --- | --- | --- |
| Build and publish a fixed training dataset | `webank-<model>-dataset-build` | one GPU (placement only — ai-helm#948) |
| Train a governed candidate | `webank-<model>-train` | one GPU |

There is one template of each kind for document detector, document recognizer,
face detector, SFace, and PAD liveness. Do not choose a different entrypoint:
the displayed `build` or `train` entrypoint is fixed by the selected template.

> **All five `webank-<model>-dataset-build` templates are currently disabled**
> (`datasetBuild.enabled` unset/`false` in `ai-helm-values`) and will not
> appear in the Argo Workflows dashboard. None of their publish calls is
> preceded by a `readiness-gate` step — dataset-build produces none of the
> `/workspace/governance/*` evidence that gate needs — so, per webank-models
> [ADR-0046](https://github.com/ADORSYS-GIS/webank-models/blob/main/docs/adr/0046-fixed-dataset-publish-governance-gate.md)
> and issue [#482](https://github.com/ADORSYS-GIS/webank-models/issues/482),
> they must not be able to publish ungoverned data. `*-train` is unaffected
> and already enforces the gate. Re-enabling a given model's dataset-build
> template is gated on that model having a source manifest and a readiness
> attestation.

Each template's LakeFS routes are fixed in reviewed `ai-helm-values`, not in
the Argo form. Dataset builds use `ds-<model>/main`; training candidates use
`model-<model>/main`. Every Dataset Build target may be created from its
reviewed storage namespace. SFace and PAD additionally resolve distinct fixed
governed-source repositories; those sources must already exist and be approved.

## Build a dataset

Open the model's `webank-<model>-dataset-build` template and select **Submit**
with no fields. No Dataset Build accepts a LakeFS ref, source artifact,
repository, branch, URL, prompt, or transform from the dashboard.

- Document detector, document recognizer, and face detector build their
  reviewed hermetic synthetic starter data from image-bundled policies. They
  fetch no source dataset at runtime and must not be used as real-world
  evaluation data.
- SFace and PAD resolve the configured governed-source `main` branch to an
  immutable commit internally. They fail closed if the sealed source bundle,
  manifest, or approval is absent or inconsistent; fix that governed source
  rather than supplying an alternate input.

A successful run writes one validated training bundle through the fixed
LakeFS boundary into that model's `ds-<model>/main` repository and reports the
server-issued immutable commit.

Dataset-build pods select `nvidia.com/gpu.present=true`, tolerate
`nvidia.com/gpu:NoSchedule` (Exists), and use `runtimeClassName: nvidia`, the
same GPU node placement as candidate training. The work itself — generation,
image decode/resize, tensor packing, and a LakeFS upload — performs no forward
pass and needs no GPU compute (webank-models#415), but the pinned
`webank-train-gpu` image links `libcuda.so.1` as a hard dependency, so every
subcommand fails to start without the driver library the GPU claim injects
(ai-helm#948); dataset-build therefore competes with candidate training for
one of the fleet's two GPU cards even though it runs no kernel. Its CPU and
memory come from the reviewed `training.datasetBuild.resources` profile, not
`training.gpu.resources` — the two footprints are measured separately.

If an SFace or PAD governed-source repository is empty, the operation fails
before materialization. Do not use fixtures or placeholder evidence as a
substitute.

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
5. Submit. The pod must show `runtimeClassName: nvidia`,
   `nvidia.com/gpu.present=true`, the `nvidia.com/gpu:NoSchedule` (Exists)
   toleration, and a one-GPU request before it begins candidate training.

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
| `*-train` or `*-dataset-build` pod remains Pending | GPU placement requirements cannot currently be met, or MLOps is preempted by serving (ADR-0114). Both template kinds request GPU node placement. | Check an `nvidia.com/gpu.present=true` node and its allocatable GPU; do not remove placement constraints. |
| `libcuda.so.1` cannot be opened | The pod did not use the NVIDIA runtime handler, so host driver libraries were not injected. Every subcommand in the pinned image needs this, including `*-dataset-build`'s (ai-helm#948) — it is not `*-train`-only. | Confirm the rendered template and pod both have `runtimeClassName: nvidia`; do not copy CUDA driver files into the image. |
| PAD train exits immediately | There is no PAD trainer. | Keep it blocked until a model-specific trainer lands. |
