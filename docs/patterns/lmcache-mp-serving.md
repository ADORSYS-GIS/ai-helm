# Serving vLLM with a separate LMCache MP server

*Status: **PARKED** — design + findings recorded 2026-08-24. The fleet currently
serves `qwen3-5-2b` in **default mode (no external LMCache)** while this path is
completed.*

---

## 1. What "MP" means, and why we externalize LMCache

### 1.1 MP = Multi-Process

`LMCacheMPConnector` runs the LMCache cache server as a **separate process** (the
`lmcache/standalone` image) that vLLM connects to over ZMQ on `:5555`. This is in
contrast to `LMCacheConnectorV1`, which runs LMCache **inside the vLLM process**.

### 1.2 Why externalize when the image is `lmcache/vllm-openai`?

The image name is the source of the confusion. `lmcache/vllm-openai` is **vLLM
with LMCache libraries baked in** — it means vLLM *can* use LMCache, not that
LMCache always runs in-process. There are two deployment shapes:

| Connector | Where LMCache runs | Notes |
| :--- | :--- | :--- |
| `LMCacheConnectorV1` | Inside the vLLM process | Default for dense/full-attention models. **Disables vLLM's hybrid KV cache manager.** |
| `LMCacheMPConnector` | Separate `lmcache/standalone` server process | Required for GDN hybrids. Keeps the hybrid KV cache manager enabled. |

**Why Qwen3.5-2B needs MP:** the in-process connector disables vLLM's hybrid KV
cache manager, which the hybrid Gated DeltaNet + Gated Attention architecture
**requires** — the engine crashes at KV-cache init without it (ticket #973). So
the cache must live in a separate process, and that process is the
`lmcache/standalone` image.

---

## 2. The blocker we hit (2026-08-24)

We implemented the `LMCacheMPConnector` path (chart change in `charts/inference`,
then catalog activation in `ai-helm-values`) and hit a **fundamental scheduling
problem** that the how-to (inference-ops PR #22) did not anticipate.

### 2.1 The sidecar cannot see the GPU

`LMCacheMPConnector` registers vLLM's KV caches via **CUDA IPC handles**. The
receiving process must resolve the GPU device UUID — which requires **GPU
visibility** (`/dev/nvidia*` + NVML).

- A sidecar container that does **not** request `nvidia.com/gpu` cannot see the
  GPU → the MP server fails at `register_kv_cache`:
  ```
  RuntimeError: Device UUID a9bd16dd-... not found in the discovered devices.
  ```
- A sidecar that **does** request `nvidia.com/gpu: 1` makes the pod request
  **2 GPUs** — but each node has exactly **1** (fleet rule: one card = one
  model). The pod goes `Pending` with `Insufficient nvidia.com/gpu`.

So the same-pod sidecar approach (as in inference-ops PR #20) **cannot work** on
this fleet. The MP server must either run **inside the vLLM container** (sharing
its GPU allocation) or on a **separate GPU**.

### 2.2 Secondary findings

- **Image tag:** `lmcache/vllm-openai:nightly-2026-08-18` (plain) is a **CUDA 13**
  build and fails on the fleet driver (550 / CUDA 12.4):
  `RuntimeError: The NVIDIA driver on your system is too old (found version 12040)`.
  The working tag is **`nightly-2026-08-18-cu129`** (CUDA 12.9) — verified with a
  real `import vllm` + `torch.cuda.init()` on the RTX 4000 SFF Ada. Same class of
  trap as llama.cpp `server-cuda13`.
- **`kvCacheDtype: auto` is mandatory.** Independently, on Qwen2.5-VL-7B we found
  `fp8_e4m3` KV cache produces **garbage vision** (vLLM warns the checkpoint
  provides no q/k scaling factors and falls back to scaling factor 1.0). This
  reinforces the ADR-0118 requirement to keep `auto` with LMCache.

---

## 3. The path forward: DRA (Dynamic Resource Allocation)

### 3.1 Why DRA solves the problem

The legacy device-plugin model allocates GPUs **per container**. DRA
(KEP-4381) lets a **pod** declare one shared `ResourceClaim` that **multiple
containers reference** — so vLLM and the LMCache MP server can share the **same
single GPU** without over-requesting:

```yaml
spec:
  resources:
    claims:
      - name: gpu            # ONE claim for the whole pod
        request: nvidia.com/gpu
  containers:
    - name: vllm
      resources:
        claims:
          - name: gpu        # vLLM sees the GPU
    - name: lmcache
      resources:
        claims:
          - name: gpu        # LMCache sidecar sees the SAME GPU
```

### 3.2 Cluster state (verified 2026-08-24)

| Check | Result |
| :--- | :--- |
| Kubernetes version | **v1.35.3+k3s1** (all nodes) |
| DRA API group (`resource.k8s.io/v1`) | ✅ Present (resourceclaims, deviceclasses, resourceslices, resourceclaimtemplates) |
| Feature gate (`DynamicResourceAllocation`) | ✅ Enabled (API group present ⇒ stable in v1.35) |
| DRA objects in use | ❌ None (no claims/classes/slices) |
| NVIDIA device plugin | `nvcr.io/nvidia/k8s-device-plugin:v0.20.0` — running in **legacy mode**, not DRA mode |

**Conclusion:** DRA is enabled at the API level but **not wired up for GPUs**.
The NVIDIA plugin is still doing per-container allocation.

---

## 4. Steps to complete serving vLLM with a separate LMCache MP server

### Phase A — Cluster: enable DRA for GPUs

1. **Deploy the NVIDIA DRA driver** (`nvidia-dra-driver-gpu`) on both GPU nodes.
   This is a separate component from the legacy device plugin; it registers the
   `resource.k8s.io` driver and fulfills claims.
2. **Run the device plugin in DRA mode.** `v0.20.0` supports both modes; it must
   be configured for DRA (the legacy DaemonSet is not enough).
3. **Create a `DeviceClass`** (e.g. `nvidia.com/gpu`) that the chart's claims
   reference.
4. **Verify:** a test pod with a shared claim sees the GPU from two containers.

### Phase B — Chart: emit a shared ResourceClaim

5. In `charts/inference/templates/_helpers.tpl`, for `LMCacheMPConnector` mode,
   render a pod-level `resources.claims` entry plus a `ResourceClaim` (or
   `ResourceClaimTemplate`) instead of per-container `nvidia.com/gpu` requests.
6. Both the `model` container and the `lmcache` sidecar reference the **same**
   claim name.
7. Keep the change **backward-compatible**: default mode (no LMCache) keeps the
   legacy per-container GPU request; only `LMCacheMPConnector` switches to DRA.

### Phase C — Values: activate MP mode

8. In `ai-helm-values` `environments/prod/values/inference.yaml`, set
   `qwen3-5-2b` to `lmcache.connector: LMCacheMPConnector` with:
   - `lmcache.mp.image`: `lmcache/standalone:nightly-2026-08-18`
   - `lmcache.mp.chunkSize`: `N` (probed on the exact image — expected 544, **unverified**)
   - `serving.mambaCacheMode: align`
   - `serving.maxNumBatchedTokens`: `>= N`
   - `serving.kvCacheDtype: auto` (mandatory, ADR-0118)
9. Bump the vLLM image to `lmcache/vllm-openai:nightly-2026-08-18-cu129` (the
   plain tag is CUDA 13).

### Phase D — Validate (inference-ops PR #20 gates)

10. **Boot** — MP server + connector start without crash with config aligned on `N`.
11. **Real store/retrieve** — external LMCache KV storage/retrieval, including
    persistence across a vLLM restart (not just "2nd request faster", which can
    come from vLLM's local L0/APC cache).
12. **Score-equivalent generations** — comparison at the score level (GDN is not
    bit-exact).
13. Re-run **P6** (prefix cache) and confirm the SLO (p50 < 800 ms, p95 < 1200 ms,
    p99 < 1500 ms) is now met vs the LMCache-off baseline.

---

## 5. Current fleet state (2026-08-24)

- **gpu-1:** `z-image-turbo` (LocalAI, image gen, LibreChat-internal, not federated)
- **gpu-2:** `qwen3-5-2b` — **default mode, no external LMCache** (replaced
  `qwen2-5-vl-7b-instruct`, which is disabled and kept as a toggleable entry)

`qwen3-5-2b` is federated as `qwen3-5-2b-local` and reachable through the gateway.

---

## 6. References

- inference-ops PR #22 — how-to: hybrid cache + streaming validation (reviewed;
  findings left on the PR)
- inference-ops PR #20 — LMCache MP probe & spike (READY TO RUN, not executed)
- ai-helm tickets #973 (crash + optimization), #1020 (KV-cache offloading)
- Kubernetes pod-level resource specification:
  https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/#pod-level-resource-specification
- DRA (KEP-4381): https://kubernetes.io/docs/concepts/workloads/pods/dynamic-resource-allocation/
