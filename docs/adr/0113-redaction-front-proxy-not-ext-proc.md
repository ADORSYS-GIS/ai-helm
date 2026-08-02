# ADR-0113: PII redaction as a front proxy, not an Envoy ext_proc filter

**Status:** Accepted
**Date:** 2026-08-02
**Deciders:** @stephane-segning

## Context

Governance epic [#873](https://github.com/ADORSYS-GIS/ai-helm/issues/873)
needs PII redaction and blocking applied to AI traffic. The source spec's
design puts a custom `ext_proc` processor inside the Envoy filter chain,
positioned before Envoy AI Gateway's own processor — and hedges that this
*"may not"* be achievable on EG v1.8.2 / AIEG v1.0.0, falling back to a
pinned fork of the AI Gateway controller if it isn't.

That ordering question was never answered by measurement (spike
[#874](https://github.com/ADORSYS-GIS/ai-helm/issues/874) is still open) and
does not need to be, because the roadmap's redaction engine choice makes it
moot: [`censgate/redact`](https://github.com/censgate/redact) — Rust,
Apache-2.0 — ships `redact-gateway`, a standalone OpenAI-compatible proxy,
not just the traversal library the original spec assumed. A proxy in front
of the gateway sidesteps the filter-chain positioning problem entirely
rather than solving it.

The ordering spike also lost its second justification. It was originally
expected to be shared with the dynamic-budget-refill epic's data-path
option (a live "how much budget is left" check in the request path); that
epic chose discrete tiers (option A,
[ADORSYS-GIS/lightbridge-authz#188](https://github.com/ADORSYS-GIS/lightbridge-authz/issues/188))
and needs no data-path component at all. A fork of the AI Gateway controller
would now exist to serve exactly one feature.

## Decision

**Deploy `redact-gateway` as a front proxy in front of `core-gateway-internal`,
not as an `ext_proc` filter inside Envoy's chain.**

```
client → redact-gateway (off the shelf) → core-gateway-internal (Authorino → AIEG → provider)
```

`redact-gateway` forwards the caller's own `Authorization` header through
unmodified (`CENSGATE_PROVIDER_FORWARD_CLIENT_AUTHORIZATION=true`) and runs
its own `auth.mode: none` — the only mode the upstream gateway allows to
combine with forwarding, since any other mode would leak `redact-gateway`'s
own credential to the provider. Trust is therefore network-level: ClusterIP
+ `CiliumNetworkPolicy`, matching the existing ADR-0021 internal-plane model
(first-party-only, no route from outside the cluster) rather than a second
credential layer.

**As of this ADR, the deployment is an internal canary only.** The chart
(`charts/censgate-redact-gateway`) is deployed and verified end-to-end
against the real `core-gateway-internal` backend, but no production client's
traffic is routed through it in this change — cutting a real client over is
a separate, reviewed follow-up.

The bundled `default` policy profile is used: `default_action: replace`,
blocks credentials/secrets outright, masks high-sensitivity IDs (SSN, cards,
…) at confidence ≥ 0.7, and **`fail_closed: true`** — matching decision 10
of the governance roadmap (`failOpen: false` in production,
[ai-helm#872](https://github.com/ADORSYS-GIS/ai-helm/pull/872)). Streaming
mode is `buffered` (the documented default), which gives a full-completeness
detection guarantee — no entity can hide in a token split — at the cost of
time-to-first-token equalling total completion time. Incremental mode
(lower latency, weaker guarantee for entities longer than the hold-back
window) is deferred; see "Neutral / follow-ups".

## Consequences

**Positive**
- No `ext_proc` protocol, no filter-chain ordering dependency, no fork of
  Envoy AI Gateway. Spike #874 becomes optional rather than blocking —
  close it as "not needed" once this proxy is proven, rather than running it
  out of completeness.
- Off-the-shelf, maintained upstream (Apache-2.0). No custom image, matching
  this platform's `charts/mcp` proxy precedent (ADR-0040) and the house
  preference to stay Rust/Go-only.
- Redaction metrics (how much was trimmed, per request) come for free via
  the upstream gateway's own OTel instrumentation — a stated requirement of
  the epic, not something this ADR has to design.
- Network-level trust reuses the existing internal-plane model instead of
  inventing a second credential scheme.

**Negative**
- A new hop in the request path once real traffic is cut over. `fail_closed:
  true` means an outage of this proxy becomes an outage of whatever traffic
  depends on it — accepted deliberately (decision 10), but real: it needs
  alerting and a rehearsed rollback before any client depends on it in
  production.
- `redact-gateway` defaults to one replica; scaling out needs a shared
  `vault_kv2` token map, which this canary does not configure (the `default`
  profile doesn't use `tokenize`, so it isn't needed yet — but revisit before
  running more than one replica).
- Buffered streaming mode means time-to-first-token equals total upstream
  completion time for any client routed through this proxy — a real latency
  cost for exactly the traffic (opencode, Kilo-Code) that streams today.

**Neutral / follow-ups**
- Cutting a real production client over to route through this proxy is
  separate, follow-up work — see epic #873 for the sequencing (embeddings
  traffic first, per spike #875's findings).
- Incremental streaming mode, if interactive latency turns out to matter
  more than buffered's completeness guarantee, is a config change
  (`CENSGATE_STREAM_MODE=incremental` + a hold-back window sized above the
  longest entity that must be caught), not a redeploy.
- If a future requirement genuinely cannot be expressed by a front proxy
  (e.g., per-route policy that must live inside the filter chain), spike
  #874 is where that gets answered — with a real requirement behind it
  instead of a hedge.

## Alternatives considered

- **Custom `ext_proc` processor inside Envoy's filter chain** — the
  source spec's original design. Rejected for now: unresolved positioning
  risk on EG v1.8.2/AIEG v1.0.0, and the fallback (a pinned AI Gateway fork)
  is expensive to maintain for a single feature. Revisit only if the front
  proxy provably cannot express a requirement.
- **Writing a first-party redaction engine** — rejected outright.
  `censgate/redact` already exists, in Rust, Apache-2.0, with the exact
  OTel metrics this epic needs. `redact-core` remains the library seam if
  the `ext_proc` variant is ever genuinely required.
- **`CENSGATE_STREAM_MODE=incremental` from the start** — rejected for the
  canary. Buffered is the documented default and the only mode with a
  full-completeness detection guarantee; optimizing for latency before the
  proxy has any real traffic on it is premature.

## Related

- Chart: `charts/censgate-redact-gateway`
- App registration: `charts/apps/values.yaml` (`censgate-redact-gateway`)
- Values-repo file: `ai-helm-values` `environments/prod/values/censgate-redact-gateway.yaml`
- Epic: [ADORSYS-GIS/ai-helm#873](https://github.com/ADORSYS-GIS/ai-helm/issues/873)
- Story: [ADORSYS-GIS/ai-helm#876](https://github.com/ADORSYS-GIS/ai-helm/issues/876)
- Non-streaming canary evidence: [ADORSYS-GIS/ai-helm#875](https://github.com/ADORSYS-GIS/ai-helm/issues/875)
- Deferred: [ADORSYS-GIS/ai-helm#874](https://github.com/ADORSYS-GIS/ai-helm/issues/874) (filter-ordering spike)
