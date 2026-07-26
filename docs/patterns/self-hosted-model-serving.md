# Self-hosted model serving — the pattern

**How a model gets onto the GPU fleet and in front of users.** This page is the
*how* for this repo; the *why* is in the ADRs it links, and the *inference
knowledge* — VRAM budgeting, quantization, engine choice, benchmarks, runbooks —
lives in the team's **`inference-ops`** repository, which is the source of truth
for all of it. Do not duplicate that material here.

> **Rewritten 2026-07-26** for the Hetzner GPU fleet (ADR-0094/0095). The previous
> version of this page described the one-chart-per-model, public-edge pattern on
> the `admin@homeos` cluster. That generation still runs and is described in
> [§7](#7-the-legacy-generation-adminhomeos) — but nothing new should be built
> that way.

---

## 1. The shape

```
 USER ─TLS + Keycloak JWT─▶  Envoy AI Gateway  ──HTTP, pod network──▶  model pod
                             (envoy-gateway-system)                    (inference ns)
                             auth · budgets · rate limits              1 GPU · 1 model
                             metering (ADR-0021)                       CiliumNetworkPolicy
```

Everything is on **one cluster** (`home-remote`). The gateway reaches a model at
`<model>.inference.svc.cluster.local:8080`. There is no public route to a model,
no TLS between gateway and model, and no API key — the network policy is the
control (ADR-0095).

From the gateway's point of view a self-hosted model is identical to a SaaS
backend: an OpenAI-compatible endpoint. All identity, budget and metering policy
is applied before the request reaches it.

## 2. The charts

| Chart | Role |
|---|---|
| **`charts/model-serving`** | Orchestrator. One ApplicationSet, one child per catalog entry. `controlPlane: true`. **Holds the engine profiles.** |
| **`charts/model-server`** | Generic leaf. One model's resources: bjw-template renders the StatefulSet + seed Job + Service; own templates render PVC, ExternalSecrets, CiliumNetworkPolicy, ServiceMonitor. |
| **`charts/ai-models`** | Unchanged. The gateway catalog — a backend entry + a model entry federate a served model to users. |

**Adding a model is one ~15-line entry** in `charts/model-serving/values.yaml`
(plus its `charts/ai-models` entries to make it user-reachable). No new chart, no
new Application, no ADR. The step-by-step recipe with verification is
`inference-ops` → `docs/how-to/add-a-model.md`.

### Why the engine profiles live in the orchestrator

A Helm parent **cannot compute subchart values at render time**. The workload comes
from the `bjw-template` subchart, so the leaf cannot derive its seed command from
`model.hfRepo`. Every per-model chart worked around this by hardcoding the seed
repo and glob under a `⚠️ keep in sync` comment — one careless edit from serving
one set of weights while downloading another.

The orchestrator writes each child's values as a YAML string, so it *can* derive
everything from one source of truth. That is the whole reason the pair is split
this way (ADR-0094).

To see what a catalog entry actually expands into:

```bash
helm template chk charts/model-serving | awk '/valuesYaml: \|-/{f=1;next} f' | sed 's/^              //' > /tmp/child.yaml
helm template x charts/model-server -f /tmp/child.yaml -n inference
```

## 3. Engines

| | `llamacpp` | `vllm` |
|---|---|---|
| Image | `ghcr.io/ggml-org/llama.cpp:server-cuda` | `lmcache/vllm-openai` |
| Weights | GGUF (one file via `include`) | safetensors (AWQ/GPTQ/FP8/BF16) |
| Prefix / health | `/v1` · `/health` | `/v1` · `/health` |
| Extras | — | opt-in LMCache, `/dev/shm` volume |
| Containers | **1** | **1** |

**The weight format selects the engine, not preference** — `inference-ops`
ADR-0002. Do not serve GGUF on vLLM (~8× throughput regression).

⚠️ **CUDA 12 only.** The fleet runs driver 550 / CUDA 12.4, so `server-cuda13`
will not run.

### On the Caddy sidecar (it is gone, and why it existed)

Neither engine profile has a proxy sidecar. If a model opts into
`apiKey.enabled`, **both engines enforce the Bearer themselves**: llama.cpp via
`--api-key-file` (Secret mounted at `/etc/model-api-key`), vLLM via
`VLLM_API_KEY`.

The Caddy auth-proxy in the legacy charts was never a vLLM limitation. It was
required only by **`kserve/huggingfaceserver`**, KServe's wrapper, which ignores
`VLLM_API_KEY` outright — ADR-0022 verified that unauthenticated *and* wrong-key
requests both returned 200. That wrapper is deliberately not an engine profile
here, so the sidecar has nothing to come back for.

The key itself is off by default: a cluster-local model has no bypass to defend.

## 4. GPU scheduling

Placement is a **resource request**, not a hand-assignment:

```yaml
nodeSelector:     { nvidia.com/gpu.present: "true" }
runtimeClassName: nvidia
tolerations:      [{ key: nvidia.com/gpu, operator: Exists, effect: NoSchedule }]
resources.limits: { nvidia.com/gpu: 1 }
```

Two cards ⇒ two concurrent models. A third enabled model sits `Pending` with
`Insufficient nvidia.com/gpu` — a legible queue that replaces the old "disable that
model to enable this one" dance across four files.

⚠️ The **seed Job carries the same nodeSelector and toleration** despite needing no
GPU: Longhorn runs only on the GPU nodes (ADR-0092), so a pod elsewhere could not
mount the weights volume at all.

## 5. Weights

A one-time seed Job downloads into an RWX Longhorn volume; the model mounts it
read-only, so pod restarts never re-download.

- **`storageClassName: longhorn` is mandatory** — it is not the cluster default and
  cannot bind outside the GPU nodes. Omit it and the claim silently targets
  `hcloud-volumes` and stays `Pending`.
- **`revision` must be a commit SHA.** Hub repos are mutable; the pin is what makes
  the measured bytes the served bytes.
- The Job is an **ArgoCD Sync hook** (`hook: Sync`,
  `hook-delete-policy: BeforeHookCreation`) — a plain tracked Job goes perpetually
  OutOfSync. It writes a `.seeded` stamp of `revision|include`, so repeat syncs are
  no-ops and a changed revision re-seeds.
- `accessModes` are immutable; RWO→RWX means delete + recreate.
- `reclaimPolicy: Retain` — a deleted PVC orphans, not destroys, the weights.

## 6. Sync waves

`-2` ExternalSecrets → `-1` PVC → `0` seed Job + CiliumNetworkPolicy → `1`
StatefulSet + Service + ServiceMonitor.

## 7. The legacy generation (`admin@homeos`)

Eight `charts/model-serving-<model>` charts serve from the **other** cluster over
a public Traefik Ingress with `cert-cloudflare` TLS, a static API key, and
`homeCluster: true` (ADR-0022). `zimage-turbo` is live there; the rest are its
rollback set.

They are **retained, not deleted** — retiring them is a decommissioning exercise on
that cluster. Do not copy their shape for a new model, and do not "fix" them to
match this page; they are correct for where they run.

`homeCluster: true` is now scoped to that generation and should retire with it.

## 8. Gotchas that survived the redesign

- **Probes must gate on a real readiness endpoint.** An engine that binds its port
  before weights finish loading passes a `tcpSocket` probe in seconds; startup then
  stops gating and liveness kills a still-loading pod in a loop. Use `httpGet
  /health` with a long startup budget, `tcpSocket` for liveness only.
- **The NetworkPolicy must allow kubelet probes** (`fromEntities: host,
  remote-node, health`). Without them every probe fails and the pod never goes
  Ready — indistinguishable from a crash-looping engine. A plain `NetworkPolicy`
  `ipBlock` does not work; node IPs carry `remote-node`/`host` identity in Cilium.
- **Memory limits are host RAM, not VRAM.** llama.cpp mmaps the GGUF, so its page
  cache counts against the container limit; vLLM needs headroom above any LMCache
  CPU pool.
- **A context that does not fit fails minutes into loading**, as an allocation
  error that reads like a crash. Measure, don't guess.
- **⚠️ llama.cpp `--ctx-size` is the TOTAL KV pool, split across `--parallel`
  slots.** `--ctx-size 16384 --parallel 2` gives each *request* 8192 tokens, not
  16384. Confirm from the startup log (`n_ctx_slot`) and advertise **that** number
  as `contextLength` in `charts/ai-models`, or the gateway promises users a window
  the model will refuse. `--kv-unified` shares one pool across slots instead.
- **⚠️ A reasoning model's default can dominate the experience.** OpenMythos-27B
  measured 18.2 s for "what is 17 × 23" with thinking on versus 0.2 s with it off,
  and a short `max_tokens` returned an *empty* answer because the whole budget went
  to `reasoning_content`. The fleet default is thinking **off** via
  `--chat-template-kwargs '{"enable_thinking": false}'`, with clients opting back
  in per request. `reasoning_budget: 0` as a *request* field was ignored by
  llama.cpp build 10133 — it is not the lever.
- **Deploy = brief downtime.** One replica on one card; the StatefulSet recreates
  its single pod. A CrashLooping pod blocks its own rollout — `kubectl delete pod`.
- **Route timeout defaults to 60 s** and takes precedence over the upstream BTP, so
  a slow model needs an explicit `timeout.requestTimeout` in `charts/ai-models`
  or long generations 504 (ADR-0034).
- **Ampere-era "no FP8" notes are hardware history.** These Ada cards have hardware
  FP8. FP8 is still 8 bits/weight, so it suits small models here, not a 27B.

## 9. Verification

```bash
helm dep build charts/model-serving && helm dep build charts/model-server
helm lint charts/model-serving --strict
for f in charts/model-server/ci/*-values.yaml; do
  helm lint charts/model-server --strict -f "$f" && helm template x charts/model-server -f "$f" --dry-run >/dev/null
done
./tools/check-model-catalogs.sh
```

`check-model-catalogs.sh` (wired into `helm-lint` CI) enforces the one cross-chart
invariant: a cluster-local gateway backend must have a running model behind it.
Serving *without* federating is allowed on purpose — that is how a model is
measured before users can reach it.

## 10. Where the rest lives

| Topic | Where |
|---|---|
| VRAM budgeting, quantization, engine choice | `inference-ops` `docs/explanation/`, ADR-0002 |
| Add / replace / roll back / measure a model | `inference-ops` `docs/how-to/` |
| Operational failures | `inference-ops` `docs/runbooks/` |
| Hardware facts, model catalog | `inference-ops` `docs/reference/` |
| Measured performance | `inference-ops` `docs/benchmarks/` |
| GitOps shape decisions | ADR-0094 (charts), ADR-0095 (exposure), ADR-0092 (storage) |
| Pricing basis | ADR-0028 |
| Per-model papers (this repo) | [`../models/`](../models/) — legacy generation |
