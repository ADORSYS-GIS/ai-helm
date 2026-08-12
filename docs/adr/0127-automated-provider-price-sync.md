# ADR-0127: Sync model prices from the providers' own APIs on a six-hour schedule

**Status:** Accepted
**Date:** 2026-08-12
**Deciders:** @stephane-segning

## Context

Every model in the catalog carries a per-1M price (`pricing.standard.*`). These
are not documentation: they are the coefficients of the `llm_custom_total_cost`
CEL expression the gateway evaluates on every request (`charts/ai-model`), so
they drive the monthly budget rate-limit (ADR-0021), the per-user cost
dashboards, and the €/hour cost-recovery comparison for self-hosted models
(ADR-0028).

They are also transcribed by hand from provider price pages, and providers move
them. A stale price fails silently in the worst possible way: nothing errors,
every request is simply billed against the wrong budget, and the drift compounds
until someone happens to re-read a price page. Measuring the catalog against
DeepInfra's live API on 2026-08-12 found **39 drifted price fields across 16
models** — GLM-5.2 was ~20% high on every axis, DeepSeek-V4-Flash-0731 ~11%,
Kimi-K2.7-Code ~8% — i.e. those users' budgets had been consuming faster than
their real spend for weeks.

Two providers were assessed as machine-readable sources:

- **DeepInfra** publishes `https://api.deepinfra.com/models/list` — unauthenticated,
  one request for its whole catalog, with `cents_per_input_token`,
  `cents_per_output_token`, `rate_per_input_token_cached` (a ratio) and
  `rate_per_service_tier_priority`. It backs 24 of the 27 SaaS entries.
- **Fireworks** does not, and this was checked properly rather than assumed:
  against the live API with a real key, `serverlessModes` — the only documented
  pricing path (`gatewaySKUInfo`, docs.fireworks.ai/api-reference/get-model) —
  returns **empty** from get, list and `?readMask=*` alike; the
  `/serverlessModes` sub-resource 404s; `/inference/v1/models` carries no price
  fields. Fireworks bills by parameter-count tier off a marketing page.

ADR-0126 having moved the catalog into `ai-helm-values`, a bot can write it.

## Decision

**Adopt a scheduled job in `ai-helm-values` that reads the providers' price APIs
every six hours and commits any drift straight to `main`.**

- `tools/update-model-prices.py` + `.github/workflows/model-prices.yml`
  (cron `0 */6 * * *`, plus `workflow_dispatch` with a `dry_run` input).
- **DeepInfra only.** Fireworks (`qwen3-embedding-8b`, `qwen3p7-plus`), Google AI
  Studio and the self-hosted fleet stay hand-maintained — and are *listed as
  unmanaged in every run's summary*, so the gap is stated rather than inferred
  from silence.
- Which models it owns is **derived from the catalog**, not from a parallel list:
  a model is managed when all its `backends[].ref` resolve to backends on one
  provider host with one agreed `modelNameOverride`. An entry can opt out with
  `pricingAutoUpdate: false`.
- The derivation reproduces the conventions the hand-maintained values already
  encoded: `$/1M = cents_per_token × 10⁴`; cached = input × the published cache
  ratio, or input where none is published; × the priority multiplier, because
  every DeepInfra backend forces `service_tier: priority`. Where the API reports
  no priority rate the model does not support the tier and DeepInfra bills
  standard — we still multiply by 1.5, deliberately over-estimating, because the
  number feeds a budget and a budget that trips early is safe while one that
  trips late is not. Embeddings and rerankers (`type: input_tokens`) get no
  multiplier: the `service_tier` body field is ignored on those endpoints.
- **The write is line surgery on price scalars only.** The catalog is 1,700 lines
  of hand-written comments, anchors and merge keys; a YAML round-trip would
  reflow all of it. Before writing, the script asserts that the set of changed
  lines is exactly the set it intended to change, then re-parses the result and
  checks each value. Anything else — network, parse, verification — writes
  nothing.
- Failure policy: a *deprecated* upstream still has a price, so it is updated and
  warned about. An upstream the provider no longer lists at all is an error that
  turns the run red — but only after the prices that did resolve are committed.

## Consequences

**Positive**

- Prices track reality within six hours instead of within however long it takes
  someone to re-read a price page, and every change lands as a reviewable commit
  with a per-field old → new → Δ table.
- The catalog stops being a place where drift can hide. The first run alone
  corrects 39 fields.
- Free deprecation early-warning: the same payload flags upstreams DeepInfra is
  retiring. It already found three live entries pointing at models deprecated in
  July — `minimax-m2p5`, `ornith-1p0-35b` and `adorsys-frontend` (Nemotron-3) —
  none of which anything else in the fleet was watching.

**Negative**

- **A bot writes to `main` in the deploy repo unattended**, which in this fleet is
  a live deploy. Mitigated by scope (price scalars only), the write-refusal
  assertions, and a `helm template` gate before the push — not by review. Accepted
  because the alternative failure (silent mis-billing) is worse and unbounded,
  while this one is bounded and visible in `git log`.
- A provider price cut immediately loosens everyone's effective budget and a rise
  tightens it, with no human in the loop. That is the intended behaviour, but it
  does mean budget headroom now moves on its own.
- The uniform priority-multiplier rule changes two disabled entries that had been
  hand-set inconsistently (`claude-sonnet-5` +50%, `claude-fable-5` cached
  1.50 → 15.00 where no cache ratio is published). No live effect; both are
  `enabled: false`.
- One more scheduled job to notice when it goes red, in a repo whose other
  automated commits (argocd-image-updater) nobody watches closely.

**Neutral / follow-ups**

- Fireworks stays manual until it publishes a price source. If that stays true,
  the cleaner fix is to stop routing through Fireworks rather than to scrape it.
- The script has no state, so "a price we corrected yesterday moved back today"
  is invisible except in `git log`. Fine for now; a flapping price would show up
  as repeated commits.
- Google AI Studio (`gemini-3p1-flash-lite`) may be worth revisiting — the
  Gemini pricing page is structured, but it is a page, not an API.

## Alternatives considered

- **A separate machine-owned prices file merged over the catalog** — attractive
  because a fully generated file cannot be mangled, and rejected because it
  duplicates every price across two files. That is precisely the duplicated-list
  drift pattern that has bitten this fleet's release pipeline before, and it also
  needed a `charts/apps` change to inject a second `valueFiles` entry.
- **A YAML round-trip with `ruamel.yaml`** — rejected. It preserves comments in
  the common case, but "in the common case" is not a property you want in an
  unreviewed six-hourly write to a file whose comments carry most of its
  operational knowledge. Line surgery plus an assertion that nothing else moved
  is strictly stronger.
- **Open a PR instead of committing to main** — rejected by the request, and on
  merit: a PR that nobody merges is a stale price with extra steps. The
  verification is what makes the direct commit safe, not the presence of a human.
- **Scrape the Fireworks pricing page** — rejected. A marketing page parsed on a
  six-hourly schedule is a worse source than a human edit, and it would fail
  quietly in exactly the way this ADR exists to prevent.
- **Ship the 39-field correction in the same commit as the move** — rejected. The
  move is provably render-neutral and was kept that way; the repricing lands as
  the bot's own first commit, where it is visible as a pricing change rather than
  buried in a 2,000-line file move.

## Related

- Docs: `ai-helm-values/docs/model-price-automation.md` (the *how*)
- Values repo: `tools/update-model-prices.py`,
  `.github/workflows/model-prices.yml`, `environments/prod/values/models.yaml`
- Depends on: ADR-0126 (the catalog is in the values repo)
- Constrains: ADR-0021 (budget rate-limit coefficients), ADR-0028 (cost recovery)
