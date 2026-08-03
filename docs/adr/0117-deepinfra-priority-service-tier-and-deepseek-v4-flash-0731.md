# ADR-0117: DeepInfra `service_tier=priority` gateway-wide + retire `deepseek-v4-flash`/`-pro` for `deepseek-v4-flash-0731`

**Status:** Accepted
**Date:** 2026-08-02
**Deciders:** @stephane-segning

## Context

[anomalyco/opencode#12297](https://github.com/anomalyco/opencode/issues/12297)
requests client-side `service_tier` configuration (opencode → OpenAI). DeepInfra
ships the equivalent feature server-side
([deepinfra.com/blog/priority-service-tier](https://deepinfra.com/blog/priority-service-tier)):
adding `"service_tier": "priority"` to a `/v1/chat/completions` (or
`/v1/completions`) request body jumps it to the front of the engine's
scheduling queue under load, billed at **1.5x** the model's standard
per-token rate — but only when the backing engine actually supports it
(vLLM-stack models today; SGLang/TensorRT-LLM rolling out). An unsupported
model silently falls back to standard billing and echoes
`"service_tier": "default"` in the response, so the field is safe to send
unconditionally.

Envoy AI Gateway v1.0.0's `AIGatewayRoute.spec.rules[].backendRefs[].bodyMutation`
(`set`/`remove` on top-level JSON body fields — its own CRD docstring uses
`service_tier` as the worked example) is the mechanism: it lets the gateway
inject the field per backend, independent of what the calling client sends.

Separately, DeepInfra's model page for `deepseek-ai/DeepSeek-V4-Flash-0731`
(deepinfra.com/deepseek-ai/DeepSeek-V4-Flash-0731) is "the official release
of DeepSeek-V4-Flash", outperforming the catalog's existing
`deepseek-v4-pro` on multiple benchmarks despite a smaller parameter count —
making both existing `deepseek-v4-flash` and `deepseek-v4-pro` catalog
entries redundant.

The gateway has no per-caller routing distinction on a model route
(`AIGatewayRoute` backendRefs are per-model, matched only on the
`x-ai-eg-model` header) — so a `bodyMutation` on a backendRef applies to
**every** caller of that model (LibreChat, opencode, internal agents alike),
not just callers who would have opted in themselves.

## Decision

1. **Force `service_tier=priority` gateway-wide, for every caller, on every
   deepinfra-backed model.** Added `bodyMutation.set` (`service_tier` →
   `"priority"`) to the shared `deepinfraBackendPrimary`/`deepinfraBackendSecondary`
   anchors in `charts/ai-models/values.yaml` (`modelDefaults.backendRefs`),
   so it applies uniformly to all 26 deepinfra-backed models without a
   per-model repeat. `charts/ai-model`'s `aigatewayroute.yaml` template
   renders `bodyMutation` (`set`/`remove`) on any backendRef that carries it.
   Rejected the alternative of leaving this to client opt-in — see
   Alternatives.
2. **Bump `pricing.standard` (and any per-model `longContext` tier) 1.5x on
   every deepinfra-backed model**, to keep the gateway's own cost-tracking /
   monthly-budget rate-limit (`BackendTrafficPolicy`, fed by
   `pricing.standard`) matching what DeepInfra will actually bill. Verified
   the flat 1.5x multiplier against DeepInfra's own quoted Priority-tier
   pricing for `Kimi-K2.7-Code` and `DeepSeek-V4-Flash-0731` — both matched
   the computed value exactly. `qwen3-reranker-8b` (disabled) is
   **exempted** from the price bump: priority tier is a chat/completions
   feature, `/v1/rerank` ignores the injected field and bills standard
   regardless.
3. **Retire `deepseek-v4-flash` and `deepseek-v4-pro`; add
   `deepseek-v4-flash-0731`** (`deepseek-ai/DeepSeek-V4-Flash-0731`,
   1,048,576-token context, 131k max output, priced at DeepInfra's confirmed
   Priority-tier rate $0.135 / $0.027 / $0.27 per 1M). Repointed
   `adorsys-researcher`'s backing from `deepseek-ai/DeepSeek-V4-Flash` to the
   new release at the same pricing. Updated
   `charts/librechat-opencode-wellknown` (opencode well-known
   `reasoningEffort` caps) to match: dropped the `deepseek-v4-pro` entry,
   renamed `deepseek-v4-flash` → `deepseek-v4-flash-0731`.

## Consequences

**Positive**
- Every deepinfra-backed model gets DeepInfra's queue-priority treatment
  under load — fewer HTTP 429s during peak traffic for all callers, with no
  per-model wiring required for future additions (new deepinfra models pick
  up `service_tier=priority` automatically via the shared anchor).
- `deepseek-v4-flash-0731` collapses two redundant, weaker catalog entries
  into one stronger, cheaper-per-token model.
- The billing-side risk (undercounting spend against what DeepInfra actually
  bills) is closed by the pricing bump, in the same change — no silent gap
  between what the gateway tracks and what gets invoiced.

**Negative**
- **Every caller pays 1.5x on every deepinfra model, whether or not they
  wanted priority.** There is no way to opt out per-request at the gateway
  layer today — a LibreChat user doing routine chat pays the same premium
  as a latency-sensitive opencode agent. Accepted as the simplest uniform
  behavior; see Alternatives for what was traded away.
- For any deepinfra-backed model that does **not** actually support
  priority tier on its current engine (only vLLM-stack models do today —
  unverified per-model here, would require checking each DeepInfra model
  page individually), the 1.5x-bumped `pricing.standard` **overestimates**
  true spend. This is the safe failure direction (our budget rate-limit
  trips earlier than DeepInfra would actually bill, never later — no silent
  overspend), but it means some models' budget consumption is now
  pessimistic until each is individually confirmed.
- `deepseek-v4-flash` and `deepseek-v4-pro` disappear from the catalog. A
  user or agent that had explicitly selected either (not a brand alias)
  must reselect `deepseek-v4-flash-0731` — same acceptable-migration
  precedent as prior catalog consolidations (e.g. ADR-0075's `glm-5`/`glm-5p1`
  retirement).

**Neutral / follow-ups**
- Per-model confirmation of actual DeepInfra priority-tier support (vLLM vs
  SGLang vs TensorRT-LLM backing) is not done here; DeepInfra's own
  documented fallback behavior (silent default-tier billing, echoed in the
  response) is relied on instead of enumerating engines per model.
- If a future need arises to give only some callers priority tier (e.g.
  opencode users specifically), it requires either a distinguishing
  header + a second `AIGatewayRoute` rule per affected model, or per-model
  `-priority` catalog variants (see Alternatives) — not a small change to
  today's shared-anchor shape.
- **Fireworks priority tier — investigated, deliberately deferred
  (2026-08-02).** Fireworks supports the identical field
  (`"service_tier": "priority"`, OpenAI-compatible chat completions and the
  Anthropic-compatible `messages` API — docs.fireworks.ai/serverless/serving-paths),
  so the same `bodyMutation` mechanism this ADR uses for DeepInfra would
  drop in directly on the `fwBackendPrimary`/`fwBackendSecondary` anchors.
  Not applied because, checked live against Fireworks' own catalog: (1)
  Priority tier is documented as "available on select models," and neither
  of the two models currently routed through Fireworks —
  `qwen3-embedding-8b` and `qwen3p7-plus` — shows a Priority badge or
  Priority pricing on its own Fireworks model page; (2) unlike DeepInfra,
  Fireworks' docs do not state what happens when `service_tier=priority` is
  sent to a model that doesn't support it — DeepInfra's documented safe
  fallback (standard billing, `service_tier: "default"` echoed) is what
  makes sending the field unconditionally safe there, and that guarantee is
  unverified for Fireworks; (3) `qwen3-embedding-8b` is an `/v1/embeddings`
  model — priority tier is documented only for chat completions and
  `messages`, so the field is likely a no-op there at best. Revisit when
  either current Fireworks model gains a Priority badge on its own page, or
  a new Fireworks-backed chat model is added to the catalog that shows one.

## Alternatives considered

- **Don't force it server-side — let clients opt in** (the literal ask in
  anomalyco/opencode#12297: once opencode ships `serviceTier` config, users
  set it themselves and it passes through the gateway untouched). Rejected:
  the maintainer wants uniform priority-tier behavior across all callers now,
  not gated on opencode shipping the feature, and not leaving LibreChat/
  internal-agent traffic on standard tier by default.
- **Split by route: publish separate `-priority` catalog ids** (e.g.
  `deepseek-v4-flash-0731-priority`) alongside the existing standard-tier
  ids, so callers explicitly pick priority. Rejected: doubles the catalog
  size for every deepinfra model, and the maintainer's stated preference was
  the simpler gateway-wide behavior over an explicit per-model opt-in
  surface.
- **Keep `deepseek-v4-flash` and `deepseek-v4-pro` alongside the new
  release.** Rejected: DeepInfra's own model page describes
  `DeepSeek-V4-Flash-0731` as strictly superseding both on benchmarks at a
  lower price than `-pro`, so keeping either older id would only be dead
  weight in the catalog.

## Related

- Charts/files touched: `charts/ai-model/templates/aigatewayroute.yaml`,
  `charts/ai-models/values.yaml`, `charts/ai-models/README.md`,
  `charts/librechat-opencode-wellknown/values.yaml`
- External references:
  [anomalyco/opencode#12297](https://github.com/anomalyco/opencode/issues/12297),
  [deepinfra.com/blog/priority-service-tier](https://deepinfra.com/blog/priority-service-tier),
  [deepinfra.com/deepseek-ai/DeepSeek-V4-Flash-0731](https://deepinfra.com/deepseek-ai/DeepSeek-V4-Flash-0731),
  [docs.fireworks.ai/serverless/serving-paths](https://docs.fireworks.ai/serverless/serving-paths)
  (Fireworks priority tier — deferred follow-up, see above)
