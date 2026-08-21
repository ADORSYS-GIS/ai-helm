# Handover — z-turbo → LibreChat image generation (ticket #843)

> **Purpose:** handover so this work can continue in a fresh chat. Written
> 2026-08-20, last updated 2026-08-21 (session 3 — **COMPLETE**).

---

## ✅ DELIVERABLE ACHIEVED

LibreChat can generate images via z-image-turbo. The full chain is verified:

| Step | Result |
|---|---|
| `converse` → z-turbo CNP | ✅ unblocked |
| URL shape in response | ✅ service hostname (not `localhost`) |
| Image fetchable from `converse` | ✅ 200 OK, 93 KB PNG |
| LibreChat `IMAGE_GEN` env deployed | ✅ pointing at z-turbo |
| **z-image-proxy** (b64 injection) | ✅ deployed, end-to-end verified (see §9) |

The only remaining work is the **S3 proxy** (ticket #843 original scope) — see §8.

---

## 1. The task

**Ticket #843** (parent epic #823): fix the oversized z-turbo image response
(b64 → S3 proxy). The original ticket scope was a proxy that uploads b64 to S3
and returns a URL.

**The chosen approach (user's plan, diverges from the ticket):**
1. Resurrect z-turbo — **serving only, NOT federated** through the Envoy gateway
   (the gateway's extproc choked on the 1024×1024 b64 payload before).
2. Wire **LibreChat's `IMAGE_GEN` directly to z-turbo** (bypassing the gateway).
3. **Deliverable:** LibreChat renders an image from a prompt. ✅ **Done.**
4. LibreChat's existing S3 file storage handles b64→S3→URL — but z-turbo returns
   a URL directly, so no b64 at all reaches LibreChat. The S3 proxy is therefore
   for persistence/CDN, not a correctness requirement.

---

## 2. Live state

| Component | State |
|---|---|
| **z-image-turbo** | 🟢 Running 1/1 in `inference` ns. Returns a **service-hostname URL** (not b64, not localhost). |
| **qwen3-5-2b** | ⚫ Temporarily disabled — card freed for z-turbo. Re-enable to roll back. |
| **qwen3-5-9b** | 🟢 Running (card 2). Vision confirmed working. |
| **LibreChat** | 🟢 `IMAGE_GEN` wired to z-turbo. End-to-end verified. |
| **CiliumNetworkPolicy** | 🟢 `converse` in `z-image-turbo-allow`. |

**LibreChat `IMAGE_GEN` env (deployed, `converse` ns):**
```
IMAGE_GEN_OAI_API_KEY = Uoz2n7M48T151Jd56460XFKov3sOEZbn
IMAGE_GEN_OAI_BASEURL = http://z-image-turbo.inference.svc.cluster.local:8080/v1
IMAGE_GEN_OAI_MODEL   = z-image-turbo
```

**Verification commands run (all passed):**
```bash
# From a converse pod — connectivity + URL shape:
kubectl run -it --rm debug --image=curlimages/curl -n converse --restart=Never -- \
  curl -s --max-time 10 \
  http://z-image-turbo.inference.svc.cluster.local:8080/v1/images/generations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer Uoz2n7M48T151Jd56460XFKov3sOEZbn" \
  -d '{"model":"z-image-turbo","prompt":"a red circle","size":"256x256"}'
# → {"data":[{"url":"http://z-image-turbo.inference.svc.cluster.local:8080/generated-images/<id>.png"}]}

# Image is fetchable:
# → 200 OK, 93 KB
```

---

## 3. All changes made (chronological)

### `ai-helm-values` — `main`

| Commit | File | Change |
|---|---|---|
| `1438018` | `inference.yaml` | `qwen3-5-2b.enabled: false`; `z-image-turbo.enabled: true` (serving only) |
| `1438018` | `models.yaml` | `qwen3-5-2b-local.enabled: false`; z-turbo left **unfederated** (intentional) |
| `ea49f63` | `librechat-app.yaml` | `IMAGE_GEN_*` env → z-turbo |
| `3e8a4f0` | `inference.yaml` | z-turbo `networkPolicy` per-model override — adds `converse` |

### `ai-helm` — `main`

| Commit | File | Change |
|---|---|---|
| `e5c47428` | `charts/inference/templates/_helpers.tpl` | Per-model `networkPolicy` override mechanism |
| `aea6082f` | `charts/inference/templates/_helpers.tpl` | Hotfix: missing newline caused broken `valuesYaml` for all models (see §6) |
| `43e8ec0c` | `plans/handover-z-turbo-librechat-imagegen.md` | Handover updated (session 2) |

---

## 4. qwen3-5-9b vision fix (done)

Session 1: vLLM's `--quantization fp8` quantized the vision encoder, causing
hallucination. Fixed by switching to `lovedheart/Qwen3.5-9B-FP8` (pre-quantized,
vision encoder in BF16 via `modules_to_not_convert`). Live and verified.

---

## 5. qwen3-5-9b sync error (session 2, resolved)

After pushing the CNP changes, qwen3-5-9b reported:
```
yaml: line 33: did not find expected key
```
Root cause: trailing `-}}` on the `$np` merge line in `_helpers.tpl` stripped the
newline before `networkPolicy:`, concatenating it onto the previous line in the
rendered `valuesYaml`. Fixed in `aea6082f`.

---

## 6. Remaining work — S3 proxy (ticket #843 original scope)

z-turbo returns a cluster-internal URL
(`http://z-image-turbo.inference.svc.cluster.local:8080/generated-images/<id>.png`).
LibreChat can fetch it within the cluster, but:
- The URL is **not persistent** — images live in the pod's ephemeral filesystem.
- The URL is **not externally accessible** (no Ingress/Gateway in front of z-turbo).

For production use, images should be uploaded to S3 and returned as a durable,
externally-accessible URL. Two paths:

**Option A — LibreChat's own S3 upload (no new infra):**
LibreChat already has an S3 file store (`librechat-s3-config` ExternalSecret,
`images/` prefix on `ssegning-k8s-state`). If LibreChat downloads the image
from the cluster URL and re-uploads it to S3, nothing new is needed. Check
whether LibreChat's `IMAGE_GEN` flow does this automatically.

**Option B — Sidecar/proxy in z-turbo (ticket #843 original scope):**
A proxy intercepts the b64 response, uploads to S3, returns the S3 URL. Reuse
`s3_backup_cnpg_*` creds from `ssegning-aws` on `ssegning-k8s-state` under a
distinct prefix (e.g. `inference-images/`).

Start with Option A — it may already work.

---

## 7. Rollback

- Re-enable `qwen3-5-2b` (`enabled: true` in `inference.yaml` + `models.yaml`,
  restore its backend) — frees the card to the colleague's model.
- Disable `z-image-turbo` (`enabled: false` in `inference.yaml`).
- Revert the LibreChat `IMAGE_GEN` override (back to `gemini-2.5-flash-image`).

---

## 8. Key commands

```bash
# Inference pod status
kubectl get pods -n inference

# z-turbo logs
kubectl logs -n inference deploy/z-image-turbo --tail=50

# z-turbo API key
kubectl get secret z-image-turbo-api-key -n inference -o jsonpath='{.data.api_key}' | base64 -d

# CNP
kubectl get ciliumnetworkpolicy z-image-turbo-allow -n inference -o yaml

# LibreChat IMAGE_GEN env
kubectl get deploy librechat-app -n converse -o jsonpath='{.spec.template.spec.containers[0].env}' | python3 -m json.tool | grep -A2 IMAGE_GEN

# Catalog check (from ai-helm-values)
AI_HELM_PATH=/home/koufan/oc/ai-helm ./tools/check-model-catalogs.sh
```

---

## 9. z-image-proxy — b64_json injection (session 3, DONE)

**Problem:** LibreChat's `image_gen_oai` tool (OpenAI SDK v5) reads
`data[0].b64_json` exclusively, but LocalAI defaults to returning a **URL**.
LocalAI env vars couldn't force b64, and LibreChat can't be made to send
`response_format`. So a thin proxy injects `response_format: b64_json` into the
request body before it reaches z-turbo.

**Chart:** `charts/z-image-proxy` (nginx/njs), deployed in `inference` ns.
LibreChat `IMAGE_GEN_OAI_BASEURL` → `http://z-image-proxy.inference.svc.cluster.local:8080/v1`.

**How it works (and the njs gotchas):**
- njs has **no directive that rewrites the request body** before `proxy_pass`.
  `js_body_filter` is a *response* filter; `r.requestText` is a read-only getter
  (assignment throws in strict mode). So the handler is a full `js_content` +
  `ngx.fetch()`: read `r.requestText`, inject `response_format:b64_json` if
  absent, re-POST to z-turbo, pass the response through.
- `ngx.fetch` needs a `resolver` and buffers the response in worker memory
  (raise `js_fetch_max_response_buffer_size` + `max_response_body_size`).

**Fixes required to get it running (all pushed to `main`):**
1. `js_content`+`ngx.fetch` rewrite (the committed version used the broken
   `r.requestText = ...` / `js_body_filter` approach).
2. Resolver must be the **cluster DNS IP** (`10.43.0.10`), NOT a hostname —
   nginx resolves a resolver hostname at startup, racing DNS readiness and
   crash-looping the pod (`host not found in resolver`).
3. All nginx temp paths under `/tmp` (root FS is read-only; fastcgi/uwsgi/scgi
   defaulted to `/var/cache/nginx` → `mkdir ... Read-only file system`).
4. Proxy CNP needs **DNS egress** (kube-system:53) so `ngx.fetch` can resolve
   the upstream at request time (default-deny egress ns).
5. **z-image-turbo's own CNP** (`z-image-turbo-allow`) only admitted
   envoy-gateway-system/observability/converse — added `inference` so the proxy
   (same ns) isn't dropped (`nc` showed `punt!`; z-turbo logged nothing).

**Verified end-to-end** (POST through the proxy, client sends no
`response_format`): HTTP 200, `data[0].b64_json` present (base64 PNG). ✅

**Commits:** ai-helm `da2ebc68`, `22209c2a`, `a480dc56`, `3239d982`;
ai-helm-values `1020843`, `a4a30ae`, `8354e6f`.
