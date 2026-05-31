# ADR-0015: OpenRouter-shape `/v1/models/info` catalog endpoint for opencode

**Status:** Accepted
**Date:** 2026-05-24
**Deciders:** @stephane-segning

## Context

opencode CLI fetches a per-model metadata blob (context length, USD
pricing, modalities, capability flags) and merges it onto its
in-process provider config. The mechanism is the
[`@vymalo/opencode-models-info`](https://www.npmjs.com/package/@vymalo/opencode-models-info)
plugin (vymalo's npm scope, same maintainer as
`@vymalo/opencode-oauth2`). The plugin opts in per-provider via
`options.meta.modelsInfoUrl` and expects a JSON document in
**OpenRouter shape**:

```json
{ "data": [
  { "id": "glm-5",
    "name": "GLM-5",
    "context_length": 128000,
    "pricing": { "prompt": "0.00000060", "completion": "0.00000208", "input_cache_read": "0.00000012" },
    "architecture": { "input_modalities": ["text"], "output_modalities": ["text"] },
    "top_provider": { "max_completion_tokens": 8192 },
    "supported_parameters": ["tools","temperature","reasoning"]
  }
] }
```

Envoy AI Gateway already serves a vanilla OpenAI-shape `/v1/models`
(`{id, object, owned_by}`) — that's **not** what the plugin wants. A
separate route is required.

The model fleet's source-of-truth lives in
`charts/ai-models/values.yaml`: per-model `kind`, `pricing.strategy`,
`pricing.standard.*` (USD per 1M tokens). The catalog endpoint should
compute its JSON from that same data at Helm-render time so a model
addition / pricing change → one PR updates everything.

## Decision

Add `charts/ai-models-info` as a new leaf under the `ai-models`
orchestrator (per ADR-0012). The leaf is a tiny nginx + ConfigMap +
HTTPRoute that serves the OpenRouter-shape JSON at
`https://api.ai.camer.digital/v1/models/info`.

### Mechanism

- **nginx-unprivileged** (2 replicas, 10m/16Mi requests, hardened —
  `runAsNonRoot`, `readOnlyRootFilesystem`, drop ALL capabilities,
  seccomp `RuntimeDefault`, `automountServiceAccountToken: false`).
- **Two ConfigMaps:**
  - `nginx-config` — custom `default.conf` with one exact-match
    location, `Content-Type: application/json` forced, short
    `Cache-Control` (the plugin already caches 24h on its end).
  - `content` — the OpenRouter-shape JSON, computed at chart-render
    time by `templates/_helpers.tpl`. Mounted at
    `/usr/share/nginx/html/v1/models/info` via `subPath`.
- **`HTTPRoute`** attached to the existing `core-gateway` Gateway
  (sectionName `api-https`, host `api.ai.camer.digital`), exact path
  match `/v1/models/info`. NOT a Traefik Ingress — `api.ai.camer.digital`
  is on the Envoy AI Gateway, so an `HTTPRoute` is the right attach
  point. Same role as Ingress, different API.

### Catalog computation (`templates/_helpers.tpl`)

| Source field | OpenRouter field | Notes |
|---|---|---|
| model map key | `id` | |
| `info.displayName` | `name` | defaults to `id` |
| `pricing.standard.inputPer1M` ÷ 1e6 | `pricing.prompt` | USD per token string, 10 decimal places |
| `pricing.standard.outputPer1M` ÷ 1e6 | `pricing.completion` | |
| `pricing.standard.cachedInputPer1M` ÷ 1e6 | `pricing.input_cache_read` | optional |
| `pricing.standard.effectivePer1M` ÷ 1e6 (flat) | both `prompt` + `completion` | |
| `kind: text` | `architecture.{input,output}_modalities = ["text"]` | |
| `kind: multimodal` | `input_modalities = ["text","image"]`, `output_modalities = ["text"]` | |
| `info.contextLength` (optional) | `context_length` | |
| `info.maxOutputTokens` (optional) | `top_provider.max_completion_tokens` | |
| `info.supportedParameters[]` (optional) | `supported_parameters[]` | |

`kind ∈ {embedding, reranker}` is excluded from the catalog by default
(chat-only catalog). Configurable via `excludeKinds:` in
`charts/ai-models/values.yaml` `modelsInfo:`.

### Orchestrator wiring

`charts/ai-models/values.yaml` gains a `modelsInfo:` block:

```yaml
modelsInfo:
  enabled: true
  excludeKinds: [embedding, reranker]
  route: { ... }
```

The orchestrator's `templates/applicationset.yaml` adds an extra
element to the List generator (alongside the backends element and the
per-model elements) that targets `charts/ai-models-info` at sync-wave 1.

### opencode well-known JSON

`charts/librechat-opencode-wellknown/values.yaml` declares the second
plugin and the URL:

```yaml
plugin:
  - "@vymalo/opencode-oauth2"
  - "@vymalo/opencode-models-info"
provider:
  camer-digital:
    options:
      meta:
        modelsInfoUrl: "models/info"   # → baseURL + "models/info"
```

Both plugins auto-install via bun-install on first launch (no manual
`opencode plugin add`).

### Auth scope

The HTTPRoute attaches to the same listener Authorino guards via its
SecurityPolicy. The catalog endpoint inherits the AuthConfig — callers
must present a valid JWT. opencode's models-info plugin reuses the
provider's already-resolved `options.headers` for the fetch (including
the `Authorization: Bearer …` set by the oauth2 plugin's config-time
write), so this is transparent.

If we ever want a public catalog (visible before login), add an
`AuthConfig.when:` predicate that exempts the
`/v1/models/info` path. Not doing that today — auth-required is the
safer default.

## Consequences

**Positive**
- Single source of truth for model pricing / capabilities — the same
  `models:` map drives inference routing AND the catalog. No risk of
  the catalog drifting from what the gateway actually proxies.
- Plugin auto-install means end users still run
  `opencode auth login https://ai.camer.digital/opencode` and nothing
  else. Both plugins land in the cache; both compose correctly (per
  the lightbridge-opencode `docs/models-info.md`).
- Adding a new model: one `models:` entry under `charts/ai-models/`,
  one PR; catalog updates automatically.
- Tiny footprint: 2 × (10m CPU, 16Mi RAM) ≈ negligible.

**Negative**
- HTTPRoute exact-match is fragile — typos in the path won't match
  and produce 404. The chart pins the path in values so the URL stays
  consistent with what the opencode well-known declares.
- Catalog is a snapshot at chart-render time. Pricing changes that
  bypass the chart (e.g. an upstream provider adjusts mid-day) don't
  reflect until the chart is re-rendered. Acceptable — pricing changes
  are not frequent and the plugin's local 24h TTL is the dominant
  staleness anyway.
- Adding rich metadata fields (context_length, supportedParameters)
  requires adding `info:` blocks to each model in
  `charts/ai-models/values.yaml`. Today the catalog ships only what
  we have (id, pricing, modalities); rich enrichment lands per-model
  as we fill in those blocks.

**Neutral / follow-ups**
- Fill in `info:` blocks for each model with context window + output
  limit + supported parameters. Tracked separately.
- If the catalog ever needs to be public (e.g. for a "browse models"
  marketing page), add an Authorino path-exemption. Today it's
  auth-required.
- Could grow into a more complete OpenRouter clone (per-provider
  rates, etc.) — but only when there's a real consumer. YAGNI for v0.

## Alternatives considered

- **Use the existing `/v1/models` route.** opencode-models-info's
  docs explicitly warn against this — vanilla OpenAI shape lacks every
  field the plugin maps. Pointing at it fetches successfully and
  enriches nothing. Rejected.
- **Traefik Ingress on `ai.camer.digital/models-info`.** Different
  host, different infra. Would require absolute `modelsInfoUrl` in the
  opencode config (loses URL-resolution-against-baseURL ergonomics).
  Rejected; the gateway HTTPRoute pattern is cleaner.
- **Generate the catalog at build time, ship as a baked file in
  `charts/ai-models-info/files/`.** Same end state, but tooling
  (build pipeline, drift check) for what Helm can do in 50 lines.
  Rejected.
- **Live `/v1/models/info` implemented as a Go/Python service** that
  queries each provider's catalog on demand. Heavy. The static
  Helm-rendered shape covers the metadata we publish; live polling
  would only help if upstream pricing changed under us, which it
  doesn't at a rate we need to track in real time. Rejected.

## Related

- ADR-0012 — `ai-models` orchestrator split (this leaf attaches there)
- ADR-0014 — opencode well-known endpoint (declares the second plugin)
- Lightbridge-opencode `docs/models-info.md` and `plans/models-info-plan.md`
  describe the plugin's design and OpenRouter mapping in full
- `charts/ai-models-info/README.md` — the how

## Files

- `charts/ai-models-info/` — the new leaf
- `charts/ai-models/values.yaml` — `modelsInfo:` block
- `charts/ai-models/templates/applicationset.yaml` — extra element
- `charts/librechat-opencode-wellknown/values.yaml` — plugin + URL
