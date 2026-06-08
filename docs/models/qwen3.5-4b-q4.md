# Qwen3.5-4B Q4 (llama.cpp) — deployment paper

> One of three self-hosted-model papers. Shared mechanics: the
> **[pattern guide](../self-hosted-model-serving.md)**. Siblings:
> [Qwen3-4B (shipped)](./qwen3-4b.md) · [Qwen3.5-4B vLLM/BF16](./qwen3.5-4b.md).

| | |
|---|---|
| **Status** | 🟢 **BUILT & STAGED** (2026-06-08) — chart `charts/model-serving-qwen3-5` + gateway/app wiring are committed but **disabled** (`enabled: false`) behind the load-gate (§5); engine recorded in **[ADR-0032](../adr/0032-llama-cpp-engine-for-self-hosted-models.md)**. Cutover = flip the `enabled` flags (new on / qwen3-4b off) + release + repoint root. |
| **Engine** | **llama.cpp** (`llama-server`, OpenAI-compatible) — `ghcr.io/ggml-org/llama.cpp:server-cuda` |
| **Quant** | unsloth **`UD-Q4_K_XL`** GGUF (imatrix; ~2.7 GB) |
| **Chart** | NEW `charts/model-serving-qwen3-5` (copy of `charts/model-serving-qwen3-4b`) |
| **Gateway model-id** | `qwen3-5-4b-local` · backend `llama-local-01` (`prefix: /v1`) |
| **Edge host** | `qwen3-5-4b--poc.ssegning.com` |
| **Strategy** | **keep the old Qwen3-4B deployment disabled** (rollback) + stand up this **new parallel** one. One GPU ⇒ only one runs at a time. |

> **Why llama.cpp, not vLLM.** Qwen3.5's Gated-DeltaNet-MoE-VLM is new and vLLM's
> support is turbulent (no text-only class, multimodal-class "not supported"
> reports, transformers churn — see [the vLLM paper §3](./qwen3.5-4b.md#3-️-why-this-is-not-the-chosen-path--vllms-qwen35-support-is-turbulent)).
> llama.cpp **already runs this model** via reputable community GGUFs, with native
> API-key auth, friendly KV math, and no LMCache to skew. Trade-off: lower peak
> throughput/concurrency than vLLM — fine for this low-concurrency owned/cheap tier.

---

## 1. Model card delta & why it suits a 12 GB card

See the [vLLM paper §1](./qwen3.5-4b.md#1-model-card-delta-vs-qwen3-4b) for the full
delta. The short version: [`Qwen/Qwen3.5-4B`](https://huggingface.co/Qwen/Qwen3.5-4B)
(Feb 2026, Apache-2.0) is a **Gated DeltaNet + sparse-MoE** hybrid, natively
multimodal, 262k native context. **3-of-4 blocks are linear-attention** → KV barely
grows → long context (64k; test toward 128k+) is comfortable on the A2000. We run it
**text-only** (no `--mmproj`).

## 2. Why Q4_K_M + llama.cpp

`Q4_K_M` is a **GGUF k-quant (~4.8 bpw)** native to **llama.cpp**, *not* vLLM
(vLLM's GGUF loader is slow — ~93 vs ~741 tok/s vs Marlin-AWQ). On llama.cpp it's
the sweet spot: **~2.7 GB weights**, ~92–98 % of BF16 quality. Reputable GGUFs
already exist (meets the "no random artifacts" bar):

- **[`unsloth/Qwen3.5-4B-GGUF`](https://huggingface.co/unsloth/Qwen3.5-4B-GGUF)** —
  **`UD-Q4_K_XL`** (imatrix dynamic; higher accuracy + tool-calling fixes) — **chosen**.
- [`bartowski/Qwen_Qwen3.5-4B-GGUF`](https://huggingface.co/bartowski/Qwen_Qwen3.5-4B-GGUF)
  — plain `Q4_K_M` — alternative.

---

## 3. Decisions (LOCKED 2026-06-08)

- **Engine:** llama.cpp (`llama-server`). The [ADR-0030](../adr/0030-merge-model-and-proxy-into-one-statefulset-bjw.md)
  chart shape (bjw StatefulSet, RWX seed PVC, Ingress + cert-cloudflare,
  `homeCluster: true`, federation via `charts/ai-models`) **stays**; only the model
  engine changes.
- **Quant:** unsloth `UD-Q4_K_XL`.
- **No Caddy sidecar** — `llama-server` enforces the Bearer natively via
  `--api-key-file`; the 600 s long-generation timeout moves to the **Traefik Ingress
  + the Envoy BTP**.
- **Text-only** — no `--mmproj`, no image input at the gateway.
- **Keep + disable the old, stand up a new one** — not an in-place swap. Disable the
  `model-serving-qwen3-4b` app + `qwen3-4b-local` model (kept for rollback); create
  the new parallel deployment. Single GPU ⇒ enabling the new requires disabling the
  old (the cutover window).

---

## 4. Planned change-set

**NEW chart `charts/model-serving-qwen3-5`** — copy `charts/model-serving-qwen3-4b`
(the §14 "model #2" move), redesign the model container for llama.cpp:

- **Image** `ghcr.io/ggml-org/llama.cpp:server-cuda` (CUDA 12; **not**
  `server-cuda13` — it [fails on some GPUs](https://github.com/ggml-org/llama.cpp/issues/22561)).
  Pin a **recent** digest (GDN operators need a current build — §5 gate).
- **Args:** `--model /models/<file>.gguf`, `--host 0.0.0.0 --port 8080`, `-ngl 99`
  (all layers on GPU), `--ctx-size 65536` (test higher), `--jinja` (tool calling via
  the chat template — replaces vLLM's `--tool-call-parser`), `--alias qwen3-5-4b`,
  **`--api-key-file /etc/llama/api-key`**, optional `-fa` + `--metrics`.
- **Probes simplify** → `httpGet /health` (503 loading → 200 ready) for startup +
  readiness. The vLLM `/v2/health/ready` dance and the **8081-gRPC probe-port
  collision both disappear** (llama-server binds only 8080).
- **Drop all vLLM cruft:** `--kv-transfer-config`, `LMCACHE_*`, `--enforce-eager`,
  `--dtype`, the fp8-ban note, `--tool-call-parser=hermes`.
- **Single container** (no Caddy). Service targets the model `:8080` directly. ⚠️
  Verify Traefik doesn't cut long streams now that the Caddy `response_header_timeout`
  is gone (set Traefik timeout annotations / a `ServersTransport`; the Envoy BTP
  `timeout.requestTimeout` stays 600 s).

**Seed Job:** one GGUF file —
`hf download unsloth/Qwen3.5-4B-GGUF --include "*UD-Q4_K_XL*.gguf" --local-dir /models`
(~2.7 GB vs ~8 GB; confirm the exact filename). RWX PVC + ArgoCD Sync hook +
HF_TOKEN unchanged; PVC can shrink (10–15 Gi).

**`charts/ai-models/values.yaml`:** disable `vllm-local-01` + `qwen3-4b-local`
(keep YAML for rollback); add `llama-local-01` backend (**`prefix: /v1`**, host
`qwen3-5-4b--poc.ssegning.com`, APIKey) + `qwen3-5-4b-local` model
(`modelNameOverride: qwen3-5-4b` = the `--alias`; new `contextLength`; no image
input; `minBackends: 1`; ADR-0028 cost-recovery pricing re-checked — same €/h TCO,
lighter Q4_K_M).

**`charts/apps/values.yaml`:** disable the `model-serving-qwen3-4b` app (rollback);
add `model-serving-qwen3-5` (`homeCluster: true`, `path: charts/model-serving-qwen3-5`).
New DNS record `qwen3-5-4b--poc.ssegning.com` → home.

---

## 5. Gate & verification (before committing)

1. **GATE — prove it loads:** run a **recent** `server-cuda` against the GGUF on the
   A2000; confirm the **GDN operators are present** (older builds error on the new
   ops) and `/health` → 200. Cheapest: a throwaway pod. ⚠️ contends with the live
   Qwen3-4B on the 12 GB card → a short maintenance window.
2. **Prove the budget:** ~2.7 GB weights + KV at the target `--ctx-size` fit; settle
   the context number.
3. **Smoke test:** a completion, then **with `tools`** (`--jinja`), then the gateway
   path (JWT + `x-ai-eg-model`), then cost CEL non-zero.

## 6. Cost

Same hardware → same €/h TCO as Qwen3-4B (~€0.05/h serving; see
[that paper §6](./qwen3-4b.md#6-cost--hour-tco--catalog-price-erlangen-2026-adr-0028)).
Re-derive the per-token catalog price per ADR-0028 — lighter Q4_K_M may shift
throughput, so re-check `output/input/cachedInput Per1M` at cutover.
