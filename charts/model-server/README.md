# model-server — the generic self-hosted model leaf

One model, one GPU, one Application's worth of resources. **Never deployed
directly**: [`charts/model-serving`](../model-serving) generates a child per
catalog entry and hands this chart a fully-expanded values block.

> Looking for where to add or change a model? That is
> [`charts/model-serving/values.yaml`](../model-serving/values.yaml). Nothing in
> this directory needs to change to deploy a new model.

Replaces the per-model `charts/model-serving-<model>` copies
([ADR-0094](../../docs/adr/0094-generic-model-serving-orchestrator.md)).

## What it renders

| From | Resource |
|---|---|
| `bjw-template` subchart (alias `modelServing`, ADR-0030) | StatefulSet (the engine), seed Job, Service |
| `templates/pvc.yaml` | Longhorn RWX weights volume |
| `templates/externalsecret-hf-token.yaml` | HuggingFace token for seeding |
| `templates/externalsecret-api-key.yaml` | Optional engine-enforced API key (off by default) |
| `templates/ciliumnetworkpolicy.yaml` | Ingress restricted to the gateway + metrics scraper |
| `templates/servicemonitor.yaml` | Scrape of the engine's own `/metrics` |

## Exposure: cluster-local ([ADR-0095](../../docs/adr/0095-cluster-local-model-federation.md))

No Ingress, no public hostname, no DNS record, no cert-manager `Certificate`, no
static API key, no Caddy auth-proxy sidecar. The GPU nodes are in the same
cluster as the Envoy AI Gateway, so the gateway reaches the model directly at
`<name>.<namespace>.svc.cluster.local:8080` and remains the single place identity,
budgets, rate limits and metering are enforced (ADR-0021).

This is a **stronger** posture than the public edge it replaces: the model has no
route off the cluster at all, so there is no bypass to defend and no shared
secret to rotate.

## Things that will bite you

- **`accessModes` are immutable.** Switching an existing claim RWO→RWX means
  delete + recreate, and the weights re-seed.
- **The seed Job must stay a Sync hook.** A plain tracked Job goes perpetually
  OutOfSync once complete.
- **`longhorn` is not the cluster-default StorageClass** and exists only on the
  GPU nodes (ADR-0092). Omitting `storageClassName` lands the claim on
  `hcloud-volumes`, where it never binds. This is also why the seed Job carries
  the GPU nodeSelector even though it needs no GPU.
- **The NetworkPolicy must allow kubelet probe traffic** (`fromEntities: host,
  remote-node, health`). Without it every probe fails and the pod never goes
  Ready — which reads exactly like a crash-looping engine.
- **Probes must gate on a real readiness endpoint.** An engine that binds its
  port before the weights finish loading passes a `tcpSocket` probe in seconds,
  startup stops gating, and liveness then kills a still-loading pod in a loop.
- **Memory limits are host RAM, not VRAM.** llama.cpp mmaps the GGUF, so its page
  cache counts against the container limit; vLLM needs headroom above any LMCache
  CPU pool.

## Linting

This is a render-only leaf (`lint-mode: ci-values`): its templates fail-guard on
values the orchestrator injects, so a default lint aborts by design. CI lints and
renders `ci/llamacpp-values.yaml` and `ci/vllm-values.yaml` instead — one per
engine profile, so both paths stay covered.

```bash
for f in charts/model-server/ci/*-values.yaml; do
  helm lint charts/model-server --strict -f "$f"
  helm template x charts/model-server -f "$f" --dry-run > /dev/null
done
```

The fixtures are representative, not authoritative. The real check that the leaf
and the orchestrator agree is rendering the orchestrator — see
[`../model-serving/README.md`](../model-serving/README.md#verification).
