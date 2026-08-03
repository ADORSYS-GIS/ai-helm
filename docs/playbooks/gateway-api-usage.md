# Calling the models — command reference

Everything below runs from **outside the cluster**, against the public gateway.
Verified live 2026-07-29.

```bash
export AI_BASE=https://api.ai.camer.digital
export AI_TOKEN=<your Keycloak JWT>        # realm camer-digital
```

The token is an ordinary Keycloak access token. Humans already have one after
`opencode auth login` (see [`../integrations/opencode-well-known.md`](../integrations/opencode-well-known.md));
CI/service accounts mint theirs via client-credentials against the realm. A valid
JWT **is** the authorization boundary (ADR-0021) — there is no separate API key on
this plane.

## What you can call

```bash
curl -s $AI_BASE/v1/models -H "Authorization: Bearer $AI_TOKEN" | jq -r '.data[].id'
curl -s $AI_BASE/v1/models/info -H "Authorization: Bearer $AI_TOKEN" | jq       # OpenRouter-shape catalog
```

Self-hosted on our own GPUs: **`z-image-turbo-local`** (images). Everything
else is a SaaS backend behind a branded alias. Ids ending `-internal` are
routed on the internal listener only — picking one externally returns
`404 No matching route found`.

## Image generation — `z-image-turbo-local`

> ⚠️ **KNOWN LIMITATION (2026-07-29): only ≤512×512 works through the gateway.**
> Anything larger fails with `HTTP 500` / `Internal Server Error`. It is not your
> request — Envoy's ext_proc buffers the whole response body to extract usage and
> rejects it above ~1 MiB:
>
> ```
> response_code_details: response_payload_too_large
> ```
>
> Measured: 512×512 → 801 KB → 200. 768×768 → ~1.8 MB → 500. 1024×1024 → 500.
> The listener (500 MiB) and cluster (100 MiB) buffer limits are NOT the cause —
> both were checked. The same 1024×1024 request succeeds when sent directly to
> the pod in-cluster, so the model is fine; the limit is in the gateway.
>
> **`response_format: "url"` is not a workaround.** It returns 200 at any size
> with a small body, but the URL it hands back
> (`https://api.ai.camer.digital/generated-images/….png`) **404s** — the gateway
> routes `/v1/*` only, and nothing serves `/generated-images/*`.
>
> Until this is fixed, generate at 512×512.

```bash
curl -s $AI_BASE/v1/images/generations \
  -H "Authorization: Bearer $AI_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "z-image-turbo-local",
    "prompt": "a red bicycle leaning on a blue wall",
    "size": "512x512",
    "n": 1,
    "response_format": "b64_json"
  }' | jq -r '.data[0].b64_json' | base64 -d > out.png
```

| | |
|---|---|
| 512×512 | **~4.8 s** in-cluster, ~8.7 s via gateway — the only size that works end to end today |
| 1024×1024 | **~32 s** — generates fine, but the response cannot be returned (see the limitation above) |
| Concurrency | **one at a time** — the model holds a mutex, so a second caller queues |
| Timeout | 300 s request / 1 h idle — rides a short queue, not a cold start |
| Billing | flat **$0.0100/image**, tokens always 0 (ADR-0104) |

Image-only: `z-image-turbo-local` does **not** answer `/v1/chat/completions`.

## Chat completions

```bash
curl -s $AI_BASE/v1/chat/completions \
  -H "Authorization: Bearer $AI_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemma-4",
    "messages": [{"role": "user", "content": "Explain sync waves in one sentence."}]
  }' | jq -r '.choices[0].message.content'
```

Streaming — add `"stream": true` and read the SSE frames:

```bash
curl -N -s $AI_BASE/v1/chat/completions \
  -H "Authorization: Bearer $AI_TOKEN" -H "Content-Type: application/json" \
  -d '{"model":"gemma-4","messages":[{"role":"user","content":"count to 5"}],"stream":true}'
```

## Vision (image input)

Any `kind: multimodal` model — e.g. `adorsys-frontend`, `claude-sonnet-5`:

```bash
IMG=$(base64 -w0 photo.png)
curl -s $AI_BASE/v1/chat/completions \
  -H "Authorization: Bearer $AI_TOKEN" -H "Content-Type: application/json" \
  -d '{
    "model": "claude-sonnet-5",
    "messages": [{"role":"user","content":[
      {"type":"text","text":"What is in this image?"},
      {"type":"image_url","image_url":{"url":"data:image/png;base64,'"$IMG"'"}}
    ]}]
  }' | jq -r '.choices[0].message.content'
```

## Embeddings

```bash
curl -s $AI_BASE/v1/embeddings \
  -H "Authorization: Bearer $AI_TOKEN" -H "Content-Type: application/json" \
  -d '{"model":"qwen3-embedding-8b","input":"some text"}' | jq '.data[0].embedding | length'
```

## When something fails

| Symptom | Cause |
|---|---|
| `401` | missing/expired JWT — mint a new one |
| `404 No matching route found` | the model id doesn't exist, or it is `-internal` and you're on the external host |
| `429` | plan burst (req/min or tokens/min) or the monthly µ$ budget — see the ratelimit-quota dashboard |
| `503` on a `*-local` model | its GPU pod isn't Ready — `kubectl -n inference get pods` |
| `500` on image generation | response >~1 MiB — generate at 512×512 (see the limitation above). Confirm with `response_code_details: response_payload_too_large` in the gateway access log |
| image `url` 404s | expected today — nothing serves `/generated-images/*` through the gateway |

Related: [`../patterns/self-hosted-model-serving.md`](../patterns/self-hosted-model-serving.md) ·
[`../architecture/09-model-serving.md`](../architecture/09-model-serving.md)
