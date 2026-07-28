# ADR-0104: Correct the GPU cost basis — €184/month was wrong, and it under-recovers fleet-wide

**Status:** Accepted
**Date:** 2026-07-28
**Deciders:** @stephane-segning
**Supersedes:** [ADR-0096](0096-gex44-fleet-cost-recovery-pricing.md)

## Context

[ADR-0096](0096-gex44-fleet-cost-recovery-pricing.md) established cost-recovery
pricing for the GPU fleet. Every self-hosted price in `charts/ai-models` derives
from one number in it:

> €184/mo ÷ 730 h = €0.2521/hour

That number was taken from Hetzner's published list price, and
[the follow-ups doc](../migrations/2026-07-27-gpu-fleet-followups.md) §1.4 flagged
it as unconfirmed — "derives from Hetzner's **published list price** for GEX44,
not a confirmed invoice". Checked against the product page, the GEX44 is
**~$234/month ≈ €217/month**.

So the basis is understated by **~€33/month, about 18%**, and because every price
is a linear function of it, **every self-hosted price on the fleet is ~18% low** —
not only the image model that prompted the check.

| | ADR-0096 | Corrected |
|---|---|---|
| Monthly | €184 | **€217** (~$234) |
| €/hour | 0.2521 | **0.2968** |

Two things make this worth an ADR rather than a values edit.

**It is not confined to one model.** `qwen3-8b-fast`'s published prices
(`$0.88 / $0.18 / $5.85` per 1M) were derived from the low basis and are
correspondingly low:

| | Current | Corrected |
|---|---|---|
| `inputPer1M` | $0.88 | **$1.04** |
| `cachedInputPer1M` | $0.18 | **$0.21** |
| `outputPer1M` | $5.85 | **$6.89** |

**The other input in the same formula is also unverified.** ADR-0096 applies a
**3.45× duty-cycle uplift** inherited from the old A2000 deployment — an
assumption about how idle the card is, never measured on this fleet
([follow-ups §2.3](../migrations/2026-07-27-gpu-fleet-followups.md)). One input is
now known wrong and the other is unmeasured, in the same multiplication. Fixing
only the one we happened to check would leave the arithmetic looking more
trustworthy than it is.

## Decision

**Correct the basis to €217/month (€0.2968/hour) and re-derive every self-hosted
price from it.** ADR-0096's *method* stands unchanged — €/hour ÷ measured
throughput × duty-cycle uplift. Only the first term was wrong.

Three commitments that come with it:

1. **Cite an invoice, not a list price.** The basis records where the number came
   from. A published price is a starting point that drifts with currency, setup
   fees and negotiated rates; the next revision should quote billing.
2. **Re-derive, do not scale.** For each model, recompute from its measured
   throughput rather than multiplying the old price by 1.18 — the measurements
   themselves have changed (the image model's step count, for one), and scaling
   would bake a stale numerator into a corrected denominator.
3. **The 3.45× uplift stays flagged, not fixed.** Correcting it needs utilisation
   data from the fleet, which we do not have. It remains the largest unverified
   term in the formula and is recorded as such rather than quietly inherited
   again.

## Consequences

**Positive**

- Prices stop under-recovering by ~18%. On owned hardware that is the difference
  between covering the machine and quietly subsidising it.
- The make-vs-buy signal ADR-0028 exists to produce gets *more* honest, not less:
  self-hosting was already the expensive option for text, and it is 18% more so.
- The basis now carries its provenance, so the next reader can tell a list price
  from an invoice.

**Negative**

- **User-visible price increases** on every self-hosted model. Small in absolute
  terms and defensible, but real, and they land on internal consumers who did not
  cause the error.
- **Every published figure in the catalog and in `inference-ops` is stale until
  re-derived.** This ADR corrects the basis; it does not by itself correct the
  numbers, and a partially-updated catalog is its own hazard.

**Neutral / follow-ups**

- The image model's price must be re-derived after the `step: 25 → 8` change,
  which invalidates the 94.2 s measurement the current figure rests on. Two
  corrections land on that one number at once.
- Worth asking whether a duty-cycle uplift belongs in the formula at all, or
  whether utilisation should be measured and the price recomputed periodically.
  That is a bigger question than this correction.

## Alternatives considered

- **Leave it and note the discrepancy.** Rejected: an 18% error in the one input
  every price depends on is not a footnote, and it had already been flagged once
  and carried forward.
- **Scale existing prices by 1.18.** Rejected — see commitment 2. It would look
  like a correction while preserving stale throughput numbers underneath.
- **Wait for the invoice before changing anything.** Tempting, and rejected
  because the list price is demonstrably closer to reality than €184; being
  approximately right beats being precisely wrong while the meter runs. The
  invoice remains a follow-up.

## Related

- Supersedes [ADR-0096](0096-gex44-fleet-cost-recovery-pricing.md) (basis only;
  method unchanged)
- Method: [ADR-0028](0028-owned-hardware-model-pricing.md)
- Flagged in [`2026-07-27-gpu-fleet-followups.md`](../migrations/2026-07-27-gpu-fleet-followups.md)
  §1.4 (basis) and §2.3 (duty cycle)
- Affects `charts/ai-models/values.yaml` — every `*-local` model
