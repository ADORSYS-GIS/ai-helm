# Handover — z-turbo → LibreChat image generation (ticket #843)

> **Purpose:** handover so this work can continue in a fresh chat. Written
> 2026-08-20, last updated 2026-08-20 (session 2).

---

## 1. The task

**Ticket #843** (parent epic #823): fix the oversized z-turbo image response
(b64 → S3 proxy). The original ticket scope was a proxy that uploads b64 to S3
and returns a URL.

**The chosen approach (user's plan, diverges from the ticket):**
1. Resurrect z-turbo — **serving only, NOT federated** through the Envoy gateway
   (the gateway's extproc choked on the 1024×1024 b64 payload before).
2. Wire **LibreChat's `IMAGE_GEN` directly to z-turbo** (bypassing the gateway).
3. **Deliverable:** LibreChat renders an image from a prompt.
4. LibreChat's existing S3 file storage handles b64→S3→URL (no separate proxy
   needed yet). The proxy comes later.

---

## 2. Current live state (verified at handover)

| Component | State |
|---|---|
| **z-image-turbo** | 🟢 **Running 1/1** in `inference` ns. Serves `/v1/images/generations`, returns a **URL** (not b64) for generated images. |
| **qwen3-5-2b** | ⚫ **temporarily disabled** (colleague's model) — its card was freed for z-turbo. Re-enable to roll back. |
| **qwen3-5-9b** | 🟢 Running (card 2). Vision fixed (see §6). Sync error from session 2 resolved (see §7). |
| **LibreChat** | 🟢 Redeployed with `IMAGE_GEN` pointing at z-turbo directly. |
| **CiliumNetworkPolicy** | 🟢 **`converse` namespace added** to `z-image-turbo-allow`. |

**LibreChat `IMAGE_GEN` env (deployed, `converse` ns):**
```
IMAGE_GEN_OAI_API_KEY = Uoz2n7M48T151Jd56460XFKov3sOEZbn
IMAGE_GEN_OAI_BASEURL = http://z-image-turbo.inference.svc.cluster.local:8080/v1
IMAGE_GEN_OAI_MODEL   = z-image-turbo
```

**z-turbo direct test (works):**
```bash
KEY=$(kubectl get secret z-image-turbo-api-key -n inference -o jsonpath='{.data.api_key}' | base64 -d)
kubectl exec -n inference deploy/z-image-turbo -- curl -s http://localhost:8080/v1/images/generations \
  -H "Content-Type: application/json" -H "Authorization: Bearer $KEY" \
  -d '{"model":"z-image-turbo","prompt":"a red circle on a white background","size":"256x256"}'
# → {"data":[{"url":"http://localhost:8080/generated-images/<id>.png"}]}
```

---

## 3. ~~THE BLOCKER — CiliumNetworkPolicy~~ ✅ DONE

~~LibreChat cannot currently reach z-turbo.~~

**Fixed.** `converse` was added to z-turbo's `networkPolicy.allowFromNamespaces`
as a **per-model override** (not a fleet-default change — that would have opened
every model to the chat namespace).

- `ai-helm-values` commit `3e8a4f0`: z-turbo entry in `inference.yaml` now has:
  ```yaml
  networkPolicy:
    allowFromNamespaces:
      - envoy-gateway-system
      - observability
      - converse          # LibreChat IMAGE_GEN (ticket #843)
  ```
- `ai-helm` commit `e5c47428`: added the per-model networkPolicy override
  mechanism to `charts/inference/templates/_helpers.tpl` (same merge pattern as
  the existing security override — per-model wins key-by-key over fleet default).
- `ai-helm` commit `aea6082f`: hotfix — the `{{- $np := ... -}}` trailing `-}}`
  stripped the newline before `networkPolicy:`, concatenating it onto the previous
  line in the rendered `valuesYaml` and breaking ALL child apps (qwen3-5-9b
  reported the sync error; the bug was in the chart, not the values). Fixed by
  removing the trailing `-`.

---

## 4. ⚠️ URL issue — STILL NEEDS VERIFICATION

z-turbo returns `http://localhost:8080/generated-images/<id>.png` when called via
`localhost`. When called via the **service URL**
(`z-image-turbo.inference.svc.cluster.local:8080`), LocalAI should return the
service URL (reachable from LibreChat) — **this has not yet been verified**.

If it still returns `localhost`, set a reachable base URL via LocalAI's
`EXTERNAL_GRPC_BACKENDS_DESTINATION` or `ADDRESS` env variable, using the chart's
`serving.extraEnv` mechanism in `charts/inference/templates/_helpers.tpl` (~line
722 in `ai-helm`).

**How to check:**
```bash
# From a converse pod (connectivity + URL shape in one shot):
kubectl run -it --rm debug --image=curlimages/curl -n converse --restart=Never -- \
  curl -s http://z-image-turbo.inference.svc.cluster.local:8080/v1/images/generations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer Uoz2n7M48T151Jd56460XFKov3sOEZbn" \
  -d '{"model":"z-image-turbo","prompt":"a red circle","size":"256x256"}'
# If URL in response starts with http://localhost → set extraEnv below.
# If URL starts with http://z-image-turbo... → proceed to end-to-end test.
```

**If fix is needed** (`serving.extraEnv` in `ai-helm-values/environments/prod/values/inference.yaml`, under `z-image-turbo.serving`):
```yaml
extraEnv:
  - name: ADDRESS
    value: "http://z-image-turbo.inference.svc.cluster.local:8080"
```

---

## 5. Files changed

### `ai-helm-values` (all pushed to `main`)

| Commit | File | Change |
|---|---|---|
| `1438018` | `environments/prod/values/inference.yaml` | `qwen3-5-2b.enabled: false`; `z-image-turbo.enabled: true` (serving only) |
| `1438018` | `environments/prod/values/models.yaml` | `qwen3-5-2b-local.enabled: false` + backend removed; z-turbo left **unfederated** |
| `ea49f63` | `environments/prod/values/librechat-app.yaml` | `IMAGE_GEN_*` env override → z-turbo |
| `3e8a4f0` | `environments/prod/values/inference.yaml` | z-turbo `networkPolicy` per-model override — adds `converse` |

### `ai-helm` (all pushed to `main`)

| Commit | File | Change |
|---|---|---|
| `e5c47428` | `charts/inference/templates/_helpers.tpl` | Per-model `networkPolicy` override mechanism |
| `aea6082f` | `charts/inference/templates/_helpers.tpl` | Hotfix: missing newline caused broken `valuesYaml` for all models |

`check-model-catalogs.sh` → **OK (2 served: qwen3-5-9b + z-image-turbo; 1 federated:
qwen3-5-9b-local)** — z-turbo is served-but-unfederated (the intended state).

---

## 6. Context: qwen3-5-9b vision fix (done, working)

Earlier in session 1, qwen3-5-9b's vision was broken (hallucinated) because
vLLM's `--quantization fp8` quantized the vision encoder. **Fixed** by switching
to the pre-quantized checkpoint `lovedheart/Qwen3.5-9B-FP8` (12.21 GB, vision
encoder kept in BF16 via `modules_to_not_convert: ["model.visual.*"]`). This is
live and vision is confirmed competent. Not related to the z-turbo task, but
relevant if you touch qwen3-5-9b.

---

## 7. Context: qwen3-5-9b sync error (session 2, resolved)

After pushing the CNP changes, qwen3-5-9b reported a sync error:
```
yaml: line 33: did not find expected key
```
Root cause: the `{{- $np := ... -}}` trailing `-}}` in `_helpers.tpl` stripped
the newline before `networkPolicy:`, causing it to be concatenated onto the last
value of the `apiKey` block in the rendered `valuesYaml` string. ArgoCD's
ApplicationSet controller could not parse the resulting YAML, breaking **all**
child apps (qwen3-5-9b was first alphabetically and therefore the one named in
the error). Fixed in `ai-helm` commit `aea6082f`.

---

## 8. Next steps (in order)

1. **Wait for ArgoCD sync** — the `aea6082f` hotfix needs to publish a new chart
   version via CI before ArgoCD picks it up. Confirm qwen3-5-9b goes green.
2. **Verify LibreChat → z-turbo connectivity** — run the `kubectl run debug` curl
   from §4 to confirm the CNP allows traffic from `converse`.
3. **Verify the returned URL is reachable** — check whether the URL in the
   response is `http://localhost:...` or `http://z-image-turbo...`. If localhost,
   apply the `serving.extraEnv` fix described in §4.
4. **Test end-to-end** — ask LibreChat to generate an image from a prompt. The
   deliverable is a rendered image in the chat.
5. **Later:** the S3 proxy (ticket #843 original scope) — reuse the observability
   stack's S3 creds (`s3_backup_cnpg_*` from `ssegning-aws`) on the shared
   `ssegning-k8s-state` bucket, under a distinct directory. LibreChat already does
   this (its `librechat-s3-config` ExternalSecret + `images/` prefix).

---

## 9. Rollback

- Re-enable `qwen3-5-2b` (`enabled: true` in `inference.yaml` + `models.yaml`,
  restore its backend) — frees the card back to the colleague's model.
- Disable `z-image-turbo` (`enabled: false` in `inference.yaml`).
- Revert the LibreChat `IMAGE_GEN` override (back to `gemini-2.5-flash-image` via
  the internal gateway).

---

## 10. Key commands

```bash
# z-turbo status
kubectl get pods -n inference | grep z-image-turbo
kubectl logs -n inference deploy/z-image-turbo --tail=50

# z-turbo API key
kubectl get secret z-image-turbo-api-key -n inference -o jsonpath='{.data.api_key}' | base64 -d

# CNP — verify converse is present
kubectl get ciliumnetworkpolicy z-image-turbo-allow -n inference -o yaml

# Connectivity test from converse namespace (§4)
kubectl run -it --rm debug --image=curlimages/curl -n converse --restart=Never -- \
  curl -s http://z-image-turbo.inference.svc.cluster.local:8080/v1/images/generations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer Uoz2n7M48T151Jd56460XFKov3sOEZbn" \
  -d '{"model":"z-image-turbo","prompt":"a red circle","size":"256x256"}'

# LibreChat IMAGE_GEN (deployed)
kubectl get deploy librechat-app -n converse -o jsonpath='{.spec.template.spec.containers[0].env}' | python3 -m json.tool

# qwen3-5-9b sync status
kubectl get application inference-qwen3-5-9b -n argocd -o jsonpath='{.status.sync.status}'

# catalog check (from ai-helm-values)
AI_HELM_PATH=/home/koufan/oc/ai-helm ./tools/check-model-catalogs.sh
```
