Here’s a good **v1 design doc draft**, followed by a **practical task list**.

---

# Budget-Driven Rate Limiting for LLM Usage — V1

## Purpose

This document describes a first version of budget-driven rate limiting for LLM traffic in the gateway layer.

The goal is to approximate a **shared wallet** model without requiring the backend to support real-time pricing, spend accounting, or dynamic quota derivation yet.

Instead of enforcing real cost consumption, we derive **static per-model limits** from:

* a plan budget
* a pricing table
* a set of approximation rules
* gateway-enforced rate limits

This gives us a predictable and configurable control plane now, while keeping the door open for a later iteration with true usage-based accounting.

---

## Problem Statement

We expose multiple LLMs with different costs and token behaviors.

Examples:

* cheap text models
* expensive reasoning models
* embedding models
* rerankers
* image or multimodal models

We want to provide a plan-level budget, such as:

* Free: `$30/month`
* Pro: `$200/month`

But the backend does not yet support:

* model pricing logic
* actual spend computation
* remaining wallet computation
* dynamic quota derivation

So for the first version, we need a **static approximation** that can be rendered in Helm and enforced by the gateway.

---

## V1 Goal

The v1 goal is to derive **gateway limits** from a **budget abstraction**.

We want users to effectively self-allocate their usage:

* if they use cheaper models, they get more usable tokens
* if they use more expensive models, they consume their allowance faster

In this version, we do not enforce a true dynamic shared wallet.
We approximate it through model-specific static limits derived from the same plan budget.

---

## Non-Goals for V1

This version does **not** attempt to provide:

* real billing accuracy
* true cross-model wallet sharing
* dynamic carry-over of unused model quota
* runtime recomputation of limits
* real-time spend-based throttling
* precise request-cost accounting
* automatic synchronization with provider pricing APIs

Those belong to a later iteration.

---

## End Goal

The longer-term end state is:

* a project or account has a **real shared budget**
* actual provider pricing is tracked
* actual input/output/reasoning/image cost is computed from telemetry or usage events
* the system can enforce:

  * remaining budget
  * hard spend caps
  * dynamic throttling
  * per-tier policy
* gateway limits become an operational safety layer, not the source of truth

In other words:

**V1** = budget-derived static rate limits
**Later** = usage-driven dynamic budget enforcement

---

## Core Idea

We start from a plan budget:

```yaml
plans:
  free:
    monthlyBudgetUsd: 30
```

Then for each model, we define a pricing approximation.

For text-like models, we use weighted pricing:

```yaml
pricing:
  gemini-2.5-flash-lite:
    mode: weighted
    inputPer1M: 0.25
    outputPer1M: 1.50
    avgInputShare: 0.80
    avgOutputShare: 0.20
```

For non-text or special cases, we use a fixed effective price:

```yaml
pricing:
  text-embedding-3-large:
    mode: fixed
    effectivePer1M: 0.13
```

From these, we derive static limits such as:

* daily equivalent tokens
* weekly equivalent tokens
* monthly equivalent tokens
* base tokens per minute
* burst tokens per minute
* optional request-per-minute estimate

These limits are then rendered by Helm into gateway rate-limit policies.

---

## Shared Wallet Approximation

We do **not** define model allocations in v1.

That means we do **not** say:

* 70% of budget goes to model A
* 20% to model B
* 10% to model C

Instead, we define one plan budget and derive, for each model:

> “If the whole daily budget were spent only on this model, how many tokens would that represent?”

This teaches users to self-arbitrage:

* cheap models yield more tokens/day
* expensive models yield fewer tokens/day

This is simpler than allocations and scales better when the catalog contains many models.

---

## Constraints

### 1. Backend constraints

The backend does not yet support:

* pricing tables
* spend tracking
* dynamic cost-based quota enforcement

Therefore, all logic must be static and renderable at deploy time.

### 2. Gateway constraints

The gateway can enforce:

* request-based rate limits
* token-based rate limits
* header-based selectors

But it is not the ideal place for full business logic.

### 3. Helm constraints

Helm can compute static values, but it should not become a business engine.

Helm should:

* normalize config
* compute derived values
* render rate limit resources

Helm should not:

* act as live pricing storage
* simulate runtime usage accounting
* own dynamic wallet logic

### 4. Model diversity

Not all models behave the same way:

* chat/text models
* embeddings
* rerankers
* image models
* multimodal models

So one single pricing schema for all models is too rigid.

### 5. Shared wallet limitation

Since we are deriving per-model static limits from one global budget, this is only an approximation of a shared wallet.

It is possible for users to use multiple models in ways that do not perfectly map to real shared spend.

That is acceptable for v1.

---

## Validation Rules

## Plan validations

Each plan must satisfy:

* `monthlyBudgetUsd > 0`
* `safetyFactor > 0 and <= 1`
* `burstMultiplier >= 1`

Optional:

* `defaultAvgTokensPerRequest > 0`

Example:

```yaml
plans:
  free:
    monthlyBudgetUsd: 30
    safetyFactor: 0.85
    burstMultiplier: 3
```

---

## Pricing validations

Each model entry must define:

* a `mode`
* a valid pricing configuration for that mode

### Weighted mode

Required fields:

* `inputPer1M`
* `outputPer1M`
* `avgInputShare`
* `avgOutputShare`

Rules:

* `inputPer1M > 0`
* `outputPer1M > 0`
* `0 <= avgInputShare <= 1`
* `0 <= avgOutputShare <= 1`
* `avgInputShare + avgOutputShare = 1`

### Fixed mode

Required fields:

* `effectivePer1M`

Rules:

* `effectivePer1M > 0`

### Optional fields

Optional fields may include:

* `kind`
* `avgTokensPerRequest`
* `identifier`
* `enabled`

Rules:

* if `avgTokensPerRequest` is set, it must be `> 0`

---

## Model identifier rule

We should support an `identifier` field so we do not repeatedly redefine the same pricing blocks.

This is especially useful when:

* several public model names share the same pricing behavior
* multiple aliases should map to the same pricing family
* we want one canonical config source and many references

Example:

```yaml
pricingProfiles:
  gemini-flash-lite:
    mode: weighted
    inputPer1M: 0.25
    outputPer1M: 1.50
    avgInputShare: 0.80
    avgOutputShare: 0.20
    avgTokensPerRequest: 1500

models:
  gemini-2-5-flash-lite:
    identifier: gemini-flash-lite

  gemini-2.5-flash-lite:
    identifier: gemini-flash-lite
```

This lets us:

* avoid duplication
* centralize tuning
* hide complexity
* keep templates readable

---

## Recommended Configuration Structure

## High-level structure

```yaml
rateLimitBudgeting:
  enabled: true

  plans:
    free:
      monthlyBudgetUsd: 30
      safetyFactor: 0.85
      burstMultiplier: 3

  pricingProfiles:
    gemini-flash-lite:
      kind: text
      mode: weighted
      inputPer1M: 0.25
      outputPer1M: 1.50
      avgInputShare: 0.80
      avgOutputShare: 0.20
      avgTokensPerRequest: 1500

    gpt-5-mini:
      kind: text
      mode: weighted
      inputPer1M: 2.50
      outputPer1M: 10.00
      avgInputShare: 0.70
      avgOutputShare: 0.30
      avgTokensPerRequest: 1800

    text-embedding-large:
      kind: embedding
      mode: fixed
      effectivePer1M: 0.13
      avgTokensPerRequest: 500

  models:
    gemini-2-5-flash-lite:
      identifier: gemini-flash-lite

    gemini-2.5-flash-lite:
      identifier: gemini-flash-lite

    gpt-5-mini:
      identifier: gpt-5-mini

    text-embedding-3-large:
      identifier: text-embedding-large
```

---

## Derived Fields

For a given plan:

```text
usableMonthlyBudgetUsd = monthlyBudgetUsd * safetyFactor
dailyBudgetUsd = usableMonthlyBudgetUsd / 30
weeklyBudgetUsd = usableMonthlyBudgetUsd * 7 / 30
```

For a model in `weighted` mode:

```text
effectivePer1M =
  avgInputShare * inputPer1M +
  avgOutputShare * outputPer1M
```

For a model in `fixed` mode:

```text
effectivePer1M = effectivePer1M
```

Then:

```text
dailyTokens = dailyBudgetUsd * 1_000_000 / effectivePer1M
weeklyTokens = weeklyBudgetUsd * 1_000_000 / effectivePer1M
monthlyTokensEquivalent = usableMonthlyBudgetUsd * 1_000_000 / effectivePer1M
baseTpm = dailyTokens / 1440
burstTpm = baseTpm * burstMultiplier
```

Optional:

```text
rpmEstimate = burstTpm / avgTokensPerRequest
```

This is only valid if `avgTokensPerRequest` is present.

All values should be rounded down before rendering rate limits.

---

## Implementation in Helm

## Design principle

The Helm layer should hide complexity behind functions.

Instead of spreading formulas across templates, we should centralize logic in helper templates.

That gives us:

* one implementation of the math
* one implementation of validations
* easy reuse
* fewer template errors
* clearer manifests

---

## Recommended helper responsibilities

### 1. Resolve plan config

Function responsibility:

* load the current plan
* validate required fields
* expose normalized values

Example conceptual helper:

* `budgeting.plan`

### 2. Resolve model profile

Function responsibility:

* take a model name
* read its `identifier`
* resolve the actual pricing profile
* validate presence

Example conceptual helper:

* `budgeting.profileForModel`

### 3. Compute effective pricing

Function responsibility:

* branch on `mode`
* validate required fields
* return `effectivePer1M`

Example conceptual helper:

* `budgeting.effectivePer1M`

### 4. Compute derived limits

Function responsibility:

* compute daily/weekly/monthly token equivalents
* compute baseTpm and burstTpm
* compute optional rpm estimate

Example conceptual helper:

* `budgeting.derivedLimits`

### 5. Validation helpers

Function responsibility:

* fail early with readable messages
* prevent rendering broken configs

Example conceptual helpers:

* `budgeting.validatePlan`
* `budgeting.validateProfile`

---

## Why identifiers matter

Identifiers let us separate:

* **public model names**
  from
* **pricing behavior definitions**

Without identifiers, we would duplicate almost identical blocks many times.

With identifiers:

```yaml
models:
  gemini-2.5-flash-lite:
    identifier: gemini-flash-lite
  gemini-2-5-flash-lite:
    identifier: gemini-flash-lite
```

This means:

* one pricing profile
* many model mappings
* less repetition
* less risk of drift

This is especially important with 24 models.

---

## Example Helm rendering approach

The templates should iterate over `models`, not over raw pricing definitions.

Flow:

1. iterate models
2. resolve identifier
3. fetch pricing profile
4. compute effective price
5. compute derived limits for the selected plan
6. render rate-limit rules

That means the complexity is mostly in helpers, not in the main manifest template.

---

## Suggested validations in Helm

Use `fail` aggressively when config is invalid.

Examples:

* missing plan
* missing profile for a model identifier
* invalid pricing mode
* missing required fields
* `avgInputShare + avgOutputShare != 1`
* `monthlyBudgetUsd <= 0`
* `effectivePer1M <= 0`

This prevents silent bad renders.

Because Helm number handling can be awkward, it is okay to use small normalization helpers and strict conventions for numeric values.

---

## V1 Enforcement Strategy

We can render at least two kinds of limits:

### 1. Project + model token limits

This is the main budget approximation.

It answers:

* “How much of this model can a project use within the derived envelope?”

### 2. API key + model request limits

This is burst protection.

It answers:

* “Is this key too noisy right now?”

Optional later:

* account + model hard caps
* user + model fairness caps

But for v1, project + model and api-key + model are enough.

---

## Tradeoffs

### Advantages

* simple to deploy
* plan-driven
* model-aware
* no backend pricing engine required
* easy to reason about
* scalable to many models with identifiers

### Limitations

* not true spend enforcement
* not a real shared wallet
* depends on approximated pricing and request profiles
* request-per-minute estimates are only as good as `avgTokensPerRequest`
* special model families may still need overrides

---

## Future Evolution

Later, this system can evolve toward:

* provider-accurate pricing tables
* telemetry-driven average request profiles
* real remaining budget computation
* OTEL/Phoenix-based cost analytics
* dynamic policy derivation in backend/authz
* gateway as enforcement layer only

At that point:

* Helm remains useful for defaults
* but real quotas come from runtime state

---

# First Version Task List

## 1. Define the configuration schema

Create a clear values schema for:

* `plans`
* `pricingProfiles`
* `models`
* optional global defaults

Deliverable:

* documented `values.yaml` contract

---

## 2. Add model identifiers

Introduce `identifier` support in model entries so model names can reuse shared pricing profiles.

Deliverable:

* model-to-profile mapping mechanism

---

## 3. Implement pricing modes

Support at least:

* `weighted`
* `fixed`

Deliverable:

* helper logic to resolve effective price per 1M tokens

---

## 4. Implement plan normalization

Add helper logic for:

* `usableMonthlyBudgetUsd`
* `dailyBudgetUsd`
* `weeklyBudgetUsd`

Deliverable:

* normalized plan helper

---

## 5. Implement derived metric helpers

Add helper functions to compute:

* `effectivePer1M`
* `dailyTokens`
* `weeklyTokens`
* `monthlyTokensEquivalent`
* `baseTpm`
* `burstTpm`
* optional `rpmEstimate`

Deliverable:

* single reusable derived-limits helper

---

## 6. Add strict validations

Implement validation helpers with `fail` for:

* missing plan
* missing identifier target
* invalid pricing mode
* invalid shares
* non-positive prices
* invalid budget parameters

Deliverable:

* fail-fast rendering

---

## 7. Refactor templates to hide complexity

Move all math and branching into `_helpers.tpl` functions.

Main templates should only:

* iterate models
* call helper functions
* render final policy

Deliverable:

* readable policy templates

---

## 8. Render project-level token rate limits

Generate token-based limits using:

* selected plan
* resolved model profile
* derived burst/base values

Deliverable:

* project + model token limit rules

---

## 9. Render api-key burst request limits

Generate request-per-minute limits per model using:

* fixed plan default
  or
* derived `rpmEstimate` where present

Deliverable:

* api-key + model request burst rules

---

## 10. Document model family guidelines

Write conventions for how to configure:

* text/chat models
* embedding models
* rerankers
* image models
* multimodal models

Deliverable:

* configuration guidance for all 24 models

---

## 11. Add example plan bundles

Provide example values for:

* free
* pro
* enterprise

Deliverable:

* reusable example configurations

---

## 12. Add test cases for render output

Create Helm test cases or snapshot-style render checks for:

* valid weighted model
* valid fixed model
* alias via identifier
* invalid share sum
* missing profile
* invalid plan config

Deliverable:

* confidence in rendering behavior

---

## 13. Expose derived values for debugging

Optionally render computed values as annotations or comments during development, or output them in helper debug templates.

Deliverable:

* easier troubleshooting of pricing math

---

## 14. Prepare for future OTEL/Phoenix integration

Document which derived fields will later be replaced by real telemetry-driven values.

Deliverable:

* clean migration path to runtime cost enforcement

---

# Suggested Minimal V1 Scope

If you want the smallest good first version, do only this:

1. plan schema
2. pricing profiles
3. identifiers
4. weighted + fixed modes
5. fail-fast validation
6. derived limit helpers
7. project/model token limits
8. api-key/model request burst limits
9. examples and docs

That is enough to ship something useful without overbuilding.

---

# Final Design Principle

The key design principle for this work is:

> keep the values expressive, keep the templates small, and hide all derivation complexity behind helper functions and identifiers.

That gives you:

* less duplication
* safer config
* easier maintenance
* easy extension toward real cost tracking later

If you want, I can also turn this into a concrete `values.yaml` proposal plus the Helm helper function layout.
