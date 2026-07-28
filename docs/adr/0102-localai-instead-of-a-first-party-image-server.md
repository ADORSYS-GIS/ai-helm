# ADR-0102: Serve image generation with LocalAI — we should not have been maintaining an inference server

**Status:** Accepted
**Date:** 2026-07-28
**Deciders:** @stephane-segning

## Context

[ADR-0100](0100-image-generation-on-the-gpu-fleet.md) adopted a **first-party
Rust + Candle server** as the `zimage` engine profile, on the strength of an
alternatives analysis that concluded no off-the-shelf option existed:

> **ComfyUI / SwarmUI / a general diffusion UI.** Rejected: none speaks the
> OpenAI `/v1/images/generations` shape, so each would need a translation layer…

That analysis was incomplete, and the gap was not subtle. It weighed
`diffusers`-as-a-library, ComfyUI and SwarmUI, and **never considered the
category of software that exists specifically to solve this problem**:
OpenAI-compatible multi-backend inference servers.

Checked against primary sources, not summaries:

| | Evidence |
|---|---|
| **LocalAI** ships `/v1/images/generations` | `router.GET("/metrics", …)` and the OpenAI image route in `core/http`; 47.9k stars, pushed daily |
| **LocalAI serves this exact model** | **Four** gallery entries: `z-image-turbo-diffusers` (diffusers backend), `Z-Image-Turbo` (ggml/GGUF), `z-image-diffusers`, `vllm-omni-z-image-turbo` |
| **Xinference serves it natively** | `Z-Image`, `Z-Image-Turbo`, `Z-Image-Turbo-GGUF` in its builtin `model_spec.json` |
| A pinnable CUDA-12 image exists | `quay.io/go-skynet/local-ai:v4.7.1-gpu-nvidia-cuda-12` |

⚠️ A note on how this was checked, because it matters: a search summary asserted
LocalAI had "fully integrated" the model and cited issue
[#7399](https://github.com/mudler/LocalAI/issues/7399) — which is **closed as
`not_planned`**. The summary's conclusion was right and its evidence was wrong;
the gallery entries arrived by a different route. Both halves had to be checked
separately.

There was also a signal in our own working notes on day one. `Comfy-Org/z_image_turbo`
has **5.28M downloads against the base repo's 1.15M**, and ships pre-packaged
single-file weights at 12.31 GB (bf16), 6.20 GB (int8) and 4.51 GB (nvfp4). The
ecosystem was plainly not reconstructing a 33 GB FP32 diffusers repo to run this
model. That was visible and unweighted.

**What the wrong call cost, in one working day:**

| | |
|---|---|
| A server to maintain | ~1000 lines of Rust, and the review burden of needing someone who reads Rust *and* diffusion |
| A hand-built image | No CI builds it, so a "build-first" ordering rule became a permanent tax (ADR-0100) |
| A lost observability surface | No `/metrics`, forcing a compensating kube-state-metrics alert |
| An unenforceable policy | ADR-0097's CORS pin, declared `corsConfigurable: false` |
| Three follow-up PRs | Seed OOM (#792), staging disk (#793), un-federation (#794) — all downstream of hand-rolling weight management |
| A user-facing outage | The model was federated the whole time and could never have answered ([ADR-0101](0101-load-gate-before-federation-no-exceptions.md)) |

None of that was caused by the engine being *hard*. It was caused by choosing to
own one without checking whether we had to.

## Decision

**Replace the `zimage` engine profile with `localai`, and delete the first-party
server.**

- `defaults.engines.localai` pins `quay.io/go-skynet/local-ai:v4.7.1-gpu-nvidia-cuda-12`.
  ⚠️ The `master`/`latest` tags are built against **CUDA 13**; these nodes run
  driver 550 / CUDA 12.4 — the same trap CLAUDE.md records for llama.cpp's
  `server-cuda13` and vLLM's `-cu129`. The CUDA-12 tag is pinned, not floated.
- `images/z-image-turbo-server/` is **deleted**. It was moved out of a legacy
  chart yesterday specifically so it would not be lost; today there is nothing to
  preserve. Its history remains in git.
- The catalog entry becomes a **gallery name** (`serving.galleryModel`) instead of
  an HF repo, a revision, a file selector and a size budget.

Two structural additions the engine-profile contract needed, both expressed as
profile data rather than engine-name branches:

| Profile key | Why |
|---|---|
| `seedJob: false` | LocalAI downloads its own model **and its inference backend** (`AUTOLOAD_BACKEND_GALLERIES` defaults true). There is no seed Job, no HF token, and no pinned revision. |
| `writableModelStore: true` | …and therefore the weights volume must be writable, and must persist `backends/` as well as `models/`, or every restart re-downloads both. |

`metrics` returns to `true`: LocalAI serves `/metrics` unless
`DISABLE_METRICS_ENDPOINT` is set. The route sits behind its admin middleware, so
the scrape presents the API key — which `charts/model-server`'s ServiceMonitor
already does whenever `apiKey.enabled`, exactly as for llama-server.

## Consequences

**Positive**

- We stop maintaining an inference server. Upstream fixes arrive as a tag bump.
- The build-first rule, the hand-built image and the `cargo-auditable` gap all
  disappear with it.
- **Engine metrics come back**, so `up{namespace="inference"}` covers the whole
  fleet again and the image tier gets a real dashboard surface.
- ADR-0097's CORS policy stops having an engine-shaped hole.
- The catalog entry shrinks to a gallery name, and the weight-management traps we
  spent a day on (seed memory, staging disk, FP32-vs-marketing sizing) become
  someone else's problem — one whose users number in the tens of thousands.
- Three quantization variants become reachable by changing one string
  (`Z-Image-Turbo` ggml at 4.5–6.2 GB versus ~33 GB of FP32).

**Negative**

- **We lose the pinned-SHA guarantee.** A seed Job fetched an exact commit, so the
  bytes measured were the bytes served. A gallery reference does not pin that
  way — the gallery entry can move under us. This is a real regression in
  reproducibility and it is the main thing given up. Mitigation is the pinned
  *image* tag plus the load gate; if it bites, the fallback is a LocalAI model
  config file we own, mounted into `MODELS_PATH`.
- **A bigger, less familiar dependency.** LocalAI is a multi-backend platform, not
  a single-purpose server; more surface, more configuration, more that can change
  between releases.
- **Runtime downloads at start-up.** First boot fetches a backend *and* weights,
  so it is slow and needs egress — fine in `inference` (no deny-egress baseline),
  but it means a cold pod is not a fast pod.
- ⚠️ **The Deployment name changes for this engine.** With no seed Job there is a
  single controller, and bjw-template then names it `<model>` rather than
  `<model>-main`. Nothing functional depends on it (the Service and
  CiliumNetworkPolicy select on the `ai-helm…/model` label), but every runbook
  command written as `deploy/<model>-main` — which ADR-0098 standardised — misses
  for image models. Documented in the pattern doc and the runbooks.

**Neutral / follow-ups**

- The exact accepted form of a gallery reference in `MODELS` cannot be settled by
  rendering; it is the first thing the load gate confirms. So is the diffusers
  backend running on driver 550.
- Xinference remains a credible alternative if LocalAI disappoints; it has native
  builtin support and was the other serious candidate.
- `vllm-omni` now does diffusion, which makes ADR-0002's "the text engines have no
  diffusion code path" true-when-written and no longer true. Worth revisiting if
  the fleet ever wants one engine for both.

## Alternatives considered

- **Keep the Rust server.** Rejected. It works and it type-checks, and that is not
  the question — the question is whether serving a commodity capability justifies
  owning a server, and the answer is no.
- **Xinference instead of LocalAI.** Genuinely close: native builtin support for
  Z-Image and Z-Image-Turbo. Chose LocalAI on packaging fit — a single container
  with a pinnable CUDA-12 tag, matching one-model-per-pod, versus a
  supervisor/worker platform designed to manage many models itself. Revisit if
  LocalAI's gallery indirection proves fragile.
- **ComfyUI plus a shim.** The most-used path in the wider ecosystem, and rejected
  for the reason ADR-0100 gave and got right: no OpenAI endpoint, a browser UI to
  hide, and a workflow graph as the unit of configuration.
- **Drop image generation.** Still available, and cheaper than any of the above.
  It is a product call, not an engineering one.

## Related

- Supersedes the engine choice in [ADR-0100](0100-image-generation-on-the-gpu-fleet.md);
  everything else there (moving off the home GPU, retiring OpenMythos, the
  engine-profile contract) stands
- Builds on [ADR-0101](0101-load-gate-before-federation-no-exceptions.md) — the
  model is still unfederated, which is what made this switch safe to make
- [ADR-0097](0097-engine-agnostic-serving-hardening.md) — CORS is enforceable again
- `inference-ops` `docs/adr/0004-*` supersedes its ADR-0003 with the inference-side
  reasoning
- Charts: `charts/model-serving/{values.yaml,templates/_helpers.tpl}`,
  `charts/model-server/{templates/_validate.tpl,ci/localai-values.yaml}`
