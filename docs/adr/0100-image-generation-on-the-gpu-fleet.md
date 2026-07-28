# ADR-0100: Image generation on the GPU fleet — a first-party engine profile, and OpenMythos retired to make room

**Status:** Accepted
**Date:** 2026-07-27
**Deciders:** @stephane-segning

## Context

Two things came together.

**1. The fleet had no image model, and the one we owned was stranded.**
[PR #704](https://github.com/ADORSYS-GIS/ai-helm/pull/704) deployed Tongyi-MAI
**Z-Image-Turbo** — a 6B-parameter distilled DiT answering the OpenAI
`POST /v1/images/generations` shape — as `charts/model-serving-zimage-turbo`, a
per-model chart on the **home** RTX A2000 (`admin@homeos`), reached over a public
`z-image-turbo--poc.ssegning.com` edge with a static Bearer. That was the only
shape available at the time.

It is not the shape available now. [ADR-0094](0094-generic-model-serving-orchestrator.md)
replaced the eight per-model charts with one orchestrator plus a generic leaf, and
[ADR-0095](0095-cluster-local-model-federation.md) put models on the same cluster
as the gateway, so a model reaches the gateway over a ClusterIP with no Ingress,
no certificate, no DNS and no shared secret to rotate. Z-Image-Turbo was the last
workload still on the old shape, and it was holding the entire legacy generation
alive: ADR-0094 kept those eight charts explicitly *because* `zimage-turbo` was
live on the other cluster.

**2. Both fleet cards were occupied, and one of them was the weaker use of a card.**
`openmythos-27b` (llama.cpp, quality tier) and `qwen3-8b-fast` (vLLM, speed tier)
each held one RTX 4000 SFF Ada. A third model queues `Pending` — that is ADR-0094
working as designed, and it means adding an image model is a *choice*, not an
addition. OpenMythos was measured at **15.05 tok/s** decode and priced at
`$2.55/$0.50/$17.00` per 1M by [ADR-0096](0096-gex44-fleet-cost-recovery-pricing.md)
— roughly an order of magnitude above the SaaS entries in the same catalog. It
worked, it was honest about its cost, and a SaaS model does the same job better
per euro. An image model does something no entry in the catalog does at all.

**What actually blocked the move was none of the above.** Reviewing the PR-#704
artifact against the fleet turned up four defects that meant the deployment could
not have been working as configured, on any cluster:

| Defect | Consequence |
|---|---|
| **Lazy model load behind a readiness-gated `/health`** — the engine loaded on the first `/v1/images/generations`, but `/health` answers 503 until it is loaded | Deadlock: not-Ready ⇒ no Service endpoint ⇒ no request ⇒ never loads ⇒ never Ready. The pod restarts forever with nothing in the log. |
| **A 20 GiB weights PVC** for a repo that is **~33 GB** on disk (the published weights are FP32, not the "FP8" the PR claimed: transformer 24.62 GB + text encoder 8.05 GB + VAE 0.17 GB) | The seed Job fills the volume and fails, hours in. |
| **A Dockerfile that cannot build** — a `cargo build` line with no `RUN`, a `COPY tests/ tests/` for a directory that does not exist (the tests are inline `#[cfg(test)]`), and `-fuse-ld=lld` without lld installed | Whatever `ghcr.io/adorsys-gis/z-image-turbo-server:v0.1.0` is, it was not built from the committed source. |
| **CUDA 12.8 base and kernels compiled for the build host's card** | The fleet runs driver 550 / **CUDA 12.4** on **sm_89** Ada cards. Candle bakes kernels for ONE compute capability at build time; an image built on the sm_86 A2000 fails at first inference — *after* the pod goes Ready — with "no kernel image is available for execution on the device". Exactly the trap CLAUDE.md already records for llama.cpp's `server-cuda13` and vLLM's `-cu129` tags. |

So the question was not "move the chart" but "is this server worth adopting as
fleet infrastructure, once fixed". The answer is yes: `candle-transformers` 0.11
ships a real `z_image` module (verified — every symbol the server imports exists),
the whole crate type-checks and its 15 unit tests pass, and the alternative
serving paths are all worse (below).

## Decision

**Add a third engine profile, `zimage`, to `charts/model-serving`, and serve
Z-Image-Turbo on the GPU fleet as an ordinary catalog entry. Retire
OpenMythos-27B to free the card.**

Concretely:

- **`defaults.engines.zimage`** in `charts/model-serving/values.yaml`, alongside
  `llamacpp` and `vllm`. Adding an engine remains "a profile plus a
  `ci/<engine>-values.yaml` fixture, and nothing else in the repo changes" —
  ADR-0094's contract holds for an engine that is neither a language model nor an
  upstream image.
- **The catalog entry is ~20 lines** (`z-image-turbo`), and takes image geometry
  and sampling parameters where a text model takes `contextSize` and `parallel`.
  There is no new chart. There is no `charts/model-serving-<model>`.
- **The image is ours** — `images/z-image-turbo-server/` (moved out of the legacy
  chart, where it would have been deleted along with it). Rust + Candle,
  `CUDA_COMPUTE_CAP=89`, CUDA 12.4, non-root with a read-only root filesystem.
- **The server pre-loads its weights at start-up**, on a plain OS thread, and
  exits non-zero if the load fails. This is what makes `/health` — 503
  `model_loading` → 200 — a signal a startup probe can gate on, and it is the fix
  for the deadlock above.
- **OpenMythos-27B is removed** from both catalogs. Its entry is retained,
  commented out, in `charts/model-serving/values.yaml`: the pinned SHA still
  resolves, so restoring it re-seeds byte-identical weights to the ones that were
  measured.
- **The legacy `model-serving-zimage-turbo` app is disabled.** With it, every
  chart of the legacy generation is now disabled.

Three engine-level facts are declared as *profile data* rather than handled with
`if engine == …` branches, because the alternative is a helper that grows a
branch per engine:

| Profile key | Why it exists |
|---|---|
| `apiKey.mode: file\|env` (+ `path` / `envName`) | llama.cpp reads the Bearer from a **file** (`--api-key-file`); vLLM and zimage read it from an **environment variable**, with different names. This replaced two hardcoded `eq $engine "vllm"` tests. |
| `metrics: false` | zimage exposes no Prometheus endpoint at all, so the orchestrator emits `serviceMonitor.enabled: false`. Scraping it anyway would poll a 404 every 30s forever and plant a permanently-down target in Mimir — worse than no target, because it teaches people to ignore a red panel. |
| `devShm: true` | vLLM's workers need more than the 64 MB default `/dev/shm`; nothing else does. |

## Consequences

**Positive**

- The fleet gains a capability it did not have — text-to-image — and the platform
  serves it through the same gateway, the same Keycloak JWT, the same
  per-account rate limits and the same cost accounting as every other model.
- Image generation stops depending on a second cluster, a public hostname, an
  ACME certificate and a static Bearer. It is now a ClusterIP behind a
  `CiliumNetworkPolicy`, like everything else on the fleet.
- The last reason to keep the eight legacy `charts/model-serving-*` charts is
  gone. Deleting them becomes a decommissioning task rather than a blocked one.
- The engine-profile contract survived contact with a genuinely different kind of
  engine: a diffusion model with no context window, no tokens, no metrics and a
  first-party image slotted in without touching the leaf chart, the
  ApplicationSet, or any other model.
- Four latent defects in the inherited artifact are fixed rather than inherited.

**Negative — and these are real**

- **Nothing in CI builds this image.** It is built and pushed by hand, exactly
  like `ghcr.io/adorsys-gis/lakefs-proxy`. That makes the deploy **build-first**:
  push `v0.2.0` *before* merging the catalog entry, or the pod sits in
  `ImagePullBackOff`. This is the same class of ordering rule as
  values-repo-first (ADR-0056) and out-of-band-secret-first, and it is a standing
  tax on every future change to this server. A build workflow is a follow-up.
- **We now own an inference server.** Upstream fixes to llama.cpp and vLLM arrive
  as a tag bump; fixes here arrive as our own Rust. The dependency that matters
  is `candle-transformers`' `z_image` module — if it stalls, so do we.
- **No engine metrics.** The vLLM and llama.cpp dashboards have no image-model
  equivalent, and `up{namespace="inference"}` is now structurally blind to half
  the fleet. Compensated by a new `ms-model-unavailable` alert reading
  `kube_deployment_status_replicas_available{namespace="inference"}` from
  kube-state-metrics — engine-independent, verified against live Mimir. GPU-level
  telemetry (DCGM) is unaffected, so the card is still observed; only the server
  is not.
- **The fleet CORS policy cannot be applied.** The server hardcodes
  `allow_any_origin()` with no flag to pin it, so `security.corsOrigins` — part
  of the [ADR-0097](0097-engine-agnostic-serving-hardening.md) policy — is
  silently unenforceable for this engine. Declared as `corsConfigurable: false`
  in the profile rather than quietly ignored. Contained by the NetworkPolicy
  (nothing browser-based can reach the pod) and by there being no cookie or
  credential an origin could protect. Fixable in our own source; not yet done.
- **The price is a placeholder.** `$0.005/image` is carried over from the home
  GPU and has no cost basis on rented hardware. ADR-0096 derives a fleet price
  from €/hour ÷ measured throughput, and nobody has measured images/hour here.
- **No load gate.** Every number in the catalog entry — VRAM, PVC size, memory
  limit — is derived from published file sizes and arithmetic, not observation.
  It is federated anyway, deliberately: users already had this model, so this is
  a *migration* and pulling it during the move would be a visible regression.
  That is a different situation from `qwen3-8b-fast`, which was served
  unfederated until it had been measured, and the difference is worth being
  explicit about rather than blurring.
- **The llama.cpp tier is dormant.** Its dashboard renders empty and
  `ms-llamacpp-queueing` sits at a flat zero until a GGUF model returns. Both
  self-heal; neither is deleted.
- **One text tier, not two.** Considered long-form analysis now routes to SaaS.
  ADR-0096's make-vs-buy signal said that was the better trade at 15 tok/s; this
  acts on it.

**Neutral / follow-ups**

- Two things cannot be proven by rendering and must be confirmed on the first
  live request: the **image tag exists and its kernels run on sm_89**, and the
  gateway backend's **`prefix: /v1`** reaches `/v1/images/generations` (the
  legacy backend used `/`, which would strip the version segment).
- The seed Job's fixed 6 GiB memory limit has not been exercised against a ~10 GB
  safetensors shard. If it OOMs, the limit becomes a per-model knob.
- A `--cors-origins` flag in our own server would close the ADR-0097 gap in one
  small change, on the next rebuild.

## Alternatives considered

- **Keep Z-Image-Turbo on the home GPU and change nothing.** Rejected. It keeps
  a public internet-facing model endpoint with a static Bearer, keeps eight dead
  charts alive, keeps an unfixed deadlock and an undersized PVC, and leaves a
  fleet card doing work SaaS does better. The stranded model was the problem.
- **Serve it with vLLM or llama.cpp.** Not possible — neither does diffusion.
  This is not a tuning question; there is no code path.
- **A Python/`diffusers` server.** The obvious default, and genuinely tempting:
  `diffusers` is the reference implementation (the repo is tagged
  `diffusers:ZImagePipeline`), so it would track upstream for free. Rejected for
  this deployment because it means a ~3 GB torch image against our ~150 MB one,
  a GIL around a single-GPU model, and a second dependency universe on the fleet
  — while the Rust server already existed, compiles, and passes its tests.
  ⚠️ This is the alternative to revisit if `candle-transformers` stalls; it is
  not a bad option, just a worse one *today*.
- **ComfyUI / SwarmUI / a general diffusion UI.** Rejected: none speaks the
  OpenAI `/v1/images/generations` shape, so each would need a translation layer
  and would bring a browser UI we would then have to hide — the exact
  unauthenticated surface ADR-0097 exists to remove.
- **A per-model chart, as PR #704 wrote it.** Rejected — that is precisely the
  shape ADR-0094 removed, and adopting it for the ninth model would re-open the
  "~300 values lines that differ in five fields" problem with an implicit
  "keep in sync" contract between the seed job and the server args.
- **Retire `qwen3-8b-fast` instead of OpenMythos.** Rejected: the speed tier is
  the one local text model that beats SaaS on a dimension we care about
  (latency, and no data leaving the cluster), at 45 tok/s and a defensible price.
  The 27B was the expensive one.
- **Buy a third card.** The honest option, and deferred rather than dismissed:
  it is a recurring €/month decision, and it should be made against measured
  demand for image generation, which this deployment is what produces.

## Related

- Builds on [ADR-0094](0094-generic-model-serving-orchestrator.md) (orchestrator +
  generic leaf; the engine-profile contract), [ADR-0095](0095-cluster-local-model-federation.md)
  (cluster-local, no public edge), [ADR-0097](0097-engine-agnostic-serving-hardening.md)
  (hardening policy — with the CORS exception recorded above),
  [ADR-0098](0098-deployment-recreate-instead-of-statefulset.md) (Deployment +
  `Recreate`), [ADR-0092](0092-longhorn-for-hetzner-gpu-nodes.md) (weights storage)
- Supersedes the deployment shape of [ADR-0022](0022-self-hosted-gpu-model-federated-into-gateway.md)
  for this model: `homeCluster: true` and the public edge are gone
- Pricing basis: [ADR-0096](0096-gex44-fleet-cost-recovery-pricing.md) — **not yet
  applied to this model**
- Charts: `charts/model-serving/{values.yaml,templates/_helpers.tpl}`,
  `charts/model-server/{templates/_validate.tpl,ci/zimage-values.yaml}`,
  `charts/ai-models/values.yaml`, `charts/apps/values.yaml`,
  `charts/observability-dashboards/values.yaml`
- Image source: `images/z-image-turbo-server/`
- Docs: `docs/patterns/self-hosted-model-serving.md`,
  `docs/migrations/2026-07-27-gpu-fleet-followups.md`
- Inference knowledge: `inference-ops` `docs/adr/0003-image-generation-engine-selection.md`,
  `docs/reference/model-catalog.md`, `docs/how-to/measure-a-model.md`
- Tickets: closes the deployment half of #475/#476/#477 (OpenMythos); originating
  image-model ticket #693 / [PR #704](https://github.com/ADORSYS-GIS/ai-helm/pull/704)
