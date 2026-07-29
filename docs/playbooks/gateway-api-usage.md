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

Self-hosted on our own GPUs: **`z-image-turbo-local`** (images) and
**`qwen3-vl-4b-thinking-local`** (text + vision). Everything else is a SaaS
backend behind a branded alias. Ids ending `-internal` are routed on the internal
listener only — picking one externally returns `404 No matching route found`.

## Image generation — `z-image-turbo-local`

⚠️ **Always pass `"response_format": "b64_json"`.** The default returns
`{"url": "http://127.0.0.1:8080/generated-images/….png"}` — the model's own
in-pod address, which is not reachable from anywhere you'd run this.

```bash
curl -s $AI_BASE/v1/images/generations \
  -H "Authorization: Bearer $AI_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "z-image-turbo-local",
    "prompt": "a red bicycle leaning on a blue wall",
    "size": "1024x1024",
    "n": 1,
    "response_format": "b64_json"
  }' | jq -r '.data[0].b64_json' | base64 -d > out.png
```

| | |
|---|---|
| 1024×1024 | **~32 s** |
| 512×512 | **~4.8 s** |
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
    "model": "adorsys-tiny",
    "messages": [{"role": "user", "content": "Explain sync waves in one sentence."}]
  }' | jq -r '.choices[0].message.content'
```

Streaming — add `"stream": true` and read the SSE frames:

```bash
curl -N -s $AI_BASE/v1/chat/completions \
  -H "Authorization: Bearer $AI_TOKEN" -H "Content-Type: application/json" \
  -d '{"model":"adorsys-tiny","messages":[{"role":"user","content":"count to 5"}],"stream":true}'
```

## Vision (image input)

Any `kind: multimodal` model — e.g. `qwen3-vl-4b-thinking-local` (self-hosted),
`adorsys-frontend`, `claude-sonnet-5`:

```bash
IMG=$(base64 -w0 photo.png)
curl -s $AI_BASE/v1/chat/completions \
  -H "Authorization: Bearer $AI_TOKEN" -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-vl-4b-thinking-local",
    "messages": [{"role":"user","content":[
      {"type":"text","text":"What is in this image?"},
      {"type":"image_url","image_url":{"url":"data:image/png;base64,'"$IMG"'"}}
    ]}]
  }' | jq -r '.choices[0].message.content'
```

⚠️ `qwen3-vl-4b-thinking-local` reasons by default; the trace comes back in a
separate `reasoning_content` field, not inside `content`. Disable per request with
`"chat_template_kwargs": {"enable_thinking": false}`.

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
| image `url` unreachable | you omitted `response_format: b64_json` (see above) |

Related: [`../patterns/self-hosted-model-serving.md`](../patterns/self-hosted-model-serving.md) ·
[`../architecture/09-model-serving.md`](../architecture/09-model-serving.md)
