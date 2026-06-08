# GPU platform comparison — local A2000 vs eBay 5×V100 vs Hetzner GEX44 / GEX131

> **Point-in-time procurement analysis (2026-06-08).** A make-vs-buy comparison
> for the *next* self-hosted-model platform, against four candidates. This is a
> dated audit, not a long-lived subsystem guide — the pattern for *how* we serve
> models lives in [`self-hosted-model-serving.md`](./self-hosted-model-serving.md);
> the pricing *method* is **[ADR-0028](./adr/0028-owned-hardware-model-pricing.md)**.
> Re-price if the Hetzner matrix, the eBay listing, or the €/kWh tariff move.

## TL;DR verdict

| If you want… | Pick | Why |
|---|---|---|
| Keep serving 4–8B to a small team at ~zero marginal cost | **Local A2000 (keep)** | Already owned, 70 W, llama.cpp live ([ADR-0032](./adr/0032-llama-cpp-engine-for-self-hosted-models.md)). Cheapest per-token at PoC volume. |
| Managed 7–14B FP8 for more concurrency, pure OpEx | **GEX44 — €184/mo** | Modern Ada FP8, no hardware risk, ~150–300 named users on 8B. Capped below 32B. |
| Owned, on-prem **70B** on a budget, you control the box | **eBay 5×V100** *(if the price is right)* | Only sub-€900/mo route to 70B. **But** power-dominated, no warranty, Volta EOL-track, 16 GB host RAM bottleneck. Plug the asking price into §6. |
| Serious multi-tenant 70B / 100B-MoE, single managed GPU, FP4 | **GEX131 — €889/mo** | Runs everything up to 70B-Q8 / MoE-FP4 on one card, highest throughput, FP4/FP8 native, fully managed. Best €/capability at the top end. |

**Bottom line:** for the current 4–8B workload the **A2000 stays cheapest**; the
honest make-vs-buy signal (per ADR-0028) is that self-hosting small models is a
control/privacy/learning play, **not** a price win until utilization is high.
70B changes the calculus — only the V100 box and GEX131 can serve it, and there
the choice is **owned-but-power-heavy (V100)** vs **managed-fast-warrantied
(GEX131)** at roughly a **2–3× lifetime-cost gap** in the V100's favour, paid back
in hardware risk and electricity.

---

## 1. Scope & sources

Four candidates, one question: *which can serve which models, for how many
users, at what cost?*

| # | Candidate | Kind | Source |
|---|---|---|---|
| 1 | **Local RTX A2000 12GB** | Owned (Erlangen home GPU) | Live in-cluster; [`models/qwen3.5-4b-q4.md`](./models/qwen3.5-4b-q4.md) §6 (measured) |
| 2 | **eBay 5× Tesla V100 16GB** | Owned (refurb "Llama3 KI-Server", seller *biercologne*) | [ebay.de/itm/306748779023](https://www.ebay.de/itm/306748779023) — listing text only; **asking price not captured** |
| 3 | **Hetzner GEX44** | Rented (dedicated) | [hetzner.com/dedicated-rootserver/gex44](https://www.hetzner.com/dedicated-rootserver/gex44/) |
| 4 | **Hetzner GEX131** | Rented (dedicated) | [hetzner.com/pressroom/new-gex131](https://www.hetzner.com/pressroom/new-gex131/) |

> ⚠️ **Two open inputs.** (a) The eBay **asking price** was not retrievable (eBay
> blocks automated fetch); §6 is therefore parametric over €2,000 / €3,000 /
> €4,000 — drop the real number in to lock the table. (b) tok/s and user counts
> below are **engineering estimates** (order-of-magnitude), except the A2000 row,
> which is **measured** on the live box. Treat them as planning figures, not SLOs.

**Global assumptions** (used throughout, all from [ADR-0028](./adr/0028-owned-hardware-model-pricing.md) where applicable):
- Electricity **€0.34/kWh** (German household, Erlangen 2026).
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
| **5× V100** | **€P (unknown)** | **power only** — see bracket below | German €0.34/kWh dominates. |

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

| Axis | A2000 | 5× V100 | GEX44 | GEX131 |
|---|---|---|---|---|
| Max model | 14B Q4 (tight) | **70B Q8** | 14B (32B-Q4 tight) | **70B Q8 / MoE-FP4** |
| 8B named users (~10 %) | ~30–60 | ~400–600 | ~150–300 | ~1000+ |
| 36-mo TCO | ~€1,332 | ~€11–13k | €6,703 | €32,004 |
| Modern kernels (FP8/FP4) | ✗ | ✗ | FP8 | **FP4+FP8** |
| Managed / warranty | self | none | yes | yes |
| Power burden | trivial (70 W) | **heavy (~1.5 kW)** | trivial | moderate (300 W) |
| Best for | current 4–8B PoC | owned 70B on a budget | managed 7–14B scale-up | managed 70B / multi-tenant |

**Recommendation for this platform's trajectory:** keep the **A2000** as the live
4–8B tier (it's free and measured-good). If/when you need **managed headroom for
7–14B** with real concurrency, **GEX44 (€184/mo)** is the low-risk OpEx step. Only
reach for **70B** when a workload demands it — then decide on **cash-vs-capability**:
**5×V100** if you want owned + lowest lifetime cash and can power-manage it;
**GEX131** if you want it fast, warrantied, FP4-capable, and hands-off. **Do not
buy the V100 box for small models** — it's strictly worse than the A2000 you
already own on every axis except headroom you won't use, and its electricity bill
alone exceeds two GEX44s.

> **Next action:** drop the eBay **asking price** into §6 (`P`) to lock the V100
> TCO column, and confirm the **load profile** (idle-heavy vs sustained) to pick
> the right power row. Everything else holds.

---

*Sources:* [Hetzner GPU matrix](https://www.hetzner.com/de/dedicated-rootserver/matrix-gpu/) ·
[GEX44](https://www.hetzner.com/dedicated-rootserver/gex44/) ·
[GEX131 press release](https://www.hetzner.com/pressroom/new-gex131/) ·
eBay listing 306748779023 (5× Tesla V100 16GB, seller *biercologne*; specs from listing text, price not captured) ·
[ADR-0028](./adr/0028-owned-hardware-model-pricing.md) ·
[`models/qwen3.5-4b-q4.md`](./models/qwen3.5-4b-q4.md) §6 (measured A2000 capacity).
