# GPU platform comparison — A2000 · 2×4070 · 5×V100 · Hetzner GEX44 / GEX131

|  |  |
|---|---|
| **Document type** | 🔬 **Research document** — investigative make-vs-buy analysis. **Advisory, not normative**: it informs a decision, it does not *make* one. A choice that acts on this should be recorded in an ADR (the pricing method already is — [ADR-0028](./adr/0028-owned-hardware-model-pricing.md)). |
| **Status** | Living draft — **two inputs still open** (V100 asking price; real per-developer token rate). Refresh when the Hetzner matrix, the eBay listing, the ENEO/German tariff, or the user base move. |
| **Date** | 2026-06-08 |
| **Author** | @stephane-segning, with Claude (Opus 4.8) |
| **Scope** | Hardware for the *next* self-hosted-model platform. The pattern for *how* we serve models lives in [`self-hosted-model-serving.md`](./self-hosted-model-serving.md); per-model papers in [`docs/models/`](./models/). |
| **Confidence** | Mixed — **measured** (live A2000), **vendor-published** (Hetzner/NVIDIA/ENEO specs & prices), and **first-principles estimates** (throughput, concurrency, RoI). Each table flags which. See [§0 Methodology](#0-methodology-sources--confidence). |

> **Read §0 first** for how the numbers were derived and how far to trust each one.
> This is a *research* document: the estimates are defensible and sourced, but the
> throughput/concurrency/RoI figures are models, not benchmarks — treat them as
> planning ranges and re-run with real data before committing budget.

## TL;DR verdict

| If you want… | Pick | Why |
|---|---|---|
| **The best €-RoI move for your dev + marketing users** | **Existing 2×4070 + GLM-4.7-Flash 30B-A3B** | Sunk capex, Cameroon power (~€47/mo), runs a **real coding/agent MoE** (24 GB, FP8). RoI-positive *even after maintenance* (+~$250/mo, §9.5). GEX44 can't even hold this model. |
| Keep the live small/multilingual tier at ~zero cost | **Local A2000 (keep)** | Already owned, 70 W, llama.cpp live ([ADR-0032](./adr/0032-llama-cpp-engine-for-self-hosted-models.md)), Qwen3.5-4B @ 128 K. |
| Managed **multimodal** small models (vision/audio) | **GEX44 — €184/mo** | Gemma 4 12B with images/audio, FP8, warrantied, **near-zero maintenance**. But capped below the 30B MoEs. |
| Owned **70B / 122B-MoE** *and* you have cheap DIY ops | **eBay 5×V100** *(conditional)* | Cheapest 70B on hardware+power — **but maintenance (§6.5) ~triples its TCO and flips RoI negative** unless ops stay near-DIY. Volta EOL, no FP8/FP4 → slow. |
| Managed frontier-ish 122B-MoE at scale, hands-off | **GEX131 — €889/mo** | 122B-MoE-FP4 fast, 256 K ctx, multimodal, **maintenance-free**. Best at ≥~80 users. |

> **Siting + maintenance matter (the two things we'd ignored).** The **5×V100** and
> the **2×4070** sit in a **Cameroon office** (ENEO **~€0.16/kWh**, ~½ the German
> €0.34). But cheap power is only half the story: **§6.5 maintenance** — cooling, a
> genset for load-shedding, ops on old cards, Volta EOL — is **the dominant owned-box
> cost** and is what flips the V100's verdict.

**Bottom line:** the standout for your **developers + marketing** is the **2×4070 you
already own, running GLM-4.7-Flash (30B-A3B)** — a genuine coding/agent model at €0
capex that stays RoI-positive after maintenance. The **A2000** keeps serving the live
small tier. **70B is now a conditional buy, not a slam-dunk:** the V100 is cheapest on
hardware+power, but **once maintenance is counted its fully-loaded 36-mo TCO ~triples
to ~€16 K and its RoI goes negative unless ops are near-DIY** (§9.5) — while the
rentals barely move because Hetzner absorbs hardware/power/cooling. So: **own the
small/mid tier (you already do), and treat 70B as DIY-V100-if-cheap-labour vs
managed-GEX131-if-scale.** Per-token, self-hosting still rarely beats *budget* SaaS —
the return is control/privacy/data-residency (not priced here).

---

## 0. Methodology, sources & confidence

This is a **research document**, so it states *how* every number was obtained and
*how far to trust it* — that provenance is the point, not just the conclusion.

**Approach.** Five candidate platforms were profiled along the axes that actually
decide a deployment — *what models fit* + their **context** and **capabilities**
(§3, named June-2026 models), *who serves them* (§4 backends), *how many users*
(§5), and *what it truly costs* — capex + electricity (§6), **maintenance/ops the
spreadsheets ignore** (§6.5), cost-recovery (§7), and **RoI/payback** (§9). Specs
and prices are from vendor primary sources; capability from model cards; fit from
VRAM/bandwidth/precision/KV math; throughput, maintenance and economics modelled
from first principles and anchored, where possible, to the live system.

**Data provenance & confidence — by claim type:**

| Claim type | Source | Confidence | Notes |
|---|---|---|---|
| A2000 throughput / concurrency / ctx | **Measured** on the live box ([`models/qwen3.5-4b-q4.md`](./models/qwen3.5-4b-q4.md) §6) | **High** | Real `llama-server` slot timings under production traffic. |
| Hetzner specs & prices (GEX44/GEX131) | Vendor pages (linked §1) | **High** | €184/€889/mo, hardware as published 2026-06. |
| GPU architecture / VRAM / bandwidth / FP8-FP4 | NVIDIA card data | **High** | A2000, RTX 4000 SFF Ada, RTX PRO 6000 Blackwell, V100, 4070. |
| eBay V100 server specs | Listing text (price **not** captured) | **Medium** | 5×V100 16GB confirmed; **asking price open** → §6 is parametric. |
| Cameroon ENEO tariff (~€0.16/kWh) | ENEO + GlobalPetrolPrices (linked §9/footer) | **Medium-High** | XAF pegged 655.957/€; tiered, frozen since 2012, +15% proposed for >220 kWh pros. |
| Throughput / concurrency for non-A2000 boxes | First-principles estimate (bandwidth + batching) | **Medium** | Order-of-magnitude planning figures, **not** benchmarks. |
| Model-fit (§3) | VRAM budgeting | **Medium-High** | Weights are firm; KV headroom is approximate. |
| RoI / payback (§9) | Cost-avoidance model on stated personas | **Low-Medium** | Swings hard on per-dev token volume (§9.4) — the dominant unknown. |
| SaaS comparator prices | Public budget-provider pricing (DeepInfra/Together class) | **Medium** | Move with the market; re-check before deciding. |
| Current model landscape (§3.1) | Web-verified **June 2026** (Qwen3.5, Gemma 4, GLM-4.7-Flash, DeepSeek-V4, Llama 4 releases) | **Medium-High** | Names/sizes from vendor + roundup sources; the field moves monthly. |
| Context windows (§3.4) | Model native ctx (vendor) + KV-budget estimate per box | **Medium** | Native ctx firm; *servable* ctx is approximate (KV math + the A2000 measurement). |
| Capabilities (§3.3) | Model cards | **High** | Modality/tools/reasoning are model facts; the box only gates multimodal-VRAM + ctx. |
| **Maintenance / ops costs (§6.5)** | First-principles estimate (labour h/mo + cooling + genset + failure + EOL) | **Low-Medium** | The softest numbers in the doc, yet **decisive for the 70B verdict** — they hinge on *your* labour rate and the office's power reliability. Treat as a frame, set your own. |

**Key assumptions** (the knobs that move conclusions): electricity is
**location-specific** (DE €0.34 vs CM €0.16/kWh — §1); FX **$1 ≈ €0.92**;
**730 h/mo**; 3-yr (26,280 h) amortization; chat needs **≥15 tok/s/stream**; **10 %**
duty cycle for "named users"; per-developer volume **~66 M tok/mo** (moderate).

**Open inputs that would sharpen this to hard numbers:** (1) the **V100 asking
price** (locks §6 TCO); (2) the **real per-developer token rate** or current SaaS
spend (locks §9 payback dates). Both are flagged inline where they bite.

**Limitations.** Throughput/concurrency/RoI are **models, not measurements** for
every box except the A2000. Maintenance/ops (cooling, UPS/generator, staff, hardware
risk) is **now estimated and decisive — §6.5**, having moved from "out of scope" once
it proved to flip the 70B verdict; treat those figures as a frame and plug in your
own. The model still **deliberately prices no control/privacy/data-residency value**,
which is often the real reason to
self-host. Treat conclusions as **directional**, and benchmark the shortlisted box
before purchase.

---

## 1. Scope & sources

Five candidates, one question: *which can serve which models, for how many
users, at what cost — and when does each pay for itself?*

| # | Candidate | Kind | Source |
|---|---|---|---|
| 1 | **Local RTX A2000 12GB** | Owned (Erlangen, Germany — home GPU) | Live in-cluster; [`models/qwen3.5-4b-q4.md`](./models/qwen3.5-4b-q4.md) §6 (measured) |
| 2 | **eBay 5× Tesla V100 16GB** | Owned — **installed in a Cameroon office** (refurb "Llama3 KI-Server", seller *biercologne*) | [ebay.de/itm/306748779023](https://www.ebay.de/itm/306748779023) — listing text only; **asking price not captured** |
| 3 | **Hetzner GEX44** | Rented (dedicated, Germany — power incl.) | [hetzner.com/dedicated-rootserver/gex44](https://www.hetzner.com/dedicated-rootserver/gex44/) |
| 4 | **Hetzner GEX131** | Rented (dedicated, Germany — power incl.) | [hetzner.com/pressroom/new-gex131](https://www.hetzner.com/pressroom/new-gex131/) |
| 5 | **Existing 2× RTX 4070 12GB** | Owned — **running in Cameroon now** (sunk capex) | Maintainer's current Cameroon box; specs from NVIDIA RTX 4070 card data |

> ⚠️ **Two open inputs.** (a) The eBay **asking price** was not retrievable (eBay
> blocks automated fetch); §6 is therefore parametric over €2,000 / €3,000 /
> €4,000 — drop the real number in to lock the table. (b) tok/s and user counts
> below are **engineering estimates** (order-of-magnitude), except the A2000 row,
> which is **measured** on the live box. Treat them as planning figures, not SLOs.

**Global assumptions** (used throughout, all from [ADR-0028](./adr/0028-owned-hardware-model-pricing.md) where applicable):
- **Electricity is location-specific** — this is the key siting input:
  - **Germany / Erlangen** — **€0.34/kWh** (the A2000, and ADR-0028's basis).
    GEX44 / GEX131 are Hetzner-rented with **power included** in the monthly fee.
  - **Cameroon / office (ENEO)** — **~€0.16/kWh** (~106 XAF; XAF pegged at
    **655.957/€**). This is where the **5×V100** and the **existing 2×4070** run →
    their electricity is billed here, at **~47 % of the German rate**. (ENEO LV
    non-residential tiers: 84 XAF ≤110 kWh, 92 XAF to 400, 99 XAF to 1000; a
    proposed **+15 %** targets pros over 220 kWh/mo. A 24/7 server lands in the
    top tier, so €0.16 is a fair-to-slightly-low planning rate; range €0.13–0.19.)
- **Electricity scope (the §6/§6.3 tables only): the grid bill.** The §6 *hardware*
  TCO and §6.3 power comparison are deliberately electricity-only. **Maintenance/ops
  — cooling, UPS / generator for load-shedding (diesel ≈ 3–5× grid), staff time,
  hardware risk — is NOT ignored**: it's estimated in **§6.5** and folded into the
  fully-loaded TCO (§8) and RoI (§9.5), where it flips the V100 verdict. (The
  maintainer's "operation is still on us" set the *electricity-only* scope for the
  power tables; §6.5 then prices the rest.)
- FX **$1 ≈ €0.92** (so €/h × 1.087 = $/h).
- **730 h/month**; 3-year amortization horizon = **26,280 h**.
- Interactive chat needs **≥ ~15 tok/s** per stream to feel live.
- "Concurrent active" = simultaneous in-flight generations under continuous
  batching. "Named users" assumes **~10 % duty cycle** (typical chat/dev usage).

---

## 2. Hardware, side by side

| | **Local A2000** | **eBay 5× V100 16GB** | **Hetzner GEX44** | **Hetzner GEX131** |
|---|---|---|---|---|
| GPU | 1× RTX A2000 12GB | 5× Tesla V100 16GB | 1× RTX 4000 SFF Ada 20GB | 1× RTX PRO 6000 Blackwell Max-Q 96GB |
| Architecture | Ampere (GA106) | **Volta (GV100), cc 7.0** | Ada Lovelace (AD104) | **Blackwell** |
| Total VRAM | 12 GB GDDR6 | **80 GB HBM2 (5×16, _not_ unified)** | 20 GB GDDR6 ECC | 96 GB GDDR7 ECC |
| Mem bandwidth | ~288 GB/s | **~900 GB/s _per card_** | 280 GB/s | **~1.79 TB/s** |
| Low-precision math | FP16/BF16, INT8 · **no FP8** | **FP16 only** (no BF16/TF32/FP8) | **FP8** + INT8 | **FP4 + FP8** + INT8 |
| GPU power | 70 W | ~250 W ea → **~1.25 kW GPUs** | 70 W | 300 W (Max-Q) |
| CPU | host (i7-14700KF, 28 thr) | server (dual-socket) | i5-13500 (6P+8E) | Xeon Gold 5412U (24c) |
| System RAM | host | **16 GB only** ⚠️ | 64 GB DDR4 | 256 GB DDR5 ECC reg |
| Storage | host disk | NVMe (256 GB–1 TB) | 2× 1.92 TB NVMe | 2× 960 GB NVMe |
| Price | **owned** (~€24/mo power @ 24/7) | **purchase price unknown** + power | **€184/mo** + €79 setup | **€889/mo**, no setup, IPv4 incl. |
| Warranty / lifecycle | yours | **none; Volta is EOL-track** | Hetzner-managed | Hetzner-managed |

**Reading the table:**
- The V100's **900 GB/s per card** is the headline — bandwidth drives decode
  speed, and per-card it **beats GEX44 (280 GB/s) but not GEX131 (1.79 TB/s)**. And
  it's split across 5 cards, the tensor cores are **first-gen FP16-only**, the **16 GB host
  RAM** will choke model loading / KV offload, and the **5-GPU count is awkward**
  for tensor parallelism (you want 2/4/8 → you effectively run TP=4 + 1 spare).
- **GEX131** trades raw per-card bandwidth peak for **96 GB on one die at
  1.79 TB/s** + **FP4** — no parallelism overhead, the whole model on one GPU.
- **GEX44** and the **A2000** are the low-power (70 W) small-model tier; GEX44's
  edge is **Ada FP8** + 20 GB.

---

## 3. Which models fit — deployability matrix (named models)

Re-done against the **actual June-2026 models** (not generic sizes), with **native
context** and **capabilities** alongside fit. ✅ comfortable · ⚠️ tight / degraded ·
❌ won't fit. Backend + quant in the cell. Weights are for the *served* quant; the
**servable context is KV-limited per box** (§3.4), usually well below native.

| Model (served quant, weights) | Native ctx | Capabilities | A2000 12 GB | 2×4070 24 GB | 5×V100 80 GB | GEX44 20 GB | GEX131 96 GB |
|---|---|---|---|---|---|---|---|
| **Qwen3.5-4B** Q4 (~2.7 GB) *(live)* | 262 K | text·tools·reason·multiling | ✅ llama.cpp | ✅ | ✅ ×5 | ✅ | ✅ |
| **Qwen3.5-9B** Q4 (~5.5 GB) | 256 K | text·tools·reason·multiling | ⚠️ short ctx | ✅ | ✅ ×5 | ✅ FP8 | ✅ |
| **Gemma 4 12B** Q4/FP8 (~8 GB) | ~128 K | **vision·audio**·tools·reason | ⚠️ tiny KV | ✅ | ✅ | ✅ FP8 | ✅ |
| **GLM-4.7-Flash 30B-A3B** Q4 (~17 GB) ⭐ | 200 K | **coding·agent**·tools·reason | ❌ | ✅ TP=2 | ✅ | ⚠️ no KV room | ✅ |
| **Qwen3.5-35B-A3B** Q4 (~19 GB) | 256 K | text·tools·reason·agent | ❌ | ⚠️ TP=2 tight | ✅ | ⚠️ no KV room | ✅ |
| **Gemma 4 31B** (dense) Q4 (~18 GB) | ~128 K | vision·audio·tools·reason | ❌ | ⚠️ TP=2 tight | ✅ | ⚠️ no KV room | ✅ |
| Dense **70B** Q4 (~40 GB) | 128 K | text·tools·reason | ❌ | ❌ | ✅ **llama.cpp 5-way** | ❌ | ✅ |
| **Qwen3.5-122B-A10B** Q4 (~61 GB) ⭐ | 256 K | text·tools·reason·agent·multiling | ❌ | ❌ | ⚠️ Q3/Q4 **llama.cpp 5-way**, slow | ❌ | ✅ **FP4 (~55 GB)** |
| **Qwen3.5-122B-A10B** FP8 (~122 GB) | 256 K | — | ❌ | ❌ | ❌ | ❌ | ⚠️ FP4 only |
| Frontier (397B-A17B, DeepSeek-V4, Llama 4) | 256 K–10 M | full | ❌ | ❌ | ❌ | ❌ | ❌ → SaaS |

**Headlines:**
- **A2000** — the live ≤9B-Q4 box (Qwen3.5-4B, 128 K ctx, llama.cpp). Not a MoE/70B machine.
- **2×4070** — now reaches the **30B-A3B coding MoEs** (GLM-4.7-Flash, Qwen3.5-35B-A3B)
  via TP=2, the single biggest capability jump for a €0 owned box. Caps below ~35B.
- **5×V100** — the only owned route to **dense-70B / 122B-MoE** (Q3/Q4), but Volta
  has no FP8/FP4/Marlin → it runs them *slowly* (§3.2). ~20–30 tok/s on 70B.
- **GEX44** — stuck at **dense ≤14B**: 20 GB can't hold a 30B-A3B MoE *with* KV, so a
  free 2×4070 runs a *better* coding model than this rental.
- **GEX131** — runs **everything up to 70B-Q8 / 122B-MoE-FP4** on one GPU, fast, no TP.

### 3.1 The models that actually matter today (June 2026)

The generic "8B/70B dense" rows above are the *shape* of the problem; the
**current** open models are mostly **sparse MoE**, which changes the hardware
calculus — and they're genuinely better than the 2025 dense models this comparison
was first sketched against. The standouts (all Apache-2.0 unless noted):

| Tier | Model (June 2026) | Params (active) | Fits best on | Why it matters |
|---|---|---|---|---|
| Edge / small | **Qwen3.5-4B** *(live)*, **Qwen3.5-9B**, **Gemma 4 E4B/12B** | 4–12B dense | **A2000 · 2×4070 · GEX44** | Qwen3.5-9B **matches GPT-OSS-120B** on several benches; Gemma 4 is natively multimodal (incl. audio). Last-gen "70B quality" now fits 12 GB. |
| Mid | **GLM-4.7-Flash** (30B-A3B MoE) ⭐, **Qwen3.5-35B-A3B** (MoE), **Gemma 4 26B-A4B** (MoE, ~14–16 GB Q4), **Qwen3.5-27B** / **Gemma 4 31B** (dense) | 26–35B (**~3–4B act.**) | **2×4070 (Q4) · GEX131 · V100** | The ~26–35B MoEs **decode like a 3–4B** but need their full size resident. **GLM-4.7-Flash (Zhipu, Jan 2026, 200K ctx) is built for local coding/agents and runs in 24 GB** → a near-perfect fit for the owned 2×4070 dev box. **Gemma 4 26B-A4B** is consumer-GPU-sized (Q4 ~14–16 GB) — also fits 2×4070/GEX44. |
| **Large MoE (the new sweet spot)** | **Qwen3.5-122B-A10B**, **GLM-5.1**, **Kimi K2.6** | 122B+ (**~10B act.**) | **GEX131 (96 GB)** · **5×V100 (80 GB, Q3/Q4)** | ⭐ Holds 122B in VRAM but computes only ~10B/token → **frontier quality at near-small-model decode speed.** This is exactly what 80–96 GB boxes are *for*. |
| Frontier (out of reach here) | **Qwen3.5-397B-A17B**, **DeepSeek-V4**, **Llama 4 Maverick** | 397B–1.6T | none of these (→ SaaS) | Beats GPT-5.2 on IFBench; needs multi-GPU-server VRAM. Route to SaaS. |

> **The reframing:** the most interesting 2026 models aren't dense 70B — they're
> **sparse MoE that decode far cheaper than their size.** Two bands matter here:
> **(a) ~30B-A3B MoE** (GLM-4.7-Flash, Qwen3.5-35B-A3B) — fit **24 GB at Q4**,
> decode like a 3B, and GLM-4.7-Flash is explicitly a **coding/agent** model → the
> **owned 2×4070 in Cameroon becomes a genuinely strong dev box for ~free**; and
> **(b) ~100–120B-A10B MoE** (Qwen3.5-122B, GLM-5.1, Kimi K2.6) — want **60–96 GB
> resident** but still decode cheaply, which plays *directly* to the **GEX131
> (96 GB)** and **5×V100 (80 GB)**. Meanwhile the new small dense models
> (Qwen3.5-9B, Gemma 4 12B) already rival last year's 70B on the A2000/2×4070. It
> does **not** help **GEX44** — 20 GB can't hold a 30B-A3B MoE with KV, so it's
> stuck at dense ≤14B while a €0 owned box runs the better 30B-A3B coding MoE.

### 3.2 Quantization — the lever behind every cell

Every "fits / doesn't" above is really a **quantization** decision: it sets both
the VRAM (so *what fits*) and which hardware can run it *fast*. The doc has used
Q4/Q8/FP8/FP4 throughout; here's the explicit map.

**Bits → size → quality (rule of thumb):**

| Format | ~bits/wt | 70B weights | 122B-MoE weights | Quality vs FP16 | Notes |
|---|---|---|---|---|---|
| FP16/BF16 | 16 | ~140 GB | ~244 GB | 100 % (baseline) | Training precision; rarely served at scale. |
| FP8 / INT8 | 8 | ~70 GB | ~122 GB | ~99–100 % | **Ada+/Blackwell native**; near-lossless. |
| Q8_0 (GGUF) | ~8.5 | ~75 GB | ~130 GB | ~99 % | llama.cpp; CPU/any-GPU. |
| **Q4 / AWQ / GPTQ (INT4)** | ~4–4.8 | **~40 GB** | **~61 GB** | **~97–99 %** (large) / ~93–97 % (small) | **The workhorse.** Marlin/AWQ kernels need Ampere+. |
| **FP4 / MXFP4** | ~4 | ~35 GB | ~55 GB | ~97–99 % | **Blackwell-native** (GEX131) — fast *and* small. |
| Q3/Q2 (GGUF) | 2–3 | ~28 GB | ~45 GB | noticeable loss | Only when you *must* squeeze (e.g. 122B-MoE on 80 GB V100). |

**The two rules that decide everything:**
1. **Lower bits ≈ proportionally less VRAM, with only small quality loss on big
   models** (a 70B at Q4 ≈ 97–99 % of FP16) — but **small models degrade more**
   under aggressive quant, so keep 4–9B at Q4_K_M/Q5+ or FP8, not Q3.
2. **Quant format is gated by GPU architecture** — this is *why* the same model is
   ✅ on one box and ⚠️ on another:

| GPU (box) | FP4 | FP8 | INT4 (AWQ/GPTQ, Marlin) | GGUF k-quant | Best quant path |
|---|---|---|---|---|---|
| **Volta — 5×V100** | ❌ | ❌ | ⚠️ slow (no Marlin) | ✅ | **GGUF Q4** (llama.cpp) or AWQ-INT4 on old vLLM kernels |
| **Ampere — A2000** | ❌ | ❌ | ✅ | ✅ | **GGUF Q4_K_XL** (live) / AWQ-INT4 |
| **Ada — 2×4070, GEX44** | ❌ | ✅ | ✅ | ✅ | **FP8** (native, near-lossless) or AWQ-INT4 |
| **Blackwell — GEX131** | ✅ | ✅ | ✅ | ✅ | **FP4** — fast *and* the smallest footprint |

> **Why this matters for the buy:** the **V100's lack of FP8/FP4 + no Marlin
> kernels** is its real software tax — it must lean on **GGUF/AWQ-INT4** and slower
> paths, so it serves 70B/122B-MoE but **slowly** (the "20–30 tok/s" figure). The
> **GEX131's FP4** is the opposite: it makes a 122B-MoE both **fit (~55 GB)** *and*
> run fast. The **Ada boxes' FP8** is what lets a 20–24 GB card punch above its
> VRAM. **Match the quant to the silicon** — a model's row in §3 flips ✅/⚠️ purely
> on whether the box has the kernel for the quant you need.

### 3.3 Capabilities enabled — what each box can actually *do* for users

Capability is mostly a **model** property, but the box **gates** three of them:
multimodality (the vision/audio projector needs extra VRAM), long context
(KV-limited, §3.4), and concurrency (§5). Mapped to the realistic top model per box:

| Box | Top model it runs well | Text | Vision | Audio | Tools / fn-call | Reasoning | Coding / agentic | Long ctx |
|---|---|---|---|---|---|---|---|---|
| **A2000** | Qwen3.5-4B | ✅ | ⚠️ (4B is MM; we serve text-only — VRAM) | ❌ | ✅ | ✅ | ⚠️ ok | ✅ 128 K |
| **2×4070** | **GLM-4.7-Flash 30B-A3B** | ✅ | ⚠️ (add Gemma 4 12B for vision) | ⚠️ | ✅ | ✅ | ✅ **strong** | ✅ ~64–128 K |
| **5×V100** | Qwen3.5-122B-A10B | ✅ | ⚠️ (VRAM ok, but slow) | ⚠️ | ✅ | ✅ **strong** | ✅ | ✅ ~128 K |
| **GEX44** | Qwen3.5-9B / Gemma 4 12B | ✅ | ✅ (Gemma 4) | ✅ (Gemma 4) | ✅ | ✅ | ⚠️ (no 30B MoE) | ✅ |
| **GEX131** | Qwen3.5-122B-A10B (FP4) | ✅ | ✅ | ✅ | ✅ | ✅ **strong** | ✅ **strong** | ✅ **256 K** |

- **Multimodal (vision + audio)** is a **Gemma 4** story — to give users image/audio,
  run Gemma 4 (12B fits everything from 2×4070 up; the A2000 can run 12B vision only
  by sacrificing context). Qwen3.5-4B is multimodal too but we serve it text-only to
  fit 12 GB.
- **Coding / agentic** (your developers' core need) is best served by **GLM-4.7-Flash
  30B-A3B** — which needs the **2×4070 or bigger**; GEX44 can't hold it.
- **Reasoning at frontier-ish quality** wants the **122B-A10B MoE** → GEX131 (fast) or
  V100 (slow). Everything below is "good", not "frontier".

### 3.4 Context windows — native vs what a box can actually serve

**Native context is a model property; servable context is a VRAM/KV property of the
box.** KV cache grows with tokens × layers × heads; it is the *second* claim on VRAM
after weights, and it's why a model's full native window is rarely servable:

| Box | Weights headroom for KV | Servable ctx (typical) | Lever to extend |
|---|---|---|---|
| **A2000 12 GB** | ~9 GB after Qwen3.5-4B Q4 | **128 K** *(measured; GDN linear-attn KV is cheap)* | `--cache-type-k/v q8_0` → 256 K |
| **2×4070 24 GB** | ~7 GB after GLM-4.7-Flash Q4 | **~64–128 K** | Q8 KV-cache, FP8 |
| **5×V100 80 GB** | ~19 GB after 122B-MoE Q4 — **only via llama.cpp layer-split across all 5 cards** (vLLM TP=4 = 64 GB → ~61 GB Q4 leaves ~no KV → not deployable that way) | **~128 K** (llama.cpp) | use llama.cpp, not TP=4; bandwidth-bound not KV-bound |
| **GEX44 20 GB** | ~9 GB after 14B Q4 | **~64–128 K** | FP8 KV (Ada) |
| **GEX131 96 GB** | ~35–40 GB after 122B-MoE FP4 | **~256 K (native)** | abundant — the only box that serves full native ctx of a big MoE |

> **Takeaways:** (1) **long context is cheap on the live A2000 *because* Qwen3.5 is a
> Gated-DeltaNet MoE** (3-of-4 blocks linear-attn → KV barely grows); a dense model
> the same size would hit a far lower ctx wall. (2) **prefill latency, not VRAM, is
> the practical ceiling** at very long ctx (a 128 K prompt at ~1.3 K tok/s ≈ 100 s to
> read). (3) Only **GEX131** can serve a big MoE at its **full 256 K native** window;
> the owned boxes trade ctx for fitting the weights.

### 3.5 Recommended deployment per box (the anchor)

Pinning a concrete target to each box turns the abstract tiers into a plan:

| Box | Deploy | Quant | Serves | For |
|---|---|---|---|---|
| **A2000** (live) | Qwen3.5-4B | GGUF Q4_K_XL | 128 K, 4 slots, ~52 tok/s | the live PoC / light dev + marketing |
| **2×4070** (owned, CM) | **GLM-4.7-Flash 30B-A3B** | GGUF/AWQ Q4 | ~64 K, ~40–60 tok/s | **developers' coding/agent model — €0 capex** |
| **5×V100** (owned, CM) | Qwen3.5-122B-A10B | GGUF Q4, **llama.cpp 5-way split** | ~128 K, ~30–50 tok/s | owned frontier-ish reasoning, budget |
| **GEX44** (rent) | Qwen3.5-9B / Gemma 4 12B | FP8 | ~128 K | managed small + multimodal |
| **GEX131** (rent) | Qwen3.5-122B-A10B | **FP4** | 256 K, fast | managed frontier-ish + multimodal, at scale |

---

## 4. Backend fit per platform

The gateway speaks OpenAI-compatible HTTP to whatever serves the model; the
backend choice is per-platform and per-architecture.

| Platform | Primary backend | FP8/FP4? | Notes |
|---|---|---|---|
| **A2000** (Ampere) | **llama.cpp** (`llama-server`, live) | no FP8 | GGUF Q4 + native `--api-key`; 128k ctx via cheap GDN-MoE KV. vLLM works but no FP8, KV-hungry. ([ADR-0032](./adr/0032-llama-cpp-engine-for-self-hosted-models.md)) |
| **5× V100** (Volta **cc 7.0**) | **llama.cpp** (primary) · Ollama · *(vLLM only if pinned to an old Volta build)* | **no** | ⚠️ **Current vLLM needs cc 7.5+ — it will not install/run on cc 7.0 V100.** So the dependable path is **llama.cpp**, which splits layers across **all 5 cards** (uses the full 80 GB; not vLLM TP=4's 64 GB) and runs GGUF Q4 well. No FlashAttn-2 / Marlin / FP8. vLLM/TP only on a pinned legacy release — don't assume current vLLM works here. |
| **GEX44** (Ada) | **vLLM / SGLang with FP8** | **FP8** | FP8 weights + FP8 KV cache stretches 20 GB a long way — the real value of this card. TGI/llama.cpp fine too. |
| **GEX131** (Blackwell) | **vLLM / SGLang with FP4 + FP8** | **FP4 + FP8** | Biggest models, highest throughput, single GPU (no TP). The natural serious-multi-tenant backend. |

---

## 5. How many users / clients — concurrency matrix (named models)

Estimates (A2000 row **measured**). Single-stream ≈ short context; aggregate assumes
continuous batching. **The MoE rule that drives these numbers:** decode speed tracks
**active** params, VRAM tracks **total**. So a 30B-A3B decodes ~like a 5–6B dense and
a 122B-A10B ~like a 15–20B dense — *fast for their size*, which is the whole point.

**Qwen3.5-4B — the current live model (A2000 = measured):**

| | A2000 *(measured)* | 2×4070 | 5×V100 | GEX44 | GEX131 |
|---|---|---|---|---|---|
| Single-stream | **~50–53 tok/s** | ~90–120 tok/s | ~100+/card | ~80–120 tok/s | ~200+ tok/s |
| Concurrent active | **4 slots** | ~30–50 | ~50–80 | ~30–50 | ~150+ |
| ~Named users (10 %) | ~30–60 | ~200–400 | ~400–600 | ~150–300 | ~1000+ |
| Prefill | **~1.3 K tok/s** | ~2.5 K | ~2 K/card | ~2 K | ~10 K+ |

**GLM-4.7-Flash 30B-A3B — the developers' coding/agent model (decodes like a ~6B):**

| | 2×4070 ⭐ | 5×V100 | GEX44 | GEX131 |
|---|---|---|---|---|
| Backend | vLLM-FP8/llama.cpp TP=2 | **llama.cpp 5-way** (not vLLM — cc7.0) | ❌ (no KV room) | vLLM FP8 |
| Single-stream | ~40–60 tok/s | ~50–70 tok/s | ❌ | ~120–180 tok/s |
| Concurrent active | ~10–20 | ~20–30 | ❌ | ~60–100 |
| ~Named users (10 %) | ~100–200 | ~200–300 | ❌ | ~600–1000 |

**Qwen3.5-122B-A10B — frontier-ish MoE (decodes like a ~15–20B):**

| | 5×V100 (llama.cpp 5-way, Q4) | GEX44 | GEX131 (FP4) |
|---|---|---|---|
| Single-stream | ~30–50 tok/s | ❌ | ~60–100 tok/s |
| Concurrent active | ~6–12 | ❌ | ~30–60 |
| ~Named users (10 %) | ~60–120 | ❌ | ~300–600 |

> A2000 figures from `llama-server` slot timings under real traffic
> ([`models/qwen3.5-4b-q4.md`](./models/qwen3.5-4b-q4.md) §6): ~52 tok/s decode,
> ~37 tok/s/slot under load, 4 concurrent slots, 128 K ctx (real 35 K-token prompts).
> **Why MoE looks so good here:** the 122B-A10B serves ~300–600 users on GEX131 at
> *near-30B quality* because only 10 B params are read per token — capacity you could
> never get from a dense 122B. The V100 runs the same model but ~½–⅓ the speed (no
> FP8/FP4/Marlin), so its user counts are lower despite the same VRAM.

---

## 6. TCO — 12 / 24 / 36 months (the procurement question)

Total **cash outlay** over the horizon (not amortized — what leaves your account).
Rented platforms: `setup + monthly × N`. Owned platforms: `purchase + power × N`.

### Monthly run-rate basis

| Platform | Capex (one-time) | Monthly run-rate | Notes |
|---|---|---|---|
| **A2000** | €0 (sunk) | **~€24/mo** @ 24/7 (95 W wall × €0.34, power-only) | Already owned; capex is gone. (§7 cost-recovery uses ADR-0028's amortized ~€37/mo, which *adds back* capex — a different, non-cash basis.) |
| **GEX44** | €79 setup | **€184/mo** | Power + IPv4 included. |
| **GEX131** | €0 | **€889/mo** | Power + IPv4 included. (Hetzner also quotes €1.4247/h on-demand.) |
| **5× V100** | **€P (unknown)** | **power only** — see bracket below | ⚠️ The box is in **Cameroon** (€0.16/kWh), **not** Germany — the tables just below use €0.34 for reference; the **real, Cameroon-rate numbers are in §6.3**, and they're roughly **half**. |

**V100 power is the swing factor**, not the purchase price:

| Load profile | Wall draw | €/mo @ €0.34/kWh |
|---|---|---|
| Idle-heavy (bursty PoC, GPUs mostly parked) | ~0.35 kW | **~€87/mo** |
| Typical always-on inference (planning midpoint) | ~0.60 kW | **~€149/mo** |
| Sustained 24/7 serving (full tilt) | ~1.50 kW | **~€372/mo** |

### TCO table (V100 at the **€250/mo** power planning midpoint — between "typical" and "sustained")

| Horizon | **GEX44** | **GEX131** | **V100 @ €2,000** | **V100 @ €3,000** | **V100 @ €4,000** |
|---|---|---|---|---|---|
| **12 mo** | €2,287 | €10,668 | €5,000 | €6,000 | €7,000 |
| **24 mo** | €4,495 | €21,336 | €8,000 | €9,000 | €10,000 |
| **36 mo** | €6,703 | €32,004 | €11,000 | €12,000 | €13,000 |

> Formulas: GEX44 `= 79 + 184·N` · GEX131 `= 889·N` · V100 `= P + 250·N` (N in
> months). **A2000 baseline** for reference: ~€24·N → €288 / €576 / €864 — by
> far the cheapest, but ≤8–14B only.

### Same V100 (P = €3,000), power sensitivity

| Horizon | Idle-heavy (€87/mo) | Typical (€149/mo) | Midpoint (€250/mo) | Sustained (€372/mo) |
|---|---|---|---|---|
| 12 mo | €4,044 | €4,788 | €6,000 | €7,464 |
| 24 mo | €5,088 | €6,576 | €9,000 | €11,928 |
| 36 mo | €6,132 | €8,364 | €12,000 | €16,392 |

### What the TCO says

- **V100 vs GEX131:** over **36 months the V100 (€3k, midpoint) ≈ €12,000 vs
  GEX131 €32,004** — roughly **⅓ the lifetime cost** for the *same 70B capability
  class*. GEX131 buys **speed (FP4, 1.79 TB/s), a warranty, 256 GB RAM, and zero
  electricity/heat/noise** for that ~2.7× premium. If you run 70B and value
  ownership + low cash-out over throughput → V100; if you value managed speed and
  hate hardware risk → GEX131.
- **V100 vs GEX44:** V100 (€12k) ≈ **1.8× GEX44 (€6.7k)** over 36 mo — but GEX44
  **physically cannot run 70B**. Different leagues; only compare them if your
  ceiling is ≤14B (then GEX44 wins on every axis).
- **Electricity is the V100's real cost**, not the sticker. At sustained load the
  power bill alone (€372/mo) exceeds **two** GEX44s. Power-manage it (scale-to-idle
  between bursts) or the economics erode fast.
- **Break-even purchase price** where 36-mo V100 TCO = 36-mo GEX131 (€32,004), at
  €250/mo power: `P = 32,004 − 9,000 = €23,004`. I.e. unless the V100 box costs
  **more than ~€23k** (it won't), it's always cheaper than GEX131 over 3 years on
  pure cash — the decision is **capability/risk, not price**.

> The tables above use the **German €0.34/kWh** to stay consistent with the rest of
> the doc. But the V100 actually sits in **Cameroon** — §6.3 redoes the bill at the
> real ENEO rate, and §6.4 introduces the 2×4070 you already run there.

### 6.3 Reality check — the V100 is in Cameroon (electricity-only)

The 5×V100 is billed by **ENEO at ~€0.16/kWh** — **less than half** the German rate
assumed above. Per scope we compare the **grid electrical bill only** (generator/
cooling/reliability excluded — "operation is still on us"). Same hardware, same
load, two countries:

| Load profile | Wall draw | Germany €0.34/kWh | **Cameroon €0.16/kWh** | Δ |
|---|---|---|---|---|
| Idle-heavy (bursty) | ~0.35 kW | €87/mo | **€41/mo** | −53 % |
| Typical always-on | ~0.60 kW | €149/mo | **€70/mo** | −53 % |
| Sustained 24/7 | ~1.50 kW | €372/mo | **€175/mo** | −53 % |

Siting in Cameroon **roughly halves the V100's only real running cost.** Re-running
the §6 TCO at the Cameroon **typical (€70/mo)** rate (P = €3,000):

| Horizon | **V100 @ Cameroon €70/mo** | V100 @ Cameroon €175/mo (sustained) | (recall) GEX44 | (recall) GEX131 |
|---|---|---|---|---|
| 12 mo | **€3,840** | €5,100 | €2,287 | €10,668 |
| 24 mo | **€4,680** | €7,200 | €4,495 | €21,336 |
| 36 mo | **€5,520** | €9,300 | €6,703 | €32,004 |

> Formula `= 3,000 + cameroon_power·N`. At the typical rate the **36-mo V100
> (~€5,520) now undercuts even GEX44 (€6,703)** and is **~⅙ of GEX131**. Cheap power
> flips the V100 from "budget 70B" to "by far the lowest-cash 70B"; the V100-vs-GEX131
> call becomes almost purely **capability/risk** (old/slow/no-warranty vs
> fast/FP4/managed), not euros. The Cameroon break-even purchase price vs 36-mo
> GEX131 rises to `P = 32,004 − 2,520 = ~€29,500` — i.e. it is *never* realistically
> more expensive than GEX131.

#### Would German electricity annihilate the V100's benefit? — yes, and here's by how much

The V100's whole case is "cheapest 70B." That case is **made by cheap Cameroon
power and unmade by German retail power.** Same box, same P = €3,000, **electricity
is the only variable:**

| | Power €/mo | **36-mo electricity** | **36-mo TCO** | RoI vs budget-70B SaaS¹ |
|---|---|---|---|---|
| **V100 — Cameroon, typical** | €70 | €2,520 | **€5,520** | **+$255/mo → ~13-mo payback** ✅ |
| V100 — Cameroon, sustained | €175 | €6,300 | €9,300 | +~$180/mo → ~18-mo ✅ |
| V100 — Germany, typical | €149 | €5,364 | €8,364 | +~$143/mo → ~23-mo ⚠️ |
| **V100 — Germany, sustained** | €372 | €13,392 | **€16,392** | **−~$90/mo → NEVER** ❌ |

¹ *Net monthly saving = ~$305 avoided 70B SaaS (at the box's ~263 M out/mo capacity) − power-in-USD. §9 basis.*

**By how much.** Over 3 years, Cameroon saves **€2,844 (typical) to €7,092
(sustained)** in electricity alone vs Germany — ~**€79–197/mo**. The sustained
saving (€7,092) is **more than 2× the V100's purchase price.** Put differently:
in Germany at sustained load the V100's **power bill alone (~$404/mo) exceeds the
~$305/mo of SaaS it would replace** → it is **RoI-negative**: you'd lose money vs
just calling budget SaaS, and you'd be better off renting GEX131 or using the API.
**Cameroon's half-price power is the entire reason the owned-V100 plan works.**

**Compared to the others** (36-mo TCO, capability in brackets):

| Box (siting) | 36-mo TCO | Class |
|---|---|---|
| 2×4070 — Cameroon, owned | **~€1,700** | ≤14B (power-only) |
| **V100 — Cameroon, typical** | **€5,520** | **70B (cheapest 70B)** |
| GEX44 — Germany, rent | €6,703 | ≤14B |
| V100 — Germany, typical | €8,364 | 70B |
| **V100 — Germany, sustained** | **€16,392** | 70B (power-wrecked) |
| GEX131 — Germany, rent | €32,004 | 70B (fast/managed) |

So: in **Cameroon the V100 is the cheapest 70B by far** (below even the ≤14B
GEX44); in **Germany it costs 1.5–3× more** and at sustained load lands between
GEX44 and GEX131 with none of GEX131's speed/warranty — the worst of both worlds.
**The €0.34-vs-€0.16 tariff gap is decisive**, because Hetzner's boxes hide their
(cheap, datacenter-scale) power inside the rent while an owned box pays retail.

### 6.4 The box you already have — 2× RTX 4070 12GB (Cameroon, live now)

A **2× RTX 4070 12GB** server is **already running in Cameroon**, so for a large
slice of this comparison the answer may simply be **"use what's on the floor."**
It's a consumer-Ada pair — **FP8-capable like the GEX44**, with **more aggregate
VRAM (24 GB)** and **faster per-card bandwidth (504 GB/s vs GEX44's 280)** — split
across two PCIe cards (no NVLink), capex already sunk.

| | 2× RTX 4070 12GB |
|---|---|
| Architecture | Ada Lovelace (AD104) — **FP8** + INT8 |
| Total VRAM | **24 GB GDDR6X** (2×12, not unified) |
| Bandwidth | ~504 GB/s **per card** |
| Power | ~200 W ea → ~0.55 kW serving at the wall |
| Cameroon power bill | **~€47/mo** typical (0.40 kW) · ~€64/mo sustained (€0.16/kWh) |
| Capex | **owned (sunk)** |

**What it deploys** (backends: vLLM FP8 / SGLang / llama.cpp):

| Model (quant) | 2× 4070 24GB |
|---|---|
| Qwen3.5-9B FP8 | ✅ 1 card → **2 replicas**, or TP=2 |
| Gemma 4 12B (vision/audio) | ✅ TP=2 |
| **GLM-4.7-Flash 30B-A3B Q4** ⭐ | ✅ TP=2 (~17 GB + KV) — the dev model |
| Qwen3.5-35B-A3B / Gemma 4 31B Q4 | ⚠️ TP=2, tight (little KV room) |
| Dense 70B / 122B-MoE | ❌ (24 GB too small) |

**Concurrency:** ~400–600 tok/s aggregate on a 9B (≈200–400 named users); on
GLM-4.7-Flash 30B-A3B ~10–20 concurrent (≈100–200 users) at **near-30B quality**
since only ~3 B params decode. All for a box whose *power* is **~€47/mo** — though
see **§6.5: its maintenance, not its power, is the real cost.**

> **Implication:** for everything **≤14B and the 30B-A3B coding MoEs** you likely
> **don't need to rent or buy** — the owned 2×4070 already beats the GEX44 envelope
> (it runs GLM-4.7-Flash; GEX44 can't). GEX44 wins only on *managed/warrantied* +
> German-grid reliability. Reserve **V100 / GEX131** spend for **dense-70B / 122B-MoE**,
> which the 2×4070 and GEX44 can't hold.

### 6.5 Maintenance & operations — the cost we almost always ignore

§6's TCO counts **capex + electricity** only. The bill nobody puts in the
spreadsheet is **keeping the thing alive**: ops labour, hardware failure, the
power/cooling *infrastructure* (not the kWh), and obsolescence. For an owned box in
a Cameroon office this is **the dominant cost**, and it is exactly what flips the
earlier "V100 is the cheapest 70B" conclusion. Estimates below (flagged Low-Medium
confidence — they hinge on your labour rate and the office's power reliability):

| Cost driver | A2000 (DE, home) | 2×4070 (CM office) | 5×V100 (CM office) | GEX44 (rent) | GEX131 (rent) |
|---|---|---|---|---|---|
| **Ops labour** (patching, monitoring, incidents) | ~1 h/mo (in GitOps) | ~3 h/mo | **~6 h/mo** (5 old cards, Volta workarounds) | ~1–2 h/mo (stack only) | ~1–2 h/mo |
| **Hardware failure / replacement** | low | small | **high** (refurb, out-of-warranty, 5× parts) | €0 (Hetzner replaces) | €0 |
| **Power *infrastructure*** (UPS / genset for load-shedding, fuel) | n/a (stable grid) | shared office UPS | **genset + fuel** for ~1.5 kW | included | included |
| **Cooling** (AC for the heat) | negligible (70 W) | modest (~0.55 kW) | **significant (~1.5 kW of heat)** | included | included |
| **Obsolescence / EOL** | low | low | ⚠️ **Volta CUDA support being dropped → forced re-platform** within horizon | none | none |
| **Software stack** (vLLM/llama.cpp updates, re-quant) | ~1 h/mo | ~1 h/mo | ~1–2 h/mo | ~1 h/mo | ~1 h/mo |
| **≈ Maintenance €/mo (midpoint)** | **~€40** | **~€100** | **~€300** (range €200–450) | **~€40** | **~€60** |

**Fully-loaded 36-month TCO (capex + electricity + maintenance):**

| Box | Hardware-only 36-mo (§6) | + Maintenance | **Fully-loaded 36-mo** | What maintenance does |
|---|---|---|---|---|
| A2000 (DE) | €864 | +€1,440 | **~€2,304** | maint > power (but labour is largely shared/sunk) |
| 2×4070 (CM) | €1,692 | +€3,600 | **~€5,292** | maintenance becomes the dominant cost |
| **5×V100 (CM)** | €5,520 | **+€10,800** | **~€16,320** | **~3× — erases the "cheap 70B" lead** |
| GEX44 (DE, rent) | €6,703 | +€1,440 | **~€8,143** | barely moves (no hardware ops) |
| GEX131 (DE, rent) | €32,004 | +€2,160 | **~€34,164** | barely moves |

> **The reframe, in one line:** **maintenance roughly triples the owned 5×V100's
> Cameroon TCO (€5.5 K → €16.3 K)** — now *above* GEX44 (€8.1 K) and ~half of GEX131
> — while the **rentals barely move** because Hetzner absorbs hardware, power-infra,
> cooling and replacement. **That near-zero maintenance is a large part of what the
> rental premium buys.** Once you stop ignoring the bit everyone ignores, the owned
> 70B box is no longer the runaway-cheapest. (§9 nets this into RoI — and it flips
> the V100's payback.)

---

## 7. Cost-recovery pricing — ADR-0028 applied to each platform

[**ADR-0028**](./adr/0028-owned-hardware-model-pricing.md) prices every
owned-hardware model at **cost-recovery**, derived from a documented **€/hour
TCO**, mapped to a **`weighted`** per-token catalog price (decode carries the
cost; prefill cheaper; LMCache prefix-hit near-free). The live A2000 ships at
**$1.00 / $0.15 / $0.03 per 1M** (out / in / cached). This section extends that
method to all four platforms so you can see what each *would* charge if federated
into the gateway — and whether it beats SaaS.

### 7.1 Method recap

```
cost-recovery $/1M out  =  monthly_TCO_USD  ÷  ( monthly_decode_capacity_Mtok × utilization )
$/1M in     = $/1M out × 0.15      (prefill ≈ 5–7× cheaper than decode)
$/1M cached = $/1M out × 0.03      (LMCache prefix reuse ≈ near-free)
```

`monthly_decode_capacity = aggregate_decode_tok/s × 730 h × 3600 s ÷ 1e6`
(= `tok/s × 2.628` M/mo). Utilization = fraction of that capacity you actually
sell. Capex accrues even at scale-to-zero, so **low utilization → high per-token
price** — that's ADR-0028's whole point.

### 7.2 The inputs

| Platform | Monthly TCO (USD) | 8B/30B-MoE aggregate decode | capacity | 70B aggregate decode | 70B capacity |
|---|---|---|---|---|---|
| **A2000** | ~$40 (€37) | ~150 tok/s (4B live) | ~394 M/mo | — | — |
| **2×4070** *(recommended — GLM-4.7-Flash)* | ~$84 (€77, 36-mo amort) | ~500 tok/s | ~1,314 M/mo | — | — |
| **GEX44** | ~$202 (€186) | ~400 tok/s | ~1,051 M/mo | — | — |
| **GEX131** | ~$966 (€889) | ~2,000 tok/s | ~5,256 M/mo | ~350 tok/s | ~920 M/mo |
| **5× V100** | ~$166 (€153, 36-mo amort) | ~450 tok/s | ~1,183 M/mo | ~100 tok/s | ~263 M/mo |

> **2×4070** TCO uses amortized capex (~€1,100 / 36 mo ≈ €31/mo) + Cameroon power
> €47/mo ≈ **€77/mo**; throughput is for **GLM-4.7-Flash 30B-A3B** (decodes ~like a
> 6B) or an 8B. Capex is cash-sunk but amortized here for ADR-0028 consistency (same
> as the A2000). **V100** TCO = amortized capex (€3,000 / 36 ≈ €83) + **Cameroon**
> power €70/mo = **€153/mo** (ADR-0028 local-power rule — *not* the German €250
> reference). Both are **capex+power only** — §6.5 maintenance is not in ADR-0028
> cost-recovery; it lands in §9.5 RoI.

### 7.3 Cost-recovery `$/1M out` vs utilization

**8B model:**

| Utilization | A2000 | 2×4070 | GEX44 | GEX131 | 5× V100 |
|---|---|---|---|---|---|
| 10 % (PoC / bursty) | **$1.02** ✅*anchor* | $0.64 | $1.92 | $1.84 | $1.40 |
| 30 % (steady team) | $0.34 | $0.21 | $0.64 | $0.61 | $0.47 |
| 100 % (saturated) | $0.10 | $0.06 | $0.19 | $0.18 | $0.14 |

> ✅ **Method check:** the A2000 at **~10 % utilization → $1.02/1M**, which is
> exactly the live catalog **$1.00**. So ADR-0028's shipped price implies the live
> 4B box is sized for ~10 % decode duty — consistent with "PoC, bursty, low duty
> cycle". The model is self-validating.

**70B model** (only GEX131 + V100 qualify):

| Utilization | GEX131 | 5× V100 (Cameroon) |
|---|---|---|
| 10 % | $10.50 | $6.31 |
| 30 % | $3.50 | $2.10 |
| 100 % | $1.05 | $0.63 |

> The V100 now prices **below GEX131** per-token (cheap Cameroon power + amortized
> capex) — but remember §9.5: this is the **maintenance-blind** cost-recovery basis.
> Add §6.5 ops and the V100's real per-token recovery rises again.

### 7.4 Suggested `pricing.standard` blocks (if federated)

Mirroring the [Qwen3-4B table](./models/qwen3-4b.md#6-cost--hour-tco--catalog-price-erlangen-2026-adr-0028),
at a **30 % steady-team utilization** assumption (re-tune as real data lands):

| Platform / model | `outputPer1M` | `inputPer1M` | `cachedInputPer1M` |
|---|---|---|---|
| A2000 / 4B *(live, 10 % util)* | **$1.00** | $0.15 | $0.03 |
| **2×4070 / GLM-4.7-Flash** *(recommended)* | **$0.21** | $0.03 | $0.01 |
| GEX44 / 8B | $0.64 | $0.10 | $0.02 |
| GEX131 / 8B | $0.61 | $0.09 | $0.02 |
| GEX131 / 70B | $3.50 | $0.53 | $0.11 |
| 5× V100 / 70B (Cameroon) | $2.10 | $0.32 | $0.06 |

### 7.5 Make-vs-buy (the honest signal)

SaaS comparators, mid-2026 (per-1M, output, approximate):

| Tier | SaaS (DeepInfra / Together / Fireworks) |
|---|---|
| 4–8B | **~$0.02–0.10** |
| 70B (Llama-3.3-70B class) | **~$0.40–0.90** |

- **Small models (4–8B / 30B-MoE):** self-hosting recovers cost at **$0.06–0.19/1M**
  *saturated* (§7.3) vs SaaS **$0.02–0.10** — *close*, and the recommended
  **2×4070 reaches $0.21/1M at a realistic 30 % util** (vs $0.64 at PoC-10 %). So at
  steady-team utilization it's roughly SaaS-parity, not 10× off; at low PoC duty it's
  ~3–10× SaaS. Net: small self-hosting is **near-parity once busy**, and the real
  return is **control / privacy / data-sovereignty / learning** — still not a clear
  price *win*, consistent with ADR-0028.
- **70B:** GEX131 reaches SaaS-parity (**~$1.05/1M**) only at near-saturation; at
  30 % it's **$3.50/1M**. The Cameroon **V100 actually prices *below* GEX131 per-token**
  on the ADR-0028 basis ($2.10 vs $3.50 at 30 %, §7.3) thanks to cheap power — so its
  drawback is **not** per-token cost; it's **speed/quality (no FP8/FP4, slow), the
  ~27-user throughput cap, Volta EOL, and the §6.5 maintenance** that §7.3 omits and
  §9.5 shows flips the real RoI. For 70B the owned case is **data-residency + flat
  cost**, with V100 cheap-on-paper but operationally heavy.
- **The crossover:** self-hosting wins on €/token only as utilization climbs.
  GEX131 needs **multi-billion output tokens/month** (≈ saturated) to undercut
  Together's 70B price. Until then, every box here is a sovereignty/latency
  decision dressed as a cost decision — exactly why ADR-0028 insists on truthful
  cost-recovery accounting rather than a flattering $0 or a SaaS-parity fiction.

---

## 8. Decision summary

| Axis | A2000 | 2× 4070 *(own, CM)* | 5× V100 *(own, CM)* | GEX44 | GEX131 |
|---|---|---|---|---|---|
| Top model it runs well | Qwen3.5-4B | **GLM-4.7-Flash 30B-A3B** | Qwen3.5-122B-A10B (slow) | Qwen3.5-9B / Gemma 4 12B | Qwen3.5-122B-A10B (fast) |
| Servable context | 128 K | ~64–128 K | ~128 K | ~128 K | **256 K (native)** |
| Key capabilities | text·tools | **coding·agent**·tools | reasoning·MoE | text·**vision·audio** (Gemma 4) | **all + frontier-ish reasoning** |
| Named users (top model, 10 %) | ~30–60 | ~100–200 | ~60–120 | ~150–300 | ~300–600 |
| **Hardware-only 36-mo TCO** | ~€864 | **~€1,692** (CM) | ~€5.5 k (CM) / ~€16 k (DE-sust) | €6,703 | €32,004 |
| **Fully-loaded 36-mo (+maint, §6.5)** | ~€2,304 | **~€5,292** | **~€16,320** | ~€8,143 | ~€34,164 |
| Maintenance burden | low (home, GitOps) | medium (CM office) | **high** (5 old cards, genset, EOL) | **near-zero** | **near-zero** |
| Modern kernels (FP8/FP4) | ✗ | **FP8** | ✗ | FP8 | **FP4+FP8** |
| Managed / warranty | self | self | none | yes | yes |
| RoI vs budget SaaS (§9.5) | +$20/mo (small) | **+$250/mo** (w/ 30B MoE) | **maint-dependent → mostly negative** | +ve only >~90 u | +ve only >~78–85 u |
| Best for | current PoC | **≤30B-MoE coding, owned** | owned 70B *if* DIY-cheap ops | managed multimodal small | managed frontier-ish at scale |

*CM = Cameroon (ENEO €0.16/kWh); DE = Germany (€0.34). Hardware-only = capex+electricity (§6); fully-loaded adds §6.5 maintenance. V100 capex parametric (P=€3k).*

**Recommendation for this platform's trajectory:** keep the **A2000** as the live
Erlangen small-model tier (free, measured-good). For **≤30B-MoE** — which now covers
most developer coding/agent work *and* all marketing — **run GLM-4.7-Flash on the
2×4070 you already own in Cameroon before renting or buying anything.** It's the one
choice that is RoI-positive even after maintenance (§9.5), gives developers a real
coding model, and costs only Cameroon power + modest ops. **GEX44** is then only
worth it for **managed multimodal** (Gemma 4 vision/audio) or German-grid SLA. Reach
for **70B / 122B-MoE** only when a workload truly needs it — and here the headline
has changed: the V100 is the cheapest 70B *on hardware+power*, but **once maintenance
is counted (§6.5) its fully-loaded 36-mo TCO ~triples to ~€16 K and its RoI is
negative unless you keep ops near-DIY.** So the V100 is a "we have cheap labour and
tolerate old/EOL hardware" play; **GEX131** is the answer when you want it fast,
FP4-capable, warrantied and **maintenance-free** — and at ≥~80 users it also wins on €.

> **Next action:** (1) drop the eBay **asking price** into §6 (`P`); (2) confirm the
> V100 **load profile** *and* a realistic **maintenance/ops €/mo** (§6.5 — it decides
> the 70B verdict more than the purchase price does); (3) confirm the **4070 variant**
> (4070 / Super / Ti — TDP 200/220/285 W shifts the bill); (4) confirm your real
> **per-dev token rate** (§9.4). With those, §6/§9 collapse to hard numbers.

---

## 9. RoI / payback — when does each box pay for itself?

This is an **internal platform** (developers + marketing), so the "return" isn't
revenue — it's **SaaS spend avoided**. RoI here = *"does running the box cost less
than the API calls it replaces, and if there's capex, how long until the savings
repay it?"*

```
avoided_SaaS = min(demand, box_capacity) × SaaS_price     (a box can't avoid more than it can serve)
net_saving   = avoided_SaaS − running_cost
payback (mo) = capex ÷ net_saving        (∞ if net_saving ≤ 0; rentals have no capex → it's just monthly P&L)
```

Baseline (your pick): **budget open-model SaaS** — 8B-class ≈ **$0.04 in / $0.08
out** per 1M; 70B-class ≈ **$0.23 in / $0.40 out** (DeepInfra Llama-3.3-70B). The
comparison is **like-for-like capability**: an 8B box is scored against 8B SaaS, a
70B box against 70B SaaS.

### 9.1 Workload model — developers vs marketing

Your users are **mostly developers + marketing**, and they consume *very*
differently. Stated per-user monthly volumes (the dominant knobs — see §9.4):

| Persona | Tokens/mo | in : out | Why |
|---|---|---|---|
| **Developer** (opencode / LibreChat, code context) | **~66 M** (≈3 M/day) | 80 / 20 | Large code context in, moderate generation. *Heavy agentic users run 3–5× this.* |
| **Marketing** (chat content/copy) | **~7 M** | ~55 / 45 | Short prompts, generation-heavy, lower frequency. Cheap to serve. |

**Worked team (the 30–100 band you chose):** a **2 : 1 dev : marketing** mix.
The whole marketing cohort is a rounding error on cost; **developers — especially
agentic ones — are where both the spend and the RoI live.**

### 9.2 Payback per scenario — worked at 60 users (40 dev + 20 mkt)

Team demand ≈ **2,192 M in / 588 M out per month**. Budget-SaaS bill *if fully
served*: **$135/mo at 8B**, **$739/mo at 70B**.

| Box (class, siting) | Capex | Run $/mo | Serves | Avoided SaaS $/mo | **Net $/mo** | **Payback** |
|---|---|---|---|---|---|---|
| **A2000** (8B, DE, owned) | $0 | $26 | 67 %¹ | $90 | **+$64** | **instant** (sunk) |
| **2× 4070** (8B, CM, owned) | $0 | $51 | 100 % | $135 | **+$84** | **instant** (sunk) |
| **GEX44** (8B, DE, rent) | — | $202 | 100 % | $135 | **−$67** | **never** (< ~90 users) |
| **5× V100** (70B, CM, owned) | ~$3,261² | $76 | 45 %¹ | $331 | **+$255** | **~13 mo** |
| **GEX131** (70B, DE, rent) | — | $966 | 100 % | $739 | **−$227** | **never** (< ~78 users) |

¹ *Capacity-capped* — the box saturates (A2000 ~394 M out/mo, the §7.2 basis;
V100-70B ~263 M out/mo) and the overflow spills to SaaS anyway, so its
avoided-SaaS plateaus.
² P = €3,000 example; the V100 asking price is still open (§6).

> ⚠️ **These rows use power-only running cost.** They are the *maintenance-blind*
> view. **§9.5 nets in §6.5 maintenance** — which flips the V100 from "+$255/mo,
> ~13 mo" to **negative**, and makes the 2×4070's RoI depend on running the *good*
> model. Read both.

### 9.3 How it scales with team size, and the break-evens

**Net saving $/mo by team size** (negative = SaaS would be cheaper):

| Box | 30 users | 60 users | 100 users | RoI verdict |
|---|---|---|---|---|
| A2000 (8B, owned) | +$41 | +$64 | +$62 (capped) | ✅ instant, but tiny + capacity-bound |
| 2× 4070 (8B, owned) | +$16 | +$84 | +$169 | ✅ **instant, scales — best small-model RoI** |
| GEX44 (8B, rent) | −$135 | −$67 | +$18 | ⚠️ break-even **~90 users** vs budget-8B SaaS |
| V100 (70B, owned) | +$255 → **13 mo** | +$255 → 13 mo | +$255 → 13 mo | ⚠️ *maintenance-blind* — **§9.5 flips this** (9–17 mo only if ops near-DIY) |
| GEX131 (70B, rent) | −$596 | −$227 | +$187 | ⚠️ break-even **~78 users** vs budget-70B SaaS |

So, against *budget* SaaS at moderate dev volume:

- **Already-owned boxes (A2000, 2×4070) pay back instantly** — capex is gone, and
  their power bill (~$40–51/mo) is below the SaaS they replace. The **2×4070 in
  Cameroon is the standout**: ample 24 GB capacity for the whole ≤14B team and the
  net saving *grows* with headcount. For ≤14B, **you're already done — keep using it.**
- **GEX44 doesn't pay back below ~90 users** — at 30–60 users its €184/mo rental
  *exceeds* the cheap 8B SaaS bill. It's a **control/SLA/German-grid purchase, not a
  cost saving**, until you're near the top of your band.
- **The V100 is the one investment with a clean payback (~9–17 mo)** — *only*
  because cheap Cameroon power (~$76/mo) is trivial against 70B SaaS. But it
  **saturates at ~27 users of 70B** (~263 M out/mo), so beyond that it caps the
  savings and the rest spills to SaaS — buy it for 70B *quality on a budget*, not
  to absorb unlimited volume.
- **GEX131 only pays back above ~78 users** of genuine 70B demand — but it's the
  box that serves **nearly all** of a 100-person team's 70B load: its ~920 M out/mo
  cap covers ~96 % of the ~963 M/mo a 100-user team generates (the last ~4 % spills
  to SaaS), vs the V100's ~27 % — so GEX131 is the only one that scales to that band
  without large spillover. Below ~78 users it's a capability/SLA buy; above it, it wins outright.

### 9.4 The knob that moves everything: per-developer volume

Every break-even above assumes a **moderate ~66 M tok/mo/dev**. RoI scales almost
linearly with it, and **break-even team size ∝ 1 ⁄ volume**:

| If devs are… | ~tok/mo | GEX44 break-even | GEX131 break-even | V100 payback |
|---|---|---|---|---|
| Light (chat only) | ~20 M | ~300 users | ~260 users | slower (volume-starved) |
| **Moderate (assumed)** | **~66 M** | **~90 users** | **~78 users** | **~13 mo** |
| Heavy agentic (Claude-Code-style) | ~250 M | **~24 users** | **~21 users** | **→ ~9 mo floor** |

> **Translation:** if your developers are heavy agentic coders, the rentals
> (GEX44/GEX131) flip to **positive RoI inside your 30–100 band**, and the V100
> hits its ~9-month payback floor fast. If they're light, *budget SaaS just wins* —
> don't buy hardware. **Measure your real per-dev token rate before committing** —
> it's worth more than the V100 price quote.

### 9.5 Net of maintenance (§6.5) — the RoI that survives reality

Re-run with **fully-loaded** running cost (power **+ maintenance**, §6.5) and the
**model class actually served** (the 2×4070 should run the 30B-A3B coding MoE, not
8B → it replaces pricier ~30B SaaS, not cheap 8B SaaS). 60-user worked example:

| Box / model served | Fully-loaded $/mo | Avoided SaaS $/mo | **Net $/mo** | Payback | Δ vs maintenance-blind |
|---|---|---|---|---|---|
| **2×4070 / GLM-4.7-Flash 30B-A3B** ⭐ | $160 | $410 (≈30B SaaS) | **+$250** | **instant** (sunk) | ✅ *better* — the right model lifts it |
| 2×4070 / only 8B | $160 | $135 | −$25 | never | ⚠️ wasting the box on 8B |
| A2000 / Qwen3.5-4B | $70 | $90 (67 % capped) | **+$20** | instant (sunk) | small but positive; labour mostly sunk |
| **5×V100 / 70B** | **$402** | $331 (capped) | **−$71** | **NEVER** | ❌ **flipped** from +$255/~13 mo |
| GEX131 / 70B | $1,032 | $739 | −$293 | never (< ~85 u) | ~unchanged |

**V100 RoI is now entirely a maintenance question:**

| V100 maintenance | Fully-loaded $/mo | Net $/mo | Payback |
|---|---|---|---|
| **DIY, ~€80/mo** (your own time, minimal cooling) | $163 | **+$168** | **~19 mo** |
| Low, €200/mo | $293 | +$37 | ~88 mo |
| **Midpoint, €300/mo** | $402 | **−$71** | **never** |
| High, €450/mo | $565 | −$235 | never |

> **The lesson you asked for:** the V100's celebrated "~13-month payback" was a
> **maintenance-blind artifact**. Counting the cooling, genset, failure reserve and
> ops on five out-of-warranty cards, it pays back **only if you keep maintenance
> near-DIY (~€80/mo)** — otherwise it's **RoI-negative** and you're better off with
> SaaS or GEX131. Meanwhile the **2×4070 stays the standout** *because* you run
> GLM-4.7-Flash on it (replacing ~30B SaaS, not 8B). **Maintenance is the variable
> that decides the whole 70B question.**

### 9.6 RoI verdict

- **≤14B + 30B-A3B coding (most dev work + all marketing):** the **2×4070 you
  already own**, running **GLM-4.7-Flash**, is RoI-positive even after maintenance
  (+~$250/mo) — *provided you put the good model on it*. **Don't rent GEX44** unless
  you need managed SLA or you're past ~90 users. Marketing is too cheap to serve to
  justify any new spend.
- **70B (quality-critical dev work):** the Cameroon V100 is the cheapest 70B *only
  on hardware+power*; **once maintenance is counted it pays back only at near-DIY
  ops, and is otherwise RoI-negative** (§9.5). Treat it as a "we have cheap labour
  and tolerate old hardware" bet, not a slam-dunk. **GEX131** wins above ~78–85
  users or when you need its speed/FP4/SLA/zero-maintenance — and its low
  maintenance is part of the value.
- **Overarching (ADR-0028's point, in € terms):** versus *budget* SaaS, self-hosting
  is **rarely a pure price win** — its real return is
  control/privacy/data-residency/no-rate-limits, which this model deliberately does
  **not** price. The one robust €-RoI play is **(1) exploit sunk capex — the 2×4070
  running GLM-4.7-Flash for ≤30B-MoE**; the V100/GEX131 70B case is **conditional**
  (V100 on maintenance, GEX131 on scale).

> **To turn these into hard dates:** give me (a) your real **per-developer token
> rate** (or current monthly SaaS spend) and (b) the **V100 asking price**, and I'll
> collapse §9 to single payback dates instead of a band.

---

*Sources:* [Hetzner GPU matrix](https://www.hetzner.com/de/dedicated-rootserver/matrix-gpu/) ·
[GEX44](https://www.hetzner.com/dedicated-rootserver/gex44/) ·
[GEX131 press release](https://www.hetzner.com/pressroom/new-gex131/) ·
eBay listing 306748779023 (5× Tesla V100 16GB, seller *biercologne*; specs from listing text, price not captured) ·
[ENEO Cameroon tariffs](https://www.eneocameroon.cm/index.php/en/clients-professionnels-vos-factures-et-paiement-en/clients-professionnels-vos-factures-et-paiement-tarifs-delectricite-en) ·
[Cameroon electricity prices — GlobalPetrolPrices (Jun 2025, ~XAF 106/kWh business)](https://www.globalpetrolprices.com/Cameroon/electricity_prices/) ·
[ADR-0028](./adr/0028-owned-hardware-model-pricing.md) ·
[`models/qwen3.5-4b-q4.md`](./models/qwen3.5-4b-q4.md) §6 (measured A2000 capacity).
