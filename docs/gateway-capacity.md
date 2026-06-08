# Gateway capacity & readiness (Envoy AI Gateway)

**Status as of 2026-06-08.** Assessment of whether `core-gateway` (Envoy AI
Gateway) is ready for a large user population, what the current Hetzner cluster
can actually serve, and the "average user" profile that feels good on it.

## Verdict

**Config-ready, not yet capacity-proven — and the cluster compute, not Envoy, is
the real ceiling.** The Envoy/auth/rate-limit *architecture* is correctly tuned
for high HTTP/2 concurrency; the unproven parts are (1) no load test on Hetzner
yet, and (2) worker CPU headroom. Don't claim "proven for 2000 concurrent" until
the load test runs.

## What's ready (the Envoy layer)

- **Data plane**: HPA (live, wired to the data-plane Deployment), pods spread
  across nodes, PDB `maxUnavailable: 1`, 60s drain / 15s min-drain so SSE/token
  streams aren't cut on rollout.
- **HTTP/2 for fan-out** (`clientTrafficPolicy`): `maxConcurrentStreams: 1000`,
  `connectionLimit: 100000`, 500Mi buffers, 1Mi/16Mi flow-control windows, 1h
  idle timeouts, tcpKeepalive. 2000 laptops multiplex cheaply over ~1–2
  connections each.
- **Upstream resilience** (`backendTrafficPolicy`): circuit breaking, outlier
  ejection (eject on 5×5xx, 30s), LeastRequest LB, gzip, upstream keepalive.
- **Auth + rate-limit are HA**: Authorino instance (`kuadrant-policies-main` CR,
  `converse-gateway`) with a JWT TTL cache; Envoy rate-limit ×2 backed by
  external **Redis-HA** (2 redis + 2 sentinel, `redis-system`).

## The real ceiling: cluster compute

Workers = **4 × 8 CPU / 16 GB = 32 CPU / 64 GB**, already running Mimir, the model
orchestration apps, LibreChat, MCPs, the self-hosted GPU model, and observability
(worker-3 sits ~67% at baseline; ~10 CPU in use, ~20 CPU shared headroom).

The Envoy HPA was previously `maxReplicas: 20` (20 CPU requested / 80 CPU limit) —
a ceiling the 32-CPU pool **cannot feed** alongside the rest of the platform.
**Right-sized to `[3; 5]` (2026-06-08):** 5 pods request 5 CPU (burst ≤20), which
fits the headroom and is ample — Envoy proxies thousands of HTTP/2 streams per pod
at low CPU. Raise `maxReplicas` only in lockstep with adding worker capacity.

> Envoy CPU is **not** the bottleneck for LLM traffic. A request spends ~sub-ms to
> low-ms in the proxy + auth + rate-limit hot path, then **seconds** streaming from
> the model backend. The gateway holds a cheap long-lived HTTP/2 stream; the cost
> is at the backend.

## The "average user" that feels good on the current cluster

**Profile — interactive developer** (opencode / LibreChat): a handful of LLM
calls per *active* minute, each streaming for seconds, with long idle gaps
(reading, thinking, editing). Holds 1–2 HTTP/2 connections, multiplexes a few
streams. This is the workload the gateway is tuned for, and it feels good because:

- **Gateway overhead is negligible** — low-single-digit-ms added latency
  (proxy + cached JWT verify + Redis rate-limit lookup).
- **Well within plan limits** — free = 20 req/min, pro = 120 req/min per user
  (ADR-0021); interactive coding rarely approaches that, so no 429s.
- **Streams stay open** — 1h idle timeout + 60s drain; token streams and idle
  agent sessions aren't dropped.

**How many such users?** For interactive dev, *concurrent in-flight requests* —
not registered users — is what matters, and the duty cycle is low (~5–15% of users
mid-request at any instant). The gateway hot path (Envoy `[3;5]` + Authorino HA +
Redis-HA) comfortably sustains on the order of **a few hundred concurrent in-flight
streaming requests** before Envoy is the limit. At a ~10% active duty cycle that
maps to roughly a **~1,000–2,000 registered interactive-dev population** *at the
gateway layer* — but this is **gated by backend quotas**, and is an estimate until
the load test confirms it.

**It will NOT feel good for:**

- **High-QPS / batch / programmatic clients** sustaining near or above their plan's
  req/min → rate-limited (429). The platform is tuned for interactive bursts, not
  steady high throughput per client.
- **Heavy use of the self-hosted `qwen3-4b`** — single GPU, `max-num-seqs=4`, 16k
  context → it queues/slows under concurrency. Route volume to the SaaS-backed
  models (Fireworks/DeepInfra/Google); keep the GPU model for low-concurrency / PoC.
- **A thundering herd** (most users active at once) — would hit cluster CPU and
  SaaS backend quotas well before Envoy's limits.

## What governs throughput (in order)

1. **Model backends.** Most models are SaaS — real volume is governed by provider
   quotas + our per-org monthly budgets / per-user burst caps (ADR-0021), not by
   Envoy. The self-hosted GPU model is the hard limit for its own traffic.
2. **Cluster CPU** for scale-out (Envoy + Authorino + the platform sharing 32 CPU).
3. **Envoy / Authorino / Redis** — last, and cheap, on the interactive profile.

## Next steps to turn "config-ready" into a measured number

1. **Run the artillery suite against the Hetzner gateway** (`plans/artillery/`) —
   the standing arc42 §11 open item. It will show where it breaks first (Envoy CPU,
   Authorino, Redis, or a backend) and yield a real concurrency number.
2. **Add worker capacity** before raising the Envoy HPA ceiling — the `[3;5]` cap
   matches today's 32-CPU pool; more workers → raise it in lockstep.
3. **Confirm Authorino instance replicas** (HA) and watch Redis under load (the
   rate-limit hot path).
