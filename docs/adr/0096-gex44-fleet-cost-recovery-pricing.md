# ADR-0096: Cost-recovery pricing for the rented GEX44 GPU fleet

**Status:** Accepted
**Date:** 2026-07-26
**Deciders:** @stephane-segning

## Context

[ADR-0028](0028-owned-hardware-model-pricing.md) requires every self-hosted model
to be priced at **cost-recovery from a documented €/hour TCO**, never flat $0, so
budgets (ADR-0021), metering and make-vs-buy comparisons stay meaningful. Its
worked example is the **owned** home A2000 box: amortized capex over three years
plus German household electricity, ≈ **€0.05/hour**.

Every input to that derivation is wrong for the new fleet. The two GPU nodes are
**rented Hetzner Robot dedicated servers**, not owned hardware:

| | Home A2000 (ADR-0028) | GEX44 fleet (here) |
|---|---|---|
| Ownership | owned, capex amortized over 3 y | **rented monthly** |
| Power | attributed draw × €0.34/kWh | **included in the rent** |
| GPU | RTX A2000 12 GB | RTX 4000 SFF Ada 20 GB |
| Sharing | CPU/RAM shared with other workloads, charged by pod caps | **whole server dedicated to one model** |

Rented hardware makes the arithmetic *simpler* — there is no depreciation schedule
to model and no electricity to attribute — but it is a different formula, and the
first model on the fleet (OpenMythos-27B) needs a price before it can be federated.

The node specification was verified live (`i5-13500`, 20 threads, 64 GiB,
RTX 4000 SFF Ada) and matches Hetzner's published **GEX44**, documented in
[`../patterns/2026-06-08-gpu-platform-procurement-comparison.md`](../patterns/2026-06-08-gpu-platform-procurement-comparison.md)
at **€184/month, power included**.

## Decision

**Keep ADR-0028's cost-recovery principle and `weighted` strategy; replace its TCO
formula for rented nodes with:**

```
€/hour = monthly rent ÷ 730 hours
```

No capex amortization, no power term, no per-pod CPU/RAM apportionment — a model
owns its whole node, because one model owns one GPU and the node has one GPU.

For the GEX44 fleet: **€184 / 730 = €0.252/hour**, i.e. **5× the A2000 basis**.

Mapping €/hour → per-token, per ADR-0028 step 2, using the **measured** decode rate
rather than an assumed one ([load-gate report](https://github.com/ADORSYS-GIS/inference-ops/blob/main/docs/benchmarks/2026-07-26-openmythos-27b-q4k-rtx4000-ada.md),
15.05 tok/s):

```
saturated floor = €0.252/h ÷ (15.05 tok/s × 3600) = €4.65 per 1M output tokens
```

ADR-0028 prices at *realistic (low/bursty)* utilization, not the saturated floor,
because the rent accrues whether or not a token flows. The existing Qwen3-4B entry
implies that multiplier: €0.05/h at ~52 tok/s is a €0.267/1M floor, shipped at
$1.00/1M ≈ €0.92 — a **≈3.45× uplift (~29 % assumed duty cycle)**. Reusing it for
consistency, and keeping ADR-0028's `1 : 0.15 : 0.03` out/in/cached split:

| | per 1M tokens |
|---|---|
| `outputPer1M` | **$17.00** |
| `inputPer1M` | **$2.55** |
| `cachedInputPer1M` | **$0.50** |

**These numbers are honest and they are high.** A 27B at 15 tok/s on a €184/month
rented card costs roughly an order of magnitude more per token than the SaaS
frontier models in the same catalog. That is not a reason to fudge the price — it
is exactly the make-vs-buy signal ADR-0028 exists to surface. Two independent
factors compound: the hardware costs 5× per hour, and the model produces tokens
3.5× more slowly than the 4B it replaces.

**Worked a second time, for the fast tier** (Qwen3-8B-AWQ, measured 45 tok/s on
the same €0.252/h node):

```
saturated floor = €0.252/h ÷ (45 tok/s × 3600) = €1.56 per 1M output
× 3.45 uplift ⇒ €5.38/1M ⇒ $5.85 / $0.88 / $0.18  (out / in / cached)
```

Same hardware cost, three times the token rate, one third of the price. That the
formula reproduces that relationship without special-casing is the point of
anchoring on a **measured** rate: a slow model is expensive because it is slow,
and the catalog says so in the only units users act on.

Every input remains a documented knob, re-tuned as real utilization data arrives.

## Consequences

**Positive**

- Rented-node pricing is a two-input formula (rent, measured tok/s) instead of a
  capex model with assumptions about depreciation and electricity.
- The price is anchored to a **measured** token rate, not an estimate.
- Budgets and dashboards show a truthful figure. The free tier's $50/month buys
  ~2.9M output tokens on this model, which is a real and visible constraint.
- Makes the economics of *slow* models explicit: halving tok/s doubles the price.

**Negative**

- The model will look expensive next to SaaS entries and users may avoid it. That
  is the accounting working, not failing — but it should be a conscious choice,
  not a surprise in a dashboard.
- The ~3.45× utilization uplift is inherited from the A2000 precedent, not measured
  on this fleet. If real duty cycle turns out much higher, we over-recover.
- `inputPer1M` at the inherited 0.15 ratio is **conservative-high**: measured
  prefill (625 tok/s) is ~41× decode, so physics would justify ~0.024. Kept for
  consistency with the existing catalog; worth revisiting fleet-wide.

**Neutral / follow-ups**

- ⚠️ **€184/month is Hetzner's published list price, not a confirmed invoice.**
  Setup fees, IPv4 charges or negotiated rates would shift every number
  proportionally. Confirm against billing and re-tune.
- The second, idle node costs the same €184/month while serving nothing. Idle
  capacity is not attributed to any model's price — it is a fleet-utilization
  question, not a per-token one.
- Revisit when real utilization data exists, or if the fleet moves back to owned
  hardware (in which case ADR-0028's original formula applies again).

## Alternatives considered

- **Reuse ADR-0028's capex formula with a notional purchase price** — rejected as
  fiction: we do not own the hardware and would be amortizing a number we never
  paid, while ignoring the rent we do.
- **Price at the saturated floor (~$5/1M)** — rejected: it under-recovers whenever
  the model is idle, which is most of the time, and ADR-0028 explicitly rejects the
  saturated-marginal floor for that reason.
- **Match a comparable SaaS price** — rejected: it destroys the make-vs-buy signal
  and quietly subsidises self-hosting from somewhere else in the budget.
- **Keep flat $0** — rejected by ADR-0028 already; it puts a hole in the accounting.

## Related

- Extends [ADR-0028](0028-owned-hardware-model-pricing.md) (principle unchanged,
  TCO formula replaced for rented nodes)
- [ADR-0094](0094-generic-model-serving-orchestrator.md) / [ADR-0095](0095-cluster-local-model-federation.md) — the fleet this prices
- [`../patterns/2026-06-08-gpu-platform-procurement-comparison.md`](../patterns/2026-06-08-gpu-platform-procurement-comparison.md) — the €184/mo source
- Measured inputs: `inference-ops` `docs/benchmarks/2026-07-26-openmythos-27b-q4k-rtx4000-ada.md`
