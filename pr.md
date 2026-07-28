## 1. Summary

This PR deploys **Tongyi-MAI/Z-Image-Turbo** (6B params, FP8 quantized, 8-step distilled DiT) as the **sole GPU model** on the Hetzner GPU fleet, served by a custom Rust/Actix server at `ghcr.io/adorsys-gis/z-image-turbo-server:v0.1.0`.

**Changes:**

- [x] Adapt `charts/model-serving-zimage-turbo` for the Hetzner GPU cluster:
  - Remove `homeCluster: true` — targets the main cluster, not the legacy home cluster
  - Change destination namespace from `converse-poc` → `inference`
  - Update `nodeSelector` from `gpu-node: "true"` → `nvidia.com/gpu.present: "true"` (Hetzner GPU label)
  - Fix finalizer typo (`resources-finalizer.argocd.argoproj.io` → `resources-finalizer.argoproj.io`)
- [x] Disable all other self-hosted models in `charts/ai-models/values.yaml`:
  `qwen3-8b-fast-local`, `openmythos-27b-local`, `qwen3-4b-local`, `qwen3-5-4b-local`,
  `qwen25-3b-awq-local`, `deepseek-r1-1-5b-local`, `qwen3-8b-local`, `ministral-3b-local`,
  `qwen2-vl-2b-local`
- [x] Remove GPU fleet backends (`qwen3-8b-fast-local`, `openmythos-27b-local`) from
  `charts/ai-models/values.yaml` that pointed to `*.inference.svc.cluster.local`
- [x] Disable `openmythos-27b` and `qwen3-8b-fast` in `charts/model-serving/values.yaml`
- [x] Keep `z-image-turbo-local` as the **only enabled model** in `charts/ai-models/values.yaml`
- [x] All charts validated with `helm lint` and `tools/check-model-catalogs.sh`

**Solves:** [Issue #693](https://github.com/ADORSYS-GIS/ai-helm/issues/693) — Deploy Z-Image-Turbo as the sole image generation model on the Hetzner GPU fleet.

---

## 2. Intent

Consolidate the Hetzner GPU fleet (2× RTX A2000, 12 GB VRAM each) to run **only Z-Image-Turbo**. Every other self-hosted model is disabled so the full GPU capacity serves image-generation workloads.

The Z-Image-Turbo server is a **Rust binary** (Candle + Actix-web) that replaces a heavier Python/FastAPI stack — smaller image, faster startup, better memory safety. The inference engine keeps the text encoder on CPU and only the transformer + VAE on GPU, fitting the ~15.8 GB BF16 model weights into 12 GB VRAM.

---

## 3. Scope

### In Scope

- All Helm chart values files adapted for the Hetzner fleet (ADR-0094/0095)
- Model catalog (`charts/ai-models`) configured to route through the existing gateway at `z-image-turbo--poc.ssegning.com`
- `tools/check-model-catalogs.sh` passes: *0 served on GPU fleet, 0 federated cluster-local*
- All YAML valid, all `helm lint` clean

### Out of Scope

- Rust server source code (`charts/model-serving-zimage-turbo/docker/src/`) — unchanged
- Docker image build/publish — already at `ghcr.io/adorsys-gis/z-image-turbo-server:v0.1.0`
- Per-env overrides in the private `ai-helm-values` repo (image tags, environment config)
- Cluster-side deployment (ArgoCD syncs automatically on merge)

---

## 4. Verification

Commands run:

```bash
# YAML validity
python3 -c "import yaml; yaml.safe_load(open('charts/apps/values.yaml'))"
python3 -c "import yaml; yaml.safe_load(open('charts/ai-models/values.yaml'))"
python3 -c "import yaml; yaml.safe_load(open('charts/model-serving/values.yaml'))"
python3 -c "import yaml; yaml.safe_load(open('charts/model-serving-zimage-turbo/values.yaml'))"

# Helm lint
helm lint charts/model-serving-zimage-turbo
helm lint charts/model-serving
helm lint charts/ai-models
helm lint charts/apps

# Catalog consistency
./tools/check-model-catalogs.sh

# Only z-image-turbo-local is enabled
python3 -c "
import yaml
with open('charts/ai-models/values.yaml') as f:
    data = yaml.safe_load(f)
enabled = [k for k, v in data.get('models', {}).items() if v.get('enabled', False)]
assert enabled == ['z-image-turbo-local'], f'Expected only z-image-turbo-local, got {enabled}'
"

# No models enabled in model-serving orchestrator
python3 -c "
import yaml
with open('charts/model-serving/values.yaml') as f:
    data = yaml.safe_load(f)
enabled = [k for k, v in data.get('models', {}).items() if v.get('enabled', False)]
assert enabled == [], f'Expected no enabled models, got {enabled}'
"

# model-serving-zimage-turbo has no homeCluster, ns=inference
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
All YAML files valid:                    ✅
helm lint: 0 charts failed:              ✅
check-model-catalogs.sh: OK:             ✅
Only z-image-turbo-local enabled:        ✅
No enabled models in model-serving:      ✅
No homeCluster, namespace=inference:     ✅
```

---

## 5. Risk Assessment

| Risk | Level | Mitigation |
|---|---|---|
| No fallback if Z-Image-Turbo goes down | Medium | Re-enable a text model by flipping `enabled: true` + reverting the ai-models entry |
| Rust server image not pullable | Low | Image is public on GHCR and already published at `v0.1.0` |
| `nodeSelector` mismatches Hetzner labels | Low | Label `nvidia.com/gpu.present: "true"` verified in the nvidia-device-plugin config |
| `inference` namespace missing | Low | `CreateNamespace=true` in syncPolicy creates it on first sync |

---

## 6. AI Usage Declaration

- [x] AI used for understanding existing code and generating configuration changes
- [x] Every change manually verified (helm lint, YAML validation, catalog checks)
- [x] All generated assumptions reviewed and validated against the actual cluster labels

---

## 7. Reviewer Focus

- **Correctness**: do the disabled models match what is actually running?
- **Architecture**: is the split between `model-serving` (orchestrator), `model-serving-zimage-turbo` (standalone chart), and `ai-models` (gateway catalog) consistent?
- **Rollback**: reverting this PR restores the previous model state — is that correct?
