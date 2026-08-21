# inference — the self-hosted model orchestrator

Emits **one ApplicationSet** with a child `inference-server` Application per enabled
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
   ApplicationSet child `inference-<name>` → charts/inference-server (OCI)
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
| `defaults.lmcacheEnv` | LMCache tuning applied when a vLLM model uses the in-process `LMCacheConnectorV1`. |
| `defaults.engines.<engine>` | Image, health path and security contexts per engine. `defaults.engines.vllm.lmcacheMp.image` supplies the default `lmcache/standalone` image for `LMCacheMPConnector`. |
| `models.<name>` | The per-model entry: `engine`, `weights`, `serving`, `resources`, optional `lmcache`. |

## Engines

| | `llamacpp` | `vllm` |
|---|---|---|---|
| Weights | GGUF (one file, fetched by `include` glob) | safetensors (AWQ / GPTQ / FP8) |
| Best for | GGUF-only releases, brand-new architectures | throughput, prefix reuse via LMCache |
| Extras | — | opt-in `lmcache.enabled`, `/dev/shm` volume; optional `LMCacheMPConnector` sidecar for GDN hybrids |

Which to pick is an inference decision, recorded in `inference-ops`
`docs/adr/0002-engine-selection-matrix.md`. One rule that is not negotiable:
**do not serve GGUF on vLLM** — its GGUF loader is roughly an 8× throughput
regression versus a Marlin/AWQ kernel.

### LMCache connectors

The chart supports two LMCache connectors for vLLM:

| Connector | When to use | Sidecar | Required flags |
|---|---|---|---|
| `LMCacheConnectorV1` (default) | Dense / full-attention models | none | `lmcache.enabled: true` |
| `LMCacheMPConnector` | Gated DeltaNet / Mamba hybrids (e.g. Qwen3.5-2B) | `lmcache/standalone` MP server | `serving.mambaCacheMode`, `serving.maxNumBatchedTokens`, `lmcache.mp.chunkSize/image` |

The legacy `LMCacheConnectorV1` disables vLLM's hybrid KV cache manager and crashes
GDN hybrids (ticket #973). Those models MUST use `LMCacheMPConnector`, which
keeps the hybrid manager enabled and runs LMCache as a same-pod multiprocess
server. See `inference-ops` `docs/how-to/validate-qwen3.5-2b-hybrid-cache.md`.

## Verification

```bash
helm dep build charts/inference && helm dep build charts/inference-server
helm lint charts/inference --strict
helm template chk charts/inference --dry-run > /dev/null
```

The cross-catalog check (`this fleet ↔ the gateway's federated backends`) runs in
`ai-helm-values` (`./tools/check-model-catalogs.sh` there), because the gateway
catalog moved to that repo in ADR-0126. Run it from an `ai-helm-values` checkout
after publishing a fleet change here.

To render what a child will actually receive — the check worth doing after
editing `_helpers.tpl`, since it exercises the orchestrator *and* the leaf:

```bash
helm template chk charts/inference | awk '/valuesYaml: \|-/{f=1;next} f' | sed 's/^              //' > /tmp/child.yaml
helm template x charts/inference-server -f /tmp/child.yaml -n inference
```
