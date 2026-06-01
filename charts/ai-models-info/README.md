# `ai-models-info` — leaf

Tiny nginx + ConfigMap + HTTPRoute serving an OpenRouter-shape JSON
catalog at `https://api.ai-v2.camer.digital/v1/models/info`. Consumed by
opencode's `@vymalo/opencode-models-info` plugin (ADR-0015).

**ADR:** [`0015`](../../docs/adr/0015-models-info-catalog-endpoint.md)
**Orchestrator:** [`ai-models`](../ai-models/) (sync-wave 1)

## What it renders

The Deployment, Service, and HTTPRoute come from
[`bjw-s app-template` v4.6.2](https://bjw-s-labs.github.io/helm-charts/docs/app-template/)
(aliased as `models-info` in `Chart.yaml`). The two ConfigMaps are
emitted by this chart's own `templates/configmap.yaml` because the
catalog content is computed by `templates/_helpers.tpl::ai-models-info.catalog`
at Helm-render time — app-template's `configMaps:` block expects
static string data.

- `Deployment` (app-template) — `nginxinc/nginx-unprivileged:1.27-alpine`,
  2 replicas, 10m / 16Mi requests. Hardened (`runAsNonRoot`,
  `readOnlyRootFilesystem`, drop ALL caps, seccomp `RuntimeDefault`,
  `automountServiceAccountToken: false`). ConfigMaps + scratch dirs
  come in via the `persistence:` block.
- `Service` (app-template) — ClusterIP, port 80 → 8080
- `HTTPRoute` (app-template's `route:` block) — attached to
  `core-gateway` (`api.ai-v2.camer.digital`, exact match
  `/v1/models/info`). **NOT an Ingress** — the API host is on Envoy AI
  Gateway, so the right attach is `HTTPRoute`.
- Two `ConfigMap`s (this chart's `templates/configmap.yaml`):
  - `nginx-config` — `default.conf` with one exact-match location,
    JSON Content-Type, `Cache-Control: public, max-age=300`
  - `content` — the OpenRouter-shape catalog JSON, computed at
    Helm-render time by `templates/_helpers.tpl`. Data key is `info`
    (not `catalog`) so bjw-s persistence projects it to `models/info`
    under the mount root.

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

The `models:` + `excludeKinds:` blocks live at the **root** of
`values.yaml` (read by the catalog helper + `templates/configmap.yaml`).
The Deployment / Service / HTTPRoute knobs live under the `models-info:`
sub-chart alias (bjw-s app-template's standard schema).

| Key | What |
|---|---|
| `models` | Mirror of the orchestrator's `models:` map. Populated by the orchestrator's ApplicationSet element values; default `{}` for standalone testing. |
| `excludeKinds` | Kinds omitted from the catalog. Defaults to `[embedding, reranker]`. |
| `models-info.controllers.main.containers.nginx.image.{repository, tag, pullPolicy}` | nginx image pin |
| `models-info.controllers.main.replicas` | Defaults to 2 |
| `models-info.controllers.main.containers.nginx.resources` | requests/limits |
| `models-info.route.main.{hostnames, parentRefs, rules}` | bjw-s `route.<name>` shape. Defaults to `core-gateway` `api-https` listener, host `api.ai-v2.camer.digital`, exact path `/v1/models/info`. |

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
        "baseURL": "https://api.ai-v2.camer.digital/v1",
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
`opencode auth login https://ai-v2.camer.digital/opencode` and nothing
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
  https://api.ai-v2.camer.digital/v1/models/info | jq '.data | length'
```

## See also

- [ADR-0015](../../docs/adr/0015-models-info-catalog-endpoint.md) — the why
- Lightbridge-opencode `docs/models-info.md` — opencode-side plugin design
  (auth composition, cache shape, log events, OpenRouter field mapping
  in full detail)
