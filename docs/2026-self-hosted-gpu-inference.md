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
      runtime: kserve-huggingfaceserver      # vLLM backend, LMCache-capable
      storageUri: "hf://Qwen/Qwen3-4B"       # or a PVC-cached path
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
- **Model cache:** `hf://` re-downloads on a cold pod; with `minScale: 1` that's
  once. For resilience, mount a Longhorn PVC for the HF cache (the
  `podspec-persistent-volume-claim` flag is on).
- **Exposure is automatic:** Knative + net-gateway-api create the HTTPRoute on
  the Traefik gateway; cert-manager (`cert-cloudflare`) issues the public cert.
  Resulting FQDN: **`qwen3-4b-converse-poc--sls.ssegning.com`**. OpenAI paths land
  under **`/openai/v1/...`** (KServe's huggingface runtime prefixes them).
- **Secret:** `vllm-local-api-key` (key `api_key`) via an in-chart ExternalSecret
  → `ssegning-aws` key `ai/camer/digital/prod/env`, property `vllm_local_api_key`
  (maintainer populates it in AWS SM).

### Application wiring (ai-helm `charts/apps/values.yaml`)

The one sanctioned ADR-0017 exception — a workload that targets the **home**
cluster:

```yaml
- name: model-serving
  project: ai
  source:
    repoURL: https://github.com/ADORSYS-GIS/ai-helm
    targetRevision: claude/magical-bohr-390242
    path: charts/model-serving
    helm: { releaseName: model-serving, valuesObject: {} }
  destination:
    server: https://kubernetes.default.svc   # the HOME (in-cluster) GPU cluster
    namespace: converse-poc
  allowInCluster: true                        # bypass the home-remote render guard
  syncPolicy:
    syncOptions: [CreateNamespace=true, ServerSideApply=true]
    automated: { prune: true, selfHeal: true }
```

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
  backends:
    vllm-local-01:
      ref: vllm-local-01
      priority: 0
      modelNameOverride: "Qwen/Qwen3-4B"      # what vLLM expects in the body
  # optional resilience — cloud fallback when the home GPU/uplink is down:
  # deepinfra-01: { ref: deepinfra-01, priority: 1, modelNameOverride: "Qwen/Qwen3-4B" }
```

Clients then call the gateway as usual:
`POST /v1/chat/completions` + `x-ai-eg-model: qwen3-4b-local` (+ the Keycloak JWT).
The model inherits ADR-0021 auth, rate limits, and metering; pricing `$0` means
no monthly-budget rule, but burst req/min + tokens/min still apply per plan.

### 4c. Cilium egress (Hetzner default-deny baseline)

The gateway pod must be allowed to egress to the public FQDN:

```yaml
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata: { name: allow-vllm-local-egress, namespace: envoy-gateway-system }
spec:
  endpointSelector:
    matchLabels: { app.kubernetes.io/component: proxy }
  egress:
    - toFQDNs: [{ matchName: "qwen3-4b-converse-poc--sls.ssegning.com" }]
      toPorts: [{ ports: [{ port: "443", protocol: TCP }] }]
```

Ship it via the gateway's deps overlay (`environments/prod/deps/*`), matching the
pattern used for the S3/object-storage FQDN allows.

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

## 6. Build order

1. **ai-helm `charts/model-serving`** — author the InferenceService chart
   (values-driven: model, runtime args, GPU, LMCache env, the API-key
   ExternalSecret). `helm template` it.
2. **AWS SM** — maintainer adds `vllm_local_api_key` to `ai/camer/digital/prod/env`.
3. **ai-helm `charts/apps`** — add the `model-serving` Application (home
   destination, `allowInCluster: true`).
4. **ai-helm `charts/ai-models/values.yaml`** — add the `vllm-local-01` backend +
   the `qwen3-4b-local` model. `helm template` the orchestrator.
5. **Cilium egress** — add the gateway→FQDN allow via the deps overlay.
6. Commit on the deploy branch; let ArgoCD reconcile (flag the consequential
   syncs to the maintainer).

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
curl -s https://api.ai-v2.camer.digital/v1/chat/completions \
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
| Gateway → backend `no healthy upstream` | Cilium egress missing | add the `toFQDNs` CiliumNetworkPolicy (§4c) |
| 404 at `/v1/...` | KServe prefixes paths | backend `prefix: /openai/v1` |
| Cold start minutes long | scale-to-zero reloaded weights | keep `minScale: 1`; PVC-cache the HF download |
| Pod won't schedule | GPU node taint / label | confirm `gpu-node: "true"` + `nvidia.com/gpu` capacity on the A2000 node |
