# Plan: Replace Qwen2.5-3B-Instruct-AWQ with Qwen3.5-2B (vLLM)

> **Objective:** fully disable `Qwen/Qwen2.5-3B-Instruct-AWQ` (the fleet's
> coding model) and replace it with
> [`Qwen/Qwen3.5-2B`](https://huggingface.co/Qwen/Qwen3.5-2B), served by
> **vLLM** on the fleet GPU (RTX 4000 SFF Ada, 20 GiB).
>
> **Status:** proposed plan · **Date:** 2026-08-10 · **Branch:**
> `feat/qwen3-5-2b-replacing-qwen25-3b-awq`

---

## 1. Context

- `qwen25-3b-awq` is currently the fleet's coding model
  (`charts/inference/values.yaml` + `charts/ai-models/values.yaml`), served by
  vLLM in AWQ INT4 with LMCache.
- It is replaced by **Qwen3.5-2B**, a newer, more capable model (multimodal,
  262K native context, high-efficiency hybrid architecture), Apache-2.0.
- Fleet rule: **one GPU card = one model** (2 cards, 2 models). Disabling
  `qwen25-3b-awq` frees the card for `qwen3-5-2b`.

### 1.1 Already done on this branch (full disable)

| File | Change |
|---|---|
| `charts/inference/values.yaml` | `qwen25-3b-awq.enabled: false` (rollback surface kept, repo convention) |
| `charts/ai-models/values.yaml` | `qwen25-3b-awq-local.enabled: false` + **`qwen25-3b-awq-local` backend removed** (backends of disabled models are removed — `check-model-catalogs.sh`) |

Verified: `./tools/check-model-catalogs.sh` → OK (1 served, 1 federated);
`helm lint --strict` + `helm template --dry-run` on both charts → OK.

---

## 2. Qwen3.5-2B — key facts

| Property | Value |
|---|---|
| Type | **Multimodal causal LM** (vision + text) — `image-text-to-text` |
| Parameters | 2B (hidden 2048, 24 layers) |
| Architecture | **Hybrid: Gated DeltaNet (linear attention) + Gated Attention + MoE FFN** — near-constant KV memory, high efficiency |
| Native context | **262,144 tokens** |
| License | Apache-2.0 |
| Thinking mode | Non-thinking by default; thinking via `enable_thinking` (no `/think` soft-switch) |
| Tool calling | Yes — recommended parser: `qwen3_coder` |
| MTP (Multi-Token Prediction) | Yes — `qwen3_next_mtp` (vLLM) |
| Serving prerequisite | **vLLM from the `main`/nightly branch** (not a stable release) |
| Weights | ~2B params in BF16 ≈ 4–5 GiB |

⚠️ **Qwen3.5-2B is multimodal**: it loads a vision encoder. Two options at
deployment (see §4.11): keep multimodality (default) or drop it with
`--language-model-only` to free VRAM.

---

## 3. Why vLLM?

vLLM is the chosen engine for this model for precise reasons:

1. **Official support.** The Qwen3.5 model card documents vLLM as a reference
   engine (`vllm serve Qwen/Qwen3.5-2B`), with dedicated recipes (tool calling,
   MTP, text-only).
2. **Hybrid architecture.** Linear attention (Gated DeltaNet) gives near-constant
   KV memory: vLLM can serve very long windows (up to 262K) on a single 20 GiB
   card — exactly this model's use case.
3. **Already the fleet's infrastructure.** The `vllm` profile of the `inference`
   chart (image `lmcache/vllm-openai`, `--max-model-len`, `--max-num-seqs`,
   `--kv-cache-dtype`, tool calling, LMCache) is proven — it is the engine
   `qwen25-3b-awq` used.
4. **OpenAI-compatible API.** Native `/v1/chat/completions` → federation via the
   Envoy AI Gateway without a sidecar (ADR-0095).
5. **Throughput.** vLLM is built for high concurrency (continuous batching,
   CUDA graphs) — relevant for a multi-user coding model.

> ⚠️ **Constraint #1 (blocking, to verify):** Qwen3.5 requires vLLM from the
> `main` branch. The current profile image is
> `lmcache/vllm-openai:nightly-2026-05-01` (verified on `hetzner-k8s-gpu-1`).
> The model shipped in February 2026, so this nightly **might** support it, but
> that **must be proven** with a real `import vllm` + ModelRegistry check for
> the `Qwen3_5*` architecture, on the actual card — the repo's hard-won lesson
> (CUDA 13 incident, §`engines.vllm` of `charts/inference/values.yaml`). If the
> image does not support Qwen3.5, bump to a newer nightly (or a matched LMCache
> image) and re-verify.

---

## 4. Hyperparameters to initialize — detailed explanation

### 4.1 The `charts/inference/values.yaml` entry (what runs the model)

```yaml
qwen3-5-2b:
  enabled: true
  engine: vllm
  weights:
    hfRepo: Qwen/Qwen3.5-2B
    revision: <pinned sha>          # curl -s https://huggingface.co/api/models/Qwen/Qwen3.5-2B | jq -r .sha
    sizeGi: 10
  serving:
    contextSize: 131072              # → --max-model-len 131072 (128k initial — see row 5)
    parallel: 4                      # → --max-num-seqs 4
    dtype: bfloat16                  # → --dtype bfloat16
    toolCallParser: qwen3_coder      # → --enable-auto-tool-choice --tool-call-parser qwen3_coder
    kvCacheDtype: auto               # → --kv-cache-dtype auto
    reasoning: "off"                 # → --default-chat-template-kwargs {"enable_thinking": false}
    # extraArgs: ["--language-model-only"]   # optional — see §4.11
  lmcache:
    enabled: false                   # OFF initially — see §4.10
  resources:
    cpuRequest: "2"
    cpuLimit: "8"
    memoryRequest: 8Gi
    memoryLimit: 16Gi
```

### Explanation of each hyperparameter

| # | Chart key | vLLM flag | Role | Initial value & why |
|---|---|---|---|---|
| 1 | `engine: vllm` | — | Selects the engine profile (image, args, healthcheck) | `vllm` — the only engine supporting Qwen3.5 (see §3) |
| 2 | `weights.hfRepo` | — | HuggingFace repo of the weights | `Qwen/Qwen3.5-2B` — the official repo |
| 3 | `weights.revision` | — | Pinned commit SHA of the weights | Full SHA, **never** `main`: weights are mutable on the Hub; a SHA means the bytes you measured are the bytes you serve, and the seed Job re-seeds if the SHA changes |
| 4 | `weights.sizeGi` | — | Longhorn RWX PVC size | `10` GiB — ~4–5 GiB of BF16 weights + headroom (convention: comfortably above the file) |
| 5 | `serving.contextSize` | `--max-model-len` | **Maximum context window** (prompt + completion) per request. vLLM does not split it across slots: it IS the per-request window | `131072` (128k) initially — **decision from the review** (PR #970, benie-joy-possi): the fleet had already concluded on 128k for a GDN linear-attention model (`qwen3-5-4b-local` precedent: *"GDN linear-attn → KV cheap; ~8.5GB of 12GB"*), and 32768 caused a prompt-too-long error loop for coding workloads. Native is 262,144; the DeltaNet architecture makes KV nearly free, so **256k (262144) is the stretch goal** after the load-gate VRAM measurement (see §6.2) |
| 6 | `serving.parallel` | `--max-num-seqs` | **Maximum number of sequences processed concurrently** (continuous batching) | `4` initially — same as the predecessor. A 2B is light: raise toward 8–16 after measurement if VRAM allows |
| 7 | `serving.dtype` | `--dtype` | **Precision of weights and activations** | `bfloat16` — the model's native dtype (F32/BF16 on the card). No quantization needed: 2B in BF16 fits easily on 20 GiB |
| 8 | `serving.toolCallParser` | `--enable-auto-tool-choice` + `--tool-call-parser` | **Tool calling**: enables automatic tool choice and the parser for the tool-call format | `qwen3_coder` — the parser Qwen recommends for Qwen3.5 (the predecessor used `hermes`; Qwen3.5 has its own format) |
| 9 | `serving.kvCacheDtype` | `--kv-cache-dtype` | **KV cache precision** (the memory attention reads) | `auto` (16-bit) initially — the hybrid architecture (DeltaNet + Gated Attention) is **new**: the fleet's fp8_e4m3 is unverified on it. Measure first, then try `fp8_e4m3` (÷2 KV) at the load gate |
| 10 | `serving.reasoning` | `--default-chat-template-kwargs {"enable_thinking": false}` | **Thinking mode default at the server** | `"off"` — Qwen3.5 is non-thinking by default; clients opt in per request (`enable_thinking: true`). Consistent with the fleet convention (openmythos-27b, qwen3-8b-fast): the catalog does not advertise `reasoning` |
| 11 | `serving.gpuMemoryUtilization` (default 0.90) | `--gpu-memory-utilization` | **Fraction of VRAM vLLM may use** for weights + KV cache | `0.90` (chart default) — leaves 10% for the CUDA runtime / graphs. Adjust if the load gate shows headroom |
| 12 | `serving.extraArgs` | (extra flags) | vLLM flags passed verbatim | Optional: `--language-model-only` (drop the vision encoder, §4.11) and/or `--speculative-config '{"method":"qwen3_next_mtp","num_speculative_tokens":2}'` (MTP, §6.6) |
| 13 | `lmcache.enabled` | `--kv-transfer-config` (LMCacheConnectorV1) | **KV cache offload to host RAM** for prefix reuse | `false` initially — LMCache serializes KV tensors as stored on the GPU; with the hybrid architecture (DeltaNet layers without classic KV), compatibility is **unverified**. Enable only after measurement (and then `kvCacheDtype` must stay `auto` — ADR-0118) |
| 14 | `resources.cpuRequest/cpuLimit` | — | Pod CPU | `2` / `8` — same as the predecessor |
| 15 | `resources.memoryRequest/memoryLimit` | — | Pod RAM | `8Gi` / `16Gi` — same as the predecessor; without LMCache, no need to exceed `LMCACHE_MAX_LOCAL_CPU_SIZE` |

### 4.2 The `charts/ai-models/values.yaml` entry (federation — AFTER the load gate)

Added **only after measurement** (ADR-0101: a model must be measured before any
user can route to it):

```yaml
# backends:
qwen3-5-2b-local:
  schema: OpenAI
  prefix: "/v1"
  fqdn:
    hostname: qwen3-5-2b.inference.svc.cluster.local
    port: 8080
  securityType: APIKey
  resourceName: qwen3-5-2b-local-svc
  secretRef:
    name: qwen3-5-2b-api-key
  externalSecret:
    key: ai/camer/digital/prod/env
    property: vllm_local_api_key

# models:
qwen3-5-2b-local:
  enabled: true
  kind: text                      # VLMs are catalogued `kind: text` (qwen3-vl-4b)
  minBackends: 1                  # one GPU card, one backend, by design
  timeout:
    requestTimeout: 600s
    connectionIdleTimeout: 1h
  info:
    displayName: "Qwen3.5-2B (self-hosted)"
    contextLength: 131072          # 128k = vLLM --max-model-len
    maxOutputTokens: 8192
    supportedParameters: *spStandard   # non-thinking by default → no `reasoning` advertised
  pricing:
    strategy: weighted            # cost-recovery (ADR-0028), basis ADR-0104
    standard:
      inputPer1M: <derived from MEASURED tok/s>      # €0.2968/h ÷ 3600 ÷ tok/s × 3.45 × 1.09
      cachedInputPer1M: <same × 0.15>
      outputPer1M: <same × 1.0>
  backends:
    qwen3-5-2b-local:
      ref: qwen3-5-2b-local
      priority: 0
      modelNameOverride: "qwen3-5-2b"   # = vLLM --served-model-name
```

**Never a guessed price** (the 30B rule, revert #938): prices are derived from
the throughput measured at the load gate.

### 4.3 Sampling hyperparameters (client-side, recommended by Qwen)

These are not in the chart (the client passes them per request), but they are
documented here because Qwen explicitly recommends them for Qwen3.5:

| Mode | temperature | top_p | top_k | min_p | presence_penalty | repetition_penalty |
|---|---|---|---|---|---|---|
| Non-thinking, text | 1.0 | 1.00 | 20 | 0.0 | 2.0 | 1.0 |
| Non-thinking, vision | 0.7 | 0.80 | 20 | 0.0 | 1.5 | 1.0 |
| Thinking, text | 1.0 | 0.95 | 20 | 0.0 | 1.5 | 1.0 |
| Thinking, vision/precise coding | 0.6 | 0.95 | 20 | 0.0 | 0.0 | 1.0 |

- `temperature`: sampling randomness (1.0 = raw distribution).
- `top_p`: cumulative-probability nucleus (keep only tokens covering p).
- `top_k`: keep only the k most probable tokens.
- `min_p`: relative threshold (token < min_p × max probability → excluded).
- `presence_penalty`: penalizes tokens already present (0–2; reduces
  repetition, but too high → language mixing).
- `repetition_penalty`: penalizes direct repetition.
- `enable_thinking` (extra_body): enables thinking mode per request.

⚠️ **Qwen3.5-2B is more prone to thinking loops** than other Qwen3.5 models
(model card): in thinking mode, prefer streaming to detect and interrupt an
abnormal generation.

---

## 5. Complete deployment plan — step by step

### Step 0 — Pre-flight: verify the vLLM image supports Qwen3.5 (BLOCKING)

1. On `hetzner-k8s-gpu-1`, run a probe pod with the image
   `lmcache/vllm-openai:nightly-2026-05-01` (the current profile image).
2. Verify with a **real `import vllm`** (not just `torch.cuda.init()`):
   - `Qwen3_5*` architecture (or the exact class) present in the ModelRegistry;
   - `CUDA_OK` on the RTX 4000 SFF Ada.
3. If KO → bump the `engines.vllm` profile image to a newer nightly (or a
   matched LMCache image) and re-verify on the actual card.
   ⚠️ Always sort LMCache tags by **date**, never by version number (trap
   documented in `charts/inference/values.yaml`).

### Step 1 — Disable Qwen2.5-3B-Instruct-AWQ ✅ (done on this branch)

- `charts/inference/values.yaml`: `qwen25-3b-awq.enabled: false`
- `charts/ai-models/values.yaml`: `qwen25-3b-awq-local.enabled: false` +
  backend removed.
- Verified: `check-model-catalogs.sh` OK, `helm lint` + `helm template` OK.

### Step 2 — Add the `qwen3-5-2b` entry in `charts/inference/values.yaml`

- Copy the §4.1 block.
- Pin `revision`:
  `curl -s https://huggingface.co/api/models/Qwen/Qwen3.5-2B | jq -r .sha`
- Verify: `helm dep build charts/inference && helm lint charts/inference --strict
  && helm template chk charts/inference --dry-run > /dev/null`
  and `./tools/check-model-catalogs.sh` (the model is served but **not**
  federated → normal load-gating state, the script announces it as a `note:`).

### Step 3 — Seed the weights (ArgoCD sync-hook Job)

- The chart generates the `qwen3-5-2b-seed` Job (sync hook) that downloads
  `Qwen/Qwen3.5-2B` into the `qwen3-5-2b-weights` PVC (Longhorn RWX) via
  `hf download ... --local-dir /models/Qwen3.5-2B`.
- ArgoCD waits for the Job before deploying the StatefulSet (sync waves -2 → 1).
- Verify: `kubectl -n inference get job qwen3-5-2b-seed` → Completed;
  `kubectl -n inference get pvc qwen3-5-2b-weights` → Bound.

### Step 4 — Deploy + smoke test

- ArgoCD sync → StatefulSet `qwen3-5-2b` (containers `model` + optional
  sidecar), ClusterIP Service `qwen3-5-2b:8080`, CiliumNetworkPolicy,
  ServiceMonitor.
- Smoke test (port-forward or through the gateway):
  ```bash
  kubectl -n inference port-forward svc/qwen3-5-2b 8080:8080 &
  curl -s http://localhost:8080/v1/chat/completions \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $VLLM_LOCAL_API_KEY" \
    -d '{"model":"qwen3-5-2b","messages":[{"role":"user","content":"Say hello in 5 words."}],"max_tokens":64}'
  ```
- Also verify: `/v1/models` advertises `qwen3-5-2b`; `/metrics` responds;
  no ` thinking` leaking into `content` (reasoning off).

### Step 5 — Load gate: measure (ADR-0101) — condition for federation

Measure on the actual card, and record in `inference-ops`
`docs/benchmarks/` (immutable, dated):

1. **Throughput** (tok/s) — gate throughput, to derive prices (ADR-0104).
2. **Latency** — TTFT + TPOT, p50/p95.
3. **VRAM** — peak in MiB (60% budget ≈ 12,285 / 20,475 MiB).
4. **Quality** — fp8 gate: compare `kvCacheDtype: auto` vs `fp8_e4m3`
   (if fp8 passes, adopt it — ÷2 KV).
5. **Tool calling** — a real tool call via `qwen3_coder`.
6. **Vision** (if multimodality kept) — a real image via
   `/v1/chat/completions` with `image_url`.
7. **Window** — if VRAM allows, raise `contextSize` toward 262,144
   (the DeltaNet architecture makes KV nearly free) and `parallel` toward 8–16.

### Step 6 — Federate (AFTER the load gate)

- Add the `qwen3-5-2b-local` backend (§4.2) in `charts/ai-models/values.yaml`.
- Add the `qwen3-5-2b-local` model with **prices derived from the measured
  tok/s** (never an estimate).
- Verify: `./tools/check-model-catalogs.sh` → OK (2 served, 2 federated);
  `helm lint` + `helm template` on `charts/ai-models`.
- Verify `/v1/models` through the gateway: `qwen3-5-2b-local` advertised.

### Step 7 — Final verification + documentation

- `helm lint --strict` + `helm template --dry-run` on both charts.
- `./tools/check-model-catalogs.sh`.
- Update the docs (ADR if an architecture decision, `inference-ops`
  how-to/benchmark, this plan → status "executed").

---

## 6. Post-load-gate optimizations (in order)

| # | Optimization | Flag / key | Condition |
|---|---|---|---|
| 6.1 | fp8 KV cache | `kvCacheDtype: fp8_e4m3` | fp8 quality gate passed |
| 6.2 | 256k window (stretch) | `contextSize: 262144` | measured VRAM OK at 128k (DeltaNet architecture) |
| 6.3 | More concurrency | `parallel: 8` → `16` | measured VRAM + latency OK |
| 6.4 | LMCache | `lmcache.enabled: true` | compatibility verified with the hybrid architecture + `kvCacheDtype: auto` (ADR-0118) |
| 6.5 | MTP (speculative decoding) | `extraArgs: ["--speculative-config", "{\"method\":\"qwen3_next_mtp\",\"num_speculative_tokens\":2}"]` | vLLM nightly supports it; measure the real gain |
| 6.6 | Text-only | `extraArgs: ["--language-model-only"]` | if multimodality is unused — frees the vision encoder's VRAM |

---

## 7. Risks & mitigations

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Current vLLM image does not support Qwen3.5 | Medium | Blocking | Step 0 (probe `import vllm` on the actual card) before any merge; bump the nightly if needed |
| Thinking loops (Qwen3.5-2B) | Medium | UX degradation | `reasoning: off` at the server; streaming recommended client-side |
| fp8 KV unverified on the hybrid architecture | High | Quality/errors | `kvCacheDtype: auto` initially; quality gate before adopting fp8 |
| LMCache unverified on DeltaNet | High | Errors/OOM | `lmcache.enabled: false` initially; verify before enabling |
| Federated prices based on an estimate | Medium | Wrong billing | 30B rule: prices derived from measured tok/s, never guessed |
| 3rd enabled model → insufficient GPU | Low | Pod Pending | Only one model enabled at a time (qwen25-3b-awq disabled first) |

---

## 8. Rollback

1. `git revert` the federation commit (ADR-0055: a merge to `main` is a live
   deploy; rollback = revert).
2. Re-enable `qwen25-3b-awq` (`enabled: true` in both charts) + restore its
   backend — the disabled entries are kept as a rollback surface.
3. ArgoCD re-syncs; the `qwen25-3b-awq-weights` PVC is retained
   (reclaimPolicy: Retain).

---

## 9. Verification (command summary)

```bash
# Charts
helm dep build charts/inference && helm dep build charts/ai-models
helm lint charts/inference --strict && helm lint charts/ai-models --strict
helm template chk charts/inference --dry-run > /dev/null
helm template chk charts/ai-models --dry-run > /dev/null
./tools/check-model-catalogs.sh

# Cluster (after ArgoCD sync)
kubectl -n inference get job qwen3-5-2b-seed        # Completed
kubectl -n inference get pvc qwen3-5-2b-weights     # Bound
kubectl -n inference get pods -l app=qwen3-5-2b     # Running
kubectl -n inference get svc qwen3-5-2b             # ClusterIP 8080
kubectl -n inference port-forward svc/qwen3-5-2b 8080:8080 &
curl -s http://localhost:8080/v1/models             # advertises qwen3-5-2b

# camerdigital (after federation)
curl -s https://api.ai.camer.digital/v1/models | jq -r '.data[].id' | grep qwen3-5-2b
```