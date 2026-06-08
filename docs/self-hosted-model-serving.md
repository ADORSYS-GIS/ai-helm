# Self-hosted model serving on the home GPU — the pattern

**The reusable pattern for serving *any* self-hosted model/agent on the home GPU**,
federated into the Hetzner Envoy AI Gateway like a SaaS backend. This guide is
**model-agnostic**; each concrete deployment has its own paper:

| Paper | Engine | Status |
|---|---|---|
| [**Qwen3.5-4B Q4 (llama.cpp)**](./models/qwen3.5-4b-q4.md) | llama.cpp (`llama-server`), UD-Q4_K_XL GGUF | 🟢 **LIVE** — the active model; ~52 tok/s decode, 4 slots, 128k ctx |
| [**Qwen3-4B**](./models/qwen3-4b.md) | vLLM (`huggingfaceserver`) + LMCache, BF16 | 🟦 standby (disabled 2026-06-08; rollback; the reference build) |
| [**Qwen3.5-4B (vLLM/BF16)**](./models/qwen3.5-4b.md) | vLLM, BF16 | 📋 studied, not chosen (documented alternative) |

The *why* of the pattern: [ADR-0022](./adr/0022-self-hosted-gpu-model-federated-into-gateway.md)
(federation + exposure) · [ADR-0028](./adr/0028-owned-hardware-model-pricing.md)
(owned-hardware pricing) · [ADR-0029](./adr/0029-self-hosted-model-plain-deployment.md)
(off Knative) · [ADR-0030](./adr/0030-merge-model-and-proxy-into-one-statefulset-bjw.md)
(one StatefulSet via bjw-template) · [ADR-0032](./adr/0032-llama-cpp-engine-for-self-hosted-models.md)
(llama.cpp as a 2nd engine). **Adding the next model → the checklist in §8.**

> Per-cluster facts assumed live (do not re-create): the **home GPU node**
> (`gpu-node: "true"`, `RuntimeClass nvidia`, nvidia-device-plugin), **Longhorn**
> (RWX), **Traefik** + the `cert-cloudflare` ClusterIssuer (DNS-01) + Cloudflare-
> proxied `*.ssegning.com`, and the **Hetzner gateway** with its ADR-0021 auth /
> budgets / metering. The model runs on `admin@homeos`; the gateway on `home-remote`.

---

## 1. The picture

```
 USER ─TLS + Keycloak JWT─▶  HETZNER (home-remote)              HOME Talos (admin@homeos, GPU)
                            ┌──────────────────────────┐       ┌─────────────────────────────────┐
                            │ Envoy AI Gateway          │ HTTPS │ bjw StatefulSet (always-on)     │
                            │  JWT (ADR-0021) + budgets  │ +key  │  model server (vLLM | llama.cpp) │
                            │  Backend <model>-local ────┼──────▶│  [+ Caddy auth-proxy if vLLM]   │
                            │  rate-limit + metering     │       │  pre-seeded PVC · RTX A2000 12GB │
                            └──────────────────────────┘       └─────────────────────────────────┘
                                                                 plain Ingress (traefik) + cert-cloudflare
                                                                 at <model>--poc.ssegning.com
```

From the gateway's point of view a self-hosted model is **identical to any SaaS
backend**: an OpenAI-compatible FQDN over TLS with an API key. All the novelty is on
the home side (the engine on the GPU). It inherits Keycloak JWT, budgets, rate
limits, and metering centrally.

---

## 2. VRAM budgeting (RTX A2000, 12 GB, Ampere)

**Ampere has no hardware FP8** — never deploy FP8 checkpoints / `--kv-cache-dtype=fp8`
(dlpack BufferError every prefill). Use BF16/FP16 or a 4-bit quant.

Budget = `12 GB × util(0.90) ≈ 10.8 GB − weights − ~1 GB overhead = on-GPU KV`. The
two levers that change the equation:

- **Quant** shrinks weights: BF16 4B ≈ 8 GB → only ~1.5–2 GB KV (≈10–14k tokens);
  a **Q4/AWQ-INT4** 4B ≈ 2.5–2.7 GB → ~5+ GB freed for KV/concurrency.
- **Attention type** changes how fast KV grows: full-softmax KV is fat (a 4B at 131k
  ≈ 12–19 GB/request — infeasible); **linear-attention / Gated-DeltaNet** KV barely
  grows → long context becomes cheap (see the Qwen3.5 papers).

Prove the budget *before* committing: weights + ~1 GB + KV at your target context
must fit. One model per GPU (§7) — a 2nd concurrent model needs a 2nd GPU.

---

## 3. The chart — `charts/model-serving-<model>` (targets the home cluster)

A **hybrid `bjw-template` chart** (like `charts/librechat-app`): `Chart.yaml` deps
`bjw-template` (alias `modelServing`) which renders the **whole workload** — the
model **StatefulSet** (`replicas: 1`, always-on), the **seed `Job`** (a bjw `job`
controller, ArgoCD Sync hook), the **Service**, and the **Ingress**. The chart's
**own `templates/`** render only what bjw doesn't do natively: the weights **PVC**,
the **ExternalSecrets**, and (vLLM only) the **Caddyfile ConfigMap**.

- **Weights via a pre-seeded RWX PVC, not a per-start download.** The seed Job
  downloads once (`hf download …`, `huggingface_hub[hf_xet]` + `HF_TOKEN` to lift the
  rate limit; **no** `HF_XET_HIGH_PERFORMANCE` — it OOM-killed a 2Gi pod). The model
  mounts it read-only. **RWX** (Longhorn) so seed + model can co-mount; accessModes
  are immutable (RWO→RWX = delete+recreate). The seed Job **must** be an ArgoCD Sync
  hook (`hook: Sync`, `hook-delete-policy: BeforeHookCreation`) — a plain tracked Job
  goes perpetually OutOfSync. ⚠️ the seed repo/path are **hardcoded in the bjw seed
  args** (subchart scope can't read the parent `.Values.model.*`) — keep in sync.
- **Public route = a plain k8s `Ingress`** (`className: traefik`) with
  `cert-manager.io/cluster-issuer: cert-cloudflare` (ingress-shim issues the TLS cert;
  no `IngressRoute`/`Certificate` CR). Host `<model>--poc.ssegning.com` — **must
  match** the `ai-models` backend hostname; add the DNS record.
- **GPU access** via `runtimeClassName: nvidia` + `nodeSelector: gpu-node` (bjw
  `defaultPodOptions`) — **no `nvidia.com/gpu` resource** (the PoC node has no device
  plugin advertising it).
- **App wiring** (`charts/apps/values.yaml`): the one sanctioned ADR-0017 exception —
  `homeCluster: true` points the Application at `argocd.inClusterServer` (the home GPU
  cluster) with `allowInCluster: true`, keeping its own namespace. Renders as
  `aii-model-serving-<model>`.

### Engine choice — vLLM vs llama.cpp

| | **vLLM** (`kserve/huggingfaceserver`) | **llama.cpp** (`ghcr.io/ggml-org/llama.cpp:server-cuda`) |
|---|---|---|
| Best for | safetensors BF16/AWQ; high throughput/concurrency; LMCache prefix reuse | GGUF (Q4_K_M etc.); new/turbulent architectures; simpler, lower idle |
| Auth | ⚠️ **ignores `VLLM_API_KEY`** → needs the Caddy auth-proxy sidecar | **native `--api-key-file`** → no sidecar |
| Endpoint | `/openai/v1` | `/v1` |
| Probe | `httpGet /v2/health/ready` (binds `:8080` early — see §7) | `httpGet /health` (503→200) |
| Caveat | LMCache↔vLLM version skew is image-pinned (test before bumping) | use a **recent** build for new arch ops; `server-cuda` (CUDA 12), **not** `server-cuda13` |

Pick per model (see the per-model papers for the worked decision).

---

## 4. Gateway wiring (`charts/ai-models`, on Hetzner)

One **backend** + one **model** entry, exactly like a SaaS backend:

- **Backend** `<model>-local`: `schema: OpenAI`, `prefix:` (`/openai/v1` for vLLM,
  `/v1` for llama.cpp), `fqdn.hostname` = the edge host, `securityType: APIKey`,
  `tlsHostname` (System CA — the cert is publicly-trusted), an API-key ExternalSecret
  (`vllm_local_api_key` under `ai/camer/digital/prod/env`). Renders the usual five
  CRs (Backend, AIServiceBackend, BackendSecurityPolicy, BackendTLSPolicy, ESO).
- **Model** `<model>-local`: `info` (displayName, contextLength, maxOutputTokens,
  `supportedParameters`), `minBackends: 1`, **pricing per ADR-0028** (derive €/h TCO
  → cost-recovery weighted price), `modelNameOverride` = the served name, and a
  `timeout.requestTimeout` (route-scoped BTP; **600 s** — a model route otherwise
  falls back to Envoy's ~15 s default and 504s on long generations / reload windows).

Clients call `POST /v1/chat/completions` + `x-ai-eg-model: <model>-local` + the JWT.

**Cilium egress:** not needed — the Envoy data-plane in `envoy-gateway-system` is not
under the deny-egress baseline, so it reaches the home FQDN freely (like every SaaS
backend).

---

## 5. Security model

The home edge is internet-reachable, so two enforcement points:

1. **Keycloak JWT at the gateway** (identity, budgets, rate limits, metering — the
   real policy; ADR-0021).
2. **A static API key at the home edge** so direct hits to the home domain can't
   bypass the gateway — enforced by the engine's own auth (llama.cpp `--api-key-file`)
   or the **Caddy auth-proxy sidecar** (vLLM, whose image ignores the key). Plus
   publicly-trusted TLS (`cert-cloudflare`).

Hardening if needed: a Traefik IP-allowlist scoped to the Hetzner LB egress IP, or
Cloudflare Access on `*.ssegning.com`. Secrets are by-name from `ssegning-aws`, never
embedded.

---

## 6. Sync waves (this Application's resources, on the home cluster)

`-2` ExternalSecret(s) → `-1` PVC → `0` seed Job (Sync hook) → `1` StatefulSet +
Service + Ingress.

---

## 7. Cross-cutting gotchas (reusable lessons)

- **One model per GPU.** `replicas: 1` always-on; the single-replica StatefulSet
  rolling-update recreates the one pod (never two on the 12 GB card). A deploy =
  ~1–2 min downtime; single GPU = no HA. A CrashLooping pod blocks its own rollout →
  `kubectl delete pod` to force the new revision.
- **Probes for a slow loader.** A model server that binds its port *before* weights
  finish loading will pass a `tcpSocket` probe in seconds → startup stops gating →
  readiness/liveness kill a still-loading pod in a loop. Use an **httpGet
  readiness endpoint** that only 200s once loaded (vLLM `/v2/health/ready`,
  llama.cpp `/health`); startup = that endpoint with a long budget
  (`failureThreshold × periodSeconds ≈ 30 min`); liveness = `tcpSocket` (kernel-level,
  won't false-fail a busy-but-loaded server), gated by startup. With bjw, set
  `custom: true` or it derives the probe from the Service port.
- **Ampere = no FP8** (above).
- **Pin/test the engine image.** vLLM↔LMCache skew is image-pinned (test before
  bumping); a new architecture needs a **recent** llama.cpp build (`server-cuda`,
  not `server-cuda13`).
- **Deploy-time timeout at BOTH hops** — the gateway BTP (600 s) *and* the home edge
  (Caddy `response_header_timeout`, or Traefik Ingress annotations if no Caddy) must
  exceed a long generation + a reload window, or you get 504s.
- **SSA is strict** — a malformed field (e.g. a bare `livenessProbe.path` instead of
  `httpGet.path`) fails the *whole* apply; the pod never starts.
- **DNS/host is manual** — the edge host + the `ai-models` hostname must be set
  together, and the DNS record must point at the home cluster.
- **Host RAM** is the box's, not the pod cap — size pod memory above any CPU-offload
  pool (LMCache) or it OOM-kills mid-cache.

---

## 8. Deploying another self-hosted model / agent (checklist)

Today each model is a **copy of the chart** (`charts/model-serving-<model>`) — the
orchestrator-plus-leaves generalization is only worth it at ~3+ models (§9).

**A. Pick the model & prove the VRAM budget (§2).** No FP8 on Ampere. Choose the
engine (§3 table) and quant. One model per GPU.

**B. Serve it** — copy `charts/model-serving-<ref>` → `charts/model-serving-<model>`,
set `model.{name,hfRepo,storagePath}` + the seed args (hardcoded), the engine
container (image + args + probes per §3/§7), and keep the **edge auth** (engine
native or Caddy).

**C. Wire the gateway (§4)** — one `backends:` entry (right `prefix:`) + one
`models:` entry (`info`, `minBackends: 1`, ADR-0028 pricing, `timeout`). Edge host =
backend hostname; add DNS.

**D. Document it — "document" means *all* of these (per CLAUDE.md):**
1. **A per-model paper** under `docs/models/` (model card, as-built, cost, gotchas).
2. **An ADR** *only if it introduces a new pattern* (new runtime, exposure, pricing
   basis) — e.g. the llama.cpp engine. A same-pattern model is a release note.
3. **arc42** (§5 building-block table if the chart is new; §9 if there's an ADR).
4. **`docs/README.md`** + **`docs/adr/README.md`** indexes.
5. **Memory** (`self-hosted-gpu-model.md`).

**E. Verify** — edge 401 without key / 200 with; model cluster-local (no public
route bypass); a completion **with `tools`** if agentic; the gateway path (JWT +
model header) returns tokens; cost CEL emits non-zero micro-USD. (Per-model runbooks
in their papers.)

### 9. When to generalize the chart (model #3+)

Convert to the **orchestrator-plus-leaves** pattern (ADR-0012/0014 style): an
ApplicationSet List generator with one `model-serving-<name>` leaf per model. Worth
the indirection only once 3+ models share the lifecycle; until then, copy-the-chart
is less machinery. When that day comes, write the ADR and update arc42 §5/§9.

### 10. Choosing the *hardware* for the next model

When the next model outgrows the home A2000, the platform comparison —
**A2000 vs eBay 5×V100 vs Hetzner GEX44/GEX131** (deployability, concurrency,
12/24/36-mo TCO, and the [ADR-0028](./adr/0028-owned-hardware-model-pricing.md)
cost-recovery price of each) — is worked through in
[`2026-06-08-gpu-platform-procurement-comparison.md`](./2026-06-08-gpu-platform-procurement-comparison.md).
Short version: A2000 for ≤8B, GEX44 for managed 7–14B, GEX131 or a 5×V100 box for 70B.
