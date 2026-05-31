# `ai-models-info` — leaf

Tiny nginx + ConfigMap + HTTPRoute serving an OpenRouter-shape JSON
catalog at `https://api.ai.camer.digital/v1/models/info`. Consumed by
opencode's `@vymalo/opencode-models-info` plugin (ADR-0015).

**ADR:** [`0015`](../../docs/adr/0015-models-info-catalog-endpoint.md)
**Orchestrator:** [`ai-models`](../ai-models/) (sync-wave 1)

## What it renders

- `Deployment` — `nginxinc/nginx-unprivileged:1.27-alpine`, 2 replicas,
  10m / 16Mi requests. Hardened (`runAsNonRoot`,
  `readOnlyRootFilesystem`, drop ALL caps, seccomp `RuntimeDefault`,
  `automountServiceAccountToken: false`).
- `Service` — ClusterIP, port 80 → 8080
- `HTTPRoute` — attached to `core-gateway` (`api.ai.camer.digital`,
  exact match `/v1/models/info`). **NOT an Ingress** — the API host is
  on Envoy AI Gateway, so the right attach is `HTTPRoute`.
- Two `ConfigMap`s:
  - `nginx-config` — `default.conf` with one exact-match location,
    JSON Content-Type, `Cache-Control: public, max-age=300`
  - `content` — the OpenRouter-shape catalog JSON, computed at
    Helm-render time by `templates/_helpers.tpl`

## How the catalog is computed

Per-model entry derived from the `models:` map (mirrors what the
orchestrator passes in):

```yaml
models:
  glm-5:
    kind: text                    # → architecture.{input,output}_modalities
    pricing:
      strategy: weighted          # | flat
      standard:
        inputPer1M: 0.60          # → pricing.prompt (÷ 1e6)
        outputPer1M: 2.08         # → pricing.completion
        cachedInputPer1M: 0.12    # → pricing.input_cache_read (optional)
    info:                         # all fields optional
      displayName: "GLM-5"        # → name
      contextLength: 128000       # → context_length
      maxOutputTokens: 8192       # → top_provider.max_completion_tokens
      supportedParameters:        # → supported_parameters[]
        - tools
        - tool_choice
        - temperature
        - reasoning
```

Output (per entry):

```json
{
  "id": "glm-5",
  "name": "GLM-5",
  "context_length": 128000,
  "pricing": {
    "prompt":     "0.0000006000",
    "completion": "0.0000020800",
    "input_cache_read": "0.0000001200"
  },
  "architecture": {
    "input_modalities":  ["text"],
    "output_modalities": ["text"]
  },
  "top_provider": { "max_completion_tokens": 8192 },
  "supported_parameters": ["tools","tool_choice","temperature","reasoning"]
}
```

`kind: embedding` and `kind: reranker` are excluded by default (set via
`excludeKinds:` — chat-only catalog). Override in the orchestrator's
`modelsInfo:` block.

## Values

| Key | What |
|---|---|
| `image.{repository, tag, pullPolicy}` | nginx image pin |
| `replicaCount` | Defaults to 2 |
| `resources` | requests/limits |
| `route.{enabled, parentRef.{name, namespace, sectionName}, hostname, path}` | HTTPRoute attach point. Defaults to `core-gateway` `api-https` listener, exact path `/v1/models/info`. |
| `models` | Mirror of the orchestrator's `models:` map. Populated by the orchestrator's ApplicationSet element values; default `{}` for standalone testing. |
| `excludeKinds` | Kinds omitted from the catalog. Defaults to `[embedding, reranker]`. |

## How it slots into opencode

The opencode well-known JSON
([`charts/librechat-opencode-wellknown`](../librechat-opencode-wellknown/))
declares:

```jsonc
{
  "plugin": ["@vymalo/opencode-oauth2", "@vymalo/opencode-models-info"],
  "provider": {
    "camer-digital": {
      "options": {
        "baseURL": "https://api.ai.camer.digital/v1",
        "oauth2": { /* … */ },
        "meta": {
          "modelsInfoUrl": "models/info"      // → /v1/models/info
        }
      }
    }
  }
}
```

opencode auto-installs both plugins (`bun install` at startup, cached).
The models-info plugin fetches the catalog, merges fields onto the
already-registered models, caches 24h on disk. End-user flow stays
`opencode auth login https://ai.camer.digital/opencode` and nothing
else.

## Verifying

```bash
helm template ai-models-info . -n converse --set-json 'models={
  "glm-5": {
    "kind":"text",
    "pricing":{
      "strategy":"weighted",
      "standard":{"inputPer1M":0.60,"outputPer1M":2.08,"cachedInputPer1M":0.12}
    },
    "info":{"displayName":"GLM-5","contextLength":128000}
  }
}'
# → ConfigMap × 2 (nginx-config + content), Deployment, Service, HTTPRoute
```

Once deployed:

```bash
TOKEN=$(opencode-auth-token-helper)   # see opencode-well-known.md
curl -fsSL -H "Authorization: Bearer $TOKEN" \
  https://api.ai.camer.digital/v1/models/info | jq '.data | length'
```

## See also

- [ADR-0015](../../docs/adr/0015-models-info-catalog-endpoint.md) — the why
- Lightbridge-opencode `docs/models-info.md` — opencode-side plugin design
  (auth composition, cache shape, log events, OpenRouter field mapping
  in full detail)
