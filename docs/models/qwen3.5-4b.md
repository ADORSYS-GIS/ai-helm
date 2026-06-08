# Qwen3.5-4B (vLLM / BF16) — deployment paper

> One of three self-hosted-model papers. Shared mechanics: the
> **[pattern guide](../self-hosted-model-serving.md)**. Siblings:
> [Qwen3-4B (shipped)](./qwen3-4b.md) · [Qwen3.5-4B Q4 (llama.cpp)](./qwen3.5-4b-q4.md).

| | |
|---|---|
| **Status** | 📋 **STUDIED — NOT chosen.** The full-precision vLLM alternative, kept documented. The maintainer chose the [llama.cpp Q4 path](./qwen3.5-4b-q4.md) instead (2026-06-08). |
| **Engine** | vLLM via `kserve/huggingfaceserver` + LMCache (same stack as Qwen3-4B) |
| **Quant** | BF16 (official `Qwen/Qwen3.5-4B` weights, ~8 GB) |
| **When you'd pick this** | if you need **full-precision** quality, or want to later enable **vision** (the GGUF/llama.cpp path is text-only) — *and* vLLM's Qwen3.5 support has stabilised (§3) |

This paper exists so the full-precision option is on record with its real risks. If
the Q4/llama.cpp path proves unsatisfactory (quality, or a need for vision), this is
the fallback — but only once §3's blockers clear.

---

## 1. Model card delta vs. Qwen3-4B

[`Qwen/Qwen3.5-4B`](https://huggingface.co/Qwen/Qwen3.5-4B) (Feb 2026, Apache-2.0):

| | Qwen3-4B | **Qwen3.5-4B** |
|---|---|---|
| Attention | full softmax, GQA | **Gated DeltaNet + Gated Attention hybrid** (`8 × (3 × DeltaNet→FFN → 1 × Attn→FFN)`) |
| Dense / MoE | dense | **sparse MoE** |
| Modality | text-only | **multimodal VLM** (early-fusion; no separate text-only 4B checkpoint) |
| Native context | 32k | **262,144** (→ ~1.01M YaRN) |

The win on our hardware: **3-of-4 blocks are linear-attention (DeltaNet)** → KV
barely grows with context → the 16k wall that capped Qwen3-4B largely disappears,
so **64k+ context is realistic even at BF16** (~8 GB weights on the 12 GB A2000).
MoE adds no VRAM headroom cost (all experts resident, ~same 8 GB for a 4B-total).

"Text-only" = serve the VLM and don't send images (the vision tower still loads;
small for 4B).

---

## 2. The BF16 / vLLM design (if built)

Same chart pattern as Qwen3-4B ([guide](../self-hosted-model-serving.md)); the
deltas:

- **Image:** a Qwen3.5-capable `kserve/huggingfaceserver` — candidates `latest-gpu`
  (2026-06-03), `v0.19.0-rc0-gpu` (2026-05-27); fallback `v0.18.0-gpu` (vLLM 0.19.0).
  Pin after the §3 load test.
- **Quant:** **BF16** is the trustworthy launch. On Ampere there's **no FP8** (the
  vLLM recipe's recommended efficiency path is unavailable) and **no official
  AWQ/GPTQ** for Qwen3.5-4B — so a vLLM 4-bit would need a non-vetted community AWQ
  or the slow GGUF loader (which is why the [Q4 path](./qwen3.5-4b-q4.md) uses
  llama.cpp instead).
- **Args:** raise `--max-model-len` (target 64k+; KV is cheap with GDN), keep
  `--dtype=float16` / `--enforce-eager`; re-confirm the tool-call parser for the 3.5
  family; **no** `--kv-cache-dtype=fp8`.
- **⚠️ Disable LMCache.** The newer vLLM re-opens the `get_kv_events` skew, *and*
  LMCache's KV offload assumes standard attention — DeltaNet's recurrent state may
  not offload the same way (unproven). Launch with `--kv-transfer-config` + the
  `LMCACHE_*` env removed; re-introduce only if verified.
- **Gateway:** backend `prefix: /openai/v1` (huggingfaceserver), `qwen3-5-4b-local`
  model, no image input, re-derive ADR-0028 pricing.
- Caddy auth-proxy **stays** here (huggingfaceserver ignores `VLLM_API_KEY`, the
  Qwen3-4B trap applies).

---

## 3. ⚠️ Why this is NOT the chosen path — vLLM's Qwen3.5 support is turbulent

A capable image exists (it's **not** "too old"), but support maturity is the risk:

- vLLM's Qwen3.5 support **churned** — it broke on the 0.18.0 bump
  ([#37749](https://github.com/vllm-project/vllm/issues/37749)), (re)stabilised
  around 0.19.0.
- The **multimodal** classes (`Qwen3_5MoeForConditionalGeneration` /
  `Qwen3_5ForConditionalGeneration`) drew "not supported for now" reports
  ([#35344](https://github.com/vllm-project/vllm/issues/35344),
  [#35391](https://github.com/vllm-project/vllm/issues/35391)).
- **No text-only `Qwen3_5ForCausalLM` class** — "text-only" means loading the full
  multimodal model, contingent on that class loading on the chosen image.
- Needs a **bleeding-edge `transformers`** (~5.3.0.dev0).

**Gate if revived:** launch a candidate image against `Qwen/Qwen3.5-4B` on the A2000
and confirm the multimodal/GDN class loads cleanly *before* any chart work. The
[llama.cpp Q4 path](./qwen3.5-4b-q4.md) was chosen precisely because it sidesteps
all of this (the community GGUFs already run the model today).
