# ADR-0106: Restore the LocalAI image tier, and delete the chart that displaced it

**Status:** Accepted
**Date:** 2026-07-29
**Deciders:** @stephane-segning

## Context

On 2026-07-28, [PR #790](https://github.com/ADORSYS-GIS/ai-helm/pull/790) merged
`704-ticket-deployment-of-z-image-turbo` — a branch cut before
[ADR-0100](0100-image-generation-on-the-gpu-fleet.md) and never rebased. It
merged cleanly and, in doing so, **silently reverted the entire image-generation
workstream**: ADR-0100 through [ADR-0105](0105-pin-and-verify-the-localai-backend.md),
and the catalog entry they produced.

What went back in its place was the thing those ADRs had removed: a first-party
Rust/Candle server deployed by `charts/model-serving-zimage-turbo`, referencing
`ghcr.io/adorsys-gis/z-image-turbo-server:v0.1.0`. **That image does not exist.**
[ADR-0102](0102-localai-instead-of-a-first-party-image-server.md) deleted its
source the day after the server shipped, and nothing ever built or published it.
The pod sat in `ImagePullBackOff` (`failed to authorize: … 403 Forbidden`, and no
`imagePullSecret` anywhere in the namespace) from merge until it was disabled.

The regression was not diagnosed as one. It was met with three downstream fixes,
each correct in isolation and each treating a symptom of the revert:

| PR | Fixed | Actually a symptom of |
|---|---|---|
| [#799](https://github.com/ADORSYS-GIS/ai-helm/pull/799) | GPU tolerations on the legacy chart | a chart that should not have been redeployed |
| [#802](https://github.com/ADORSYS-GIS/ai-helm/pull/802) | seed Job disk exhaustion / OOM | hand-rolled weight management LocalAI does not need |
| [#804](https://github.com/ADORSYS-GIS/ai-helm/pull/804) | disabled the app — the image does not exist | the revert itself |
| [#814](https://github.com/ADORSYS-GIS/ai-helm/pull/814) | removed a federated model whose backend host was dead | the revert restoring a pre-fleet backend |

[Issue #803](https://github.com/ADORSYS-GIS/ai-helm/issues/803) named it correctly
and offered two paths: **(a)** finish the first-party server properly — build it,
publish it, prove the VRAM fit — or **(b)** restore the LocalAI deployment that
had already been built, tuned, measured and served.

Two facts decide it. First, the LocalAI path was **already done and measured on
this hardware**: 32.4 s median per 1024×1024 (34.30 / 32.18 / 32.38) at 7985 MiB
of 20475, verified by generating an image and looking at it. Second, ADR-0102
established that we should not be maintaining an inference server for this at
all, and nothing since has changed that — path (a) would re-acquire ~1000 lines of
Rust, a hand-built image with no CI, and the four defects ADR-0100 catalogued.

Path (a) is not merely more work. It is the work ADR-0102 already decided against,
on evidence that still holds.

## Decision

**Take path (b): restore the LocalAI image tier, and delete the legacy chart
outright rather than leaving it disabled.**

Concretely:

- `charts/inference/values.yaml` regains the `z-image-turbo` catalog entry —
  `engine: localai`, our own `modelConfig` under our own filename, the pinned
  `cuda12-stablediffusion-ggml` backend, `step: 8`, and no
  `offload_params_to_cpu`. This is the *tuned* configuration, the one the numbers
  above belong to, not the gallery defaults that preceded it.
- `charts/ai-models/values.yaml` regains the `z-image-turbo-local` model and
  backend, pointing at the **cluster-local** Service
  (`z-image-turbo.inference.svc.cluster.local:8080`). This is what #814 asked for
  in as many words: re-add an entry once a working server lands, rather than
  re-enabling the one that pointed at the dead `*--poc.ssegning.com` edge.
- `charts/model-serving-zimage-turbo/` is **deleted**, along with its
  `charts/apps` Application, its release-please component and its `.trivyignore.yaml`
  path. Issue #803 asked for deletion rather than disablement, and the reason is
  the one this ADR exists to record: **a disabled chart is a resurrection
  surface.** It was disabled once already (ADR-0100) and a stale branch turned it
  back on. It is also no longer even a rollback surface — you cannot roll back to
  an image that does not exist.

Two deliberate deviations from the pre-regression state:

| | Before | Now | Why |
|---|---|---|---|
| Weights PVC | `sizeGi: 100` | `sizeGi: 40` | The 100Gi was never a size decision — it was forced by an existing claim, because `spec.resources.requests.storage` may not be below `status.capacity` and Longhorn never shrinks. That claim is **gone**, verified live (`kubectl -n inference get pvc` lists only `qwen3-vl-4b-thinking-weights`), so this provisions fresh and is sized honestly: ~6.7 GB of weights plus a backend, with headroom. |
| Legacy chart | disabled | deleted | See above. |

The fleet's two cards now hold `qwen3-vl-4b-thinking` (vision-language) and
`z-image-turbo` (image generation). Both text tiers stay disabled.

## Consequences

**Positive**

- Image generation works again, on a configuration already measured on this
  hardware, at 2.9× the latency of the untuned one it briefly shipped as.
- We are back to not maintaining an inference server, which is ADR-0102's whole
  point.
- The revert cannot recur through this route: the chart is gone, so a future
  stale branch has nothing to re-enable.
- One less published chart, one less release-please component, one less
  Trivy-ignore path.

**Negative**

- **The first boot after this merges is a fresh-volume install, and two things
  ADR-0105 flagged as untested are now on the critical path.** The old volume was
  pruned with the app, so LocalAI must actually fetch the `download_files`
  weights and actually cosign-verify the backend. ADR-0105 recorded both as
  unexercised because the volume was already populated when it landed. If the
  identity regex is wrong, this is where it fails.
- The measurement being relied on predates the prune. It is the same config on
  the same hardware, but it is not a fresh measurement, which is why the
  acceptance criterion below is a re-confirmation and not a formality.
- Deleting the chart forecloses path (a) as a quick revert. Reviving the
  first-party server now means git history plus a build pipeline — which is the
  correct price, but it is a price.

**Neutral / follow-ups**

- **Re-confirm one 1024×1024 generation after the first sync**, and record peak
  VRAM — the ADR-0101 gate, applied to the fresh-volume path.
- Flip `requireBackendIntegrity` once that install confirms the cosign policy
  matches (carried over from ADR-0105; the fresh volume is the opportunity it
  was waiting for).
- The 3.45× duty-cycle uplift in the $0.0100/image price remains inherited from
  the old A2000 and unmeasured on this fleet (ADR-0104). Unchanged here.
- Deleting the remaining seven legacy `model-serving-*` charts is still a
  decommissioning exercise on the other cluster, tracked separately.

**Process**

The mechanism deserves stating, because nothing in CI caught it: **a long-lived
branch that merges cleanly can still revert everything merged after it was cut.**
Every gate passed — the charts rendered, lint was green, ArgoCD went healthy —
because reverting good config is not a syntax error. What would have caught it is
rebasing before merge, or reading the diff against `main` rather than the branch's
own history. The 29 commits it undid were all visible in that diff.

## Alternatives considered

- **Path (a): finish the first-party Rust/Candle server.** Rejected. It requires
  a CI build pipeline that has never existed, an image built for `sm_89`, a fix
  for the lazy-load deadlock, and a demonstration that FP32 weights fit a 20 GiB
  card — all to re-arrive at a capability that already works. ADR-0102 rejected
  owning this server on evidence that has not changed.
- **Restore LocalAI but leave the legacy chart disabled.** Rejected: that is
  exactly the state that allowed this regression, and the chart is not a usable
  rollback target anyway.
- **Restore the entry verbatim, including `sizeGi: 100`.** Rejected: it would
  carry forward a comment that is now factually false ("the volume is already
  100Gi" — it is not) and over-provision a fresh claim by 2.5×.
- **Leave image generation off until a fresh benchmark exists.** Rejected as
  backwards: the gate exists to stop *unmeasured* models being federated, and
  this one is measured. The fresh-volume re-confirmation is the right weight of
  check, not a redeployment freeze.

## Related

- Restores [0102](0102-localai-instead-of-a-first-party-image-server.md),
  [0103](0103-own-the-localai-model-config.md) and
  [0105](0105-pin-and-verify-the-localai-backend.md), all reverted by PR #790
- Applies the gate in [0101](0101-load-gate-before-federation-no-exceptions.md)
- Retires the chart [0100](0100-image-generation-on-the-gpu-fleet.md) had disabled
- Pricing basis [0104](0104-gpu-cost-basis-correction.md); method [0028](0028-owned-hardware-model-pricing.md)
- Orchestrator [0094](0094-generic-model-serving-orchestrator.md); federation shape [0095](0095-cluster-local-model-federation.md)
- Issue [#803](https://github.com/ADORSYS-GIS/ai-helm/issues/803)
- Charts: `charts/inference/values.yaml`, `charts/ai-models/values.yaml`, `charts/apps/values.yaml`
