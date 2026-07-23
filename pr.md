### Type

Research & Analysis

### Summary

We need to **estimate the return-on-investment (ROI) of the entire self-hosted AI infrastructure** on the home RTX A2000 12 GB — the `ai-helm` system spanning hardware (GPU server), all deployed models (Qwen3-4B, Qwen3.5-4B, Z-Image-Turbo, LMCache, Caddy proxies), the cluster ops (Talos, Longhorn, ArgoCD, Traefik), and the gateway integration (Envoy AI Gateway on Hetzner, budgets, metering). The system has been operational for months and now includes 4+ model deployments across LLM and image generation. This ticket quantifies whether the total cost is justified by the value delivered, and at what scale the self-hosted approach breaks even against purely cloud-based alternatives.

Expected result:
> A documented **total-cost-of-ownership (TCO) vs total-cloud-equivalent** analysis covering all models, all infrastructure, and all operational overhead. The analysis answers: "Is the home GPU cluster worth keeping, expanding, or should we migrate to cloud-only?" It produces a decision document stored at `docs/roi/ai-helm-system-roi.md`.

### Intent

The `ai-helm` project was started to give the ADORSYS-GIS team a self-hosted AI inference capability — initially for LLMs (`#648`), then extended to image generation (`#693`+). The hardware (a single RTX A2000 12 GB) is owned and lives on the home cluster (Talos). The system now includes:

| Component | Model | Engine | Purpose |
|---|---|---|---|
| **LLM #1** | Qwen3-4B (disabled) | vLLM + LMCache + Caddy | Text inference (standby, replaced by Qwen3.5) |
| **LLM #2** | Qwen3.5-4B (LIVE) | llama.cpp + LMCache | Primary text inference |
| **Image** | Z-Image-Turbo | Rust/Candle (custom) | Image generation |
| **Gateway** | Envoy AI Gateway | Hetzner | Auth, budgets, rate limits, metering |
| **Storage** | Longhorn RWX PVC | Home cluster | Model weights (pre-seeded) |
| **Auth** | Caddy sidecar (per LLM) + Envoy APIKey | Home cluster + Hetzner | Bearer enforcement |

The question is not "is Z-Image-Turbo worth it" but **"is the whole system worth it"**:

1. **Hardware**: €400 GPU + €?? CPU/RAM/PSU/case — amortized over 3 years = €/h.
2. **Power**: ~150W at the wall (GPU + CPU + disks) × €0.34/kWh (Germany).
3. **Ops**: Time spent writing charts, fixing merge conflicts, debugging CUDA/Candle, updating ArgoCD, responding to alerts.
4. **Cloud equivalent**: What would it cost to run the same workloads via APIs (DeepInfra/OpenAI/Flux)?
5. **Non-monetary value**: Data privacy, no rate limits, full control, learning, the "we can do it" capability.

This ticket is analytical only — it produces a decision document, not a cluster change.

### Source of truth (links)

**Architecture & decisions:**
- ADR-0022: [`docs/adr/0022-self-hosted-gpu-model-federated-into-gateway.md`](../adr/0022-self-hosted-gpu-model-federated-into-gateway.md)
- ADR-0028: [`docs/adr/0028-owned-hardware-model-pricing.md`](../adr/0028-owned-hardware-model-pricing.md) (cost-recovery pricing method)
- ADR-0029: [`docs/adr/0029-self-hosted-model-plain-deployment.md`](../adr/0029-self-hosted-model-plain-deployment.md)
- ADR-0032: [`docs/adr/0032-llama-cpp-engine-for-self-hosted-models.md`](../adr/0032-llama-cpp-engine-for-self-hosted-models.md)
- Self-hosted pattern: [`docs/patterns/self-hosted-model-serving.md`](../patterns/self-hosted-model-serving.md)
- GPU procurement comparison: [`docs/patterns/2026-06-08-gpu-platform-procurement-comparison.md`](../patterns/2026-06-08-gpu-platform-procurement-comparison.md)

**Charts & deployments:**
- LLM: `charts/model-serving-qwen3-4b/`, `charts/model-serving-qwen3-4b/`, `charts/llm-d/`
- Image: `charts/model-serving-zimage-turbo/`
- Gateway integration: `charts/ai-models/values.yaml` (all model backends + pricing)
- Apps: `charts/apps/values.yaml` (ArgoCD Applications, homeCluster)
- Observability: `charts/observability/`, `charts/observability-dashboards/`
- Cost tracking: [`docs/models-chart-docs/cost-tracking.md`](../models-chart-docs/cost-tracking.md)

**Infrastructure:**
- `#648` (Hardware provisioning)
- `#693` / `#718` (Z-Image-Turbo deployment)
- Hardware: RTX A2000 12 GB, i7-14700KF, 64 GB DDR4, Corsair PSU
- Cluster: Talos Linux, Longhorn, ArgoCD, Traefik

**Cloud pricing references (comparison baseline):**
- DeepInfra (LLM): ~$0.15/1M in, $1.00/1M out (Qwen3-4B class)
- OpenAI / DeepInfra (agents): variable per model
- DALL-E 3 API: $0.04/image (Standard 1024×1024)
- Flux Pro 1.1: $0.04–0.06/image
- Self-hosted alternatives: RunPod / Vast.ai / Hetzner cloud GPU rentals

### Current Behavior

**What is known today:**

| Element | Value | Source |
|---|---|---|
| GPU | RTX A2000 12 GB (Ampere) | `#648` |
| GPU launch MSRP | $449 (≈€400) | ADR-0028 |
| Total system power (idle) | ~80W (GPU 15W + CPU 35W + rest) | Estimate |
| Total system power (load) | ~200W (GPU 70W + CPU 120W + rest) | Estimate |
| Electricity cost (Germany 2026) | €0.34/kWh | ADR-0028 |
| GPU amortized (3y × 8760h) | €400 / 26280h = €0.015/h | ADR-0028 |
| Power cost at load | 200W × €0.34/kWh = €0.068/h | ADR-0028 method |
| Total HW + power | ~€0.08/h ≈ €58/month | Running 24/7 |
| DeepInfra Qwen3-4B equivalent | ~$0.50/1M tokens (blended) | DeepInfra pricing |
| DALL-E 3 per image | $0.04/image (Standard) | OpenAI |
| Current z-image price | $0.005/image | `ai-models/values.yaml` |
| Current LLM prices | $0.15–1.00/1M (weighted) | `ai-models/values.yaml` |
| Ops time (estimated) | ~5–10 h/week (charts, debugging, reviews, CI) | Maintainer estimate |

**LIVE models in production:**

| Model | Status | Monthly cost (cloud) | Self-hosted marginal cost |
|---|---|---|---|
| Qwen3.5-4B (LLM) | 🟢 LIVE | ~$30–150/mo (if 1M–5M tokens) | ~€0.08/h (shared) |
| Z-Image-Turbo | 🟢 LIVE | ~$0–40/mo (if 0–1000 images) | ~€0.01/h (marginal power) |
| LMCache | 🟢 LIVE | N/A (no cloud equivalent) | Included in LLM cost |
| Caddy proxies | 🟢 LIVE | N/A | Negligible |

**What is unknown (gaps this ticket fills):**

- **Total €/h TCO** of the full system (hardware + power + ops + storage + networking).
- **Actual power at the wall** under real workload mix (not just GPU TDP).
- **Ops time/cost** — how many hours per week on ai-helm maintenance, at what hourly rate.
- **Real utilisation data** — how many LLM tokens per day, how many images per day, idle ratio.
- **Cloud-equivalent cost** — what would identical workloads cost on DeepInfra + OpenAI + Flux Pro?
- **Sharing fraction** — how much of the TCO is attributable to each workload (LLM vs image vs idle).
- **Non-monetary value** — can we put a € figure on data privacy, capability building, no rate limits?
- **Break-even vs cloud** — at what usage level does self-hosted become cheaper than cloud-only?
- **Expansion signal** — should we buy a 2nd GPU? Rent Hetzner GEX44? Stay as-is?

### Expected Behavior

After this ticket, the following will be **known and documented**:

**1. Full system TCO breakdown (€/month and €/hour)**

| Cost component | €/month | % of total | Notes |
|---|---|---|---|
| GPU amortization (3y) | €11 | 10–15% | €400 / 36 months |
| CPU/RAM/PSU/case amortization (5y) | €10 | 10–15% | Estimated €600 total |
| Electricity (idle) | TBD | TBD | ~80W × 720h × €0.34 |
| Electricity (load surcharge) | TBD | TBD | Extra above idle when GPU/CPU active |
| Storage (Longhorn SSDs) | TBD | TBD | Share of cluster storage cost |
| Networking (Cloudflare, domain) | TBD | TBD | ~€5–10/mo |
| Ops labour (maintainer time) | TBD | TBD | Hours × imputed rate |
| **Total TCO** | **TBD** | **100%** | |

**2. Cloud-equivalent cost (what this would cost as SaaS)**

| Workload | Monthly volume | Cloud cost (SaaS) | Self-hosted cost (TCO share) | Delta |
|---|---|---|---|---|
| LLM inference (all models) | X tokens/mo | $TBD | $TBD | $TBD |
| Image generation | Y images/mo | $TBD | $TBD | $TBD |
| **Total** | | **$TBD** | **$TBD** | **$TBD** |

**3. Break-even analysis**

| Scenario | Self-hosted €/mo | Cloud equivalent €/mo | Verdict |
|---|---|---|---|
| Current usage (low) | TBD | TBD | Self-hosted wins/loses |
| Moderate usage (2× current) | TBD | TBD | Self-hosted wins/loses |
| High usage (10× current) | TBD | TBD | Self-hosted wins/loses |
| Idle system (no active users) | TBD (fixed cost) | €0 (pay-per-use) | Self-hosted loses |

**4. Decision matrix**

| Factor | Weight | Self-hosted score | Cloud score | Notes |
|---|---|---|---|---|
| Monetary cost | 40% | TBD | TBD | From break-even analysis |
| Data privacy | 20% | 10/10 | 3/10 | No data leaves the cluster |
| Control & flexibility | 15% | 9/10 | 4/10 | Fine-tuning, custom pipelines |
| Ops burden | 15% | 4/10 | 9/10 | No server management in cloud |
| Learning & capability | 10% | 10/10 | 2/10 | Team builds infra expertise |
| **Weighted total** | **100%** | **TBD** | **TBD** | |

**5. Recommendation** — one of:
- **Stay self-hosted** — the system delivers positive ROI at current and projected usage
- **Hybrid** — keep the GPU for development/batch, use cloud for production spikes
- **Migrate to cloud** — the ops cost + fixed hardware cost exceed cloud pay-per-use at all realistic volumes
- **Expand** — the ROI justifies a 2nd GPU (or Hetzner GEX44) for more capacity

### Acceptance Criteria

- [ ] Given all cost inputs are collected (HW amortization, power, ops time, storage, networking), when the TCO formula is applied, then a complete monthly € cost of the ai-helm system is documented.
- [ ] Given the system TCO, when it is allocated across workloads (LLM tokens, images, idle time), then a per-unit cost ($/1M tokens, $/image) is derived for each model following ADR-0028 methodology.
- [ ] Given the per-unit costs, when they are compared against DeepInfra/OpenAI/DALL-E 3/Flux Pro API pricing, then a monthly break-even volume is calculated for each workload.
- [ ] Given the monetary analysis, when non-monetary factors are scored (privacy, control, ops burden, learning), then a weighted decision matrix is produced.
- [ ] Given the complete analysis, when it is reviewed by the team, then a documented recommendation is agreed and stored at `docs/roi/ai-helm-system-roi.md`.
- [ ] Given the recommendation, when `ai-models/values.yaml` pricing is reviewed, then any necessary price adjustments are proposed in a follow-up PR.

### Out of Scope

- Benchmarking individual models/providers not deployed in ai-helm (e.g., Claude, Gemini, Midjourney) — only the models actually deployed are compared.
- A/B quality comparison of generated outputs — quality is assumed adequate per each model's published benchmarks.
- GPU procurement decisions — the decision to buy/rent a 2nd GPU or migrate to Hetzner is a separate ticket that uses this analysis as input.
- Detailed breakdown of every chart's individual contribution — system-level TCO is sufficient; per-chart micro-accounting is unnecessary overhead.

### Technical Context

**Hardware (home cluster):**
- 1× RTX A2000 12 GB (Ampere) — primary inference GPU
- 1× Intel i7-14700KF (28 threads) — CPU-offload host
- 64 GB DDR4-3200 RAM — system memory
- Storage: Longhorn (NVMe SSDs) across 3 nodes
- Networking: 1 Gbps consumer fiber (home), Cloudflare tunnel / proxied DNS
- Power: ~80W idle (desktop + GPU), ~200W+ under load

**Total hardware replacement cost (2026):**
| Component | Estimated cost | Notes |
|---|---|---|
| RTX A2000 12 GB | €400–500 | Current eBay / used price |
| i7-14700KF | €350 | |
| 64 GB DDR4 | €120 | |
| PSU + case + MB + SSD | €300 | |
| **Total** | **~€1200–1400** | If building from scratch |

**Workloads deployed:**
- LLM (vLLM/llama.cpp, one model at a time, always-on pod)
- Image (Rust/Candle, always-on pod, shares GPU via time-slicing)
- LMCache (CPU-based KV cache, sidecar to LLM)
- Gateway routes + rate-limit middleware (Envoy on Hetzner, not home cluster)

**Ops burden (notable time sinks from project history):**
- Writing and debugging Helm charts (bjw-template hybrid pattern)
- Rust/Candle compilation + CUDA compatibility
- Merge conflict resolution (FastAPI→Rust migration)
- CI/CD pipeline (commit lint, governance, release-please)
- ArgoCD sync-wave ordering (ExternalSecret → PVC → seed Job → workload)
- Model weight download and pre-seeding
- Debugging inference correctness (scheduler shift bug, device mismatch)

**Valuable non-monetary outputs of the project:**
- Functional OpenAI-compatible image generation API (Rust, custom Candle pipeline)
- Reusable Helm chart pattern (hybrid bjw — documented in `self-hosted-model-serving.md`)
- GPU inference expertise (CUDA, Candle, VRAM budgeting, quantization)
- CI/CD + ArgoCD workflow for model deployment
- Team capability to deploy and operate AI infrastructure independently

**Methodology for allocation (proposed):**

```
System TCO = Hardware_amortization + Power + Storage + Networking + Ops_labour

Workload_A_cost = System_TCO × (Workload_A_GPU_time / Total_GPU_time)
                 + Storage_A + Ops_A

If GPU is idle 80% of the time (realistic for PoC):
  Idle_cost = System_TCO × 0.80   ← unavoidable fixed cost
  LLM_cost  = System_TCO × 0.15   ← LLM inference time
  Image_cost = System_TCO × 0.05  ← Image generation time
```

### Risks

- **No utilisation data yet**: With near-zero production traffic, "expected volume" is speculative. Mitigation: produce a parametric analysis (break-even at multiple volume levels: 100, 500, 1K, 10K, 100K images/tokens per month). The decision flips as data arrives.
- **Ops labour is the hardest input to quantify**: 5 h/week at €50/h = €250/month — potentially 3× the hardware cost. Mitigation: track actual time spent over 2 weeks, use a range (€0 "learning is free" to €100/h "opportunity cost").
- **GPU sharing impact unknown**: Running LLM + image on the same GPU may degrade both. Mitigation: measure throughput with and without concurrent workloads; model the degradation in the analysis.
- **Power measurement without physical access**: The home cluster runs Talos; measuring wall power requires a smart plug or `nvidia-smi` estimates. Mitigation: use component TDP + utilisation as upper bound; note the uncertainty.
- **Comparison drift**: Cloud API prices change frequently (DALL-E 3 deprecated May 2026, replaced by GPT Image 1.5). Mitigation: timestamp all cloud prices used; note that the comparison is valid only as of the analysis date.
- **Overhead of the analysis itself**: The time spent on this ROI analysis is itself an ops cost. Mitigation: keep the document scoped; produce a decision within 2 weeks.

### Test Plan

This ticket is analytical. The "test" is the data collection + derivation:

1. **Collect hardware & power data:**
   - GPU power: `nvidia-smi -q -d POWER` under idle, LLM load, image load
   - System power: estimate from component TDP or measure with a smart plug
   - Record CPU/RAM/Storage share allocated to ai-helm workloads

2. **Collect utilisation data:**
   - LLM: total tokens per day from Envoy AI Gateway metering (last 30 days)
   - Image: total images from server logs (last 30 days)
   - Idle ratio: GPU utilisation % from Prometheus/Grafana

3. **Collect ops time data:**
   - Review git log: hours committed to ai-helm files over the last 2 months
   - Maintainer self-report: average hours/week on ai-helm tasks

4. **Collect cloud pricing:**
   - DeepInfra / OpenAI / Flux Pro current API prices (timestamped)
   - DALL-E 3 / GPT Image 1.5 current API prices

5. **Compute TCO:**
   ```
   System_TCO = ∑(Hardware_amort) + ∑(Power) + Storage + Networking + Ops
   ```

6. **Allocate across workloads:**
   ```
   LLM_share   = System_TCO × (LLM_GPU_time / Total_time)
   Image_share = System_TCO × (Image_GPU_time / Total_time)
   Idle_share  = System_TCO × (Idle_time / Total_time)
   ```

7. **Compute break-even for each workload vs cloud API price.**

8. **Build weighted decision matrix (monetary + non-monetary factors).**

9. **Write decision document** at `docs/roi/ai-helm-system-roi.md`.

### Verification evidence

Baseline (pre-analysis), captured 2026-07-23:
```
4 model-serving charts deployed (qwen3-4b, qwen3-4b, ministral-3b, zimage-turbo)
LLM and image models both operational on single RTX A2000
No systematic TCO/ROI analysis exists for the system
```

Closing evidence:
- Complete TCO spreadsheet/table with all inputs and derivations
- Utilisation data (tokens + images per day from Envoy metering)
- Cloud pricing comparison table
- Break-even analysis chart
- Decision document at `docs/roi/ai-helm-system-roi.md`
- If price changes are needed: linked PR updating `ai-models/values.yaml`

### Human accountable owner

@fossouomartial

### AI Usage Declaration

Research and drafting the analysis framework

### Human verification completed

- [x] I understood the intent
- [X] I checked the source of truth
- [ ] I reviewed all AI-generated text/code
- [ ] I verified the implementation manually
- [ ] I verified the tests
- [ ] I checked for hallucinated assumptions
- [ ] I documented remaining risks
- [x] I am the accountable owner and accept responsibility for this ticket.
