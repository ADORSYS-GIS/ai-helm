# ADR-0028: Price owned-hardware (self-hosted) models at cost-recovery, derived from a documented €/hour TCO

**Status:** Accepted
**Date:** 2026-06-07
**Deciders:** @stephane-segning

## Context

ADR-0022 federated the first self-hosted model (Qwen3-4B on the home RTX A2000)
into the gateway and set its catalog price to **flat $0** ("owned hardware, no
marginal SaaS cost"). That made the model invisible to the platform's cost
machinery: the Envoy AI Gateway `llm_custom_total_cost` CEL emitted `0`, so
budgets (ADR-0021), metering, and any make-vs-buy comparison were meaningless for
it. Owned hardware is **not** free — the GPU/CPU/RAM depreciate and draw power
whether or not a token flows. With more self-hosted models/agents planned, we need
a **repeatable** way to price them that reflects real cost, not $0. The inputs are
known and local (this is the maintainer's box in Erlangen, Germany): an A2000 12GB
(launch MSRP $449), an i7-14700KF (28 threads), Corsair DDR4-3200, German 2026
household electricity (~€0.34/kWh).

## Decision

**Price every owned-hardware model at cost-recovery, derived from a documented
€/hour total-cost-of-ownership (TCO), using the `weighted` pricing strategy.** The
method, applied per model:

1. **Compute €/hour TCO** = amortized capex + power. Capex: GPU charged **100%**
   (dedicated); CPU and RAM charged by the **pod's maximum resource caps** (e.g.
   3 vCPU of 28 threads, 6 GiB), amortized over a **3-year** continuous horizon.
   Power: attributed component draw at the wall × the local kWh price. For
   Qwen3-4B this is **≈ €0.05/hour while serving** (full derivation:
   `docs/self-hosted-model-serving.md` §13).
2. **Map €/hour → per-token** at **realistic (low/bursty) utilization**, not the
   saturated-marginal floor — capex accrues even while the model is scaled to
   zero. Split across `weighted` so **decode (`outputPer1M`)** carries the cost,
   **prefill (`inputPer1M`)** is cheaper, and an **LMCache prefix hit
   (`cachedInputPer1M`)** is near-free. Qwen3-4B ships at **$1.00 / $0.15 / $0.03
   per 1M** (out / in / cached).
3. **Treat every number as a documented knob.** Re-tune as real utilization data
   arrives, or as the hardware/electricity inputs change.

This amends only the *pricing* aspect of ADR-0022; everything else there (cluster-
local exposure, the Caddy auth-proxy, `homeCluster: true`) stands.

## Consequences

**Positive**
- Budgets (ADR-0021), token metering, and dashboards now reflect real cost for
  self-hosted models — no more `0` hole in the accounting.
- A single repeatable recipe for model #2..N (the §14 checklist references this).
- Honest make-vs-buy signal: the derivation makes plain that at PoC scale
  self-hosting a small model is a control/learning play, not a price win.

**Negative**
- The price is an **estimate** built on assumed utilization; until real usage
  data exists it can over- or under-recover. Mitigated by documenting every input
  as a knob and committing to re-tune.
- Internal users now see a non-zero price for the self-hosted model (could nudge
  traffic toward cheaper SaaS). Acceptable — the point is truthful accounting.

**Neutral / follow-ups**
- When utilization data lands, revisit the $1.00/$0.15/$0.03 split.
- If a future model runs on hardware shared with other GPU workloads, the "GPU
  charged 100%" rule needs a sharing fraction (note it in that model's §13 row).

## Alternatives considered

- **Keep flat $0** (ADR-0022's original stance) — rejected: hides real cost,
  breaks budgets/metering, and gives no make-vs-buy signal. The maintainer
  explicitly asked for a real price.
- **Marginal-at-saturation price** (~$0.30/1M out, treating capex as sunk) —
  rejected as the *default*: it systematically under-recovers because the GPU is
  idle most of the time on a PoC, while capex accrues continuously. Kept as the
  documented lower bound.
- **SaaS-parity price** (match DeepInfra-class ~$0.02–0.05/1M) — rejected:
  under-recovers true cost and just imports someone else's economics; defeats the
  purpose of measuring our own.
- **`flat` strategy (one blended per-token price)** — rejected: it can't reward
  LMCache prefix-cache hits or reflect that decode dominates GPU time; `weighted`
  already exists in `charts/ai-model` and models this correctly.
- **Bill per GPU-hour instead of per-token** — rejected: the gateway meters and
  budgets in tokens (`llm_custom_total_cost` micro-USD); a per-hour charge
  wouldn't integrate with ADR-0021 and users don't reserve GPU-time.

## Related

- Docs: [`docs/self-hosted-model-serving.md`](../self-hosted-model-serving.md) §13 (the €/hour → per-token derivation) + §14 (the per-model checklist)
- Charts/files: `charts/ai-models/values.yaml` (`qwen3-4b-local` → `pricing.strategy: weighted`), consumed by `charts/ai-model` `costExpression` CEL
- Builds on / amends: ADR-0022 (self-hosted GPU model — pricing only), ADR-0021 (the budget/metering machinery this feeds), ADR-0012 (`ai-model` pricing strategies)
