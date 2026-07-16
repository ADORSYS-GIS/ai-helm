# llm-d

**llm-d** (CNCF Sandbox, distributed inference middleware) router in standalone
mode + a **vLLM** model server. The router provides **prefix-cache-aware**,
**KV-cache-utilization-aware**, and **queue-depth-aware** intelligent routing
across model-server replicas with **no GAIE CRDs required**
(inferencePool.create=false).

- **What is llm-d?** A Kubernetes-native middleware orchestration layer between
  the gateway and vLLM. It does NOT replace vLLM -- it sits in front of it,
  providing intelligent routing, KV-cache management, and (eventually)
  disaggregated prefill/decode. See https://llm-d.ai
- **Standalone mode:** EPP (Endpoint Picker) + Envoy sidecar in one pod. No
  InferencePool CRD, no Gateway API Inference Extension CRDs. EPP discovers vLLM
  pods by label selector (--endpoint-selector app=llm-d-vllm).

## Unusual things about this chart

- **Three subcharts, not two.** Unlike model-serving-qwen3-4b (bjw + common),
  this chart adds a third: llm-d-router-standalone (OCI from
  ghcr.io/llm-d/charts, alias llmdRouter). The OCI subchart renders the EPP
  Deployment + Envoy sidecar, the scorer ConfigMaps, RBAC, and the EPP Service.
  The bjw subchart renders the vLLM StatefulSet + seed Job + Service.
- **Envoy ConfigMap is a chart-own template.** The OCI subchart presets
  (including the full Envoy static config) do not merge when the chart is used
  as a dependency -- Helm value-merge drops the presets key. So we render the
  Envoy ConfigMap ourselves (templates/configmap-envoy.yaml) and pass the
  container name/image/args/ports/volumes explicitly in values.yaml under
  llmdRouter.router.proxy. The ConfigMap name is configurable via
  llmdRouter.router.proxy.configMapName (helper: llm-d.envoyConfigMapName).
- **No GAIE CRDs needed.** inferencePool.create: false means EPP uses
  --endpoint-selector + --endpoint-target-ports instead of an InferencePool
  CRD. No kubectl apply -f for gateway-api-inference-extension CRDs required.
- **vLLM serves from PVC, not HuggingFace.** Weights are pre-seeded by a Job
  (bjw seed controller, ArgoCD Sync hook) into a PVC, then mounted read-only
  by the vLLM container. HF_HUB_OFFLINE=1 prevents runtime HF fetches. This
  avoids Docker Hub / HF rate limits at startup and gives direct vLLM version
  control (not kserve-bundled).
- **--enforce-eager is a PoC flag.** Disables CUDA graph optimization (safe on
  a 6GB GPU). Remove for production to enable CUDA graph acceleration.
- **RWO PVC (single-node).** Uses local-path with ReadWriteOnce -- fine for
  k3d (single node). For multi-node clusters, switch to RWX so the seed Job
  and model StatefulSet can mount concurrently on different nodes.

## Traffic flow

Client -> EPP Service (:8081) -> Envoy sidecar (:8081)
  -> ext_proc filter -> EPP (:9002) picks best vLLM pod
  -> Envoy routes to vLLM pod (:8000) via ORIGINAL_DST
  -> vLLM returns response -> Envoy -> Client

## What it renders (in sync-wave order)

| Wave | Resource | Rendered by | Purpose |
|------|----------|-------------|---------|
| -2 | ExternalSecret hf-token (optional) | own template | HF download token for gated models |
| -1 | PVC llm-d-models | own template | weights volume (local-path, RWO, 5Gi) |
| 0 | Job llm-d-vllm-seed (ArgoCD Sync hook) | bjw (controllers.seed) | downloads weights into the PVC once |
| 1 | StatefulSet llm-d-vllm-main + Service llm-d-vllm:8000 | bjw | the vLLM model server |
| -- | ConfigMap llm-d-epp (scorers) | llmdRouter subchart | EPP plugin config (queue, kv-cache, prefix-cache scorers) |
| -- | ConfigMap llm-d-epp-envoy | own template | Envoy static config (ext_proc, ORIGINAL_DST, health) |
| -- | Deployment llm-d-epp (EPP + Envoy sidecar) | llmdRouter subchart | the router pod |
| -- | Service llm-d-epp:8081 | llmdRouter subchart | the public entrypoint |
| -- | ServiceAccount, Role, RoleBinding | llmdRouter subchart | EPP pod watch permissions |

## Re-seeding the weights

The seed Job is an ArgoCD Sync hook (delete+recreate each sync) and hf download
is idempotent (skips files already on the PVC). To force a clean re-seed: delete
the PVC contents (or the PVC, which re-seeds) and re-sync.

## Key knobs (values.yaml)

- model.{name,hfRepo,storagePath} -- drives the PVC subPath and the EPP label
  selector. The bjw seed Job hardcodes the repo/path (subchart scope cannot read
  parent .Values.model.*) -- keep modelServing.controllers.seed in sync.
- llmdRouter.router.inferencePool.create -- false = standalone (no CRDs);
  true = requires GAIE CRDs installed.
- llmdRouter.router.modelServers.matchLabels -- the pod label EPP selects on.
  MUST match modelServing.defaultPodOptions.labels.
- llmdRouter.router.proxy.configMapName -- the Envoy ConfigMap name. Keep in
  sync with llmdRouter.router.proxy.volumes[0].configMap.name.
- llmdRouter.router.proxy.resources -- right-sized from subchart defaults
  (4 CPU / 8Gi to 100m / 128Mi). Bump for production.
- llmdRouter.router.epp.resources -- right-sized from subchart defaults
  (8 CPU / 8Gi to 500m / 512Mi). Bump for production.
- modelServing.controllers.main.replicas -- 1 (one GPU). Bump for multi-GPU.
- modelServing.controllers.main.containers.model.args -- vLLM passthrough.
  Includes --enforce-eager (PoC, remove for production).
- pvc.accessMode -- ReadWriteOnce (single-node k3d). Use ReadWriteMany
  for multi-node clusters.
- seedJob.hfToken.* -- optional HF token for gated models. Disabled by default
  (Qwen2.5-0.5B-Instruct is not gated).
