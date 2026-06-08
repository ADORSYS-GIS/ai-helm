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
| Keep serving 4–8B to a small team at ~zero marginal cost | **Local A2000 (keep)** | Already owned, 70 W, llama.cpp live ([ADR-0032](./adr/0032-llama-cpp-engine-for-self-hosted-models.md)). Cheapest per-token at PoC volume. |
| Managed 7–14B FP8 for more concurrency, pure OpEx | **GEX44 — €184/mo** | Modern Ada FP8, no hardware risk, ~150–300 named users on 8B. Capped below 32B. |
| Owned, on-prem **70B** on a budget, you control the box | **eBay 5×V100** *(if the price is right)* | Only sub-€900/mo route to 70B. **But** power-dominated, no warranty, Volta EOL-track, 16 GB host RAM bottleneck. Plug the asking price into §6. |
| Serious multi-tenant 70B / 100B-MoE, single managed GPU, FP4 | **GEX131 — €889/mo** | Runs everything up to 70B-Q8 / MoE-FP4 on one card, highest throughput, FP4/FP8 native, fully managed. Best €/capability at the top end. |
| ≤14B / 32B-Q4 **you already own**, in Cameroon now | **Existing 2× RTX 4070 12GB** | Sunk capex; FP8-capable Ada, **24 GB** total, faster VRAM than GEX44. Marginal cost ≈ **only Cameroon electricity (~€47–64/mo)**. Covers most of the GEX44 envelope without renting or buying. |

> **Siting matters (new).** The **5×V100** *and* the **existing 2×4070** live in a
> **Cameroon office**, billed by **ENEO at ~€0.16/kWh** — **less than half** the
> German €0.34/kWh. Per the maintainer we score the **grid electrical bill only**
> here ("operation is still on us"). See §6 for the full Cameroon-rate redo.

**Bottom line:** for the current 4–8B workload the **A2000 stays cheapest**, and
for **≤14B** the **2×4070 you already own in Cameroon** likely makes renting/buying
moot — its only marginal cost is ~€50/mo of (cheap) Cameroon power. The honest
make-vs-buy signal (per ADR-0028) is that self-hosting small models is a
control/privacy/learning play, **not** a per-token price win until utilization is
high. **70B** changes the calculus — only the V100 box and GEX131 can serve it, and
there the choice is **owned-but-old (V100)** vs **managed-fast-warrantied (GEX131)**.
At the **Cameroon power rate the V100's lifetime-cost lead widens sharply** (§6):
its 36-mo TCO drops below even GEX44, so the V100 vs GEX131 call becomes
almost purely capability/risk, not €.

---

## 0. Methodology, sources & confidence

This is a **research document**, so it states *how* every number was obtained and
*how far to trust it* — that provenance is the point, not just the conclusion.

**Approach.** Five candidate platforms were profiled along four axes — *what models
fit* (§3), *who serves them* (§4 backends), *how many users* (§5), and *what it
costs* (§6 TCO, §7 cost-recovery, §9 RoI). Specs and prices were gathered from
vendor primary sources; capability was derived from VRAM/bandwidth/precision math;
throughput and economics were modelled from first principles and anchored, where
possible, to the live system.

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

**Key assumptions** (the knobs that move conclusions): electricity is
**location-specific** (DE €0.34 vs CM €0.16/kWh — §1); FX **$1 ≈ €0.92**;
**730 h/mo**; 3-yr (26,280 h) amortization; chat needs **≥15 tok/s/stream**; **10 %**
duty cycle for "named users"; per-developer volume **~66 M tok/mo** (moderate).

**Open inputs that would sharpen this to hard numbers:** (1) the **V100 asking
price** (locks §6 TCO); (2) the **real per-developer token rate** or current SaaS
spend (locks §9 payback dates). Both are flagged inline where they bite.

**Limitations.** Throughput/concurrency/RoI are **models, not measurements** for
every box except the A2000. The RoI scope is **electricity-only** for the Cameroon
boxes (cooling, UPS/generator, bandwidth, staff, hardware risk excluded per the
maintainer — "operation is still on us") and **deliberately prices no
control/privacy/data-residency value**, which is often the real reason to
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
- **Scope for the Cameroon boxes: the grid electrical bill only.** Per the
  maintainer, cooling, **UPS / generator for load-shedding** (diesel ≈ 3–5× grid),
  bandwidth, staff time and hardware risk are real but **out of scope** here
  ("operation is still on us"). Reliability, not the meter, is the usual Cameroon
  catch — flagged, not costed.
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
| Price | **owned** (~€37/mo power @ 24/7) | **purchase price unknown** + power | **€184/mo** + €79 setup | **€889/mo**, no setup, IPv4 incl. |
| Warranty / lifecycle | yours | **none; Volta is EOL-track** | Hetzner-managed | Hetzner-managed |

**Reading the table:**
- The V100's **900 GB/s per card** is the headline — bandwidth drives decode
  speed, and per-card it beats *both* Hetzner single-GPU options. But it's split
  across 5 cards, the tensor cores are **first-gen FP16-only**, the **16 GB host
  RAM** will choke model loading / KV offload, and the **5-GPU count is awkward**
  for tensor parallelism (you want 2/4/8 → you effectively run TP=4 + 1 spare).
- **GEX131** trades raw per-card bandwidth peak for **96 GB on one die at
  1.79 TB/s** + **FP4** — no parallelism overhead, the whole model on one GPU.
- **GEX44** and the **A2000** are the low-power (70 W) small-model tier; GEX44's
  edge is **Ada FP8** + 20 GB.

---

## 3. Which models fit — deployability matrix

✅ comfortable · ⚠️ tight / degraded · ❌ won't fit. Recommended **backend** in
parentheses. Weight estimates are for the listed quant; add KV cache per request.

| Model (quant) | Weights | A2000 12GB | 5× V100 80GB | GEX44 20GB | GEX131 96GB |
|---|---|---|---|---|---|
| 4B Q4 *(live Qwen3.5)* | ~3 GB | ✅ (llama.cpp) | ✅ ×5 replicas (vLLM/llama.cpp) | ✅ (vLLM/llama.cpp) | ✅ (vLLM) |
| 7–8B Q4 | ~5 GB | ⚠️ short ctx (llama.cpp) | ✅ 1 card → **5 replicas** (vLLM) | ✅ (vLLM FP8) | ✅ (vLLM) |
| 7–8B FP16/BF16 | ~16 GB | ❌ | ✅ 1 card (vLLM) | ⚠️ no KV room (vLLM) | ✅ (vLLM) |
| 14B Q4 | ~9 GB | ⚠️ tiny KV (llama.cpp) | ✅ 1–2 card (vLLM) | ✅ (vLLM/llama.cpp) | ✅ (vLLM) |
| 32B Q4 | ~20 GB | ❌ | ✅ TP=2 (vLLM) | ⚠️ no KV room | ✅ (vLLM) |
| 32B FP16 | ~64 GB | ❌ | ⚠️ TP=4 (vLLM) | ❌ | ✅ (vLLM) |
| **70B Q4** | ~40 GB | ❌ | ✅ **TP=4** (vLLM) — seller's claim | ❌ | ✅ (vLLM, large KV) |
| 70B Q8 | ~70 GB | ❌ | ⚠️ TP=5 / pipeline | ❌ | ✅ (vLLM) |
| 70B FP16 | ~140 GB | ❌ | ❌ | ❌ | ❌ (use Q8/FP8) |
| 100–120B MoE Q4/FP4 | ~60 GB | ❌ | ⚠️ TP, slow | ❌ | ✅ (vLLM **FP4**) |

**Headlines:**
- **A2000** is a ≤8B-Q4 / 14B-Q4-tight box — exactly its current role (Qwen3.5-4B
  Q4, 128k ctx, llama.cpp). It is **not** a 70B machine.
- **5× V100** is the **only** option here that runs **70B-class** models
  affordably on weights — its entire pitch. But via PCIe tensor-parallel over old
  cards, so "70B at ~20–30 tok/s", not fast.
- **GEX44** is the **7–14B-with-FP8** sweet spot; 20 GB caps you below 32B.
- **GEX131** runs **everything up to 70B-Q8 / MoE-FP4** on a *single* GPU with
  huge bandwidth — no parallelism headaches.

---

## 4. Backend fit per platform

The gateway speaks OpenAI-compatible HTTP to whatever serves the model; the
backend choice is per-platform and per-architecture.

| Platform | Primary backend | FP8/FP4? | Notes |
|---|---|---|---|
| **A2000** (Ampere) | **llama.cpp** (`llama-server`, live) | no FP8 | GGUF Q4 + native `--api-key`; 128k ctx via cheap GDN-MoE KV. vLLM works but no FP8, KV-hungry. ([ADR-0032](./adr/0032-llama-cpp-engine-for-self-hosted-models.md)) |
| **5× V100** (Volta cc 7.0) | **vLLM** `--tensor-parallel-size 4` · **llama.cpp** · Ollama | **no** | No FlashAttn-2 / Marlin-AWQ / FP8 kernels → slower fallback paths. llama.cpp splits multi-GPU cleanly for 70B GGUF. Ollama is what the seller demos. ⚠️ **vLLM is deprecating Volta** — pin an older release. |
| **GEX44** (Ada) | **vLLM / SGLang with FP8** | **FP8** | FP8 weights + FP8 KV cache stretches 20 GB a long way — the real value of this card. TGI/llama.cpp fine too. |
| **GEX131** (Blackwell) | **vLLM / SGLang with FP4 + FP8** | **FP4 + FP8** | Biggest models, highest throughput, single GPU (no TP). The natural serious-multi-tenant backend. |

---

## 5. How many users / clients — concurrency matrix

Estimates (A2000 row measured). Single-stream ≈ short context; aggregate assumes
continuous batching.

**8B model — the realistic shared-workload size:**

| | A2000 | 5× V100 | GEX44 | GEX131 |
|---|---|---|---|---|
| Backend | llama.cpp | vLLM (5 replicas) | vLLM FP8 | vLLM FP8 |
| Single-stream | ~30–50 tok/s | ~60–80 tok/s/card | ~40–60 tok/s | ~120–150 tok/s |
| Concurrent active | ~3–6 | **~40–60** (5 cards) | ~15–30 | **~100+** |
| ~Named users (10 %) | ~30–60 | ~400–600 | ~150–300 | ~1000+ |

**70B Q4 model:**

| | A2000 | 5× V100 (TP=4) | GEX44 | GEX131 |
|---|---|---|---|---|
| Backend | — | vLLM | — | vLLM |
| Single-stream | ❌ | ~20–30 tok/s | ❌ | ~30–50 tok/s |
| Concurrent active | ❌ | ~4–8 | ❌ | ~10–30 |
| ~Named users (10 %) | ❌ | ~40–80 | ❌ | ~100–300 |

**4B Q4 — the current live model:**

| | A2000 *(measured)* | 5× V100 | GEX44 | GEX131 |
|---|---|---|---|---|
| Single-stream | **~50–53 tok/s** | ~100+/card | ~80–120 tok/s | ~200+ tok/s |
| Concurrent active | **4 slots** | ~50–80 | ~30–50 | ~150+ |
| Prefill | **~1.3k tok/s** | ~2k/card | ~2k | ~10k+ |

> A2000 figures from `llama-server` slot timings under real traffic
> ([`models/qwen3.5-4b-q4.md`](./models/qwen3.5-4b-q4.md) §6): ~52 tok/s decode,
> ~37 tok/s/slot under load, 4 concurrent slots, 128k ctx (real 35k-token prompts).

---

## 6. TCO — 12 / 24 / 36 months (the procurement question)

Total **cash outlay** over the horizon (not amortized — what leaves your account).
Rented platforms: `setup + monthly × N`. Owned platforms: `purchase + power × N`.

### Monthly run-rate basis

| Platform | Capex (one-time) | Monthly run-rate | Notes |
|---|---|---|---|
| **A2000** | €0 (sunk) | **~€37/mo** @ 24/7 (95 W wall × €0.34) | Already owned; capex is gone. ([ADR-0028](./adr/0028-owned-hardware-model-pricing.md)) |
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
> months). **A2000 baseline** for reference: ~€37·N → €444 / €888 / €1,332 — by
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
| 7–8B FP8 | ✅ 1 card → **2 replicas**, or TP=2 for headroom |
| 7–8B FP16 | ✅ TP=2 |
| 14B Q4/FP8 | ✅ (TP=2) |
| 32B Q4 | ⚠️ TP=2, tight (little KV room) |
| 70B | ❌ (24 GB can't hold Q4's ~40 GB) |

**Concurrency (8B FP8, estimate):** ~50–70 tok/s single-stream per card, ~400–600
tok/s aggregate → **~20–40 concurrent active**, **~200–400 named users** at 10 %
duty — **GEX44-class or a touch better** (faster VRAM, two cards), for a box whose
marginal cost is **~€50/mo of Cameroon electricity.**

> **Implication:** for everything **≤14B (and 32B-Q4 at a push)** you likely
> **don't need to rent or buy anything** — the 2×4070 already covers the GEX44
> envelope at a fraction of the cost. GEX44 wins only on *managed/warrantied* +
> German-grid reliability; the 2×4070 wins on cash (sunk capex + half-price power)
> and on 24 GB vs 20. Reserve the **V100 / GEX131** spend for **70B**, which neither
> the 2×4070 nor GEX44 can serve.

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

| Platform | Monthly TCO (USD) | 8B aggregate decode | 8B capacity | 70B aggregate decode | 70B capacity |
|---|---|---|---|---|---|
| **A2000** | ~$40 (€37) | ~150 tok/s (4B live) | ~394 M/mo | — | — |
| **GEX44** | ~$202 (€186) | ~400 tok/s | ~1,051 M/mo | — | — |
| **GEX131** | ~$966 (€889) | ~2,000 tok/s | ~5,256 M/mo | ~350 tok/s | ~920 M/mo |
| **5× V100** | ~$362 (€333, P=3k+€250 pwr, 36-mo amort) | ~450 tok/s | ~1,183 M/mo | ~100 tok/s | ~263 M/mo |

> V100 monthly TCO here uses the **amortized** capex (€3,000 / 36 mo = €83/mo) +
> €250/mo power = €333/mo, to put it on the same €/month footing as the rentals.

### 7.3 Cost-recovery `$/1M out` vs utilization

**8B model:**

| Utilization | A2000 | GEX44 | GEX131 | 5× V100 |
|---|---|---|---|---|
| 10 % (PoC / bursty) | **$1.02** ✅*anchor* | $1.92 | $1.84 | $3.06 |
| 30 % (steady team) | $0.34 | $0.64 | $0.61 | $1.02 |
| 100 % (saturated) | $0.10 | $0.19 | $0.18 | $0.31 |

> ✅ **Method check:** the A2000 at **~10 % utilization → $1.02/1M**, which is
> exactly the live catalog **$1.00**. So ADR-0028's shipped price implies the live
> 4B box is sized for ~10 % decode duty — consistent with "PoC, bursty, low duty
> cycle". The model is self-validating.

**70B model** (only GEX131 + V100 qualify):

| Utilization | GEX131 | 5× V100 |
|---|---|---|
| 10 % | $10.50 | $13.77 |
| 30 % | $3.50 | $4.59 |
| 100 % | $1.05 | $1.38 |

### 7.4 Suggested `pricing.standard` blocks (if federated)

Mirroring the [Qwen3-4B table](./models/qwen3-4b.md#6-cost--hour-tco--catalog-price-erlangen-2026-adr-0028),
at a **30 % steady-team utilization** assumption (re-tune as real data lands):

| Platform / model | `outputPer1M` | `inputPer1M` | `cachedInputPer1M` |
|---|---|---|---|
| A2000 / 4B *(live, 10 % util)* | **$1.00** | $0.15 | $0.03 |
| GEX44 / 8B | $0.64 | $0.10 | $0.02 |
| GEX131 / 8B | $0.61 | $0.09 | $0.02 |
| GEX131 / 70B | $3.50 | $0.53 | $0.11 |
| 5× V100 / 70B | $4.59 | $0.69 | $0.14 |

### 7.5 Make-vs-buy (the honest signal)

SaaS comparators, mid-2026 (per-1M, output, approximate):

| Tier | SaaS (DeepInfra / Together / Fireworks) |
|---|---|
| 4–8B | **~$0.02–0.10** |
| 70B (Llama-3.3-70B class) | **~$0.40–0.90** |

- **Small models (4–8B):** self-hosting recovers cost at **$0.10–0.31/1M** even
  *saturated* (A2000…V100), vs SaaS **$0.02–0.10**. At realistic PoC utilization
  it's **$1–3/1M** — 10–100× SaaS. Self-hosting small models is a
  **control / privacy / data-sovereignty / learning** play, **never** a price win.
  This is precisely ADR-0028's stated conclusion.
- **70B:** GEX131 only reaches SaaS-parity (**~$1.05/1M**) at **near-saturation**;
  at steady-team 30 % it's **$3.50/1M**, ~4–9× SaaS. The V100 is worse per-token
  (older/slower) but cheaper in absolute cash (§6). So for 70B, the case for
  *either* owned option is **data never leaves your infra** + **predictable flat
  cost** — not beating SaaS on the meter.
- **The crossover:** self-hosting wins on €/token only as utilization climbs.
  GEX131 needs **multi-billion output tokens/month** (≈ saturated) to undercut
  Together's 70B price. Until then, every box here is a sovereignty/latency
  decision dressed as a cost decision — exactly why ADR-0028 insists on truthful
  cost-recovery accounting rather than a flattering $0 or a SaaS-parity fiction.

---

## 8. Decision summary

| Axis | A2000 | 2× 4070 *(own, CM)* | 5× V100 *(own, CM)* | GEX44 | GEX131 |
|---|---|---|---|---|---|
| Max model | 14B Q4 (tight) | 14B (32B-Q4 tight) | **70B Q8** | 14B (32B-Q4 tight) | **70B Q8 / MoE-FP4** |
| 8B named users (~10 %) | ~30–60 | ~200–400 | ~400–600 | ~150–300 | ~1000+ |
| 36-mo TCO | ~€1,332 | **~€1,700** (power only, CM) | **~€5.5k** (CM) / ~€12k (DE) | €6,703 | €32,004 |
| Modern kernels (FP8/FP4) | ✗ | **FP8** | ✗ | FP8 | **FP4+FP8** |
| Managed / warranty | self | self | none | yes | yes |
| Power burden | trivial (70 W) | low (~0.55 kW, **cheap CM**) | **heavy (~1.5 kW, cheap CM**) | trivial | moderate (300 W) |
| Best for | current 4–8B PoC | **≤14B you already own** | owned 70B (cheapest cash) | managed 7–14B scale-up | managed 70B / multi-tenant |

*CM = Cameroon (ENEO €0.16/kWh); DE = Germany (€0.34). 2×4070 / V100 36-mo TCO is electricity-only (capex sunk / parametric — see §6).*

**Recommendation for this platform's trajectory:** keep the **A2000** as the live
Erlangen 4–8B tier (free, measured-good). For **≤14B** workloads, **use the
2×4070 you already run in Cameroon before renting anything** — it's GEX44-class
with 24 GB, and its only marginal cost is ~€50/mo of (half-price) Cameroon power;
GEX44 (€184/mo) is then only worth it for *managed/warrantied* headroom on the
German grid. Only reach for **70B** when a workload demands it — then it's
**cash-vs-capability**: the **5×V100 in Cameroon** is now the **cheapest 70B by a
wide margin** (cheap power drops its 36-mo TCO below GEX44), so pick it if you want
owned + lowest cash and can live with old/slow/no-warranty + Cameroon
reliability; pick **GEX131** if you want it fast, FP4-capable, warrantied and
hands-off. **Don't run small models on the V100** — it's strictly worse than the
A2000/2×4070 you already own except for headroom you won't use, and even at the
cheap Cameroon rate its idle draw is wasted on a 4–8B model.

> **Next action:** (1) drop the eBay **asking price** into §6 (`P`) to lock the V100
> TCO; (2) confirm the V100 **load profile** (idle-heavy vs sustained) for the power
> row; (3) confirm the **4070 variant** (plain 4070 / Super / Ti — TDP 200/220/285 W
> shifts the Cameroon bill). Everything else holds.

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
| **A2000** (8B, DE, owned) | $0 | $40 | 54 %¹ | $72 | **+$32** | **instant** (sunk) |
| **2× 4070** (8B, CM, owned) | $0 | $51 | 100 % | $135 | **+$84** | **instant** (sunk) |
| **GEX44** (8B, DE, rent) | — | $202 | 100 % | $135 | **−$67** | **never** (< ~90 users) |
| **5× V100** (70B, CM, owned) | ~$3,261² | $76 | 45 %¹ | $331 | **+$255** | **~13 mo** |
| **GEX131** (70B, DE, rent) | — | $966 | 100 % | $739 | **−$227** | **never** (< ~78 users) |

¹ *Capacity-capped* — the box saturates (A2000 ~315 M out/mo; V100-70B ~263 M
out/mo) and the overflow spills to SaaS anyway, so its avoided-SaaS plateaus.
² P = €3,000 example; the V100 asking price is still open (§6).

### 9.3 How it scales with team size, and the break-evens

**Net saving $/mo by team size** (negative = SaaS would be cheaper):

| Box | 30 users | 60 users | 100 users | RoI verdict |
|---|---|---|---|---|
| A2000 (8B, owned) | +$27 | +$32 | +$32 (capped) | ✅ instant, but tiny + capacity-bound |
| 2× 4070 (8B, owned) | +$16 | +$84 | +$169 | ✅ **instant, scales — best small-model RoI** |
| GEX44 (8B, rent) | −$135 | −$67 | +$18 | ⚠️ break-even **~90 users** vs budget-8B SaaS |
| V100 (70B, owned) | +$255 → **13 mo** | +$255 → 13 mo | +$255 → 13 mo | ✅ **fast payback** (9 mo @ €2k · 17 mo @ €4k) |
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
  **only box that serves the full 70B volume of a 100-person team** without
  spillover. Below ~78 users it's a capability/SLA buy; above it, it wins outright.

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

### 9.5 RoI verdict

- **≤14B (most dev assistance + all marketing):** the **2×4070 you already own** is
  RoI-positive today; **don't rent GEX44** for this unless you specifically need
  managed/German-grid SLA or you're past ~90 users. Marketing especially is so
  cheap to serve it never justifies new spend.
- **70B (quality-critical dev work):** the **Cameroon V100 pays back in ~9–17
  months** and is the cheapest 70B by far — provided you actually need 70B (else
  compare to 8B SaaS and the case evaporates) and accept its ~27-user throughput
  ceiling. **GEX131** is the answer only when 70B demand exceeds ~78 users or you
  need its speed/FP4/SLA — then it's the sole box that scales.
- **Overarching (ADR-0028's point, in € terms):** versus *budget* SaaS, self-hosting
  is **rarely a price win for small models** — its real return is
  control/privacy/data-residency/no-rate-limits, which this RoI model deliberately
  does **not** price. The two genuine €-RoI plays here are **(1) exploit sunk capex
  (A2000/2×4070) for ≤14B** and **(2) the cheap-power Cameroon V100 for 70B.**

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
