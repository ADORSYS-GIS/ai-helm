# Self-hosted GPU inference: Qwen3-4B on KServe + vLLM + LMCache

**The *why* is [ADR-0022](./adr/0022-self-hosted-gpu-model-federated-into-gateway.md). This is the *how*** —
the build plan, the VRAM math, the exact manifests/flags, the security model, and
how to verify it end-to-end.

> Status: **planned**. Nothing here is deployed yet. The home platform it relies
> on (KServe, Knative, Traefik, cert-manager, the GPU node) is already live.

---

## 1. The picture

```
 USER ──TLS + Keycloak JWT──▶  HETZNER k3s  (home-remote, public)         HOME Talos (admin@homeos, GPU)
                              ┌─────────────────────────────┐            ┌──────────────────────────────────┐
                              │ core-gateway (Envoy AI GW)   │            │ KServe InferenceService (Knative) │
                              │  authz: Keycloak JWT (0021)  │  HTTPS     │  kserve/huggingfaceserver (vLLM)  │
                              │  AIServiceBackend vllm-local ─┼── +APIkey ─▶  + LMCache (in-pod, CPU offload)  │
                              │  rate-limit + token metering │  (public   │  Qwen3-4B · RTX A2000 12GB        │
                              │                              │   FQDN)    │  /openai/v1/chat/completions     │
                              └─────────────────────────────┘            └──────────────────────────────────┘
                                                                            exposed by Knative→Traefik→cert-mgr
                                                                            at qwen3-4b-<ns>--sls.ssegning.com
```

The model is, from the gateway's point of view, **identical to DeepInfra**: an
OpenAI-compatible FQDN over TLS with an API key. The only novelty is on the home
side (KServe/vLLM/LMCache on the GPU). The exposure is free — Knative already
mints a public, TLS-terminated FQDN.

### What's already live (do **not** re-create)

| Piece | Where | Note |
|---|---|---|
| KServe v0.17.0 | home, ns `kserve` | `kserve-crd` + `kserve-resources` apps (home-os `charts/cd`) |
| Knative Serving | home, ns `knative-serving` | Gateway-API ingress → Traefik `kube-system/traefik-gateway` |
| Domain + TLS | — | `sls.ssegning.com`; external issuer `cert-cloudflare` (publicly-trusted) |
| Knative feature flags | — | `podspec-runtimeclassname`, `podspec-nodeselector`, `podspec-persistent-volume-claim/-write` all **enabled** |
| GPU node | home | labelled `gpu-node: "true"`, `RuntimeClass nvidia`, nvidia-device-plugin |
| Gateway + ADR-0021 policy | Hetzner | JWT auth, per-user/org rate limits, token metering |

---

## 2. Model & VRAM budget (RTX A2000, 12 GB, Ampere)

**Ampere has no hardware FP8** — do not deploy FP8 checkpoints. Use **BF16/FP16**
(launch) or **AWQ-INT4 + Marlin** (optimization).

`Qwen/Qwen3-4B`, BF16, on a 12 GB card at `--gpu-memory-utilization 0.90`
(≈10.8 GB usable):

| Consumer | ~VRAM |
|---|---|
| Weights (BF16, 4B) | ~8.0 GB |
| Activations + non-torch overhead (with `--enforce-eager`, no CUDA-graph capture) | ~1.0 GB |
| **KV cache (remainder, on-GPU)** | **~1.5–2 GB** |

That on-GPU KV is thin — which is exactly what **LMCache** fixes: it offloads KV
to **CPU DRAM** (`LMCACHE_LOCAL_CPU=True`, `LMCACHE_MAX_LOCAL_CPU_SIZE=5` GB),
extending the effective cache far past HBM and giving **prefix reuse** across
requests (repeated system prompts, RAG context, multi-turn history skip prefill).
`--kv-cache-dtype fp8` halves KV *storage* (a memory format, not FP8 compute — fine
on Ampere).

**Launch config (trustworthy, official weights):** BF16, `--max-model-len 16384`,
`--max-num-seqs 4`, `--enforce-eager`, LMCache CPU offload.
**Later optimization:** swap to a *vetted* community `Qwen3-4B` AWQ-INT4 (~2.5 GB
weights) → far more KV headroom and concurrency; add `--quantization awq_marlin`.
Vet the quant repo before trusting it (the platform's posture is "no random
third-party artifacts").

> Qwen3 quantized + thinking mode: avoid greedy decoding (repetition loops). The
> model card recommends `temperature 0.6, top_p 0.95, top_k 20`.

---

## 3. Home side — `charts/model-serving` (targets the home cluster)

A KServe `InferenceService` in **Knative Serverless** mode. Shape (values-driven;
final chart TBD):

```yaml
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: qwen3-4b
  namespace: converse-poc
  annotations:
    autoscaling.knative.dev/minScale: "1"   # keep one pod WARM (cold start = reload ~8GB)
    autoscaling.knative.dev/maxScale: "1"   # one GPU
spec:
  predictor:
    runtimeClassName: nvidia                 # needs podspec-runtimeclassname (enabled)
    nodeSelector: { gpu-node: "true" }       # needs podspec-nodeselector (enabled)
    minReplicas: 1
    maxReplicas: 1
    model:
      modelFormat: { name: huggingface }
      runtime: huggingfaceserver             # the chart's OWN namespaced ServingRuntime (§3b)
      storageUri: "pvc://qwen3-4b-models/Qwen3-4B"   # pre-seeded PVC — NOT hf:// (see §3a)
      args:
        - --model_name=qwen3-4b
        - --backend=vllm
        - --dtype=float16
        - --max-model-len=16384
        - --max-num-seqs=4
        - --gpu-memory-utilization=0.90
        - --kv-cache-dtype=fp8
        - --enforce-eager
        - --kv-transfer-config={"kv_connector":"LMCacheConnectorV1","kv_role":"kv_both"}
        # AWQ optimization only: --quantization=awq_marlin
      env:
        - { name: LMCACHE_USE_EXPERIMENTAL,  value: "True" }
        - { name: LMCACHE_LOCAL_CPU,         value: "True" }
        - { name: LMCACHE_MAX_LOCAL_CPU_SIZE, value: "5" }   # GB host RAM for KV
        - name: VLLM_API_KEY                 # the gate on the public endpoint
          valueFrom: { secretKeyRef: { name: vllm-local-api-key, key: api_key } }
      resources:
        limits:   { nvidia.com/gpu: "1", cpu: "4", memory: 16Gi }
        requests: { cpu: "2", memory: 12Gi }    # memory must cover LMCACHE CPU pool
```

Notes:
- **Memory request must exceed the LMCache CPU pool** (`12Gi` covers a 5 GB KV
  pool + the runtime). Undersize it and the pod OOM-kills mid-cache.
- **Weights come from a pre-seeded PVC, not `hf://`** — see §3a (this is the
  answer to "does it download every time?": no).
- **Exposure is automatic:** Knative + net-gateway-api create the HTTPRoute on
  the Traefik gateway; cert-manager (`cert-cloudflare`) issues the public cert.
  Resulting FQDN: **`qwen3-4b-converse-poc--sls.ssegning.com`**. OpenAI paths land
  under **`/openai/v1/...`** (KServe's huggingface runtime prefixes them).
- **Secret:** `vllm-local-api-key` (key `api_key`) via an in-chart ExternalSecret
  → `ssegning-aws` key `ai/camer/digital/prod/env`, property `vllm_local_api_key`
  (maintainer populates it in AWS SM).

### 3a. Model weights: a pre-seeded volume, **not** a per-start download

Left to its default (`storageUri: hf://…` → an `emptyDir`), KServe's
storage-initializer re-downloads the **~8 GB of weights on every cold start** —
pod restart, node reboot, OOM-kill, or *any* config change that rolls the Knative
revision. `minScale: 1` keeps the pod warm so it's not per-request, but it **is
per-rollout** — slow and HF-rate-limit-prone on a home uplink. So the weights
live on a **Longhorn PVC**.

**Chosen: pre-seed the PVC once, then mount it read-mostly** (zero download at pod
start; cold start = a local mount in seconds):

```yaml
# 1) PVC for the weights (Longhorn). ~8GB BF16 + headroom for a future AWQ variant.
apiVersion: v1
kind: PersistentVolumeClaim
metadata: { name: qwen3-4b-models, namespace: converse-poc }
spec:
  accessModes: [ReadWriteOnce]            # safe here — see the gotcha below
  storageClassName: longhorn
  resources: { requests: { storage: 25Gi } }
---
# 2) One-time seed Job — downloads Qwen3-4B into the PVC. Qwen3 is Apache-2.0,
#    so NO HF token needed. Runs once; the InferenceService never downloads.
apiVersion: batch/v1
kind: Job
metadata: { name: seed-qwen3-4b, namespace: converse-poc }
spec:
  ttlSecondsAfterFinished: 600
  template:
    spec:
      restartPolicy: OnFailure
      nodeSelector: { gpu-node: "true" }   # same node the model pins to
      containers:
        - name: seed
          image: python:3.12-slim
          command: ["sh","-c"]
          args:
            - pip install -q huggingface_hub &&
              hf download Qwen/Qwen3-4B --local-dir /models/Qwen3-4B
          volumeMounts: [{ name: models, mountPath: /models }]
      volumes:
        - name: models
          persistentVolumeClaim: { claimName: qwen3-4b-models }
```

Then the InferenceService uses `storageUri: pvc://qwen3-4b-models/Qwen3-4B` (as in
the spec above) — KServe mounts the PVC at `/mnt/models`, no network fetch.

**The Knative + RWO gotcha (and why RWO is fine here):** normally an RWO volume +
rolling Knative revisions risks a mount deadlock (old + new pod both want it). But
the model is pinned to the **single GPU node**, and **RWO = one *node*, many pods**
(the strict per-pod variant is `ReadWriteOncePod`). Both revision pods land on that
one node → RWO Longhorn mounts cleanly to both. No RWX/NFS share-manager needed.
(Unrelated single-GPU reality: a rollout's new pod can't claim `nvidia.com/gpu: 1`
until the old pod frees it, so rollouts serialize — expected with one GPU.)

> **Simpler alternative (Option A):** skip the seed Job, keep `storageUri:
> hf://Qwen/Qwen3-4B`, and mount the PVC at the HF cache dir (`HF_HOME`) so the
> *first* boot downloads once and persists. Less elegant (first start still pulls
> 8 GB, and the storage-initializer's emptyDir must be redirected), but fewer
> moving parts. The pre-seed Job is preferred for fast, network-independent cold
> starts.

> **Re-download triggers to keep in mind even with the PVC:** deleting the PVC,
> switching `modelNameOverride`/quant (seed a new path), or moving to a different
> node pool. Day-to-day config edits roll the revision but reuse the same PVC →
> **no re-download.**

### Application wiring (ai-helm `charts/apps/values.yaml`)

The one sanctioned ADR-0017 exception — a workload that targets the **home**
cluster. This needed a small `charts/apps` template affordance: a per-app
**`homeCluster: true`** flag (the global `argocd.destination` is shared by all
other workloads, so there was no per-app cluster override). `homeCluster: true`
points the app at `argocd.inClusterServer` (the cluster ArgoCD runs on = the
home GPU cluster) and calls the ADR-0017 destination guard with
`allowInCluster: true`, while keeping the app's own workload namespace (unlike
`controlPlane`, which forces the `argocd` ns). The entry:

```yaml
- name: model-serving
  finalizers: [resources-finalizer.argocd.argoproj.io]
  homeCluster: true                 # ADR-0022 exception → in-cluster (home GPU)
  source:
    repoURL: https://github.com/ADORSYS-GIS/ai-helm
    targetRevision: claude/magical-bohr-390242
    path: charts/model-serving
    helm: { releaseName: model-serving, valuesObject: {} }
  destination:
    namespace: converse-poc
  syncPolicy:
    syncOptions: [CreateNamespace=true, ServerSideApply=true]
    automated: { prune: true, selfHeal: true }
```

Renders as the Application `aii-model-serving` (the `ai-apps-v2` / new-cluster
generation) with `destination.server: https://kubernetes.default.svc`.

### 3b. The chart ships its OWN ServingRuntime (no cluster runtimes installed)

This KServe install has **zero `ClusterServingRuntime`s**
(`kubectl --context admin@homeos get clusterservingruntimes` → none), so the
default `kserve-huggingfaceserver` the InferenceService would normally bind to
doesn't exist. Rather than depend on that cluster-wide gap, the chart carries a
**namespace-scoped `ServingRuntime`** (`templates/servingruntime.yaml`, sync-wave
0) that mirrors KServe v0.17's runtime — image
**`kserve/huggingfaceserver:v0.17.0-gpu`** (match the installed KServe version),
`LMCACHE_USE_EXPERIMENTAL=True`, non-root securityContext, `supportedModelFormats:
huggingface`. The InferenceService binds to it by name (`runtime:
huggingfaceserver`); KServe appends `--model_name` + the vLLM tuning args + the
GPU resources and injects `--model_dir=/mnt/models` from the `pvc://` storageUri.

> Dropped the `/dev/shm` `emptyDir` the upstream runtime carries — the home
> KnativeServing doesn't enable the `kubernetes.podspec-volumes-emptydir` feature
> flag, so Knative would reject it. Fine for `tensor-parallel-size=1`; if vLLM
> complains about shared memory, enable that flag in home-os instead.

> Fixing it cluster-wide (so other models work too) is a separate home-os change:
> the `kserve-resources` install should create its default runtimes. Out of scope
> here — this chart is self-contained either way.

---

## 4. Gateway side — wired exactly like DeepInfra (Hetzner, `charts/ai-models`)

### 4a. Backend (`backends:` map)

```yaml
vllm-local-01:
  schema: OpenAI
  prefix: "/openai/v1"                        # KServe huggingface prefix
  fqdn:
    hostname: qwen3-4b-converse-poc--sls.ssegning.com
    port: 443
  securityType: APIKey
  tlsHostname: qwen3-4b-converse-poc--sls.ssegning.com   # System CA (public cert)
  resourceName: vllm-local-01-svc
  secretRef:    { name: vllm-local-api-key }
  externalSecret:
    key: ai/camer/digital/prod/env
    property: vllm_local_api_key
```

This renders the same five CRs every external backend gets: `Backend`
(`fqdn` endpoint), `AIServiceBackend`, `BackendSecurityPolicy` (APIKey),
`BackendTLSPolicy` (`wellKnownCACertificates: System`, since the cert is
publicly-trusted), and the API-key `ExternalSecret`.

### 4b. Model (`models:` map)

```yaml
qwen3-4b-local:
  kind: text
  info:
    contextLength: 16384                      # match --max-model-len
    maxOutputTokens: 8192
    supportedParameters: *spReasoning         # Qwen3 has a thinking mode
  pricing:
    strategy: flat
    standard: { inputPer1M: 0.0, outputPer1M: 0.0 }   # self-hosted
  minBackends: 1                              # single self-hosted backend by design
  backends:
    vllm-local-01:
      ref: vllm-local-01
      priority: 0
      modelNameOverride: "qwen3-4b"           # = the runtime's --model_name (served name)
  # optional resilience — cloud fallback when the home GPU/uplink is down:
  # deepinfra-01: { ref: deepinfra-01, priority: 1, modelNameOverride: "Qwen/Qwen3-4B" }
```

Clients then call the gateway as usual:
`POST /v1/chat/completions` + `x-ai-eg-model: qwen3-4b-local` (+ the Keycloak JWT).
The model inherits ADR-0021 auth, rate limits, and metering; pricing `$0` means
no monthly-budget rule, but burst req/min + tokens/min still apply per plan.

### 4c. Cilium egress — **not needed** (verified)

No new egress policy is required. The Hetzner deny-egress baseline (the
`allow-dns` NetworkPolicies that make a namespace egress-deny-by-default) is
applied **only** to `platform` / `observability` / `data` / `apps`
(`hetzner-k8s/platform/base/networkpolicy-dns.yaml`). The Envoy **data-plane runs
in `envoy-gateway-system`**, which is **not** in that list — so the proxy already
egresses freely to every SaaS backend (deepinfra/fireworks/google), and reaches
the home FQDN the same way. Nothing to add.

> Only if `envoy-gateway-system` is ever brought under the baseline would you need
> an additive allow — then a `CiliumNetworkPolicy` (`endpointSelector`
> `app.kubernetes.io/component: proxy`, `toFQDNs` the model FQDN on 443, plus the
> DNS L7 visibility rule) shipped via a deps overlay, matching the S3/object-storage
> pattern.

---

## 5. Security model

The endpoint is **public**, so layer the defenses:

1. **API key (primary gate).** vLLM runs with `VLLM_API_KEY`; the gateway's
   `BackendSecurityPolicy` sends `Authorization: Bearer <key>`. No key → 401.
   The key lives only in `ssegning-aws`; it is the single thing standing between
   the internet and your GPU.
2. **TLS.** Publicly-trusted cert (cert-cloudflare); the gateway validates it via
   the System CA bundle (`BackendTLSPolicy`).
3. **All real policy is at the gateway.** Keycloak JWT, per-user/per-org budgets,
   burst limits, metering (ADR-0021) apply to traffic *through* the gateway.
   **Direct hits to the FQDN bypass all of it** — which is why (1) matters.
4. **Hardening (recommended before heavy use):**
   - **Traefik IP-allowlist middleware** scoped to the Hetzner LB egress IP on the
     model's HTTPRoute — so only the gateway's source IP can even reach it.
   - and/or **Cloudflare Access** with a service token on `*.sls.ssegning.com`.
5. **Tighter future posture.** If a home↔Hetzner mesh is ever added, flip the
   Knative service to `networking.knative.dev/visibility: cluster-local` and drop
   the public exposure entirely.

Secrets touched (all by-name from `ssegning-aws`, never embedded):
`vllm_local_api_key` (property under `ai/camer/digital/prod/env`).

---

## 6. Build order (status)

1. ✅ **`charts/model-serving`** — PVC + idempotent seed Job + InferenceService
   (`pvc://`) + API-key ExternalSecret, sync-wave ordered (-2…1). The seed Job has
   **no `ttlSecondsAfterFinished`** (a TTL'd Job would vanish and ArgoCD would
   re-download); it lingers as a completed, in-sync resource. Commit `f8d9410`.
2. ✅ **AWS SM** — `vllm_local_api_key` added to `ai/camer/digital/prod/env`.
3. ✅ **`charts/apps`** — the `model-serving` Application via the new
   `homeCluster: true` flag (→ `aii-model-serving`, in-cluster/home). Commit `152c60e`.
4. ✅ **`charts/ai-models/values.yaml`** — `vllm-local-01` backend + `qwen3-4b-local`
   model (flat $0, `minBackends: 1`). Commit `152c60e`.
5. ⛔ **Cilium egress** — **not needed** (§4c): `envoy-gateway-system` isn't under
   the deny-egress baseline.
6. ⏳ **Reconcile** — committed on the deploy branch; awaiting the next
   `ai-apps-v2` root sync (consequential — creates the model on the home GPU +
   routes the gateway to it).

**On first deploy, confirm two things** (both have troubleshooting rows in §8):
the live `InferenceService` `.status.url` matches the backend `fqdn.hostname`, and
the served-model-name matches `modelNameOverride` (`qwen3-4b`).

---

## 7. Verify end-to-end

```bash
# Home: model pod up, GPU claimed, route + cert ready
kubectl --context admin@homeos -n converse-poc get inferenceservice,ksvc,pod
kubectl --context admin@homeos -n converse-poc get httproute,certificate
kubectl --context admin@homeos -n converse-poc logs deploy/qwen3-4b-... | grep -i lmcache  # cache active

# Direct (must require the key) — 401 without, 200 with:
curl -sk https://qwen3-4b-converse-poc--sls.ssegning.com/openai/v1/models            # expect 401
curl -sk -H "Authorization: Bearer $VLLM_API_KEY" \
     https://qwen3-4b-converse-poc--sls.ssegning.com/openai/v1/models                # expect the model

# Through the gateway (the real path) — JWT + model header:
curl -s https://api.ai.camer.digital/v1/chat/completions \
  -H "Authorization: Bearer $KEYCLOAK_JWT" -H "x-ai-eg-model: qwen3-4b-local" \
  -d '{"messages":[{"role":"user","content":"hi"}]}'

# Hetzner: backend CRs Accepted
kubectl --context admin@homeos -n converse get backend,aiservicebackend,backendsecuritypolicy | grep vllm-local
```

LMCache win check: fire the same long system-prompt twice; the second request's
TTFT (time-to-first-token) should drop sharply as prefill is served from cache.

---

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Pod OOM-killed shortly after ready | LMCache CPU pool > pod memory request | raise `requests.memory` above `LMCACHE_MAX_LOCAL_CPU_SIZE` + runtime |
| CUDA OOM on load | weights+graph > budget | `--enforce-eager`, lower `--gpu-memory-utilization`/`--max-model-len`/`--max-num-seqs`, or move to AWQ-INT4 |
| Route has no cert / 526 | cert-manager issuance pending | check `Certificate` in `converse-poc`; `cert-cloudflare` needs the Cloudflare token secret present |
| Gateway → backend `no healthy upstream` / DNS fail | backend FQDN ≠ the live route | **confirm on first deploy:** `kubectl -n converse-poc get inferenceservice qwen3-4b -o jsonpath='{.status.url}'` and set the `vllm-local` backend `fqdn.hostname` + `tlsHostname` to match (KServe/Knative may add a `-predictor`/route suffix) |
| Gateway → backend `no healthy upstream` | (egress is NOT restricted in envoy-gateway-system — §4c) | check the home route is actually serving (curl the FQDN direct); TLS/cert; the FQDN-vs-`.status.url` row above |
| Backend 404 `model not found` | `modelNameOverride` ≠ served name | **confirm on first deploy:** the served name = the runtime's `--model_name` (`qwen3-4b`); if huggingfaceserver advertises the HF path instead, set `modelNameOverride` to that |
| 404 at `/v1/...` | KServe prefixes paths | backend `prefix: /openai/v1` |
| Cold start minutes long / re-downloads weights | using `hf://` + emptyDir, or PVC deleted | pre-seed the PVC and use `pvc://` (§3a); keep `minScale: 1` |
| Pod won't schedule | GPU node taint / label | confirm `gpu-node: "true"` + `nvidia.com/gpu` capacity on the A2000 node |
| `No ServingRuntimes or ClusterServingRuntimes with the name …` | no cluster runtimes installed | the chart now ships a namespaced `ServingRuntime` (§3b); confirm `kubectl -n converse-poc get servingruntime huggingfaceserver` exists and the IS `runtime:` matches |
| Seed Job: `huggingface-cli is deprecated` / `extra 'cli'` | huggingface_hub 1.x renamed the CLI | use `hf download` + `pip install huggingface_hub` (no `[cli]`) — already fixed in the seed Job |
| Seed Job stalls partway (`unauthenticated requests to the HF Hub` / hangs at N%) | anonymous HF Hub rate limit throttles the big shards | set an **HF token**: add `hf_token` to `ssegning-aws ai/camer/digital/prod/env`, then `seedJob.hfToken.enabled: true`. The Job already enables `hf_transfer` + a 1h `activeDeadlineSeconds` (so a stuck attempt dies + retries) |
| Model pod can't read `/mnt/models` | root-seeded files vs non-root runtime | HF files are world-readable (644) so this is usually fine; if not, seed with the runtime's uid or add an `fsGroup` (needs the Knative securityContext feature flag) |
