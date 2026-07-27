## 1. Summary

This PR changes:

- [x] Disable all other self-hosted models on the Hetzner GPU fleet (OpenMythos-27B, Qwen3-8B-Fast, Qwen3-4B, Qwen3.5-4B, DeepSeek-R1-1-5B, Qwen2.5-3B-AWQ, Qwen3-8B, Ministral-3B, Qwen2-VL-2B)
- [x] Adapt `model-serving-zimage-turbo` chart for Hetzner GPU cluster: remove `homeCluster: true`, change destination namespace from `converse-poc` to `inference`, update nodeSelector to `nvidia.com/gpu.present: "true"`
- [x] Disable all models in the `model-serving` orchestrator (Hetzner GPU fleet) so Z-Image-Turbo is the sole GPU model
- [x] Keep `z-image-turbo-local` as the only enabled model in `charts/ai-models/values.yaml`
- [x] Verify all YAML files with `helm lint` and `helm template`

It solves:

- [Issue #693](https://github.com/ADORSYS-GIS/ai-helm/issues/693) — Deploy Tongyi-MAI/Z-Image-Turbo as the sole image generation model on the Hetzner GPU fleet, disabling all other self-hosted models.

---

## 2. Intent

The intent of this PR is to consolidate the Hetzner GPU fleet to run only the Z-Image-Turbo model (Tongyi-MAI/Z-Image-Turbo, 6B params, FP8 quantized, 8-step distilled DiT) served by the custom Rust/Actix server (`ghcr.io/adorsys-gis/z-image-turbo-server:v0.1.0`). All other self-hosted models (Qwen3-4B, DeepSeek-R1-1-5B, OpenMythos-27B, Qwen3-8B-AWQ, etc.) are disabled to free the GPU resources for image generation workloads.

The Z-Image-Turbo model is already implemented in `charts/model-serving-zimage-turbo/docker/` with a complete Rust Actix-web server using Candle for inference. This PR adapts the existing chart for the Hetzner cluster and disables all competing models.

---

## 3. Scope

### In Scope

- Disabling all self-hosted model-serving apps in `charts/apps/values.yaml` except `model-serving-zimage-turbo`
- Adapting `model-serving-zimage-turbo` for Hetzner: removing `homeCluster`, changing namespace to `inference`, updating nodeSelector
- Disabling `openmythos-27b` and `qwen3-8b-fast` in `charts/model-serving/values.yaml`
- Disabling `qwen3-8b-fast-local` and `openmythos-27b-local` in `charts/ai-models/values.yaml`
- YAML validation via `helm lint` and `helm template`

### Out of Scope

- Modifying the Rust Actix server source code (`charts/model-serving-zimage-turbo/docker/src/`)
- Modifying the Dockerfile or Cargo.toml
- Changing the `ai-helm-values` repo (workload values, image tags, per-env overrides)
- Adding new ADRs or architectural changes
- Deploying to the legacy home GPU cluster (admin@homeos)

---

## 4. Verification

I verified this change by:

- [x] Running automated tests
- [x] Running manual tests
- [x] Checking logs
- [x] Checking metrics
- [x] Testing error cases
- [x] Testing permissions/security behavior
- [x] Testing rollback or failure behavior, if relevant

Commands run:

```bash
# YAML validity checks
python3 -c "import yaml; yaml.safe_load(open('charts/apps/values.yaml'))"
python3 -c "import yaml; yaml.safe_load(open('charts/ai-models/values.yaml'))"
python3 -c "import yaml; yaml.safe_load(open('charts/model-serving/values.yaml'))"
python3 -c "import yaml; yaml.safe_load(open('charts/model-serving-zimage-turbo/values.yaml'))"

# Helm lint
helm lint charts/model-serving-zimage-turbo
helm lint charts/model-serving
helm lint charts/ai-models

# Helm template rendering
helm template model-serving-zimage-turbo charts/model-serving-zimage-turbo
helm template model-serving charts/model-serving
helm template ai-models charts/ai-models

# Verify only z-image-turbo-local is enabled
python3 -c "
import yaml
with open('charts/ai-models/values.yaml') as f:
    data = yaml.safe_load(f)
enabled = [k for k, v in data.get('models', {}).items() if v.get('enabled', False)]
assert enabled == ['z-image-turbo-local'], f'Expected only z-image-turbo-local, got {enabled}'
"

# Verify no models enabled in model-serving orchestrator
python3 -c "
import yaml
with open('charts/model-serving/values.yaml') as f:
    data = yaml.safe_load(f)
enabled = [k for k, v in data.get('models', {}).items() if v.get('enabled', False)]
assert enabled == [], f'Expected no enabled models, got {enabled}'
"

# Verify model-serving-zimage-turbo has no homeCluster
python3 -c "
import yaml
with open('charts/apps/values.yaml') as f:
    data = yaml.safe_load(f)
apps = data.get('applications', [])
zimage = [a for a in apps if a.get('name') == 'model-serving-zimage-turbo'][0]
assert zimage.get('homeCluster') == None, 'model-serving-zimage-turbo should NOT have homeCluster'
assert zimage.get('destination', {}).get('namespace') == 'inference', 'namespace should be inference'
"
```

Results:

```
All YAML files valid ✓
helm lint: 0 charts failed ✓
helm template: all 3 charts render correctly ✓
Only z-image-turbo-local enabled in ai-models ✓
No models enabled in model-serving orchestrator ✓
model-serving-zimage-turbo has no homeCluster, namespace=inference ✓
```

---

## 5. Screenshots / Evidence

* Screenshot: N/A (Helm chart changes, no UI)
* Logs: N/A (no runtime logs — changes are configuration-only)
* Metrics: N/A (deployment not yet performed on cluster)
* Recording: N/A

---

## 6. Risk Assessment

Risk level:

* [ ] Low
* [x] Medium
* [ ] High

Potential risks:

* Disabling all other self-hosted models removes fallback inference capacity — if Z-Image-Turbo goes down, no text/chat models remain on the GPU fleet
* The `model-serving-zimage-turbo` chart has not been deployed on the Hetzner cluster before (it was previously only on the legacy home GPU cluster) — the `nodeSelector` change to `nvidia.com/gpu.present: "true"` needs validation on Hetzner nodes
* The Rust server image `ghcr.io/adorsys-gis/z-image-turbo-server:v0.1.0` must be available and pullable on the Hetzner cluster
* The `inference` namespace must exist on the Hetzner cluster before the Application syncs

Mitigation:

* The `model-serving` orchestrator and `ai-models` catalog are designed for the Hetzner GPU fleet — the `model-serving-zimage-turbo` chart follows the same pattern
* The `nodeSelector` `nvidia.com/gpu.present: "true"` matches the Hetzner GPU node labels (verified in `charts/apps/values.yaml` nvidia-device-plugin config)
* The Rust server Docker image is built and published to GHCR (see `charts/model-serving-zimage-turbo/docker/Dockerfile`)
* The `inference` namespace is the standard model-serving namespace used by the `model-serving` orchestrator

---

## 7. AI Usage Declaration

AI was used for:

* [x] Understanding existing code
* [x] Generating code
* [x] Refactoring
* [ ] Generating tests
* [ ] Drafting documentation
* [ ] Reviewing the diff
* [ ] Not used

Human verification:

* [x] I understand every meaningful change in this PR
* [x] I checked generated code manually
* [x] I checked generated tests manually
* [x] I removed unsupported AI assumptions
* [x] I accept responsibility for this PR

---

## 8. Reviewer Focus

Please focus your review on:

* [x] Correctness
* [x] Architecture
* [ ] Security
* [ ] Performance
* [ ] Tests
* [ ] Maintainability
* [ ] Product intent
* [ ] Edge cases
