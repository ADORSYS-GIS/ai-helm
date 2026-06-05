# ADR-0022: Self-hosted GPU model on KServe/Knative, federated into the gateway as a public-FQDN backend

**Status:** Proposed
**Date:** 2026-06-05
**Deciders:** @stephane-segning

## Context

Every model the platform serves today is an external SaaS backend (Fireworks,
DeepInfra, Google AI Studio) — an OpenAI-compatible FQDN reached over TLS with
an API key (`charts/ai-models-backends`). We want to add a **self-hosted** model
running on the home GPU (a single NVIDIA RTX A2000, **12 GB** VRAM, Ampere — so
**no hardware FP8**; AWQ/BF16 only) to cut cost on small-model traffic and prove
out a vLLM + LMCache serving path we control.

Two clusters are in play (ADR-0017): ArgoCD and the GPU both live on the **home**
Talos cluster (`admin@homeos`, in-cluster); the Envoy AI Gateway and the rest of
the workloads live on **Hetzner** k3s (`home-remote`). The naïve worry was that
the gateway (public) would have to dial *back* into the home network (residential
NAT). It does not: the home cluster **already** runs **KServe v0.17.0 + Knative
Serving** with **Gateway-API → Traefik** ingress and **cert-manager auto-TLS**
(`cert-cloudflare`, publicly-trusted), domain `sls.ssegning.com`, and the Knative
feature flags we need (`podspec-runtimeclassname`, `podspec-nodeselector`,
`podspec-persistent-volume-claim`) already enabled. A Knative service therefore
gets a **public HTTPS FQDN for free**. There is prior art: home-os commit
`5dafc759` carried (then commented out) an `ai-poc-model-deployment` Application
that sourced an ai-helm chart and deployed a KServe `InferenceService`
(`vllm/vllm-openai`, `runtimeClassName: nvidia`, `nodeSelector: gpu-node`) to the
home cluster.

## Decision

**Serve one self-hosted model from the home GPU via KServe (Knative Serverless
mode) and federate it into the Hetzner gateway as just another OpenAI backend at
a public FQDN.** Concretely:

- **Model:** `Qwen/Qwen3-4B` — a 4B instruct model with a reasoning mode that
  leaves real KV-cache headroom on 12 GB. Start in **BF16/FP16** (official
  weights, ~8 GB) for trust; a vetted community **AWQ-INT4** quant (~2.5 GB) is a
  later optimization for more KV/concurrency, not a launch requirement.
- **Serving:** a KServe `InferenceService` (+ `ClusterServingRuntime` if needed)
  using the **`kserve/huggingfaceserver` vLLM backend** with **LMCache enabled
  in-pod** (`--kv-transfer-config '{"kv_connector":"LMCacheConnectorV1",
  "kv_role":"kv_both"}'` + `LMCACHE_LOCAL_CPU=True`). vLLM flags tuned for the
  A2000: `--quantization awq_marlin` (only if AWQ), `--dtype float16`,
  `--max-model-len 16384`, `--max-num-seqs 4`, `--gpu-memory-utilization 0.90`,
  `--kv-cache-dtype fp8` (storage), `--enforce-eager`. GPU pinned via
  `runtimeClassName: nvidia`, `nodeSelector: {gpu-node: "true"}`, limit
  `nvidia.com/gpu: 1`.
- **Knative autoscaling:** `minScale: 1` (keep one pod **warm** — a cold start
  reloads multi-GB weights), `maxScale: 1` (one GPU). Serverless mode is used for
  the routing/TLS plumbing, not for scale-to-zero.
- **Connectivity:** **no tunnel, no mesh.** The `InferenceService` is exposed by
  the existing Knative→Traefik→cert-manager path at
  `qwen3-4b-<ns>--sls.ssegning.com` with a publicly-trusted cert.
- **Where it lives:** the `InferenceService` ships from **ai-helm** (new
  `charts/model-serving`) but the Application **targets the home cluster**
  (`server: https://kubernetes.default.svc`, `allowInCluster: true`) — a
  *deliberate, single* exception to ADR-0017's "ai-helm workloads → home-remote".
  The GPU is on the home cluster; the workload must be too.
- **Gateway side (Hetzner, unchanged machinery):** add a `vllm-local` backend
  (schema `OpenAI`, `prefix: /openai/v1`, `fqdn: …sls.ssegning.com:443`,
  `securityType: APIKey`, `tlsHostname` = the FQDN, `wellKnownCACertificates:
  System`) plus a model entry in `charts/ai-models/values.yaml` with
  **pricing = $0** (self-hosted). It then inherits ADR-0021 JWT auth, per-user/
  per-org rate limits, and token metering automatically.

## Consequences

**Positive**
- Reuses everything already installed at home (KServe, Knative, Traefik,
  cert-manager) and everything already built on Hetzner (the external-backend
  machinery + ADR-0021 policy). The self-hosted model is wired *identically* to
  DeepInfra — minimal new surface area.
- No VPN/tunnel to operate; no inbound port-forward through residential NAT.
- LMCache CPU-offload + prefix reuse extends the effective KV cache well past the
  12 GB HBM, making multi-turn / RAG traffic cheap on a small card.
- Cost: small-model traffic moves off paid SaaS onto owned hardware.

**Negative**
- **The model's FQDN is public.** Direct hits bypass the Hetzner gateway and
  therefore bypass Keycloak JWT, budgets, and rate limits. The **vLLM API key is
  the sole gate** on the endpoint — it must stay secret. (Mitigation below.)
- A single 12 GB GPU is a hard ceiling: one model, modest `max-model-len` and
  concurrency. Not a capacity play — a cost/control play.
- A second egress hop (Hetzner → Cloudflare/Traefik → home) adds latency vs. a
  SaaS backend co-located with the gateway, and couples model availability to a
  residential uplink.
- One sanctioned ADR-0017 exception; the render guard must allow it explicitly
  (`allowInCluster: true`), which is a small precedent to police.

**Neutral / follow-ups**
- Harden the public endpoint beyond the API key: a Traefik IP-allowlist
  middleware scoped to the Hetzner LB egress IP, and/or Cloudflare Access with a
  service token. Tracked in the design doc.
- Optional resilience: list a cloud backend at `priority: 1` on the same model so
  Envoy outlier-detection fails over when the home GPU/uplink is down.
- `charts/lmcache` (the standalone `lmcache_experimental_server`) stays dormant —
  it is the *multi-replica shared-KV* tool, irrelevant to a single GPU. Revisit
  only if we ever run >1 vLLM replica that should share a cache.
- If a home↔Hetzner mesh is ever added, flip the Knative service to
  `cluster-local` and drop the public exposure for a tighter posture.

## Alternatives considered

- **KServe RawDeployment (no Knative)** — simpler in the abstract, but it would
  throw away the *already-wired* Knative→Traefik→cert-manager exposure + TLS and
  force us to hand-roll an Ingress/HTTPRoute + Certificate. Knative is installed,
  proven (commit `5dafc759`), and the maintainer explicitly chose it. Rejected.
- **A secure tunnel (Tailscale / Cloudflare Tunnel / WireGuard)** — the right
  answer *if* the home cluster had no public ingress. It does (Knative+Traefik),
  so a mesh would add a moving part for no gain today. Rejected for now (kept as
  the future `cluster-local` path).
- **Run the model on Hetzner** — no GPU there; the A2000 is at home. Rejected.
- **Put the serving app in home-os** (where the prior art lived) — cleaner by
  ADR-0017, but the maintainer chose to keep the model definition in ai-helm
  next to the rest of the AI platform. Accepted as the documented exception.
- **Qwen2.5-7B-Instruct-AWQ** (the higher-quality pick) — viable, but ~5–6 GB
  weights leave less KV headroom; Qwen3-4B was chosen for headroom + a reasoning
  mode. The 7B remains the obvious upgrade if quality matters more than KV.
- **`vllm/vllm-openai` custom runtime** (the prior-art image) — works, but
  LMCache needs extra wiring/packaging there; `kserve/huggingfaceserver` has
  native LMCache support (KServe PR #4320) and is already referenced by
  `charts/lmcache`. Chosen for the batteries-included LMCache path. (Trade-off:
  its OpenAI routes are prefixed `/openai/v1` — handled by the backend `prefix`.)

## Related

- Docs: [`docs/2026-self-hosted-gpu-inference.md`](../2026-self-hosted-gpu-inference.md) (the *how*: VRAM math, flags, runbook, verification)
- Charts/files (planned): `charts/model-serving/` (new), `charts/ai-models/values.yaml` (backend + model entry), `charts/apps/values.yaml` (home-destination Application)
- Prior art: home-os commit `5dafc759` (the commented-out `ai-poc-model-deployment`)
- Builds on: ADR-0017 (destination invariant — this is its sanctioned exception), ADR-0021 (the gateway policy the model inherits)
