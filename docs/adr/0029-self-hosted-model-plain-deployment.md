# ADR-0029: Serve the self-hosted model as a plain Deployment (drop KServe/Knative) — always-on + Recreate on the dedicated GPU

**Status:** Accepted
**Date:** 2026-06-07
**Deciders:** @stephane-segning

## Context

ADR-0022 chose to serve the self-hosted model (Qwen3-4B) via a **KServe
`InferenceService` in Knative Serverless mode**. In practice, on a **single,
owned, *dedicated* GPU** (the home RTX A2000, 12 GB), serverless fought us at
every turn:

- **Cold-start 504s** — scale-to-zero means the first request after idle waits
  for a pod reschedule + a multi-GB weight reload, exceeding route timeouts.
- **Blue-green rollout deadlock** — Knative brings a new revision up *before*
  tearing the old one down, but two Qwen3-4B can't fit in 12 GB, so every deploy
  stalled until the old revision scaled away. We worked around it with
  `minReplicas:0` + autoscaler retention tuning, trading deploy speed for warmth.
- **Extra moving parts** — the activator/queue-proxy hop, autoscaler tuning, and
  the Knative routing layer.

Meanwhile the *reasons* serverless was chosen (ADR-0022) had eroded:

- The "free public Knative TLS FQDN" is **unused** — KServe's huggingfaceserver
  ignores `VLLM_API_KEY`, so the model had to become **cluster-local behind a
  Caddy auth-proxy** (ADR-0022 acceptance note). We never use Knative's route.
- **Scale-to-zero saves almost nothing** on a *dedicated* card: an idle *loaded*
  A2000 draws ~10–15 W (the 70 W is only during inference, paid either way), so
  the saving is ~€3/mo — and **nothing else contends for this GPU**.

So serverless was paying a steep operational cost for a benefit that doesn't
apply here.

## Decision

**Run the model as a plain Kubernetes `Deployment`, not a KServe
`InferenceService`/Knative Service.** Concretely:

- Run the **same stock `kserve/huggingfaceserver` image** (kept for its
  batteries-included vLLM + in-pod LMCache — only the KServe/Knative
  *orchestration* is dropped, not the model server) in a `Deployment` with
  **`replicas: 1`** (always-on) and **`strategy: Recreate`** (the old pod frees
  the GPU before the new one starts — the clean single-GPU handoff Knative
  couldn't give us). Weights mount read-only from the pre-seeded PVC via
  `--model_dir` (replacing KServe's `pvc://` storageUri). GPU via
  `runtimeClassName: nvidia` + `nodeSelector: gpu-node` (no `nvidia.com/gpu`
  request — the PoC node has no device plugin).
- Front it with a **plain ClusterIP `Service`** — the model is then
  **cluster-local by construction** (nothing routes to it publicly).
- **Keep the Caddy edge-auth proxy** (the image still ignores `VLLM_API_KEY`, so
  something must enforce the Bearer), but it now reverse-proxies over **plain
  in-cluster HTTP** to the model Service — no Knative/Traefik in the pod→pod
  path, so no `:80→:443` redirect, no `https`/`tls_insecure_skip_verify`.
- **Delete** the `InferenceService` + `ServingRuntime` CRs and all Knative
  autoscaler annotations.

This **supersedes the serving-mode decision of ADR-0022 only.** ADR-0022's
federation into the Hetzner gateway, the Caddy auth-proxy exposure pattern, the
`homeCluster: true` placement (ADR-0017 exception), and ADR-0028's pricing all
stand unchanged.

## Consequences

**Positive**
- **No cold starts** — the pod is always warm; the per-model Envoy/Caddy timeout
  workarounds now only matter for the brief deploy-time restart.
- **Clean single-GPU rollouts** — `Recreate` guarantees one revision at a time;
  the blue-green deadlock is gone. (This is the "hard single-revision guarantee"
  that was on the backlog.)
- **Simpler request path** — plain HTTP pod→pod (no Traefik redirect, no TLS to
  skip), no activator/queue-proxy hop, no autoscaler to tune.
- **Fewer dependencies** — this workload no longer depends on KServe + Knative
  being healthy.

**Negative**
- **No scale-to-zero** — the pod stays resident and holds VRAM whether or not it
  serves (~€3/mo idle power; fine because the GPU is dedicated). If the GPU ever
  becomes *shared*, revisit.
- **Deploy downtime** — `Recreate` means a short gap (~1–2 min, weight reload)
  with no model pod during a deploy. Acceptable: a single GPU is single-instance
  anyway (no HA), and deploys are infrequent.
- We hand-maintain a `Deployment` instead of leaning on KServe's
  `InferenceService` abstraction (a few dozen lines of template).

**Neutral / follow-ups**
- KServe + Knative stay installed on the home cluster for any future use; we
  simply don't use them for this model.
- Multi-model / autoscaling-across-GPUs would reopen the orchestration question
  (KServe RawDeployment or back to Knative) — out of scope at one dedicated GPU.

## Alternatives considered

- **Keep Knative serverless (ADR-0022 status quo)** — rejected: cold starts +
  rollout deadlock on a dedicated single GPU, in exchange for ~€3/mo of idle
  power saving that doesn't apply (no GPU contention).
- **KServe RawDeployment mode** — keeps the `InferenceService`/`ServingRuntime`
  CRDs but emits a plain Deployment under the hood (+ `deploymentStrategy:
  Recreate`, `minReplicas:1`). The least-churn middle ground and a fine choice;
  the maintainer chose to drop KServe entirely for the simplest, fully
  transparent mental model and to remove the KServe dependency for this workload.
- **StatefulSet** — gives stable per-pod identity / ordered rollout / per-replica
  PVCs, none of which a single replica reading a shared RWO PVC needs. A
  `Deployment` with `strategy: Recreate` provides the kill-before-create property
  more simply.
- **Switch to `vllm/vllm-openai`** (which honours `--api-key`, letting us drop
  Caddy) — rejected: it lacks batteries-included LMCache, so we'd need a custom
  image (against the no-custom-images rule). Keep huggingfaceserver + Caddy.

## Related

- Docs: [`docs/self-hosted-model-serving.md`](../self-hosted-model-serving.md) (architecture, build, runbook)
- Charts/files: `charts/model-serving/templates/deployment.yaml` (replaces `inferenceservice.yaml` + `servingruntime.yaml`), `edge-auth.yaml` (plain HTTP), `values.yaml` (`server:` block replaces `inferenceService:`/`servingRuntime:`)
- Supersedes: ADR-0022 — **serving mode only** (its federation/exposure/`homeCluster` stand)
- Builds on: ADR-0017 (`homeCluster: true`), ADR-0028 (pricing, unaffected)
