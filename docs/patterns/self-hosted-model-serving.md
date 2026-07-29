# Self-hosted model serving — the pattern

**How a model gets onto the GPU fleet and in front of users.** This page is the
*how* for this repo; the *why* is in the ADRs it links, and the *inference
knowledge* — VRAM budgeting, quantization, engine choice, benchmarks, runbooks —
lives in the team's **`inference-ops`** repository, which is the source of truth
for all of it. Do not duplicate that material here.

> **Rewritten 2026-07-26** for the Hetzner GPU fleet (ADR-0094/0095). The previous
> version of this page described the one-chart-per-model, public-edge pattern on
> the `admin@homeos` cluster. That generation still runs and is described in
> [§7](#7-the-legacy-generation-adminhomeos) — but nothing new should be built
> that way.

---

## 1. The shape

```
 USER ─TLS + Keycloak JWT─▶  Envoy AI Gateway  ──HTTP, pod network──▶  model pod
                             (envoy-gateway-system)                    (inference ns)
                             auth · budgets · rate limits              1 GPU · 1 model
                             metering (ADR-0021)                       CiliumNetworkPolicy
```

Everything is on **one cluster** (`home-remote`). The gateway reaches a model at
`<model>.inference.svc.cluster.local:8080`. There is no public route to a model,
no TLS between gateway and model, and no API key — the network policy is the
control (ADR-0095).

From the gateway's point of view a self-hosted model is identical to a SaaS
backend: an OpenAI-compatible endpoint. All identity, budget and metering policy
is applied before the request reaches it.

## 2. The charts

| Chart | Role |
|---|---|
| **`charts/inference`** | Orchestrator. One ApplicationSet, one child per catalog entry. `controlPlane: true`. **Holds the engine profiles.** |
| **`charts/inference-server`** | Generic leaf. One model's resources: bjw-template renders the Deployment + seed Job + Service; own templates render PVC, ExternalSecrets, CiliumNetworkPolicy, ServiceMonitor. |
| **`charts/ai-models`** | Unchanged. The gateway catalog — a backend entry + a model entry federate a served model to users. |

**Adding a model is one ~15-line entry** in `charts/inference/values.yaml`
(plus its `charts/ai-models` entries to make it user-reachable). No new chart, no
new Application, no ADR. The step-by-step recipe with verification is
`inference-ops` → `docs/how-to/add-a-model.md`.

### Why the engine profiles live in the orchestrator

A Helm parent **cannot compute subchart values at render time**. The workload comes
from the `bjw-template` subchart, so the leaf cannot derive its seed command from
`model.hfRepo`. Every per-model chart worked around this by hardcoding the seed
repo and glob under a `⚠️ keep in sync` comment — one careless edit from serving
one set of weights while downloading another.

The orchestrator writes each child's values as a YAML string, so it *can* derive
everything from one source of truth. That is the whole reason the pair is split
this way (ADR-0094).

To see what a catalog entry actually expands into:

```bash
helm template chk charts/inference | awk '/valuesYaml: \|-/{f=1;next} f' | sed 's/^              //' > /tmp/child.yaml
helm template x charts/inference-server -f /tmp/child.yaml -n inference
```

## 3. Engines

| | `llamacpp` | `vllm` | `localai` |
|---|---|---|---|
| Serves | text | text | **images** |
| Image | `ghcr.io/ggml-org/llama.cpp:server-cuda` | `lmcache/vllm-openai` | `quay.io/go-skynet/local-ai` ⚠️ pin `-gpu-nvidia-cuda-12` |
| Weights | GGUF (one file via `include`) | safetensors (AWQ/GPTQ/FP8/BF16) | fetched by the engine from its gallery |
| Seed Job | yes | yes | **no** — and the mount is writable |
| Prefix / health | `/v1` · `/health` | `/v1` · `/health` | `/v1` · `/readyz` |
| API key | file (`--api-key-file`) | env `VLLM_API_KEY` | env `API_KEY` |
| `/metrics` | yes (`llamacpp:*`) | yes (`vllm:*`) | yes (behind its admin key) |
| Configured by | flags | flags | **environment** |
| Containers | **1** | **1** | **1** |

**The weight format selects the engine, not preference** — `inference-ops`
ADR-0002 for text, ADR-0004 for images. Do not serve GGUF on vLLM (~8× throughput
regression), and do not look for a diffusion path in either text engine — there
isn't one.

⚠️ **CUDA 12 only.** The fleet runs driver 550 / CUDA 12.4, so `server-cuda13`
will not run.

### `localai` is off the shelf — and that was a correction (ADR-0102)

The image tier is **LocalAI** (`quay.io/go-skynet/local-ai`), an OpenAI-compatible
multi-backend server that serves diffusion models natively. It replaced a
first-party Rust + Candle server we maintained for one day; ADR-0102 records why
that was the wrong call and how the survey missed it.

⚠️ **Pin the CUDA-12 tag.** `master`/`latest` are built against **CUDA 13** and
these nodes run driver 550 / CUDA 12.4 — the same trap as `server-cuda13` and
`-cu129`. Use `v4.7.1-gpu-nvidia-cuda-12`.

**It is not shaped like the text engines**, and the profile says so as data:

| | text engines | `localai` |
|---|---|---|
| Weights | a **seed Job** pre-places them, pinned to a commit SHA | the engine downloads them itself from its gallery |
| `/models` mount | **read-only** | **writable** (`writableModelStore: true`) |
| HF token | required | none — no Hub pull of ours |
| Backend | in the image | **downloaded at boot** into `BACKENDS_PATH`, which must be on the PVC or it repeats every restart |
| Configuration | flags | **environment** (`MODELS`, `MODELS_PATH`, `BACKENDS_PATH`, `API_KEY`) |

A catalog entry carries no repo, revision or glob. The short form names a gallery
entry and lets LocalAI decide everything else:

```yaml
  some-image-model:
    enabled: true
    engine: localai
    serving:
      galleryModel: z-image-turbo-diffusers   # also: Z-Image-Turbo (ggml), vllm-omni-z-image-turbo
    weights:
      sizeGi: 40                              # weights AND the downloaded backend
```

**The live entry does not use that form** — it defines the model itself
(ADR-0103/0105), because the gallery's defaults are tuned for other hardware and a
gallery name is not a pin:

```yaml
  z-image-turbo:
    enabled: true
    engine: localai
    serving:
      backends: [cuda12-stablediffusion-ggml] # REQUIRED once you name no gallery model
      modelConfigFile: z-image-turbo.yaml     # our own filename — see the trap below
      servedModel: z-image-turbo              # = modelNameOverride in charts/ai-models
      modelConfig: |
        backend: stablediffusion-ggml
        name: z-image-turbo
        step: 8                               # NOT the gallery's 25 — this model is distilled for 8
        # no offload_params_to_cpu — put the parameters on the card
        download_files:                       # sha256 per file = the pin back
          - {filename: …, sha256: …, uri: …}
    weights:
      sizeGi: 40
```

Measured difference between the two: **94.2 s → 32.4 s** per 1024×1024 and
**815 MiB → 7985 MiB** of VRAM. The gallery's `offload_params_to_cpu: true` left
a 20 GiB card idle while parameters streamed over PCIe every step.

⚠️ **Two traps specific to this engine:**

- **`deploy/<model>-main` does not exist.** With no seed Job there is a single
  controller, and bjw-template then names the Deployment `<model>` — not
  `<model>-main`, which ADR-0098 standardised every runbook on. Nothing
  functional depends on it (Service and CiliumNetworkPolicy select on the
  `ai-helm…/model` label), but your `kubectl logs deploy/<model>-main` will just
  say `NotFound`.
- **The gallery reference is not a pin — and neither is the server image.** A seed
  Job fetched an exact commit, so the bytes measured were the bytes served. A
  gallery entry can move under us, and LocalAI resolves its inference **backend**
  separately at runtime (default `…/index.yaml@master` at tag `latest`, unsigned),
  so pinning the server pins the thing that answers HTTP but not the thing that
  executes the model. ADR-0105 tried to fix all of it; **on a fresh volume, two
  thirds of that turned out not to work** (ADR-0108):
  - ✅ the **gallery index** pin (`…/index.yaml@v4.7.1`) works, and the model's
    weights are genuinely pinned by a `sha256` per file in `download_files`;
  - ❌ the **backend image tag** was never pinned — the gallery index hardcodes
    `uri: …:latest-…` and LocalAI uses it verbatim, so
    `--backend-images-release-tag` never applies;
  - ❌ the **cosign policy** was unsatisfiable — upstream signs in the legacy
    cosign format, LocalAI v4.7.1's verifier reads only the new Sigstore bundle
    format, and the mismatch hard-fails the pod at boot
    (`no Sigstore bundle referrer … signed with --new-bundle-format?`).
    Do not re-add it expecting the identity regex to be the problem; it is never
    reached. The backend binary is currently unverified and floating.
- **Do not overwrite the gallery's config file.** LocalAI logs `installing model`
  on **every** start and rewrites it, so an initContainer's version survives
  exactly until the engine boots — measured proof: latency and VRAM came back
  bit-identical to the untuned run. Write your own file under your own name
  (`serving.modelConfigFile`) instead. The `._gallery_*` marker does not prevent
  the rewrite.
- **Naming no gallery model removes the backend install that came with it.** Set
  `serving.backends` when you set `serving.modelConfig`, or LocalAI reports the
  absence as a cooldown cascade naming every backend *except* the missing one.
  The chart fails the render rather than let you find that out at boot.

On the gateway side an image model needs **`kind: image`** and
**`pricing.strategy: flatPerRequest`** in `charts/ai-models`: `charts/ai-model`
then drops the Input/Output/TotalToken cost metadata and the tokens-per-minute
burst rule, both dead weight when every response carries zero tokens.

## 4. GPU scheduling

Placement is a **resource request**, not a hand-assignment:

```yaml
nodeSelector:     { nvidia.com/gpu.present: "true" }
runtimeClassName: nvidia
tolerations:      [{ key: nvidia.com/gpu, operator: Exists, effect: NoSchedule }]
resources.limits: { nvidia.com/gpu: 1 }
```

Two cards ⇒ two concurrent models. A third enabled model sits `Pending` with
`Insufficient nvidia.com/gpu` — a legible queue that replaces the old "disable that
model to enable this one" dance across four files.

⚠️ The **seed Job carries the same nodeSelector and toleration** despite needing no
GPU: Longhorn runs only on the GPU nodes (ADR-0092), so a pod elsewhere could not
mount the weights volume at all.

## 5. Weights

A one-time seed Job downloads into an RWX Longhorn volume; the model mounts it
read-only, so pod restarts never re-download.

- **`storageClassName: longhorn` is mandatory** — it is not the cluster default and
  cannot bind outside the GPU nodes. Omit it and the claim silently targets
  `hcloud-volumes` and stays `Pending`.
- **`revision` must be a commit SHA.** Hub repos are mutable; the pin is what makes
  the measured bytes the served bytes.
- The Job is an **ArgoCD Sync hook** (`hook: Sync`,
  `hook-delete-policy: BeforeHookCreation`) — a plain tracked Job goes perpetually
  OutOfSync. It writes a `.seeded` stamp of `revision|include`, so repeat syncs are
  no-ops and a changed revision re-seeds.
- `accessModes` are immutable; RWO→RWX means delete + recreate.
- `reclaimPolicy: Retain` — a deleted PVC orphans, not destroys, the weights.

## 6. Sync waves

`-2` ExternalSecrets → `-1` PVC → `0` seed Job + CiliumNetworkPolicy → `1`
Deployment + Service + ServiceMonitor.

## 7. The legacy generation (`admin@homeos`)

Seven `charts/model-serving-<model>` charts serve from the **other** cluster over
a public Traefik Ingress with `cert-cloudflare` TLS, a static API key, and
`homeCluster: true` (ADR-0022).

> **⚠️ As of 2026-07-27 (ADR-0100) every one of them is `enabled: false`.**
> `zimage-turbo` was the last live one, and it moved to the fleet. The generation
> is now dead code kept only as a rollback surface — and ADR-0094's stated reason
> for retaining it ("zimage-turbo is live there") no longer applies. Deleting the
> remaining charts is a decommissioning exercise on that cluster, tracked as a
> follow-up.
>
> **`model-serving-zimage-turbo` was the exception and is DELETED** (ADR-0106).
> Two reasons, and the second is the general rule: the image it referenced
> (`ghcr.io/adorsys-gis/z-image-turbo-server:v0.1.0`) does not exist, so it was
> not a rollback surface — and a disabled chart is a **resurrection surface**. A
> stale branch merged cleanly and turned it back on, reverting six ADRs with it.
> Retire a chart by deleting it once it stops being a credible rollback target.

The rest are **retained, not deleted**. Do not copy their shape for a new model,
and do not "fix" them to match this page; they are correct for where they ran.

`homeCluster: true` is now scoped to that generation and should retire with it.

## 8. Gotchas that survived the redesign

- **Probes must gate on a real readiness endpoint.** An engine that binds its port
  before weights finish loading passes a `tcpSocket` probe in seconds; startup then
  stops gating and liveness kills a still-loading pod in a loop. Use `httpGet
  /health` with a long startup budget, `tcpSocket` for liveness only.
- **The NetworkPolicy must allow kubelet probes** (`fromEntities: host,
  remote-node, health`). Without them every probe fails and the pod never goes
  Ready — indistinguishable from a crash-looping engine. A plain `NetworkPolicy`
  `ipBlock` does not work; node IPs carry `remote-node`/`host` identity in Cilium.
- **Memory limits are host RAM, not VRAM.** llama.cpp mmaps the GGUF, so its page
  cache counts against the container limit; vLLM needs headroom above any LMCache
  CPU pool.
- **A context that does not fit fails minutes into loading**, as an allocation
  error that reads like a crash. Measure, don't guess.
- **⚠️ llama.cpp `--ctx-size` is the TOTAL KV pool, split across `--parallel`
  slots.** `--ctx-size 16384 --parallel 2` gives each *request* 8192 tokens, not
  16384. Confirm from the startup log (`n_ctx_slot`) and advertise **that** number
  as `contextLength` in `charts/ai-models`, or the gateway promises users a window
  the model will refuse. `--kv-unified` shares one pool across slots instead.
- **⚠️ Hardening the engine also locks `/metrics`.** llama-server exempts
  `/health` from `--api-key-file` — so probes pass and the pod stays **Ready** —
  but not `/metrics`. An unauthenticated ServiceMonitor then gets 401 and the
  model's metrics vanish while everything looks healthy; the only symptom is
  `unauthorized: Invalid API Key` in the model log at exactly the scrape
  interval. The leaf chart gives the scraper the same key via the
  ServiceMonitor's `authorization` block whenever `apiKey.enabled`.
- **A crash-looping pod NO LONGER blocks its own fix** — but know why, because
  the old behaviour is what most Kubernetes docs describe. As a StatefulSet
  (`podManagementPolicy: OrderedReady`, the default) the controller refused to
  replace a not-Ready pod, so a merged chart fix appeared to do nothing while
  `.status.currentRevision` != `.status.updateRevision`, and only
  `kubectl delete pod` applied it. The workload is now a **Deployment with
  `strategy: Recreate`** (ADR-0098), which has no such gate: bad configs
  self-heal on the next merge. `Recreate` is also what keeps the single-GPU
  invariant — under RollingUpdate the new pod would wait for a card the old pod
  still holds.
- **⚠️ Engine image tags can be older than their version number suggests.**
  `lmcache/vllm-openai:v0.7.0` was published 2025-02, `v0.5.2` in 2026-07 — the
  numbering scheme changed, so the "newer" tag is eighteen months stale and
  predates Qwen3 (`ValueError: ... model type 'qwen3' but Transformers does not
  recognize this architecture`). Sort tags by **date**, and prefer plain tags over
  `-cu129` on this fleet (driver 550 / CUDA 12.4).
- **⚠️ vLLM's model path is a POSITIONAL argument and must come first.** The
  image entrypoint is `vllm serve`, whose parser declares `model_tag`
  positionally. Passing it as `--model` exits immediately with
  `error: the following arguments are required: model_tag` and crash-loops the
  pod — a failure that looks like a bad image rather than a bad flag.
- **⚠️ A reasoning model's default can dominate the experience.** OpenMythos-27B
  measured 18.2 s for "what is 17 × 23" with thinking on versus 0.2 s with it off,
  and a short `max_tokens` returned an *empty* answer because the whole budget went
  to `reasoning_content`. The fleet default is thinking **off** via
  `--chat-template-kwargs '{"enable_thinking": false}'`, with clients opting back
  in per request. `reasoning_budget: 0` as a *request* field was ignored by
  llama.cpp build 10133 — it is not the lever.
- **Deploy = brief downtime.** One replica on one card; `Recreate` terminates the
  old pod before starting the new one.
- **Route timeout defaults to 60 s** and takes precedence over the upstream BTP, so
  a slow model needs an explicit `timeout.requestTimeout` in `charts/ai-models`
  or long generations 504 (ADR-0034).
- **Ampere-era "no FP8" notes are hardware history.** These Ada cards have hardware
  FP8. FP8 is still 8 bits/weight, so it suits small models here, not a 27B.
- **⚠️ A model's advertised precision is marketing until you check the repo.**
  Z-Image-Turbo is described everywhere — including in the PR that first deployed
  it — as "FP8, ~8 GB". The published `Tongyi-MAI/Z-Image-Turbo` weights are
  **FP32**: transformer 24.62 GB, text encoder 8.05 GB, VAE 0.17 GB, **~33 GB**
  on disk. A PVC sized from the marketing number fails hours into the seed, with
  a full volume. Size `weights.sizeGi` from the actual file sizes:

  ```bash
  for d in transformer text_encoder vae; do
    curl -s "https://huggingface.co/api/models/<org>/<repo>/tree/main/$d" \
      | python3 -c 'import sys,json;print(sum((f.get("lfs") or {}).get("size",f.get("size",0)) for f in json.load(sys.stdin))/1e9,"GB")'
  done
  ```
- **⚠️ The weights PVC must fit ~2× the repo, not 1×.** `hf download --local-dir`
  stages the entire download into `<dir>/.cache/huggingface` and only then
  materialises the real files, so peak disk is repo **plus** staging copy — and
  the staging copy is kept afterwards unless something removes it. A 45 GiB
  volume for a 33 GB repo hit **100% full with 44 GB in `.cache` and the model
  directories still empty**, which reads like a much bigger download than it is.
  The seed script now `rm -rf`s the staging area *after* writing the `.seeded`
  stamp (after, so an interrupted run stays resumable), but the volume still has
  to survive the peak. Size for 2× + margin. Longhorn can grow a PVC and can
  never shrink one, so err high.
- **⚠️ Seed-Job memory is sized by the LARGEST SHARD × workers, not by repo size.**
  `hf download` fans out over **8 workers by default** and hf_xet buffers per
  file, so a repo of three ~10 GB safetensors shards needs several times what a
  single 16 GB GGUF needs — the fleet's 6 GiB default `OOMKilled` (exit 137) the
  Z-Image-Turbo seed four times in six minutes, while every earlier model passed
  comfortably. Two knobs, and use both: `weights.seedMaxWorkers` bounds the peak
  (the real fix) and `weights.seedMemoryLimit` is the margin. Capping workers
  costs little here — Hub bandwidth is the bottleneck, not concurrency.
- **⚠️ A server that loads its model LAZILY deadlocks against a readiness gate.**
  If `/health` is 503 until the weights are loaded, and the weights load on the
  first request, then: not-Ready ⇒ no Service endpoint ⇒ no request ⇒ never
  loads ⇒ never Ready. The pod restarts forever and the log says nothing,
  because nothing has gone wrong. Every engine on this fleet must load
  **eagerly at start-up** — the two upstream engines do; ours was fixed to
  (ADR-0100). Suspect this whenever a startup probe burns its whole budget with
  a quiet, idle process behind it.

## 9. Verification

```bash
helm dep build charts/inference && helm dep build charts/inference-server
helm lint charts/inference --strict
for f in charts/inference-server/ci/*-values.yaml; do
  helm lint charts/inference-server --strict -f "$f" && helm template x charts/inference-server -f "$f" --dry-run >/dev/null
done
./tools/check-model-catalogs.sh
```

`check-model-catalogs.sh` (wired into `helm-lint` CI) enforces the one cross-chart
invariant: a cluster-local gateway backend must have a running model behind it.
Serving *without* federating is allowed on purpose — that is how a model is
measured before users can reach it.

## 10. Where the rest lives

| Topic | Where |
|---|---|
| VRAM budgeting, quantization, engine choice | `inference-ops` `docs/explanation/`, ADR-0002 (text), ADR-0003 (image) |
| Add / replace / roll back / measure a model | `inference-ops` `docs/how-to/` |
| Operational failures | `inference-ops` `docs/runbooks/` |
| Hardware facts, model catalog | `inference-ops` `docs/reference/` |
| Measured performance | `inference-ops` `docs/benchmarks/` |
| GitOps shape decisions | ADR-0094 (charts), ADR-0095 (exposure), ADR-0092 (storage), ADR-0100/0102 (image generation), ADR-0101 (federation gate) |
| Pricing basis | ADR-0028 |
| Per-model papers (this repo) | [`../models/`](../models/) — legacy generation |
