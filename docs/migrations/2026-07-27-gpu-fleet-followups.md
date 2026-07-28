# GPU fleet — open follow-ups (as of 2026-07-27)

Punch-list left after bringing the two Hetzner GPU nodes into service: the
generic model-serving charts (ADR-0094/0095), OpenMythos-27B and Qwen3-8B-AWQ,
engine hardening (ADR-0097), the Deployment switch (ADR-0098), GPU telemetry,
dashboards, alerting, and Grafana branding (ADR-0099).

> **Updated later the same day (ADR-0100).** The fleet's model mix changed:
> OpenMythos-27B is **retired** and its card now runs **Z-Image-Turbo**, the
> image-generation model, moved off the home GPU. Entries touched by that change
> are marked; the new blocking item is §1.3 (build and push the image).

Everything below is **known and deliberate** — nothing here is a surprise waiting
to be discovered. Ordered by what blocks whom.

---

## 1. Needs a human — nobody else can do these

### 1.1 Discord webhooks ⚠️ blocks the channel switchover

**Updated 2026-07-27:** the plan changed. The channel originally added for GPU
alerts is now the **default receiver for everything**, and the project lead's
personal webhook moves aside under its own name:

| Contact point | Destination | State |
|---|---|---|
| `discord` | the **team** channel — default receiver, catch-all | enabled; still delivering to the lead's webhook until the property value is updated |
| `discord-stephane` | the project lead's webhook | **disabled** until its property exists |

Two actions in `ssegning-aws`, key `ai/camer/digital/prod/env`:

1. **UPDATE** `grafana_discord_webhook_url` → the **team** webhook URL.
   (The property is deliberately reused so the default receiver is never pointed
   at something that does not exist. Nothing breaks in the meantime — alerts
   simply keep arriving where they do today.)
2. **CREATE** `grafana_discord_webhook_url_stephane` → the lead's existing
   webhook URL. Then set `discord-stephane` to `enabled: true` in
   `charts/observability-dashboards/values.yaml`.

⚠️ **Order matters, and this is not theoretical.** Enabling a contact point whose
secret is missing makes Grafana reject the **entire notification policy tree**,
which stopped *all* alert delivery on 2026-07-27 — the default route included.
The chart now skips disabled contact points and any route referencing them, so
the failure is contained, but the rule stands: **secret first, then flip the
flag.**

There is no route to `discord-stephane` today; the team channel being the
default means everything already lands there. The nine model/GPU rules keep their
`team: model-serving` label for silences and filters, and re-adding a route is a
three-line change documented in the values file.

### 1.2 ~~`z-image-turbo-local` returns HTTP 500~~ → DIAGNOSED and MOVED (ADR-0100)

**Closed 2026-07-27.** The 500 was never going to be fixable on that cluster: a
source review of the PR-#704 artifact found four independent defects, any one of
which is fatal.

| Defect | Effect |
|---|---|
| The engine loaded **lazily**, on the first request, while `/health` answers 503 until loaded | Deadlock — not-Ready ⇒ no Service endpoint ⇒ no request ⇒ never loads. The pod could never have served anything. |
| PVC sized **20 GiB** for **~33 GB** of weights (the repo ships FP32, not the advertised "FP8") | The seed Job fills the volume and fails. |
| The Dockerfile **cannot build** — `cargo build` with no `RUN`, `COPY tests/` for a non-existent directory, `-fuse-ld=lld` without lld | The `v0.1.0` image was not built from the committed source, so nobody can say what it contains. |
| CUDA 12.8 base, kernels compiled for the build host's compute capability | Would fail on the fleet's sm_89 / CUDA 12.4 cards even once running. |

All four are fixed, the model **moved to the GPU fleet** as the `zimage` engine
profile, and the legacy `model-serving-zimage-turbo` app is disabled. The 500
should be gone — **but that is a prediction, not a measurement**: see §2.5.

The judgement call in the original entry was the right one. Leaving a broken
model advertised is what kept the bug visible long enough to be traced to its
source instead of silently disabled and forgotten.

### 1.3 ~~Build and push `z-image-turbo-server:v0.2.0`~~ → GONE (ADR-0102)

**Closed 2026-07-28 by deleting the problem.** The image tier is now **LocalAI**,
an off-the-shelf OpenAI-compatible server with a pinnable CUDA-12 tag. There is
no first-party image to build, so the build-first rule, the `CUDA_COMPUTE_CAP`
trap and the `cargo-auditable` gap all disappear with it. ADR-0100's survey had
missed the entire category of OpenAI-compatible multi-backend servers; ADR-0102
records how.

<details><summary>The original entry, kept because the CUDA-compute-cap trap
generalises to any Candle/CUDA image we might build later</summary>

Nothing in CI builds our first-party images. Until this tag exists in GHCR the
`z-image-turbo` pod sits in `ImagePullBackOff` and the federated model 503s.

```bash
cd images/z-image-turbo-server
docker build -t ghcr.io/adorsys-gis/z-image-turbo-server:v0.2.0 .
docker push  ghcr.io/adorsys-gis/z-image-turbo-server:v0.2.0
```

Must be built with `CUDA_COMPUTE_CAP=89` (pinned in the Dockerfile) — an image
built on any other card fails at *first inference*, after the pod is Ready, with
`no kernel image is available for execution on the device`. The build needs the
CUDA toolkit; it does not need a GPU.

⚠️ Same ordering rule as values-repo-first and secret-first: **push, then merge.**
If the catalog entry lands first, the symptom is an ImagePullBackOff rather than
anything subtler — annoying, not dangerous.

</details>

### 1.4 ~~The €184/month figure is WRONG~~ → CORRECTED (ADR-0104)

**Closed 2026-07-28** by ADR-0104, which supersedes 0096 on the basis (the method
is unchanged). €/hour goes 0.2521 → **0.2968**; `qwen3-8b-fast` re-derived from
its measured 45 tok/s rather than scaled by 1.18. The image model's price waits
on a re-measure of the tuned config, since two corrections land on it at once.

⚠️ The **3.45× duty-cycle uplift** (§2.3) is now the largest unverified term in
the formula — inherited from the old A2000, never measured here. And $234 is
still a **list price**, not an invoice.

**Original entry, 2026-07-28.** ADR-0096 derives every self-hosted price from
**€184/month** for a GEX44. The actual cost is **~$234/month** — about 18%
higher. That is not a rounding error and it is not scoped to one model: every
per-token price for `qwen3-8b-fast`, every retired OpenMythos number, and the
image model's per-image price all inherit it.

Needs an **ADR superseding 0096**, because the basis is the thing that changed,
not the arithmetic. Until then the catalog under-recovers by ~18% and the entries
say so.

Compounding it: ADR-0096 also applies a **3.45× duty-cycle uplift** inherited
from the old A2000 (§2.3) that has never been measured on this fleet. So one
input is confirmed wrong and another is unverified, in the same formula.

### 1.5 Colleagues seeing `glm-5p1` in Kilo Code

That model was retired in ADR-0075 and exists in neither the catalog nor as a
route. Almost certainly a client-side cached model list — ask them to clear it
before treating it as a platform bug.

### 1.6 Grafana Enterprise — a budget decision, not an engineering one

ADR-0099: the Grafana logo, login page, favicon and browser title remain
Grafana's, because white-labeling is Enterprise-only. If that matters, it is a
licence purchase. Decide it on the whole feature set and price, not on branding
alone.

---

## 2. Measurement gaps — the numbers we are currently guessing

### 2.1 No concurrency benchmarks

Every measurement so far is **single-stream**. Both benchmark reports say so
explicitly. Consequences:

- vLLM's continuous batching — the main reason to run that engine — is entirely
  unexercised.
- The saturation alert thresholds (llama.cpp deferring, vLLM waiting) are
  *reasoned*, not calibrated against a load test.

`inference-ops` already names the tools of record: GuideLLM, NVIDIA aiperf,
inference-perf. A concurrency sweep on both tiers would turn several assumptions
into facts.

### 2.2 LMCache is enabled but unproven — and may be costing performance

`qwen3-8b-fast` runs with LMCache on. The connector initialises, but:

- a single-stream smoke test with no shared prefixes exercises none of its value;
- there are **no LMCache metrics**, so Grafana cannot tell you whether it helps;
- vLLM warns at start-up that `--kv-transfer-config` **disables the hybrid KV
  cache manager**, and that models with sliding-window attention "run with
  reduced performance" — Qwen3 uses sliding-window attention in some configs.

So it is plausibly a net negative right now. Needs an A/B with a shared-prefix
workload before it is assumed to be a win.

### 2.3 The 3.45× duty-cycle uplift is inherited, not measured

ADR-0096 reuses the utilisation assumption implied by the old A2000 entry
(~29% duty cycle). Nothing on this fleet has been measured. If real usage is much
busier we over-recover; much quieter and we under-recover. Re-tune once there is
real utilisation data.

### 2.4 `inputPer1M` is conservative-high fleet-wide

The catalog uses a `1 : 0.15 : 0.03` out/in/cached ratio. Measured prefill is
625 tok/s against 15 tok/s decode — **41× faster** — so physics would justify
input nearer `0.024`. Kept at 0.15 for consistency with existing entries; worth a
fleet-wide decision rather than a per-model exception.

⚠️ Note this whole ratio was calibrated on OpenMythos, which is now retired
(§1.2 / ADR-0100). `qwen3-8b-fast` measured **45 tok/s** decode, so the argument
needs redoing against the model that is actually there.

### 2.5 Z-Image-Turbo has never been load-gated ⚠️ and it is federated anyway

Every number in its catalog entry — the 45 GiB PVC, the 32 GiB memory limit, the
~12.4 GB VRAM estimate — is derived from published file sizes and arithmetic. On
this hardware nobody has measured:

- **images/hour** at 1024×1024, 8 steps — the input ADR-0096 needs before the
  `$0.005/image` placeholder can become a real cost-recovery price;
- **VRAM actually used**, versus the ~12.4 GB predicted;
- **wall-clock per image**, which decides whether the 300s route timeout and the
  single-request Mutex are comfortable or marginal;
- **the two things rendering cannot prove**: that the pushed image's kernels run
  on sm_89, and that the gateway backend's `prefix: /v1` actually reaches
  `/v1/images/generations` (the legacy backend used `/`).

⚠️ **UPDATED same day — it is no longer federated (ADR-0101).** It briefly was,
on the argument that a migration is not a new offering. That was wrong: the model
had never been built, seeded or loaded on this hardware, so federation preserved a
route to a backend with nothing behind it. Two of the three size estimates then
failed on the first sync (§1.2 note, and the seed/disk fixes in PRs #792/#793)
while users could still select the model. The third — that ~12.4 GB fits a
20475 MiB card — is derived exactly the same way and decides whether the model
runs at all.

`z-image-turbo-local` is now `enabled: false` in `charts/ai-models`, with the
serving entry left enabled so the model still deploys and can be measured. This
is the item that brings image generation back.

Recipe: `inference-ops` `docs/how-to/measure-a-model.md` §8. File the report in
`inference-ops` `docs/benchmarks/`, re-derive the price from measured
images/hour, and only then flip `z-image-turbo-local` back to `enabled: true`.

---

## 3. Known platform limitations

### 3.1 `/v1/models` listing internal-only models — RESOLVED

Was: `/v1/models` is generated by Envoy AI Gateway from the AIGatewayRoutes,
not by any chart here. Six `disableExternal: true` models were appearing to
external clients anyway, which got a correct-but-confusing `404 No matching
route found` if they picked one. Believed unfixable from our side ("worth an
upstream issue") until it turned out `AIGatewayRoute.spec.hostnames` — present
since AIEG v1.0.0, the exact controller version this cluster runs — scopes the
synthesized `/v1/models` response per Host-header match, and we'd simply never
set it. A route with no `hostnames` is advertised on every host regardless of
which listener it's actually parented to; that was the real root cause, not an
upstream limitation.

Three mitigations had already landed for the believed-unfixable problem,
layered rather than sequential:
- Those models report `owned_by: "GIS AI Models (internal only)"`, the only
  field the OpenAI model schema offers (there is no display-name field).
- `/v1/models/info` — which we do control — filters them out entirely.
- Their `x-ai-eg-model` routing id got an `-internal` suffix so a copy-pasted
  config at least fails obviously instead of silently.

**Fix ([ai-helm#797](https://github.com/ADORSYS-GIS/ai-helm/pull/797), merged
2026-07-28):** `charts/ai-model` now sets
`hostnames: [core-gateway-internal.envoy-gateway-system.svc.cluster.local]` on
every `disableExternal: true` route's `AIGatewayRoute`
(`gatewayRef.internalHostname` in `charts/ai-models/values.yaml`). All three
prior mitigations are left in place as defense-in-depth (cheap, and the
`-internal` suffix is still what LibreChat/Lightbridge send as the routing id
regardless of what's listed).

**Verified live, same day:** all 6 routes carry the correct `hostnames`;
a non-`disableExternal` control model (`minimax-m2p5`) is unchanged (no
`hostnames`, still parented to both listeners); zero new Envoy `ext_proc`
errors across all 3 gateway replicas post-sync; real completions succeed on
all 6 internal models via the internal plane; and `GET
https://api.ai.camer.digital/v1/models` (tested with a real Keycloak JWT — the
operator's own already-authenticated opencode client token, not a new
credential) returns 22 models with **zero** of the 6 internal-only ids present,
while an ordinary external model (`minimax-m2p5`) still is. No revert needed.

### 3.2 Any `grafana.ini` change wipes all dashboards

Grafana is stateless (ADR-0023), so changing `grafana.ini` rolls the pod and
destroys its emptyDir — taking every operator-provisioned **folder** and
dashboard with it. The operator's cached "synchronized" status means it does not
recreate the folders, so every `folderRef` dashboard then fails with
`[400] "folder not found"`. `resyncPeriod` alone does **not** recover this.

Remedy, verified 2026-07-27 (28/28 dashboards back within 15s):

```bash
kubectl rollout restart -n observability deploy/grafana-operator
```

Worth automating — or revisiting ADR-0023 and giving Grafana a small PVC.

### 3.3 No token-rate regression alert

Nothing fires if a model falls below its benchmarked decode rate — arguably the
most useful alert we could have. `llamacpp:predicted_tokens_seconds` is a
last-value gauge that persists while idle, so a single slow generation would
latch an alert on indefinitely. Needs a sustained measure neither engine
currently exports; a recording rule over a time window is the likely shape.

### 3.4 No GPU-to-cost attribution

DCGM tells us which pod is on which card; the gateway tells us what each request
cost. Nothing joins them, so "what did this model actually cost to run this
month" still needs manual arithmetic.

---

## 4. Hygiene / deferred

| Item | Note |
|---|---|
| Engine containers run as **root** with all caps dropped | Tightening to non-root is a per-engine follow-up gated on a real GPU rollout; a previous attempt to pin `runAsUser: 1000` was written but never verified (ADR-0094) |
| Eight legacy `charts/model-serving-*` charts | ⚠️ **Now UNBLOCKED for deletion.** ADR-0094 kept them because `zimage-turbo` was live on `admin@homeos`; as of ADR-0100 all eight are `enabled: false` and that reason is gone. Deleting them is a decommissioning exercise on that cluster (ArgoCD prune + PVCs + Ingresses + certs), not a chart edit — worth its own ticket. **Do not copy their shape** meanwhile |
| `homeCluster: true` | Now legacy-only (ADR-0095) and referenced by nothing enabled; should retire with the above |
| No CI builds our first-party images | `lakefs-proxy` and now `z-image-turbo-server` are hand-built (§1.3). A path-filtered `workflow_dispatch` + `on: push` build job would remove a standing manual step and make the running image traceable to a commit |
| `z-image-turbo-server` does not build with `cargo-auditable` | Same gap `lakefs-proxy` already closed: without it Trivy scans only the base OS and reports zero crates, so a green scan means nothing for the Rust dependency tree |
| The `zimage` server hardcodes `allow_any_origin()` | The ADR-0097 CORS pin cannot be applied to this engine (`corsConfigurable: false`). A `--cors-origins` flag in our own source closes it in one small change, on the next rebuild |
| The llama.cpp dashboard and `ms-llamacpp-queueing` are dormant | No model runs on that engine since OpenMythos was retired. Both self-heal the moment a GGUF model returns; neither was deleted |
| ~~The seed Job's 6 GiB memory limit is fleet-wide, not per-model~~ | ✅ **RESOLVED 2026-07-27** — and it did OOM, exactly as predicted here: the Z-Image-Turbo seed was `OOMKilled` (exit 137) four times in six minutes on the first sync after merge. The limit is now the per-model `weights.seedMemoryLimit` (16Gi for this model), **and** `weights.seedMaxWorkers` caps `hf download`'s default 8-way fan-out to 2. The lesson generalises: peak seed memory is set by the **largest shard × concurrent workers**, not by the repo total — which is why a 33 GB repo of ~10 GB shards blows a limit that a single 16 GB GGUF never approached |
| `inference-ops` tutorial not yet run by a non-author | That repo's own rule requires it before merge; the page carries a validation-status note |
| Two ADRs numbered `0077` | Pre-existing (`my-usage-dashboard`, `phoenix-style-chat-dashboards`). Cosmetic, needs a renumber |
| `dcgm-exporter` label transition | Flipping `honorLabels` left the old `exported_*` series in the TSDB; they age out with retention. Cosmetic only |

---

### 4.1 LocalAI's inference backend is unpinned and unverified ⚠️ new 2026-07-28

Observed on the image tier's first successful boot, and not visible before it ran:

```text
installing OCI backend without signature verification
  backend="cuda12-diffusers"
  uri="quay.io/go-skynet/local-ai-backends:latest-gpu-nvidia-cuda-12-diffusers"
```

Two problems, one line:

1. **The backend tag is `latest`.** We pin the LocalAI *server*
   (`v4.7.1-gpu-nvidia-cuda-12`), but LocalAI resolves the thing that actually
   executes the model at runtime, unpinned. A backend published tomorrow is what
   a pod restarting tomorrow runs. It selects cuda12 correctly today — it reads
   the host capability — so this is unpinned, not broken.
2. **No signature verification**, stated by LocalAI itself as a WARN. This repo
   cosign-gates first-party images (ADR-0055); that gate does not reach here, and
   no chart knob changes it.

Both follow from choosing an engine that manages its own runtime (ADR-0102) — a
cost that trade did not anticipate. Options, none free: pre-populate
`BACKENDS_PATH` from an image we control, wait for upstream pinning, or accept it
explicitly for a cluster-local model behind a NetworkPolicy. **Worth a decision,
not a silent default.**

---

## Related

- ADRs: [0094](../adr/0094-generic-model-serving-orchestrator.md) ·
  [0095](../adr/0095-cluster-local-model-federation.md) ·
  [0096](../adr/0096-gex44-fleet-cost-recovery-pricing.md) ·
  [0097](../adr/0097-engine-agnostic-serving-hardening.md) ·
  [0098](../adr/0098-deployment-recreate-instead-of-statefulset.md) ·
  [0099](../adr/0099-grafana-branding-within-oss-limits.md) ·
  [0100](../adr/0100-image-generation-on-the-gpu-fleet.md) ·
  [0101](../adr/0101-load-gate-before-federation-no-exceptions.md)
- Pattern: [`../patterns/self-hosted-model-serving.md`](../patterns/self-hosted-model-serving.md)
- Inference knowledge, runbooks and benchmark reports: the **`inference-ops`** repo
