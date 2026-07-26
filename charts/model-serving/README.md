# model-serving — the self-hosted model orchestrator

Emits **one ApplicationSet** with a child `model-server` Application per enabled
entry in [`values.yaml`](./values.yaml) `models:`. Same orchestrator-plus-leaves
shape as [`ai-models`](../ai-models) (ADR-0012); the decision to generalise is
[ADR-0094](../../docs/adr/0094-generic-model-serving-orchestrator.md).

**To add, replace or remove a model, edit `values.yaml`. Nothing else.** The
step-by-step recipes, with verification, live in the team's `inference-ops` repo
(`docs/how-to/add-a-model.md`, `docs/how-to/replace-a-model.md`).

## What a catalog entry becomes

```
values.yaml models.<name>          (~15 lines you write)
        │
        └─ _helpers.tpl expands it ─────────────────────────────────┐
                                                                    ▼
   ApplicationSet child `model-serving-<name>` → charts/model-server (OCI)
                                                                    │
        ┌───────────────────────────────────────────────────────────┘
        ▼
   PVC (Longhorn RWX) · ExternalSecret (HF token) · seed Job (Sync hook)
   StatefulSet (engine + 1 GPU) · Service (ClusterIP) · CiliumNetworkPolicy
   ServiceMonitor
```

Sync waves inside a child: `-2` ExternalSecrets → `-1` PVC → `0` seed Job +
NetworkPolicy → `1` StatefulSet + Service + ServiceMonitor.

## Why the engine profiles live here and not in the leaf

A Helm parent cannot compute **subchart** values at render time. The leaf's
workload comes from the `bjw-template` subchart, so the leaf itself cannot derive
(say) the seed Job's download command from `model.hfRepo`. Every per-model chart
that came before this one worked around that by hardcoding the repo and glob in
the bjw values under a `⚠️ keep in sync` comment — one edit away from serving one
set of weights while downloading another.

The orchestrator has no such limit: it writes each child's values as a YAML
string, so `_helpers.tpl` can derive everything from one source of truth. That is
the whole reason this chart exists rather than a values file per model.

## Values

| Key | Purpose |
|---|---|
| `argocd.*` | Where children land. The ApplicationSet is a control object (in-cluster/argocd); children are workloads on `home-remote`, namespace `inference` — ADR-0017. |
| `defaults.gpu` | `nvidia.com/gpu` count, `runtimeClassName`, nodeSelector, tolerations. GPU placement is a scheduler decision, not a hand-assignment. |
| `defaults.storageClassName` | `longhorn` — GPU-nodes-only and *not* the cluster default, so it must be named (ADR-0092). |
| `defaults.hfToken` | ESO-backed HuggingFace token for the seed Job. |
| `defaults.networkPolicy` | Who may reach a model: the gateway and the metrics scraper. |
| `defaults.lmcacheEnv` | LMCache tuning applied when a vLLM model opts in. |
| `defaults.engines.<engine>` | Image, health path and security contexts per engine. |
| `models.<name>` | The per-model entry: `engine`, `weights`, `serving`, `resources`. |

## Engines

| | `llamacpp` | `vllm` |
|---|---|---|
| Weights | GGUF (one file, fetched by `include` glob) | safetensors (AWQ / GPTQ / FP8) |
| Best for | GGUF-only releases, brand-new architectures | throughput, prefix reuse via LMCache |
| Extras | — | opt-in `lmcache.enabled`, `/dev/shm` volume |

Which to pick is an inference decision, recorded in `inference-ops`
`docs/adr/0002-engine-selection-matrix.md`. One rule that is not negotiable:
**do not serve GGUF on vLLM** — its GGUF loader is roughly an 8× throughput
regression versus a Marlin/AWQ kernel.

## Verification

```bash
helm dep build charts/model-serving && helm dep build charts/model-server
helm lint charts/model-serving --strict
helm template chk charts/model-serving --dry-run > /dev/null
./tools/check-model-catalogs.sh
```

To render what a child will actually receive — the check worth doing after
editing `_helpers.tpl`, since it exercises the orchestrator *and* the leaf:

```bash
helm template chk charts/model-serving | awk '/valuesYaml: \|-/{f=1;next} f' | sed 's/^              //' > /tmp/child.yaml
helm template x charts/model-server -f /tmp/child.yaml -n inference
```
