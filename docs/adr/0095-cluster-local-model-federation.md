# ADR-0095: Federate self-hosted models over the cluster network, not a public edge

**Status:** Accepted
**Date:** 2026-07-26
**Deciders:** @stephane-segning

## Context

[ADR-0022](0022-self-hosted-gpu-model-federated-into-gateway.md) established how a
self-hosted model reaches the Envoy AI Gateway, under a constraint that no longer
exists: the GPU lived on a *different* cluster (`admin@homeos`) from the gateway
(`home-remote`). The only path between them was the public internet, so every
self-hosted model needed a public edge — a Traefik `Ingress`, a `cert-cloudflare`
DNS-01 `Certificate`, a DNS record, a static API key from `ssegning-aws` so that
direct hits to the public host could not bypass the gateway, and (whenever the
engine ignored that key, as `kserve/huggingfaceserver` does) a Caddy auth-proxy
sidecar to enforce it. The Application also needed `homeCluster: true`, the single
sanctioned exception to the [ADR-0017](0017-home-remote-destination-invariant.md)
destination invariant.

Two Hetzner Robot GPU nodes have since joined `home-remote` itself
([ADR-0092](0092-longhorn-for-hetzner-gpu-nodes.md)). The gateway data plane in
`envoy-gateway-system` and the model pods are now on the same pod network. Every
component in the list above exists solely to cross a gap that is no longer there —
and each is a moving part that can fail: an expired certificate, a stale DNS
record, a rotated key the sidecar caches, an auth-proxy that must be kept in front
of an engine that cannot authenticate itself.

## Decision

Federate self-hosted models **over the cluster network**. A model deployed by
`charts/model-serving` ([ADR-0094](0094-generic-model-serving-orchestrator.md))
gets a ClusterIP `Service` in the `inference` namespace and nothing else:

- **No** `Ingress`, public hostname, DNS record or cert-manager `Certificate`.
- **No** static API key, and therefore no `ExternalSecret` for one and no Caddy
  auth-proxy sidecar.
- The gateway's `Backend` points at `<model>.inference.svc.cluster.local:8080`
  over plain HTTP. With no `tlsHostname` no `BackendTLSPolicy` is emitted, and
  with no credential no `BackendSecurityPolicy` is emitted — the latter required a
  guard in `charts/ai-models-backends`, which previously emitted a policy with
  `targetRefs` and no `type` for any credential-less backend.
- Access control is a **`CiliumNetworkPolicy`** in the leaf chart: ingress to the
  inference port is allowed only from `envoy-gateway-system` (the gateway) and
  `observability` (metrics), plus the `host`/`remote-node`/`health` entities that
  carry kubelet probe traffic.

These models are ordinary `home-remote` workloads, so they do **not** use
`homeCluster: true`. That exception is now scoped to the legacy
`charts/model-serving-*` applications serving from `admin@homeos`, and it should
retire with them.

All identity, budgets, rate limits and metering remain exactly where they were:
the gateway, under [ADR-0021](0021-burst-budget-billing-and-dual-plane-authconfigs.md).
Nothing about how a *user* reaches a model changes.

## Consequences

**Positive**

- The model has no route off the cluster at all. There is no public endpoint to
  bypass the gateway with, so the static key that existed to defend one is not
  weakened — it is unnecessary.
- Four failure modes disappear per model: certificate expiry, DNS drift, key
  rotation skew, and a sidecar that must stay in front of the engine.
- One less container per pod, one less Secret, one less `Certificate`, one less
  DNS record to remember at deploy time.
- Latency and egress cost drop: gateway-to-model traffic stays on the pod
  network instead of leaving and re-entering over TLS.
- The `homeCluster` exception stops growing and acquires an end date.

**Negative**

- A model can no longer be reached directly for debugging from outside the
  cluster; that now requires `kubectl port-forward`. This is a deliberate trade —
  the previous convenience was also the bypass risk.
- Access control moves from "a key the engine checks" to "a NetworkPolicy the CNI
  enforces". That is stronger, but it is enforced somewhere less obvious, and a
  CNP mistake is a connectivity failure rather than a 401. The leaf chart's policy
  is generated from fleet defaults precisely so it is not hand-written per model.
- Gateway-to-model traffic is unencrypted on the pod network. Accepted: it is
  first-party traffic inside one cluster, restricted by policy to a single
  source namespace. Cilium transparent encryption would cover it fleet-wide if
  that ever becomes a requirement.

**Neutral / follow-ups**

- The optional per-model API key remains implemented (`apiKey.enabled` on a
  catalog entry, default off) for a future model that must be reachable from
  somewhere other than the gateway. When enabled, **both** engines enforce it
  natively and neither grows a proxy sidecar: `llama-server` via
  `--api-key-file` (Secret mounted at `/etc/model-api-key`), vLLM's own OpenAI
  server via `VLLM_API_KEY`. The Caddy auth-proxy the legacy charts carried was
  never a vLLM limitation — it was required only by `kserve/huggingfaceserver`,
  KServe's wrapper, which ignores `VLLM_API_KEY` outright (verified in ADR-0022:
  unauthenticated and wrong-key both returned 200). That wrapper is deliberately
  not one of the engine profiles, so the sidecar has nothing to come back for.
- The legacy public-edge models continue unchanged until `admin@homeos` retires.
- `docs/patterns/self-hosted-model-serving.md` is rewritten around this shape; its
  public-edge sections describe the legacy generation only.

## Alternatives considered

- **Keep the public edge for parity** — rejected. It preserves four moving parts
  and an internet-reachable inference endpoint to buy consistency with a
  deployment generation that is being retired.
- **Cluster-local but keep the static API key** — rejected as defence-in-depth
  that does not defend much: the threat it addresses (a caller reaching the model
  without passing the gateway) is already eliminated by the NetworkPolicy, and a
  shared secret in every model pod is itself a rotation and leak surface. The
  knob is retained, off, for a case that genuinely needs it.
- **mTLS between gateway and model** — rejected for now as disproportionate:
  per-model certificates and a `BackendTLSPolicy` reintroduce the certificate
  lifecycle this decision removes, for first-party traffic already restricted by
  policy. Cilium transparent encryption is the cheaper answer if it is ever
  needed.

## Related

- Docs: [`docs/patterns/self-hosted-model-serving.md`](../patterns/self-hosted-model-serving.md)
- Charts: `charts/model-server/templates/ciliumnetworkpolicy.yaml`,
  `charts/ai-models-backends/templates/backendsecuritypolicy.yaml`,
  `charts/ai-models/values.yaml`
- Amends: [ADR-0022](0022-self-hosted-gpu-model-federated-into-gateway.md) — the
  federation model stands; the public edge it required does not apply to models on
  `home-remote` GPU nodes. Narrows the `homeCluster` exception of
  [ADR-0017](0017-home-remote-destination-invariant.md) to the legacy generation.
- Related: [ADR-0094](0094-generic-model-serving-orchestrator.md) (the chart),
  [ADR-0092](0092-longhorn-for-hetzner-gpu-nodes.md) (the nodes),
  [ADR-0021](0021-burst-budget-billing-and-dual-plane-authconfigs.md) (auth, unchanged)
