# Getting image generation onto the GPU fleet — what happened, and what it taught us

**2026-07-27 → 2026-07-28.** Written for the team. This is a narrative, not a
reference: the reference material is in the ADRs and the pattern doc, linked
throughout. It exists because the *route* we took is more instructive than the
destination, and because most of the useful knowledge here was bought by getting
things wrong in public.

Read this if you are going to add a model, touch `charts/model-serving`, or price
anything on the fleet.

---

## 1. What we set out to do

Three things, in order:

1. **Close the "mythos" tickets** (#475 train, #476 publish, #477 deploy/serve).
2. **Move Z-Image-Turbo** — an image-generation model deployed by [PR #704](https://github.com/ADORSYS-GIS/ai-helm/pull/704)
   onto the *home* RTX A2000, behind a public edge — onto the **Hetzner GPU fleet**.
3. **Write the docs**, here and in `inference-ops`.

## 2. Where it ended

| | |
|---|---|
| Image generation | **Live on the fleet**, served by **LocalAI**, federated, **tuned** — 32.4 s per 1024×1024 |
| OpenMythos-27B | **Retired** — two cards, two models, so this was a swap |
| The fleet | `qwen3-8b-fast` (vLLM, text) + `z-image-turbo` (LocalAI, images) |
| Legacy generation | All eight `charts/model-serving-*` charts now disabled |
| New ADRs | **0100** image generation on the fleet · **0101** the load gate has no exceptions · **0102** LocalAI instead of a first-party server · **0103** own the model config · **0104** the GPU cost basis was ~18% wrong · **0105** pin and verify the backend |
| `inference-ops` | ADR-0003 (superseded) → **ADR-0004**, plus a new explanation page on diffusion inference |

Tickets #475 and #476 closed as won't-do/done-by-other-means; #477 closed as
delivered, because OpenMythos *was* deployed, measured, priced and served before
being retired.

## 3. The arc: we built a server we should not have built

PR #704 came with a **first-party Rust + Candle inference server** (~1000 lines).
We adopted it as a third engine profile (`zimage`, ADR-0100) on the reasoning
that nothing off the shelf speaks OpenAI's `/v1/images/generations`.

**That reasoning was wrong, and the way it was wrong is the main lesson of the
session.** The survey behind it checked:

- `diffusers` — a **library**
- ComfyUI, SwarmUI — **UIs**

…and never checked the category that exists to solve exactly this problem:
**OpenAI-compatible multi-backend inference servers**. LocalAI serves the
endpoint and carries *four* Z-Image gallery entries. Xinference has it builtin.
Both are mature and actively developed.

> **The rule worth carrying:** before building an inference server, survey the
> **servers**. Not the libraries, not the UIs. "Nothing speaks OpenAI" is a claim
> about a category and has to be checked against that category.

The signal was also in our own notes on day one: `Comfy-Org/z_image_turbo` has
**5.28M downloads against the base repo's 1.15M**. The ecosystem was plainly not
reconstructing a 33 GB FP32 repo to run this model. We were. Nobody weighed it.

Switching to LocalAI (ADR-0102) deleted the server, the hand-built image, the
build-first ordering rule, the missing `/metrics` and an unenforceable CORS
policy — in one change.

## 4. The failures, in order, and what each one teaches

Every one of these was found on the live cluster, not by review.

### 4.1 A model's advertised precision is marketing

Z-Image-Turbo is documented *everywhere* — including in PR #704 — as
**"FP8, ~8 GB"**. The published repo is **FP32, ~33 GB** (transformer 24.62 +
text encoder 8.05 + VAE 0.17). The PVC was sized from the model card.

**Do:** size from the HF tree API, not the model card.

### 4.2 Seed memory is largest-shard × workers, not repo size

The seed Job was `OOMKilled` four times in six minutes at a 6 GiB limit that
every previous model had cleared. `hf download` fans out over **8 workers** by
default and hf_xet buffers per file; this was the first repo with ~10 GB shards.

**Fix:** `weights.seedMaxWorkers` (cap the fan-out — the real fix) *and*
`weights.seedMemoryLimit` (the margin). [PR #792]

### 4.3 A weights volume must fit the download twice

The volume then hit **100% full with 44 GB in `.cache` and the model directories
empty**. `hf download --local-dir` stages the entire repo before materialising
it, so peak disk is ~2×, and the staging copy is *kept*.

**Fix:** delete the staging area after the `.seeded` stamp is written (after, so
an interrupted run stays resumable), and size for 2×. [PR #793]

### 4.4 A PVC cannot shrink

Having expanded to 100Gi, a later change asked for 40Gi and the app went
Degraded: `spec.resources.requests.storage: Forbidden: field can not be less than
status.capacity`. This was **one commit after** we documented "Longhorn grows a
PVC and never shrinks one, so err high".

**Do:** err high the first time. Reclaiming means deleting the PVC.

### 4.5 Readiness that gates on the wrong stage — twice, inverted

This one is worth internalising because it appeared in two opposite forms:

| | Symptom |
|---|---|
| The Rust server | Loaded **lazily** behind a readiness-gated `/health`. Not Ready ⇒ no endpoint ⇒ no request ⇒ never loads ⇒ never Ready. **Deadlock**, silent. |
| LocalAI | `/readyz` gates on the model **install** (the download); the backend loads lazily on first request. **Ready with nothing loaded** — a green ArgoCD tree, a Ready pod and a scraping `/metrics` in front of a model returning 500. |

Same root cause both times: **trusting a probe without knowing which stage it
measures.**

**Fix:** `LOAD_TO_MEMORY` moves the load into the startup sequence readiness waits
on, so Ready means loaded — the contract llama.cpp and vLLM already give us. It
proved itself immediately: the next misconfiguration failed as a **loud crash
loop at boot** instead of a 500 in a user's face.

### 4.6 `f16` is not a dtype knob

Set `F16=true` expecting half precision. LocalAI maps it to diffusers'
**`variant="fp16"`**, which selects differently-*named* files
(`*.fp16.safetensors`). The repo publishes FP32 only, so the backend died with
*"You are trying to load model files of the `variant=fp16`, but no such modeling
files are available"*.

**Do:** read what a flag *does*, not what its name suggests. Casting a dtype and
selecting a file variant are different operations that share a word.

### 4.7 `PRELOAD_MODELS_CONFIG` ≠ `MODELS_CONFIG_FILE`

Two env vars one word apart, doing different things:

- `PRELOAD_MODELS_CONFIG` — a list of **gallery sources**, each requiring a `url`
- `MODELS_CONFIG_FILE` — "YAML file containing a list of model **backend configs**"

Feeding raw model configs to the first fails at boot with
`unsupported protocol scheme ""` — an error that describes a *networking*
problem and is really a *missing field*.

### 4.8 The gallery's tuning is not your tuning

LocalAI's gallery entry ships `step: 25` for a model **distilled for 8** (~3× the
work for no quality gain) and `offload_params_to_cpu: true` — which produced
**815 MiB of VRAM used out of 20475**, i.e. a 20 GiB card sitting idle while the
PCIe bus did the work.

**Fix (ADR-0103), and it took four attempts to land.** Owning the config is
right; reaching the engine with it was not obvious:

| Attempt | Result |
|---|---|
| `PRELOAD_MODELS_CONFIG` | It is a list of **gallery sources** needing a `url` — died with `unsupported protocol scheme ""` |
| `MODELS_CONFIG_FILE` | Read the model NAME but not `parameters.model` |
| initContainer overwriting `Z-Image-Turbo.yaml` | LocalAI logs `installing model` on **every** start and rewrote it — measured proof: latency and VRAM bit-identical to untuned |
| **initContainer writing `z-image-turbo.yaml`** | ✅ Works — our own filename, which the gallery has no reason to touch |

The engine reads plain `<name>.yaml` files from `MODELS_PATH`. That is the only
mechanism; the first three attempts were ways of trying to reach it sideways.

**Result: 94.2 s → 32.4 s per 1024×1024 (2.9×), VRAM 815 MiB → 7985 MiB.** The
output is visibly *better*, not merely faster — 8 steps is what this model was
distilled for. The VRAM jump is the parameters moving onto the card instead of
streaming over PCIe on every step.

⚠️ The third attempt is the one worth remembering: it deployed green, the pod was
healthy, the initContainer log showed the right config — and the tuning was
silently discarded. Only re-measuring caught it.

### 4.9 The pricing basis was wrong fleet-wide

ADR-0096 derived **every** self-hosted price from **€184/month** for a GEX44. The
real figure is **~$234/month ≈ €217** — about 18% higher — so *every* price was
under-recovering, `qwen3-8b-fast` included. Fixed by **ADR-0104**, which
supersedes 0096 on the basis (the method is unchanged) and sets a rule:
**re-derive from measured throughput, never scale the old number.** Scaling a
stale measurement by a corrected basis produces a figure that looks fixed and is
not.

⚠️ Still unverified: the **3.45× duty-cycle uplift**, inherited from the old
A2000 and never measured here. It is the only guessed term left in the formula,
and $234 is a list price rather than an invoice.

## 5. How LocalAI actually works

The mental model that took three failures to acquire:

```
PVC  <model>-weights (Longhorn RWX)   mounted READ-WRITE at /models/<model>
├── backends/    ← inference engines, pulled at runtime from the BACKEND gallery
│                  (stablediffusion-ggml: 4.2 GiB download → 7.3 GiB extracted)
└── models/      ← weights + model configs (MODELS_PATH)
ConfigMap  <model>-config             mounted READ-ONLY at /config   ← ours, from git
```

**The difference from the text engines:** nothing is pre-placed. llama.cpp and
vLLM have a **seed Job** that fills the volume before the container starts, then
mount it read-only. LocalAI fetches everything itself, *after* start-up — hence
`seedJob: false` and a **writable** mount.

Cold-boot order:

1. Read `MODELS_CONFIG_FILE=/config/models.yaml` — our config, from the ConfigMap.
2. Download missing `download_files` (checksum-verified) into `MODELS_PATH`.
3. Resolve and extract the **backend** from a *separate* gallery into
   `BACKENDS_PATH`. **This is the slow stage and the one nobody expects.**
4. `LOAD_TO_MEMORY` loads the model into VRAM *during start-up*, so `/readyz`
   flips 503 → 200 only when it can actually serve.

Both paths live on the PVC, so 2–3 happen **once**; a restart goes straight to 4.
That is why first boot needed a 4-hour startup budget and later ones take minutes.

## 6. The measurement, and why we insisted on it

ADR-0101 says: **a model is federated when it has been measured on the hardware
it runs on** — not when it is deployed, not when it worked somewhere else, and
not because users had it before. We wrote that ADR *because* we had federated
this model unmeasured and it returned 500 to users while every dashboard was
green.

Measured before federating:

| | |
|---|---|
| 1024×1024 | 94.2 s — HTTP 200, 1.8 MB PNG, **and we looked at it** |
| 512×512 | 22.9 s |
| Peak VRAM | 815 MiB / 20475 (on the old CPU-offload config) |

Two things only the gate could have caught:

- `modelNameOverride` was wrong. LocalAI serves a model under the name of
  whatever **defines** it — the gallery's name when you use a gallery entry, ours
  when we supply the config. Wrong value ⇒ **404 on every gateway request while
  the model itself is perfectly healthy.**
- The price was a placeholder ~5× too low.

> **"Completely healthy" is a statement about Kubernetes, not about inference.**
> The whole ArgoCD tree was green while the model could not serve a single
> request. Generate an image. Look at it.

## 7. Where things stand

**Working, measured, and federated:** image generation at **32.4 s per
1024×1024** (median of three), priced at **$0.0100/image** derived from that
measurement; `qwen3-8b-fast` untouched throughout, at corrected prices;
`/metrics` restored for the image tier; an engine-independent
`ms-model-unavailable` alert, because `up{namespace="inference"}` cannot see an
engine that publishes nothing.

Also done: the **model id now tells a client what a model is for**, which it did
not before. Three shapes, and only three:

| Suffix | Meaning | Count |
|---|---|---|
| *(none)* | SaaS — anyone may use it | 22 |
| `-internal` | internal listener only; an external client gets a 404 | 6 |
| `-local` | **our GPU fleet** | 2 |

`-local` used to mean "self-hosted somewhere", spanning two clusters and a public
edge. The seven home-GPU models and their seven backends are **commented out**,
not `enabled: false` — a disabled entry reads as something you could switch back
on, and those servers no longer exist. The `-internal` rename was a coordinated
cross-repo change, because the id **is** the routing key consumers send as
`x-ai-eg-model`.

And the image tier's supply chain is pinned end to end (ADR-0105): server,
backend gallery, backend image, and every weight file by sha256 — which recovered
the pinned-bytes guarantee ADR-0102 had written off. Plus **31 GB of abandoned
FP32 download** reclaimed from the volume.

**Open:**

1. **The 3.45× duty-cycle uplift** is the only guessed term left in the pricing
   formula — inherited from the old A2000, never measured here. And $234 is a
   list price, not an invoice.
2. **The cosign identity is unproven.** The backend was already on the volume
   when verification was enabled, so it will not be exercised until a fresh one —
   meaning a wrong identity regex fails at the worst possible moment. Same for
   `download_files`: first-class in the schema, untested here because the volume
   was already populated. **The next fresh-volume boot is the real test of both.**
3. **`requireBackendIntegrity` is unset** — the correct end state, deliberately
   deferred because it turns a missing policy anywhere into a hard boot failure.
   Flip it after (2) passes.
4. **Delete the eight legacy `model-serving-*` charts** — unblocked since the
   whole generation is disabled.

## 8. If you read nothing else

- Survey the **servers** before building one.
- **Generate an image.** Ready, Synced and Healthy are not evidence.
- Size volumes for the **download**, not the weights; and err high, because a
  PVC cannot shrink.
- Know **which stage** your readiness probe measures.
- The gallery's defaults are for someone else's hardware.
- Read what a flag **does**.
- **Pinning one component is not pinning the stack.** We pinned the server image
  with care and left the thing that executes the model on `latest`, unsigned.

## Related

### Written this session

| ADR | Decision |
|---|---|
| [0100](../adr/0100-image-generation-on-the-gpu-fleet.md) | Image generation joins the fleet as a third engine profile; OpenMythos-27B retired to free the card |
| [0101](../adr/0101-load-gate-before-federation-no-exceptions.md) | The load gate has **no migration exception** — a model is federated only once measured on the hardware it runs on |
| [0102](../adr/0102-localai-instead-of-a-first-party-image-server.md) | Serve images with **LocalAI**; delete the first-party Rust server. *Supersedes 0100's engine choice* |
| [0103](../adr/0103-own-the-localai-model-config.md) | Own the model config — the gallery's tuning is for someone else's hardware |
| [0104](../adr/0104-gpu-cost-basis-correction.md) | The GPU cost basis was **~18% low, fleet-wide**. *Supersedes [0096](../adr/0096-gex44-fleet-cost-recovery-pricing.md)* |
| [0105](../adr/0105-pin-and-verify-the-localai-backend.md) | Pin **and verify** the backend; define the model ourselves. *Closes 0102's two recorded gaps* |

`inference-ops`: [ADR-0004](https://github.com/ADORSYS-GIS/inference-ops/blob/main/docs/adr/0004-off-the-shelf-image-serving.md)
— survey the *servers*, not the libraries and UIs. *Supersedes its ADR-0003.*

### The serving decisions this stands on

Read these before changing how a model is served — every one of them constrained
something above.

| ADR | Why it matters here |
|---|---|
| [0094](../adr/0094-generic-model-serving-orchestrator.md) | The orchestrator + generic leaf, and the **engine-profile contract**: an engine is a profile plus a `ci/` fixture. ADR-0100 was a test of whether that held for a non-text engine |
| [0095](../adr/0095-cluster-local-model-federation.md) | Cluster-local federation — no Ingress, cert, DNS or public edge. Why moving off the home GPU was the point, not a detail |
| [0097](../adr/0097-engine-agnostic-serving-hardening.md) | Hardening as fleet **policy** with a per-engine mapping. The first-party server could not honour its CORS pin; LocalAI can |
| [0098](../adr/0098-deployment-recreate-instead-of-statefulset.md) | `Deployment` + `Recreate`. Why a crash-looping pod self-heals on merge — which mattered a great deal tonight |
| [0092](../adr/0092-longhorn-for-hetzner-gpu-nodes.md) | Longhorn on the GPU nodes only, and **not** the default StorageClass. The volume every disk lesson here happened on |
| [0022](../adr/0022-self-hosted-gpu-model-federated-into-gateway.md) | The **previous generation** — public edge, static Bearer, `homeCluster: true`. Superseded in shape; useful for reading the commented-out entries |

`inference-ops`: [ADR-0002](https://github.com/ADORSYS-GIS/inference-ops/blob/main/docs/adr/0002-engine-selection-matrix.md)
— the weight format selects the engine, for **language** models. ADR-0004 extends
it: read the model *family* first.

### Cost and pricing

| ADR | Why it matters here |
|---|---|
| [0028](../adr/0028-owned-hardware-model-pricing.md) | The **method**: cost recovery on owned hardware, €/hour ÷ measured throughput. Unchanged by anything this session |
| [0096](../adr/0096-gex44-fleet-cost-recovery-pricing.md) | The original fleet basis. **Superseded by 0104** — the method was right, the €184 was not |
| [0104](../adr/0104-gpu-cost-basis-correction.md) | The correction, and the rule that came with it: **re-derive from measured throughput, never scale the old number** |

### The documents that changed, and what each is for

**In this repo** — *how to render and deploy*:

| Document | Why you would open it |
|---|---|
| [`../patterns/self-hosted-model-serving.md`](../patterns/self-hosted-model-serving.md) | **Start here to add or change a model.** The three-engine table, the catalog-entry shapes, and the gotcha list every failure below was added to |
| [`charts/model-serving/values.yaml`](../../charts/model-serving/values.yaml) | The catalog itself. Densely commented on purpose — the engine profiles carry the reasoning next to the knob |
| [`charts/ai-models/values.yaml`](../../charts/ai-models/values.yaml) | The gateway catalog, and the **id-suffix convention** (`-internal` / `-local`) at the top |
| [`2026-07-27-gpu-fleet-followups.md`](2026-07-27-gpu-fleet-followups.md) | The live punch-list. Entries are closed in place with what actually happened, not deleted |
| [`../architecture/09-model-serving.md`](../architecture/09-model-serving.md) | The subsystem map — engines, placement, the legacy generation |
| [`../architecture/07-data-secrets.md`](../architecture/07-data-secrets.md) | Storage: the two unrelated Longhorns, and why the home one now holds orphaned data |
| [`../arc42.md`](../arc42.md) | §5 building blocks · §9 decisions · §11 **risks** — the four new ones are worth a read on their own |
| [`../README.md`](../README.md) · [`../adr/README.md`](../adr/README.md) | The indexes. Every ADR summary above is expanded there |
| [`../../CLAUDE.md`](../../CLAUDE.md) | The agent/contributor contract. Carries the rules that are cheap to state and expensive to rediscover — build-first, CUDA-12, "Ready does not mean loaded" |
| [`tools/check-model-catalogs.sh`](../../tools/check-model-catalogs.sh) | The CI guard that a federated model has a server behind it. Note what it does **not** witness — it keys on backends, not model entries |

**In `inference-ops`** — *the inference knowledge; put it there, not here*:

| Document | Why you would open it |
|---|---|
| [`explanation/diffusion-vs-autoregressive.md`](https://github.com/ADORSYS-GIS/inference-ops/blob/main/docs/explanation/diffusion-vs-autoregressive.md) | **Read before proposing an image model.** Why there is no KV cache, why the published precision is not the served precision, why latency is a fixed cost |
| [`how-to/measure-a-model.md`](https://github.com/ADORSYS-GIS/inference-ops/blob/main/docs/how-to/measure-a-model.md) | The load gate. **§8 is the image-model gate** — and says to look at the image, because a well-formed response can be noise |
| [`how-to/add-a-model.md`](https://github.com/ADORSYS-GIS/inference-ops/blob/main/docs/how-to/add-a-model.md) | The recipe, family-first: diffusion → LocalAI, GGUF → llama.cpp, safetensors → vLLM |
| [`reference/model-catalog.md`](https://github.com/ADORSYS-GIS/inference-ops/blob/main/docs/reference/model-catalog.md) | What is deployed and what was measured. OpenMythos's record is preserved under *Retired* |
| [`reference/observability.md`](https://github.com/ADORSYS-GIS/inference-ops/blob/main/docs/reference/observability.md) | Dashboards, metrics and alert rules — including why `up{namespace="inference"}` is not enough |
| [`runbooks/model-wont-load-or-oom.md`](https://github.com/ADORSYS-GIS/inference-ops/blob/main/docs/runbooks/model-wont-load-or-oom.md) | Symptom → cause. Gained the lazy-load deadlock and the wrong-compute-capability failure |
| [`watchlist.md`](https://github.com/ADORSYS-GIS/inference-ops/blob/main/docs/watchlist.md) | Ecosystem triage — CUDA-13 default tags, `vllm-omni` gaining diffusion, and *survey the servers* |
| [`reference/glossary.md`](https://github.com/ADORSYS-GIS/inference-ops/blob/main/docs/reference/glossary.md) | DiT, VAE, latent, CFG, distilled steps — added the week they were first used |

> **The split, since it is easy to get wrong:** ai-helm ADRs own the **GitOps
> shape**; `inference-ops` ADRs own the **inference decisions**. Chart mechanics
> here, VRAM and quantization and benchmarks there.
