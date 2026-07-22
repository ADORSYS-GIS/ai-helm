# Deploy Z-Image-Turbo FP8 Vision Model (VLM) for Image Generation

## 1. Summary

This PR changes:

- **Adds `charts/model-serving-zimage-turbo/`** — a new self-hosted model-serving chart wrapping a FastAPI server (Diffusers, ZImageTurboPipeline, FP8 quantized) exposing an OpenAI-compatible `/v1/images/generations` endpoint for Tongyi-MAI Z-Image-Turbo (6B params, 1024×1024, 8-step distilled DiT).
- **Registers `zimage-local-01` backend** in `charts/ai-models/values.yaml` — points to `z-image-turbo--poc.ssegning.com:443`, reuses existing `vllm_local_api_key` SM property.
- **Registers `z-image-turbo-local` model** in `charts/ai-models/values.yaml` — `kind: image`, `pricing.strategy: flatPerRequest` at $0.005/image.
- **Deploys the chart LIVE** in `charts/apps/values.yaml` (`homeCluster: true`, namespace `converse-poc`).
- **Disables `model-serving-qwen2-vl-2b` and `qwen25-3b-awq-local`** — one GPU, one model.
- **Extends `ai-model` leaf chart** — skips token metadata (`InputToken`/`OutputToken`/`TotalToken`) and `tokensPerMin` burst rules for `kind: image` models (tokens are always 0 for image generation).
- **Extends `ai-models-info` helpers** — maps `kind: image` to output modality `image`, supports `flatPerRequest` pricing strategy.
- **Adds research document** `docs/onnxruntime-genai-research.md` covering ONNX Runtime GenAI exploration for future model serving options.

It solves:

- **#693** — Deploy a vision/language model (VLM) for image generation on the home GPU infrastructure.

---

## 2. Intent

The intent of this PR is:

> Deploy Tongyi-MAI Z-Image-Turbo FP8 (6B params) as a self-hosted image generation service behind the AI Envoy Gateway, enabling image generation via the existing OpenAI-compatible routing layer. The model runs on the single home GPU (RTX 4090), replacing the previously staged `qwen2-vl-2b` and the disabled `qwen25-3b-awq` which are swapped out due to the one-GPU constraint.

---

## 3. Scope

### In Scope

- New chart: `charts/model-serving-zimage-turbo/` (Chart.yaml, Dockerfile, app.py, templates, values.yaml) — 17 files, ~1045 lines added.
- Backend registration `zimage-local-01` in `charts/ai-models/values.yaml`.
- Model registration `z-image-turbo-local` (kind: image, flatPerRequest $0.005) in `charts/ai-models/values.yaml`.
- App-of-Apps entry in `charts/apps/values.yaml` — LIVE deployment.
- AI-model leaf chart changes: `aigatewayroute.yaml` (skip token metadata for image models), `backendtrafficpolicy.yaml` (skip tokens/min for image models), `_helpers.tpl` (add `flatPerRequest` cost CEL helper).
- `ai-models-info` helper: `_helpers.tpl` — image modality mapping + flatPerRequest pricing output.
- Research doc: `docs/onnxruntime-genai-research.md`.
- Minor ADR-0083 cleanup (already on main, included in diff due to base).

### Out of Scope

- No changes to the `common` library chart or other orchestrators (`coder`, `lightbridge`, `mcps`, `librechat`, `observability`).
- No changes to CI/CD workflows or release automation.
- No architectural changes to the AI Gateway routing layer itself.
- No horizontal scaling or multi-replica support (single GPU, single pod).

---

## 4. Verification

I verified this change by:

- [x] Running automated tests
- [x] Running manual tests
- [ ] Checking logs
- [ ] Checking metrics
- [x] Testing error cases
- [ ] Testing permissions/security behavior
- [ ] Testing rollback or failure behavior, if relevant

Commands run:

```bash
# Validate new chart compiles, lints, and renders cleanly
helm dependency build charts/model-serving-zimage-turbo/
helm lint charts/model-serving-zimage-turbo/ --strict
helm template model-serving-zimage-turbo charts/model-serving-zimage-turbo/ --dry-run > /dev/null

# Validate all orchestrator charts still lint/render
helm dependency build charts/ai-models/
helm lint charts/ai-models/ --strict

helm dependency build charts/apps/
helm lint charts/apps/ --strict
```

Results:

```text
# model-serving-zimage-turbo
helm dependency build: ✓ 1 chart(s) downloaded (common-2.31.4.tgz)
helm lint --strict:     ✓ 0 chart(s) failed
helm template:          8 manifests emitted (PVC, Service, Deployment, Job, Ingress, 2×ExternalSecret)

# ai-models
helm dependency build: ✓
helm lint --strict:     ✓

# apps
helm dependency build: ✓
helm lint --strict:     ✓
```

The FastAPI server (`docker/app.py`) was verified for:
- Correct Bearer token auth against `vllm_local_api_key`
- Lazy model loading on first request (avoids OOM at pod startup)
- Attention slicing + VAE tiling enabled for memory efficiency
- Health check endpoint (`/healthz`)
- Graceful seed image job (runs once per PVC)

---

## 5. Screenshots / Evidence

N/A — this is infrastructure-as-code; no UI changes.

---

## 6. Risk Assessment

Risk level:

- [ ] Low
- [x] Medium
- [ ] High

Potential risks:

1. **GPU contention** — the home GPU runs one model at a time. `qwen25-3b-awq-local` and `qwen2-vl-2b` are disabled; re-enabling any requires disabling z-image-turbo.
2. **First-request latency** — lazy model loading downloads the model from HuggingFace on the first inference request, causing a ~30s cold start.
3. **PVC disk pressure** — the model weight is ~12 GB FP8; `/mnt/models` PVC must have sufficient space.
4. **OpenAI compatibility surface** — only `/v1/images/generations` is implemented; `/v1/models` and other endpoints are not.

Mitigation:

1. Only one model is enabled at a time; the `enabled: false` flags on the other two models document the swap.
2. Monitoring will catch timeout issues; `requestTimeout: 120s` accommodates the cold start window.
3. PVC size is set in values.yaml and can be adjusted before deployment.
4. The Envoy route only sends `/v1/images/generations` to this backend; other paths are unaffected.

---

## 7. AI Usage Declaration

AI was used for:

- [x] Understanding existing code
- [x] Generating code
- [ ] Refactoring
- [ ] Generating tests
- [x] Drafting documentation
- [ ] Reviewing the diff
- [ ] Not used

Human verification:

- [x] I understand every meaningful change in this PR
- [x] I checked generated code manually
- [x] I checked generated tests manually
- [x] I removed unsupported AI assumptions
- [x] I accept responsibility for this PR

---

## 8. Reviewer Focus

Please focus your review on:

- [x] Correctness
- [ ] Architecture
- [ ] Security
- [ ] Performance
- [ ] Tests
- [ ] Maintainability
- [x] Product intent
- [x] Edge cases

Key areas:
- Is the `flatPerRequest` pricing strategy correctly wired end-to-end (helpers → route cost CEL → backend policy)?
- Does the `kind: image` conditional skip logic (token metadata, tokens/min) cover all rate-limiting edge cases?
- Are the `modelNameOverride: "z-image-turbo"` and backend schema/prefix correct for the OpenAI-compatible FastAPI server?
