# ADR-0125: Unified model visibility at the Envoy AI Gateway (`/v1/models`)

**Status:** Accepted
**Date:** 2026-08-10
**Deciders:** @stephane-segning
**Implementation:** 2026-08-13 (revised — see the implementation note)

## Context

Model visibility is currently controlled at **three** layers, each with a
different scope and a different mechanism:

1. **Envoy AI Gateway** (`AIGatewayRoute.spec.hostnames`, PR #797) — scopes
   the synthesized `/v1/models` response per Host-header match. A
   `disableExternal: true` model sets `hostnames: [<internal-hostname>]`,
   so it appears on the internal plane's listing but not the external
   one. Verified live 2026-07-28: external `curl /v1/models` returns 22
   models with zero internal-only ids.
2. **ai-models-info catalog** (`charts/ai-models-info/templates/_helpers.tpl`,
   `ai-models-info.catalog`) — the OpenRouter-shape `/v1/models/info`
   endpoint skips models with `disableExternal: true` outright. This is
   the catalog opencode's `@vymalo/opencode-models-info` plugin reads.
3. **opencode client-side filter** (`charts/librechat-opencode-wellknown/values.yaml`,
   `modelsInfoHideUnmatched: true`) — opencode's picker shows only models
   present in BOTH `/v1/models` AND `/v1/models/info` (the intersection).

The ticket (#840) asks for visibility to be enforced at a **single layer**
so users never see models they cannot access. Today the three layers are
defense-in-depth, but they don't cover every client: **LibreChat** uses a
static `librechat.yaml` config in `ai-helm-values` (ADR-0087 moved it out
of this repo) with a hardcoded `models.default: [...]` list — it does NOT
query `/v1/models` or `/v1/models/info`. **opencode** likewise carried a
hardcoded `provider.camer-digital.models` block in
`charts/librechat-opencode-wellknown/values.yaml` (a per-client list that
could drift from the gateway). Adding a new model today means editing
`ai-helm-values` `environments/prod/values/librechat-app.yaml` to keep
LibreChat's picker in sync, and the same edit must be repeated for every
other client that maintains its own list. Drift is the failure mode.

LibreChat's web UI is SSO-gated (Keycloak `camer-digital` realm); only
users within the org's SSO can reach it. `-internal` models are
intentionally visible to those users — the suffix signals "not
externally advertised," not "hidden from internal users." This makes
`fetch: true` against the internal gateway correct: the humans using
LibreChat's UI are internal users, and seeing `-internal` models is the
intended behavior.

## Decision

**Make `/v1/models` (Envoy AI Gateway) the single source of truth for
model visibility, and have every client fetch its model list from it.**

- **LibreChat** — set `models.fetch: true` on its custom endpoint in
  `ai-helm-values` `environments/prod/values/librechat-app.yaml`. LibreChat
  will call `GET /v1/models` on the internal gateway at startup and
  populate its picker from the response. The `default: [...]` array
  becomes a minimal fallback (one model) used only if the fetch fails.
  LibreChat already talks to the internal plane
  (`core-gateway-internal.envoy-gateway-system.svc.cluster.local/v1`,
  ADR-0021), so it correctly sees ALL models including `-internal` ones.
- **opencode** — the `provider.camer-digital.models` block in
  `charts/librechat-opencode-wellknown/values.yaml` is now **per-model
  tuning only, not a membership list**. opencode's picker membership is
  gateway-derived — `/v1/models` discovery (Envoy AI Gateway) ∩
  `/v1/models/info` (ai-models-info catalog), enforced client-side by
  `modelsInfoHideUnmatched: true`. The `models:` entries only set
  per-model options (a low default `reasoningEffort` + a high-effort
  `thinking` variant) on models the gateway already advertises; they do
  NOT add or remove models from the picker, so no per-client model list
  remains. The intersection is exactly what an external opencode user
  should see.
- **KiloCode** — no change in this repo. Users configure KiloCode locally
  with `baseURL: https://api.ai.camer.digital/v1`; KiloCode auto-queries
  `/v1/models` and populates its picker (verified against
  kilo.ai/docs/ai-providers/openai-compatible).
- **Direct API** (`curl /v1/models`) — no change. Already works via
  `AIGatewayRoute.spec.hostnames` scoping (PR #797).
- **lightbridge-code-intelligence** — N/A. Uses a single model
  (`agents.llm.model`), not a picker; operator-curated in `ai-helm-values`.

Defense-in-depth is preserved: `/v1/models/info` continues to filter
`disableExternal: true` models (the catalog is also the source of
OpenRouter-shape metadata — pricing, context length, modalities — that
opencode enriches with). The two layers are now consistent by
construction: both derive from the same `charts/ai-models/values.yaml`
source.

## Consequences

**Positive**
- One layer of truth (`/v1/models`); one config change (LibreChat
  `fetch: true` in `ai-helm-values`); opencode's picker membership is
  gateway-derived with no per-client model list (no change to KiloCode
  or direct API).
- Adding a new model is one entry in `charts/ai-models/values.yaml`; it
  appears in every client automatically.
- Drift is structurally impossible: there is no per-client list to drift
  from the gateway.
- The `hostnames` scoping (PR #797) is already verified live and is the
  mechanism that makes this work — no new chart logic needed.

**Negative**
- LibreChat `fetch: true` adds a startup-time dependency on the gateway.
  If the gateway is unreachable at boot, LibreChat falls back to
  `default: [one-model]`. Acceptable: the fallback is one model, the UI
  is never empty, and a restart once the gateway is up restores the full
  list.
- LibreChat's internal-plane baseURL means it sees `-internal` models.
  This is correct: LibreChat's UI is SSO-gated to internal users, and
  the `-internal` suffix signals "not externally advertised," not
  "hidden from internal users."
- The `ai-helm-values` change is cross-repo (ADR-0056 moved the LibreChat
  config there). Coordination required: the file must exist on
  `ai-helm-values` `main` before the chart change merges, or LibreChat
  falls back to no models/endpoints (the documented values-repo-first
  contract).
- opencode's `provider.camer-digital.models` block is now per-model
  tuning only (the `reasoningEffort` caps, issue #534 / PR #631, are
  preserved as options + `thinking` variants). This is a small, curated
  list of thinking-capable models that must be kept in sync with
  `charts/ai-models/values.yaml` — it does not drive picker membership
  (that is gateway-derived), but a model added to the gateway without a
  matching tuning entry simply runs at its backend-default reasoning
  effort. The caps remain a soft, lowest-precedence default ("a calmer/
  cheaper default, not an enforced policy").

**Neutral / follow-ups**
- The `ai-models-info` catalog (`/v1/models/info`) becomes redundant for
  MEMBERSHIP but stays as the source of OpenRouter-shape metadata
  (pricing, context length, modalities). Keep it.
- `charts/ai-model/templates/aigatewayroute.yaml` already has the
  render-time guards that fail if a `disableExternal: true` model is
  missing `gatewayRef.internalHostname` or `gatewayRef.internalSectionName`
  (lines 4-9). No change needed; the guards are the enforcement.
- A new `docs/integrations/kilocode.md` should document the user-side
  KiloCode configuration (baseURL + API key + auto-detect). Out of scope
  for this ADR; tracked separately.

## Implementation (2026-08-11)

### Changes Made

1. **Removed reasoningEffort from non-thinking models** in
   `charts/librechat-opencode-wellknown/values.yaml`:
   - `gemma-4` — no exposed thinking mode (`*spStandard`), Gemma rejects
     `reasoning_effort` with 400. Added comment explaining exclusion.
   - `qwen3-4b-local` — llama.cpp reasoning is OFF at the server
     (`serving.reasoning: "off"`), so there is no thinking channel to
     cap. Added comment explaining exclusion.

2. **Added `reasoningEffort` fields to catalog** in
   `charts/ai-models/values.yaml` for all 22 thinking-capable models:
   - `reasoningEffort: low` — default cost cap
   - `reasoningEffortHigh: high` — thinking variant
   - Enables future auto-derivation of opencode's well-known `models:`
     section from the catalog.

3. **Updated ADR status** to "Implemented".

### Visibility Layers

| Layer | Mechanism | Status |
|-------|-----------|--------|
| `/v1/models` (Envoy AI Gateway) | `AIGatewayRoute.spec.hostnames` scoping | ✅ Working |
| `/v1/models/info` (ai-models-info) | Filters `disableExternal: true` models | ✅ Working |
| opencode picker | `modelsInfoHideUnmatched: true` intersection | ✅ Working |
| LibreChat | `models.fetch: true` (cross-repo, ai-helm-values) | ⏳ Pending |

### Acceptance Criteria Verification

- ✅ Given a user without access to model X, when they list models from
  any client, then model X is not visible. (External users see only
  non-`disableExternal` models via `/v1/models` intersection with
  `/v1/models/info`.)
- ✅ Given the unified approach, when implemented, then visibility is
  enforced at one layer. (Single source: `/v1/models` via Envoy AI
  Gateway `hostnames` scoping.)
- ⏳ Given the implementation, when tested across clients, then
  behavior is consistent. (LibreChat cross-repo change pending in
  `ai-helm-values`.)

## Alternatives considered

- **Option A — Keep three layers, document the drift contract.** Rejected
  because the ticket explicitly asks for a single layer, and drift is
  the failure mode this ADR exists to prevent. The three-layer shape
  was correct as defense-in-depth before the LibreChat gap was known;
  closing the gap with a fourth layer (LibreChat's static list) would
  add the drift surface the ticket is trying to remove.
- **Option B — Move LibreChat's model list to a Helm-rendered ConfigMap
  generated from `charts/ai-models/values.yaml`.** Rejected because it
  duplicates the gateway's work (the gateway already knows the list) and
  adds a render-time dependency that `fetch: true` avoids. The
  ConfigMap would also need to be regenerated on every model change,
  which is exactly the drift surface we're trying to eliminate.
- **Option C — Add a per-user filter at the gateway (e.g., Authorino
  stamps `x-user-tier` and the gateway filters `/v1/models` per
  tier).** Rejected because the current need is binary (internal vs
  external), not per-user-tier. `hostnames` scoping already handles the
  binary case correctly. A per-user filter would be a larger change
  (Authorino metadata + Envoy filter) for a problem that doesn't exist
  yet; revisit when a real per-user-tier requirement appears.
- **Option D — Drop `/v1/models/info` entirely; have opencode read
  `/v1/models` directly.** Rejected because opencode's plugin needs the
  OpenRouter-shape metadata (pricing, context length, modalities) that
  `/v1/models` (OpenAI shape) doesn't carry. Keeping `/v1/models/info`
  as the metadata source is cheaper than teaching opencode to read both
  shapes.

## Related

- PR: [#797](https://github.com/ADORSYS-GIS/ai-helm/pull/797) — the
  `AIGatewayRoute.spec.hostnames` scoping that makes this work
- ADR: [0015](./0015-models-info-catalog-endpoint.md) — the
  `/v1/models/info` catalog (now defense-in-depth, not authoritative)
- ADR: [0021](./0021-burst-budget-billing-and-dual-plane-authconfigs.md) —
  the internal/external plane split that makes `hostnames` scoping
  meaningful
- ADR: [0056](./0056-workload-values-in-ai-helm-values.md) — the
  values-repo split that puts the LibreChat config in `ai-helm-values`
- ADR: [0087](./0087-librechat-app-config-to-values-repo.md) — the move
  of `librechat.yaml` config to `ai-helm-values`
- Docs: `docs/migrations/2026-07-27-gpu-fleet-followups.md` §3.1 — the
  live verification of `hostnames` scoping (2026-07-28)
- Docs: `docs/integrations/opencode-well-known.md` — the opencode
  client-side filter (`modelsInfoHideUnmatched: true`)
- Charts/files touched: `charts/ai-model/templates/aigatewayroute.yaml`
  (no change; guards already enforce the contract),
  `ai-helm-values` `environments/prod/values/librechat-app.yaml` (set
  `models.fetch: true` on the custom endpoint)


## Implementation note (2026-08-13) — how the opencode half actually works

The first cut of this ADR added `reasoningEffort` / `reasoningEffortHigh` to each
catalog entry and had `charts/librechat-opencode-wellknown` derive its
`provider.camer-digital.models` block from `.Values.models`. **That could not
work, and the branch said so in its own comment**: the well-known chart was a
child of the `librechart` ApplicationSet while the catalog belongs to
`ai-models`, so `.Values.models` was always empty. The derivation silently
produced nothing, the hand-maintained list was restored alongside it, and the
catalog keys became dead config in a chart nothing read them from — the exact
duplication this ADR exists to remove, now spread across two repos after
ADR-0126 moved the catalog out.

**The fix is topological: `librechat-opencode-wellknown` is now a child of the
`ai-models` orchestrator**, beside `ai-models-info`. Both are the same kind of
artifact — a client-facing view rendered from the catalog — and that orchestrator
is the only place that can hand a child `.Values.models`. The descriptor's own
content (plugins, the MCP catalog, `auth.command`) stays in the leaf chart's
defaults; only the catalog-derived part is passed in, exactly as `excludeKinds`
and `models` are passed to the info child. A model opts into a cap by carrying
`reasoningEffort` in the catalog; a model with neither key gets no `options`
block, which is how the exclusions are now expressed.

Two things this surfaced, both worth keeping:

- **The old hand-maintained list had drifted badly** — 9 of its 24 model ids no
  longer existed (the `-internal` suffix rename of 2026-07-28, plus three
  home-GPU models retired with that generation). It was shipping reasoning caps
  for models that had not existed for weeks, silently, because nothing validates
  a client-side list against the catalog. That is the strongest argument for
  derivation over a list, and it was invisible until the two were compared.
- **Moving the app between orchestrators renames it** (`librechat-opencode-wellknown`
  → `models-opencode-wellknown`), so ArgoCD prunes the old Application and creates
  a new one. The descriptor is served by an nginx static pod, so expect a brief
  window where `/.well-known/opencode` 404s. Clients re-fetch it at start-up;
  nothing persists through it. Roll forward, not back.

Verified end-to-end by rendering the orchestrator with the production catalog,
extracting the generated child's values, and rendering the leaf from them: 21
models receive `options.reasoningEffort: low` with a `thinking` variant at
`high`, the excluded models receive no `options` block, and the descriptor still
carries its 5 plugins, 17 MCP servers and `auth.command` unchanged.
