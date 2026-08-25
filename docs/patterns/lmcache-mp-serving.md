# Serving vLLM with a separate LMCache MP server

*Status: **SOLUTION FOUND & VERIFIED** (2026-08-24) — the GPU-visibility blocker
is solved with `NVIDIA_VISIBLE_DEVICES=all` on the sidecar (no GPU resource
request). The chart change is implemented; catalog activation for `qwen3-5-2b`
is pending the probe/spike (inference-ops PR #20). The fleet currently serves
`qwen3-5-2b` in **default mode (no external LMCache)** until then.*

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
this fleet with a GPU resource request. The MP server must either run **inside
the vLLM container** (sharing its GPU allocation), on a **separate GPU**, or —
the solution we found — **see the GPU without requesting it** (§3).

### 2.2 The solution: GPU visibility without a resource request

The NVIDIA container runtime injects GPU devices based on `NVIDIA_VISIBLE_DEVICES`
**regardless of the Kubernetes resources block**. So the sidecar can see the GPU
without requesting `nvidia.com/gpu`:

```yaml
# LMCache MP sidecar container
env:
  - name: NVIDIA_VISIBLE_DEVICES
    value: "all"
  - name: NVIDIA_DRIVER_CAPABILITIES
    value: "all"
# NO nvidia.com/gpu resource request
```

The pod already uses `runtimeClassName: nvidia` (set at the pod level for the
vLLM container), so the NVIDIA runtime is active for the whole pod — the sidecar
inherits it.

**Verified 2026-08-24 on `hetzner-k8s-gpu-2`:** a probe pod with these env vars
and no GPU request ran `nvidia-smi` and saw:
```
GPU 0: NVIDIA RTX 4000 SFF Ada Generation (UUID: GPU-a9bd16dd-c97d-3cc0-30a3-e3ad75af2424)
```
That UUID is **exactly** the one the MP server previously failed to resolve
(`a9bd16dd-... not found in the discovered devices`), confirming the sidecar can
now resolve it.

**Why this is safe on our fleet:** each node has exactly **1 GPU**. The vLLM
container's `nvidia.com/gpu: 1` request schedules the pod onto a GPU node; the
sidecar shares that single card via `NVIDIA_VISIBLE_DEVICES=all`. The pod still
requests only **1 GPU total**.

**Caveats (acceptable here):**
- The sidecar is not GPU-aware-scheduled (moot — the vLLM request schedules the pod).
- It sees all GPUs on the node (moot — there is only one).
- NVIDIA officially sanctions this pattern only for "GPU management containers";
  for app workloads it is a documented-but-restricted approach. Safe on a
  single-GPU node, but not a general multi-GPU sharing mechanism.

### 2.3 Second blocker: CUDA IPC needs shared `/dev/shm` (solved with `hostIPC`)

GPU visibility alone is not enough. LMCache MP shares vLLM's KV caches via
**CUDA IPC device memory** (`torch._new_shared_cuda`), which stores a ref-counter
file in `/dev/shm`. Kubernetes gives each container its **own private `/dev/shm`**
by default, so the LMCache server cannot resolve vLLM's file →
`cudaErrorMapBufferObjectFailed`:

```
torch.AcceleratorError: CUDA error: mapping of buffer object failed
cudaErrorMapBufferObjectFailed
```

**Fix:** share the host IPC namespace (`hostIPC: true`) on the pod for MP mode,
so both containers see the same `/dev/shm`. This is the documented LMCache
pattern (the LMCache Kubernetes Operator mounts the host's `/dev/shm` for exactly
this reason). Verified: both containers load the **same** `libcuda.so` (compat
build 575.51.03), ruling out a driver mismatch; the missing shared `/dev/shm` was
the cause.

⚠️ Do **not** use an `emptyDir` at `/dev/shm` — it shadows the host's and breaks
`cuIpcOpenMemHandle`.

### 2.2 Secondary findings

- **Image tag (vLLM):** `lmcache/vllm-openai:nightly-2026-08-18` (plain) is a
  **CUDA 13** build and fails on the fleet driver (550 / CUDA 12.4):
  `RuntimeError: The NVIDIA driver on your system is too old (found version 12040)`.
  The working tag is **`nightly-2026-08-18-cu129`** (CUDA 12.9) — verified with a
  real `import vllm` + `torch.cuda.init()` on the RTX 4000 SFF Ada. Same class of
  trap as llama.cpp `server-cuda13`.
- **Image tag (LMCache MP server):** the SAME trap applies to
  `lmcache/standalone`. The plain `nightly-2026-08-18` is CUDA 13 (torch
  `2.13.0+cu130`) and fails on the fleet driver — the MP server falls back to
  CPU (`torch_dev=StubCPUDevice`) and cannot resolve vLLM's GPU UUID. Use
  **`nightly-2026-08-18-cu129`** (torch `2.13.0+cu129`), verified on
  `hetzner-k8s-gpu-2`. Both images must be the `-cu129` variant.
- **`kvCacheDtype: auto` is mandatory.** Independently, on Qwen2.5-VL-7B we found
  `fp8_e4m3` KV cache produces **garbage vision** (vLLM warns the checkpoint
  provides no q/k scaling factors and falls back to scaling factor 1.0). This
  reinforces the ADR-0118 requirement to keep `auto` with LMCache.

---

## 3. The solution (implemented): GPU visibility without a resource request

The primary fix is **already implemented** in the chart
(`charts/inference/templates/_helpers.tpl`, `inference.lmcacheMpContainer`): the
LMCache MP sidecar sets `NVIDIA_VISIBLE_DEVICES=all` and
`NVIDIA_DRIVER_CAPABILITIES=all` and does **not** request `nvidia.com/gpu`. This
lets it see the single GPU without inflating the pod's GPU request.

This is far simpler than the DRA path (below) and requires **no cluster-level
changes** — it relies on the existing `runtimeClassName: nvidia` and the
single-GPU-per-node topology.

## 4. Alternative: DRA (Dynamic Resource Allocation)

If we ever need a *supported*, general multi-GPU sharing mechanism (or run on
multi-GPU nodes), DRA is the "proper" Kubernetes-native alternative. It lets a
pod declare one shared `ResourceClaim` that multiple containers reference:

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

### 4.1 Cluster state (verified 2026-08-24)

| Check | Result |
| :--- | :--- |
| Kubernetes version | **v1.35.3+k3s1** (all nodes) |
| DRA API group (`resource.k8s.io/v1`) | ✅ Present (resourceclaims, deviceclasses, resourceslices, resourceclaimtemplates) |
| Feature gate (`DynamicResourceAllocation`) | ✅ Enabled (API group present ⇒ stable in v1.35) |
| DRA objects in use | ❌ None (no claims/classes/slices) |
| NVIDIA device plugin | `nvcr.io/nvidia/k8s-device-plugin:v0.20.0` — running in **legacy mode**, not DRA mode |

**Conclusion:** DRA is enabled at the API level but **not wired up for GPUs**.
The NVIDIA plugin is still doing per-container allocation. Not needed for the
current single-GPU fix.

---

## 5. Steps to complete serving vLLM with a separate LMCache MP server

### Phase A — Chart (DONE)

1. ✅ `charts/inference/templates/_helpers.tpl` — the `lmcache` sidecar sets
   `NVIDIA_VISIBLE_DEVICES=all` + `NVIDIA_DRIVER_CAPABILITIES=all` and does not
   request a GPU resource. Backward-compatible: default mode (no LMCache) is
   unchanged; only `LMCacheMPConnector` renders the sidecar.

### Phase B — Values: activate MP mode

2. In `ai-helm-values` `environments/prod/values/inference.yaml`, set
   `qwen3-5-2b` to `lmcache.connector: LMCacheMPConnector` with:
   - `lmcache.mp.image`: `lmcache/standalone:nightly-2026-08-18`
   - `lmcache.mp.chunkSize`: `N` (probed on the exact image — expected 544, **unverified**)
   - `serving.mambaCacheMode: align`
   - `serving.maxNumBatchedTokens`: `>= N`
   - `serving.kvCacheDtype: auto` (mandatory, ADR-0118)
3. Bump the vLLM image to `lmcache/vllm-openai:nightly-2026-08-18-cu129` (the
   plain tag is CUDA 13).

### Phase C — Validate (inference-ops PR #20 gates)

4. **Boot** — MP server + connector start without crash with config aligned on `N`.
5. **Real store/retrieve** — external LMCache KV storage/retrieval, including
   persistence across a vLLM restart (not just "2nd request faster", which can
   come from vLLM's local L0/APC cache).
6. **Score-equivalent generations** — comparison at the score level (GDN is not
   bit-exact).
7. Re-run **P6** (prefix cache) and confirm the SLO (p50 < 800 ms, p95 < 1200 ms,
   p99 < 1500 ms) is now met vs the LMCache-off baseline.

---

## 6. Current fleet state (2026-08-24)

- **gpu-1:** `z-image-turbo` (LocalAI, image gen, LibreChat-internal, not federated)
- **gpu-2:** `qwen3-5-2b` — **default mode, no external LMCache** (replaced
  `qwen2-5-vl-7b-instruct`, which is disabled and kept as a toggleable entry)

`qwen3-5-2b` is federated as `qwen3-5-2b-local` and reachable through the gateway.

---

## 7. References

- inference-ops PR #22 — how-to: hybrid cache + streaming validation (reviewed;
  findings left on the PR)
- inference-ops PR #20 — LMCache MP probe & spike (READY TO RUN, not executed)
- ai-helm tickets #973 (crash + optimization), #1020 (KV-cache offloading)
- Kubernetes pod-level resource specification:
  https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/#pod-level-resource-specification
- DRA (KEP-4381): https://kubernetes.io/docs/concepts/workloads/pods/dynamic-resource-allocation/
- NVIDIA container toolkit — `NVIDIA_VISIBLE_DEVICES`:
  https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/docker-specialized.html
- NVIDIA k8s-device-plugin README (envvar strategy + "exposes all GPUs" warning):
  https://github.com/NVIDIA/k8s-device-plugin
- NVIDIA GPU Operator — GPU Management Containers (the sanctioned use of
  `NVIDIA_VISIBLE_DEVICES` without a resource request):
  https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/cdi.html
