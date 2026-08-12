# ADR-0128: Price self-hosted models nominally, abandoning cost recovery

**Status:** Accepted
**Date:** 2026-08-12
**Deciders:** @stephane-segning

## Context

Every model the gateway routes carries a per-token price that becomes the
`llm_custom_total_cost` CEL coefficient, and that number is what consumes a
user's monthly budget (ADR-0021). For SaaS models the price is the provider's,
now synced automatically (ADR-0127). For the models we serve ourselves it was a
**cost-recovery derivation**: the node's €/hour TCO divided by measured
throughput, with a duty-cycle uplift (ADR-0028, basis corrected twice —
ADR-0096, then ADR-0104). That produced `qwen3-5-2b-local` at $0.47/$0.09/$3.10
per 1M and `z-image-turbo-internal` at $0.0100/image.

The derivation was internally consistent and still produced the wrong incentive.
The GPU fleet is two Hetzner Robot machines on a monthly bill: **it costs the
same whether it is idle or saturated**. Marginal cost per request is
approximately zero, and unused capacity is not refunded. Charging a user's
shared monthly budget at cost-recovery rates therefore made the hardware we have
already paid for *more expensive to the user than several SaaS models* — the
cost-recovery price of `qwen3-5-2b-local` was ~8× DeepInfra's GLM-4.7-Flash — so
the budget mechanism actively steered traffic off our own GPUs and onto invoices
we then have to pay again. Cost recovery only makes sense where capacity is
elastic and idle time is refundable; ours is neither.

## Decision

**Price self-hosted models nominally — a token charge, explicitly not derived
from anything — and abandon cost recovery for the fleet.**

- Text (weighted): `0.001 / 0.0002 / 0.005` per 1M (in / cached / out).
- Image (flatPerRequest): `0.00001`/request — 10 micro-USD.
- Applied to all five self-hosted entries, including the three disabled legacy
  ones, so a re-enabled model cannot come back carrying an old cost-recovery
  price.

Roughly two orders of magnitude below the cheapest SaaS entry, so routing to our
own hardware is always the cheapest option available to a user.

**Nominal, not zero, and that distinction is the decision.** Zero would make
self-hosted usage indistinguishable from "no data" in the cost dashboards, and
would leave the budget machinery evaluating a constant. A small non-zero charge
keeps the `llm_custom_total_cost` series alive, keeps every downstream query and
rate-limit rule working unchanged, and still lets a runaway client be seen.

⚠️ **There is a floor.** The weighted and flat branches render coefficients with
`%.4f`, so any price below ~0.00005 collapses to `0.0000` in the emitted CEL and
becomes silently free. The chosen values sit an order of magnitude above it.
`flatPerRequest` does not share the problem (it renders `1.0 * 10.0`), but it has
the opposite trap already documented in `charts/ai-model/_helpers.tpl`: a
decimal-less literal makes the expression uncompilable and stalls the **entire**
Gateway reconcile.

## Consequences

**Positive**

- Using our own GPUs is now unambiguously the cheapest choice, which is the whole
  point of having them. A 10k-in/2k-out request on `qwen3-5-2b-local` costs 20
  micro-USD instead of 10,900 — a $15 free-tier budget buys 750,000 of them
  rather than 1,376.
- Removes a class of misleading precision. The `0.47/0.09/3.10` figures were
  labelled `ESTIMATE @ 100 tok/s — re-derive from measured tok/s` and never were;
  the image price still carried an unverified 3.45× duty-cycle uplift inherited
  from different hardware (ADR-0104). A number honestly labelled *nominal* is
  better than a derived one nobody has re-derived.
- Self-hosted usage stays visible in cost accounting, at ~$0.

**Negative**

- **We no longer recover the fleet's cost through user budgets, and the cost is
  still real** (~€217/month/node). Fleet spend is now purely a platform cost, to
  be justified on its own terms rather than netted against usage.
- Per-user cost dashboards will show self-hosted usage as approximately free.
  That is accurate as *what the user is charged* and misleading as *what the
  platform spends* — the two were previously the same number and are now not.
- A budget can no longer throttle runaway self-hosted usage in practice: 750,000
  requests is not a ceiling anyone will hit. Contention on the two GPUs is now
  managed only by the queue, not by price. If that becomes a problem the lever is
  a per-minute burst rule, not a higher price.
- Cheap enough to be worth abusing if the internal plane is ever less trusted
  than it is today.

**Neutral / follow-ups**

- ADR-0028's derivation method is not deleted, and stays correct for what it was
  for — answering "what does this model cost us to run?" It is simply no longer
  what users are charged. Keep it for capacity and make-vs-buy decisions
  (inference-ops owns those).
- The price sync (ADR-0127) already treats `*.svc.cluster.local` backends as
  unmanaged, so nothing overwrites these; its reason string now says "nominal"
  rather than "cost-recovery".

## Alternatives considered

- **Price at exactly zero** — rejected, narrowly. It expresses the policy most
  honestly, but it erases the distinction between "free" and "no data" in every
  cost panel, and leaves a constant-zero expression in the rate-limit path where
  a future reader cannot tell whether it is deliberate or broken.
- **Drop the cost metadata entirely** (a `pricing.strategy: none` in
  `charts/ai-model` omitting the `llm_custom_total_cost` key) — rejected for now.
  It is the cleanest expression of "not priced", but it removes self-hosted
  requests from cost accounting altogether, requires every Loki/Mimir query that
  unwraps that field to tolerate its absence, and needs the chart merged *before*
  the catalog can use it — the inverse of the usual values-repo-first ordering.
  Worth revisiting if nominal pricing proves noisy.
- **Keep cost recovery and raise budgets to compensate** — rejected: it keeps the
  wrong relative price between our hardware and SaaS, and fixes it with a number
  that has to be re-tuned every time either side moves.
- **Charge cost recovery only above a free allowance** — rejected as complexity
  the rate-limit shape does not support today (plans are flat monthly budgets,
  and the per-model rule is dormant under `sharedBudget.enabled`).

## Related

- Amends: [0028](./0028-owned-hardware-model-pricing.md) (cost-recovery pricing
  for owned hardware) — and, through it, the bases in
  [0096](./0096-gex44-fleet-cost-recovery-pricing.md) / [0104](./0104-gpu-cost-basis-correction.md)
- Constrains: [0021](./0021-burst-budget-billing-and-dual-plane-authconfigs.md) (budget rate-limit)
- Interacts with: [0127](./0127-automated-provider-price-sync.md) (self-hosted stays unmanaged)
- Values repo: `environments/prod/values/models.yaml`, `tools/update-model-prices.py`
