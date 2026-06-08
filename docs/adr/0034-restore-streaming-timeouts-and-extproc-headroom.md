# ADR-0034: Restore streaming-stability gateway timeouts and ExtProc headroom

**Status:** Accepted
**Date:** 2026-06-09
**Deciders:** @stephane-segning

## Context

The current `main` is the *magical-bohr / Hetzner-cutover* rewrite. It and the
pre-cutover `main` **diverged** at `db36eeb` ("chore: authorization") — the
rewrite branched off *before* a body of gateway performance/reliability work
landed, so ~6 "config for faster envoy responses" commits, the
`fix(ai-models): set explicit 600s route timeouts` commit (`20d8f4f`), and the
`plans/gateway-performance-findings.md` write-up (655 lines) were never carried
forward. The rewrite re-created most of the hardening — and improved it (data-
plane HPA, topology spread, `LeastRequest` LB, passive outlier detection, gzip,
HTTP/2 window tuning, larger Envoy CPU) — but a few **streaming-stability**
fixes were dropped, which manifests as long generations being cut mid-stream.

Three concrete gaps in the current tree:

1. **AIGatewayRoute has no `rules[].timeouts`.** The CRD **defaults `request` to
   60s** when unset, and that route-level timeout takes precedence over the
   `BackendTrafficPolicy` upstream timeout. Of the 17 models, only the **2
   self-hosted** set a per-model timeout; the **15 cloud models**
   (Fireworks/DeepInfra) get the 60s default → long code-gen / reasoning
   requests are cut at ~60s.
2. **Cloud models have no upstream `BackendTrafficPolicy` timeout either.** A
   route-scoped BTP *replaces* (no merge) the gateway-wide one, so a model with
   no `timeout` falls back to Envoy's ~15s route default → premature 504s.
3. **The ExtProc sidecar** — the AI Gateway's per-request brain (token counting,
   cost CEL, routing, metadata) that holds state for the whole stream — runs at
   `limits.cpu: 512m`, the exact inline bottleneck the original work raised to
   `2000m`. The traces OTel collector also re-grew a `debug: {}` exporter (a
   per-request stdout flood the original work removed) and lost its
   `memory_limiter`.

## Decision

Restore the lost fixes, re-implemented in the rewrite's current chart structure
(values-driven, not the old hardcoded form) rather than reverting the divergent
commits:

- **Route timeout (`charts/ai-model`).** Render `rules[].timeouts.request` and
  `backendRequest` on every `AIGatewayRoute`, defaulting to **600s**
  (`.Values.timeout.requestTimeout`). Every model — cloud included — now gets an
  explicit route budget instead of the 60s CRD default.
- **Upstream timeout (`charts/ai-model`).** Always emit
  `spec.timeout.http.requestTimeout` on the per-model `BackendTrafficPolicy`,
  defaulting to **600s** so the 15 cloud models get a real upstream budget. Per-
  model overrides (self-hosted: 600s + `connectionIdleTimeout: 1h`) still win.
- **ExtProc headroom (`charts/core-gateway`).** Make the ExtProc sidecar
  resources values-driven (`extProc.resources`) and restore a generous default
  (`limits.cpu: 2000m`, `requests.cpu: 250m`) — a burst ceiling, not a
  reservation, so it survives the constrained worker pool while not throttling
  on the request hot path.
- **Gateway-wide BTP (`charts/core-gateway`).** Make the retry `perRetry.timeout`
  and an optional whole-request `requestTimeout` values-driven (defaults 300s /
  unset). This policy now only governs non-model routes (models use per-model
  BTPs), so impact is small, but it restores the original intent and removes the
  hardcoded 30s.
- **Traces collector (`charts/core-gateway`).** Drop the `debug: {}` exporter and
  restore `memory_limiter` + a tuned `batch` (512 / 5s) on the traces pipeline.

## Consequences

**Positive**

- Long streaming generations through **all** models (especially the 15 cloud
  models) are no longer cut at the ~15–60s defaults — the headline stability
  regression is closed.
- ExtProc has headroom again under concurrent/streaming load; it stops being the
  inline data-path bottleneck.
- The traces collector no longer floods stdout per request and won't OOM the
  collector pod under load (memory_limiter as the circuit breaker).
- All knobs are values-driven, consistent with the rewrite's conventions, so a
  cluster with different capacity can tune them without template edits.

**Negative**

- A 600s default upstream/route budget means a genuinely stuck cloud backend
  holds a connection up to 10 minutes before the route times out. Passive
  outlier-detection + circuit-breaking on the gateway-wide BTP, and the
  provider's own server-side timeout, are the mitigations. Per-model overrides
  can shorten fast models (e.g. rerankers/embeddings) later.
- The ExtProc `limits.cpu: 2000m` ceiling raises the *potential* CPU draw on the
  shared 4×8-CPU worker pool. It is a limit, not a request (request stays
  250m), so scheduling pressure is unchanged; sustained draw only happens under
  real load.

**Neutral / follow-ups**

- Per-model-kind timeout tuning (short budgets for embedding/reranker models)
  remains an open optimization (was "Pending C" in the original findings).
- HTTP/2 upstream to providers and Authorino response caching were also future
  items in the original work — not in scope here.

## Alternatives considered

- **`git revert`/`cherry-pick` the old commits** — rejected: the histories
  diverged and the charts were restructured (`ai-models` → per-model `ai-model`
  leaf, values-driven knobs), so the old diffs don't apply and would clobber the
  rewrite. Re-implementing the *intent* is the only clean path.
- **Only fix the AIGatewayRoute route timeout** — rejected: that alone leaves the
  15 cloud models on the ~15s upstream BTP default, so a slow first byte still
  504s. Both layers need a budget.
- **Hardcode the timeouts back (as the old tree did)** — rejected: the rewrite
  deliberately moved gateway knobs into `values.yaml`; staying values-driven
  keeps the chart cluster-portable.

## Related

- Charts touched: `charts/ai-model/templates/{aigatewayroute,backendtrafficpolicy}.yaml`,
  `charts/ai-model/values.yaml`, `charts/core-gateway/templates/{gateway-config,backendtrafficpolicy,otel}.yaml`,
  `charts/core-gateway/values.yaml`
- Re-implements intent from the divergent pre-cutover commits `20d8f4f`
  ("explicit 600s route timeouts") and the `3d4b99e..0ccbe73` "faster envoy
  responses" series, and the deleted `plans/gateway-performance-findings.md`.
- Builds on: [ADR-0012](./0012-split-ai-models-applicationset.md) (ai-model leaf),
  [ADR-0021](./0021-burst-budget-billing-and-dual-plane-authconfigs.md) (per-model BTP),
  [ADR-0022](./0022-self-hosted-gpu-model-federated-into-gateway.md) (self-hosted timeouts).
</content>
</invoke>
