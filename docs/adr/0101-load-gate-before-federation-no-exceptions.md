# ADR-0101: The load gate has no migration exception — a model is not federated until it is measured

**Status:** Accepted
**Date:** 2026-07-27
**Deciders:** @stephane-segning

## Context

[ADR-0100](0100-image-generation-on-the-gpu-fleet.md) moved Z-Image-Turbo onto the
GPU fleet and **kept it federated through the move**, arguing:

> It is federated anyway, deliberately: users already had this model, so this is a
> *migration* and pulling it while the backend moves would be a visible
> regression. That is a different situation from `qwen3-8b-fast`, which was served
> unfederated until it had been measured.

That reasoning was wrong, and it took two hours to find out.

The repo's standing discipline is that serving and federating are separate steps
precisely so a model can be deployed and measured before any user can reach it —
`tools/check-model-catalogs.sh` treats "served but not federated" as a normal,
expected state and prints it as a note rather than an error. ADR-0100 carved an
exception out of that on the grounds that a migration is not a new offering.

Three things then happened on the first sync, in order:

1. The seed Job was `OOMKilled` four times in six minutes. The fleet's 6 GiB seed
   limit had held for every previous model, but peak seed memory is set by
   **largest shard × concurrent workers**, and this was the first repo with ~10 GB
   shards ([`fix(model-serving)` #792](https://github.com/ADORSYS-GIS/ai-helm/pull/792)).
2. The 45 GiB weights volume then filled to **100%**, with 44 GB in a staging
   directory and the model directories still empty — `hf download --local-dir`
   stages the whole repo before materialising it, so peak disk is ~2× the repo
   ([#793](https://github.com/ADORSYS-GIS/ai-helm/pull/793)).
3. Neither failure was predicted, both were arithmetic that looked sound, and
   **throughout all of it the model was advertised to users** by a gateway route
   pointing at a backend with nothing behind it.

The premise of the migration exception was that federation preserved something.
It did not: the model had never been built, never seeded and never loaded on this
hardware, so what was preserved was a catalog entry that returns errors. The
"visible regression" the exception was protecting against had already happened —
the exception just made it silent instead of explicit.

There is also a third unmeasured number still outstanding. The claim that
Z-Image-Turbo fits the card — ~12.4 GB GPU-resident of 20475 MiB, because the
transformer and VAE load at BF16 while the ~4 GB text encoder stays on the CPU —
is derived from published file sizes and the loader's dtype selection. It is
almost certainly right. It is also the third number in a row derived the same way
as the two that just failed, and it is the one that decides whether the model runs
at all.

## Decision

**Un-federate `z-image-turbo-local` until its load gate passes. The load gate has
no migration exception.**

`charts/ai-models/values.yaml` sets `enabled: false` on the model entry. The
serving catalog entry stays enabled, so the model still deploys, seeds and can be
measured — which is the entire point of the split.

Re-enable it when the report exists in `inference-ops` `docs/benchmarks/`, and
re-derive the price from measured images/hour at the same time (ADR-0096), rather
than shipping the placeholder `$0.005/image` forward.

The general rule, which was already the practice and is now written down:

> **A model is federated when it has been measured on the hardware it runs on.
> Not when it is deployed, not when it worked somewhere else, and not because
> users had it before.**

"It worked on the old hardware" is not evidence about the new hardware. If
anything it is the case that most deserves a gate, because it carries a false
sense of having already been proven.

This **amends ADR-0100's federation choice only**. Everything else there stands:
the `zimage` engine profile, the first-party image, the move off the home GPU,
OpenMythos's retirement, and the four defects fixed on the way in.

## Consequences

**Positive**

- Users stop seeing a model that cannot answer. The failure becomes an operator's
  problem, which is what it always was.
- The rule now has no exception to argue about, which is worth more than the
  exception was. Exceptions to a measurement gate are always justified by
  something that sounds reasonable at the time.
- The remaining unmeasured claim — that it fits 20 GiB — gets tested before it is
  in front of anyone, which is the whole purpose of the gate.

**Negative**

- Image generation is unavailable to users until the gate passes: the image must
  be built and pushed, the weights seeded, and the model measured. That is a real
  outage of a capability people had, and it is the honest cost of the reversal.
- A user-visible capability is now gated on a manual image build with no CI
  (ADR-0100), so "when does it come back" depends on someone doing that.

**Neutral / follow-ups**

- The backend entry stays in place. Nothing routes to it once the model entry is
  disabled — the `AIGatewayRoute` goes with the model — so it costs one unused
  `AIServiceBackend` CR and makes re-federating a single flag.
- ⚠️ `check-model-catalogs.sh` therefore still counts this model as "federated",
  and does **not** print its served-but-unfederated note. Its invariant is
  backend→server and it keys on **backends**, not on model entries. That is not a
  gap in the invariant it enforces (a backend with no server is still caught), but
  it does mean the checker is not a witness to *this* decision — do not read a
  green run as confirmation that a model is properly gated.

## Alternatives considered

- **Leave it federated and fix forward.** Rejected: it was already failing for
  users, and the argument for keeping it ("they had it before") describes a
  service they were not actually receiving.
- **Roll back ADR-0100 entirely** and put OpenMythos back. Rejected as
  over-correction — nothing about the engine profile, the image or the retirement
  was implicated. Two bad size estimates were, and both are fixed.
- **Keep the exception but write the gate as a follow-up ticket.** Rejected. This
  *was* a follow-up ticket, in `docs/migrations/2026-07-27-gpu-fleet-followups.md`
  §2.5, while the model was live. A gate that runs after users are exposed is not
  a gate.

## Related

- Amends [ADR-0100](0100-image-generation-on-the-gpu-fleet.md) (federation timing
  only); reinstates the discipline in [ADR-0094](0094-generic-model-serving-orchestrator.md)
  and `tools/check-model-catalogs.sh`
- Pricing to be re-derived per [ADR-0096](0096-gex44-fleet-cost-recovery-pricing.md)
- The gate itself: `inference-ops` `docs/how-to/measure-a-model.md` §8
- The two failures that prompted it: PRs #792, #793
