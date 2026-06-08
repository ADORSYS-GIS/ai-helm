# Qwen3.5-4B Q4 (llama.cpp) — deployment paper

> One of three self-hosted-model papers. Shared mechanics: the
> **[pattern guide](../self-hosted-model-serving.md)**. Siblings:
> [Qwen3-4B (vLLM, standby)](./qwen3-4b.md) · [Qwen3.5-4B vLLM/BF16](./qwen3.5-4b.md).

| | |
|---|---|
| **Status** | 🟢 **LIVE & serving (2026-06-08)** — the active self-hosted model. Engine recorded in **[ADR-0032](../adr/0032-llama-cpp-engine-for-self-hosted-models.md)**; released in `release-2026.06.08-v04`. Qwen3-4B is now disabled/standby (rollback). |
| **Engine** | **llama.cpp** (`llama-server`, OpenAI-compatible) — `ghcr.io/ggml-org/llama.cpp:server-cuda` (CUDA 12) |
| **Quant** | unsloth **`UD-Q4_K_XL`** GGUF (imatrix; `Qwen3.5-4B-UD-Q4_K_XL.gguf`, ~2.7 GB) |
| **Chart** | `charts/model-serving-qwen3-5` |
| **Gateway model-id** | `qwen3-5-4b-local` · backend `llama-local-01` (`prefix: /v1`) |
| **Edge host** | `qwen3-5-4b--poc.ssegning.com` |
| **Measured** | **~52 tok/s decode** single-stream · **~1.3k tok/s prefill** · **4 concurrent slots** · **64k context** (real 35k-token prompts served) — see §6 |

> **Why llama.cpp, not vLLM.** Qwen3.5's Gated-DeltaNet-MoE-VLM is new and vLLM's
> support is turbulent (no text-only class, multimodal-class "not supported" reports,
> transformers churn — see [the vLLM paper §3](./qwen3.5-4b.md#3-️-why-this-is-not-the-chosen-path--vllms-qwen35-support-is-turbulent)).
> llama.cpp **already runs this model** via reputable community GGUFs, with native
> API-key auth, friendly KV math, and no LMCache to skew.

---

## 1. Model card delta & why it suits a 12 GB card

See the [vLLM paper §1](./qwen3.5-4b.md#1-model-card-delta-vs-qwen3-4b) for the full
delta. The short version: [`Qwen/Qwen3.5-4B`](https://huggingface.co/Qwen/Qwen3.5-4B)
(Feb 2026, Apache-2.0) is a **Gated DeltaNet + sparse-MoE** hybrid, natively
multimodal, 262k native context. **3-of-4 blocks are linear-attention** → KV barely
grows → long context is cheap on the A2000 (we run **64k**; the model trains to 262k).
We serve it **text-only** (no `--mmproj`).

## 2. Why Q4_K_M-class + llama.cpp

`Q4_K_M` is a **GGUF k-quant (~4.8 bpw)** native to **llama.cpp**, *not* vLLM (vLLM's
GGUF loader is slow — ~93 vs ~741 tok/s vs Marlin-AWQ). On llama.cpp it's the sweet
spot: **~2.7 GB weights**, ~92–98 % of BF16 quality. We use unsloth's imatrix
**`UD-Q4_K_XL`** (higher accuracy + tool-calling fixes than plain Q4_K_M);
[`bartowski/Qwen_Qwen3.5-4B-GGUF`](https://huggingface.co/bartowski/Qwen_Qwen3.5-4B-GGUF)
plain `Q4_K_M` is the alternative.

---

## 3. Decisions (LOCKED 2026-06-08)

- **Engine:** llama.cpp (`llama-server`). The [ADR-0030](../adr/0030-merge-model-and-proxy-into-one-statefulset-bjw.md)
  chart shape (bjw StatefulSet, RWX seed PVC, Ingress + cert-cloudflare,
  `homeCluster: true`, federation via `charts/ai-models`) **stays**; only the engine changes.
- **Quant:** unsloth `UD-Q4_K_XL`. **Text-only** (no `--mmproj`).
- **No Caddy sidecar** — `llama-server` enforces the Bearer natively via `--api-key-file`;
  the long-generation timeout moves to the **Traefik Ingress + the Envoy BTP**.
- **Swap, not parallel** — one GPU ⇒ one model. Qwen3-4B kept disabled for instant rollback.

---

## 4. As built (`charts/model-serving-qwen3-5`)

A copy of `charts/model-serving-qwen3-4b` with the model container redesigned for llama.cpp:

- **Image** `ghcr.io/ggml-org/llama.cpp:server-cuda` (CUDA 12; **not** `server-cuda13`
  — [fails on some GPUs](https://github.com/ggml-org/llama.cpp/issues/22561)).
- **Args:** `--model /models/Qwen3.5-4B-GGUF/model.gguf`, `--alias qwen3-5-4b`,
  `--host 0.0.0.0 --port 8080`, `-ngl 99` (all layers on GPU), `--ctx-size 65536`,
  `--jinja` (tool calling via the chat template), `--api-key-file /etc/llama/api_key`
  (native Bearer auth), `--metrics`. `n_parallel` auto-resolves to **4** (`kv_unified`).
- **Single container, no Caddy.** Service → model `:8080` directly. Probes `httpGet /health`
  (503 loading → 200 ready) — no `/v2/health/ready` dance, no `:8081` gRPC collision.
- **securityContext:** `runAsNonRoot` + `runAsUser: 1000` + `seccompProfile: RuntimeDefault`
  (converse-poc warns at restricted PSS) + drop ALL caps. Verified the image runs as 1000.
- **Seed Job:** `hf download unsloth/Qwen3.5-4B-GGUF --include "*UD-Q4_K_XL*.gguf"` into the
  RWX PVC, then symlinks the file → a stable `model.gguf` (decoupled from the exact filename).
- **Gateway** (`charts/ai-models`): backend `llama-local-01` (`prefix: /v1`, host
  `qwen3-5-4b--poc.ssegning.com`, APIKey) + model `qwen3-5-4b-local` (`modelNameOverride:
  qwen3-5-4b`, `contextLength: 65536`, text-only, `minBackends: 1`, ADR-0028 pricing).
- **App** (`charts/apps`): `model-serving-qwen3-5` (`homeCluster: true`). The Qwen3-4B app +
  `qwen3-4b-local` model are `enabled: false` (kept for rollback).

> **Go-live note:** the live root `ai-apps-v2` tracks the branch `claude/magical-bohr-390242`
> (not yet a tag), so the cutover deployed by pushing `main`→that branch. Durable tag-repoint
> to `release-2026.06.08-v04` is the maintainer's pending step (same commit).

---

## 5. Verification (done — cutover 2026-06-08)

1. **Arch load-gate (non-disruptive):** a CPU `ghcr.io/ggml-org/llama.cpp:server` pod
   (`-hf unsloth/Qwen3.5-4B-GGUF --hf-file Qwen3.5-4B-UD-Q4_K_XL.gguf`) loaded the model
   cleanly (`model loaded`, `server is listening`, `n_ctx_train=262144`) — proving the build
   recognises Qwen3.5's Gated-DeltaNet arch *without* touching the live GPU. ✅
2. **GPU rollout:** `qwen3-5-4b-main-0` `1/1 Running`; `RTX A2000 12GB, 11811 MiB free` at
   boot; **text-only loads without mmproj**; `runAsUser:1000` works; `/health` → Ready. ✅
3. **End-to-end:** home Ingress + Certificate `READY`; Hetzner gateway `backend` +
   `aigatewayroute/qwen3-5-4b-local` `Accepted`; `/v1/models/info` catalog now lists
   `qwen3-5-4b-local` (qwen3-4b-local dropped); real traffic serving (§6). ✅

---

## 6. Capacity & performance (measured on the live A2000, 2026-06-08)

Numbers observed directly from `llama-server` slot timings under real production traffic
(not a synthetic benchmark):

| Metric | Measured | Notes |
|---|---|---|
| **Decode (generation)** | **~50–53 tok/s** single-stream | UD-Q4_K_XL on the A2000; steady out to 6k+ generated tokens |
| **Decode under load** | **~37 tok/s per slot** when ≥2 slots active | continuous batching shares the GPU — aggregate across slots is higher than single-stream |
| **Prefill (prompt eval)** | **~1.3–1.4k tok/s** | sustained even on a **35,728-token prompt** (processed in ~22 s) |
| **Concurrency** | **4 slots** (`n_parallel=4` auto, `kv_unified=true`) | up to 4 concurrent requests batched on one GPU |
| **Context** | **65,536** per sequence | real 35k-token prompts served live — 4× the Qwen3-4B 16k wall |
| **Prompt cache** | per-slot KV reuse (`context checkpoints`, ~50 MiB each) | idle-slot prompts saved/restored → multi-turn skips re-prefill |
| **VRAM** | ~2.7 GB weights + unified KV on 12 GB | ~9 GB headroom for the 4-slot 64k KV |
| **Quality** | UD-Q4_K_XL imatrix (~92–98 % of BF16) | — |

**What the PoC comfortably handles:** up to **4 concurrent interactive-dev streams**
(opencode / LibreChat — bursty, streaming, low duty cycle) at ~37–52 tok/s each, with
**long context now in-tier** (up to 64k — the old "route big context to SaaS" caveat is
largely lifted; 35k-token prompts prefill in ~22 s). **Still route to SaaS:** quality-critical
work, high-QPS / batch fan-out (>4 concurrent saturates the single GPU → per-stream tok/s
drops and the 5th request queues), and anything needing >64k context.

**vs Qwen3-4B (the prior vLLM build):** 4× the usable context (64k vs 16k), comparable
decode throughput (~52 vs ~30–50 tok/s), native 4-way batching, and a simpler stack (no
LMCache, no Caddy). The capacity win is **context + concurrency**, not raw single-stream speed.

**Headroom / next levers (none yet needed):** raise `--ctx-size` toward 128k (KV is cheap
with GDN; VRAM allows); raise `--parallel` past 4 for more concurrency (trades per-slot ctx
/ speed); a Prometheus benchmark via `--metrics` would turn these spot readings into tracked
SLOs (the model-side analogue of the gateway's `plans/artillery/` load test).

---

## 7. Cost (ADR-0028)

Same hardware → same €/h TCO as Qwen3-4B (~€0.05/h while serving; see
[that paper §6](./qwen3-4b.md#6-cost--hour-tco--catalog-price-erlangen-2026-adr-0028)).
The measured ~52 tok/s decode confirms the cost-recovery pricing basis, so the catalog
keeps the weighted **`$1.00 out / $0.15 in / $0.03 cached`** per 1M (re-tune if utilization
rises or `--parallel` changes the effective throughput).
