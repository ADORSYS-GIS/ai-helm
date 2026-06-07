# ADR-0030: Co-locate the model + auth-proxy in one StatefulSet, rendered via bjw-template

**Status:** Accepted
**Date:** 2026-06-07
**Deciders:** @stephane-segning

## Context

ADR-0029 moved the self-hosted model off KServe/Knative to a hand-rolled plain
`Deployment`, with the Caddy auth-proxy as a *separate* `Deployment` + a ClusterIP
`Service` the proxy dialed across the cluster. Two refinements:

1. **Render the workload via `bjw-template`** (the forked bjw-s app-template,
   ADR-0016) like every other workload in this repo, instead of hand-rolled
   manifests — consistency + less bespoke YAML.
2. **Merge the model server and the Caddy proxy into ONE pod** so the proxy
   reaches the model over `localhost` (no cross-pod Service hop, and the model's
   port is never exposed in-cluster at all), as a **StatefulSet**.

## Decision

**One `bjw-template`-rendered StatefulSet with two containers.**

- **`charts/model-serving` is now a hybrid bjw chart** (same shape as
  `charts/librechat-app`): the `bjw-template` subchart (values under
  `modelServing:`) renders the **StatefulSet + Service**; the chart's own
  `templates/` render what bjw doesn't do natively — the weights `PVC`, the
  `ExternalSecret`s, the seed `Job` (an ArgoCD hook), the Caddyfile `ConfigMap`,
  and the edge `Certificate` + Traefik `IngressRoute`.
- **Two containers in one pod:** `model` (`kserve/huggingfaceserver`, listens
  `:8080`) + `proxy` (`caddy`, listens `:8081`). They share the pod network
  namespace, so the proxy reverse-proxies to **`http://localhost:8080`**. Only
  `:8081` is exposed (Service → IngressRoute); the model's `:8080` is pod-local.
- **StatefulSet, `replicas: 1`:** on a single replica the rolling update deletes
  the pod and recreates it — never two model containers on the 12 GB GPU at once
  (the single-instance guarantee ADR-0029 achieved with `Deployment` +
  `Recreate`; the StatefulSet's per-ordinal semantics give the same property).

ADR-0029's decision (off KServe/Knative, always-on, single-instance, Caddy
enforces the Bearer the image ignores) **stands**; this refines only the
*workload shape* (Deployment→StatefulSet, separate proxy→sidecar,
hand-rolled→bjw-template).

## Consequences

**Positive**
- Proxy→model is a **localhost** call — no Service hop, and the model is not
  reachable in-cluster by anything except its pod-mate proxy.
- Fewer objects (one workload + one Service instead of two of each); consistent
  with the repo's bjw house style; probes/resources/lifecycle in one place.

**Negative**
- The proxy shares the model's lifecycle (a model restart cycles the proxy too —
  fine; the proxy is stateless and starts instantly).
- **bjw probe gotcha:** the model's probes need `custom: true` so bjw uses the
  given `spec` (port `:8080`) verbatim. Without it bjw auto-derives the probe
  from the *Service* port (`:8081`, the proxy) — which is always up, so the
  model would be marked Ready before its weights finish loading. Documented in
  the chart values.
- The StatefulSet's governing `serviceName` is the ClusterIP Service (not
  headless) — fine for a single replica with no inter-pod DNS need.

## Alternatives considered

- **Keep two separate Deployments + a Service hop (ADR-0029 as-built)** —
  rejected: an extra object and an in-cluster-reachable model Service for no
  benefit once the two are co-located.
- **A Deployment with two containers (not a StatefulSet)** — equivalent for
  `replicas: 1` (would need `strategy: Recreate` for the single-GPU guarantee).
  The maintainer chose a StatefulSet; its ordinal semantics give the
  one-at-a-time property without a strategy override.
- **Hand-rolled StatefulSet (no bjw)** — rejected: the repo standardizes
  workloads on `bjw-template` (ADR-0016); bespoke manifests are the exception.

## Related

- Charts/files: `charts/model-serving` — `Chart.yaml` (bjw-template dep, alias `modelServing`), `values.yaml` (`modelServing:` block), deleted `templates/deployment.yaml`, new `templates/configmap-caddy.yaml`, slimmed `templates/edge-auth.yaml` (Certificate + IngressRoute only)
- Builds on / refines: ADR-0029 (serving mode), ADR-0016 (bjw-template fork), ADR-0022 (federation/exposure)
- Docs: [`docs/self-hosted-model-serving.md`](../self-hosted-model-serving.md) §11
