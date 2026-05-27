# Envoy AI Gateway — Performance & Reliability Findings

**Author:** Engineering (with Claude)
**Date:** 2026-05-27
**Status:** In Progress — several issues resolved, others pending

---

## Context

Users were experiencing gateway timeouts, 5XX errors, and slow model response times routed
through the Envoy AI Gateway. This document captures every issue found during the investigation,
the fix applied (or the reason it was deferred), and the rationale behind each decision.

**Stack overview:**

```
Client
  └─► Envoy Proxy (core-gateway, 2 replicas)
        ├─► Authorino (ext-authz, gRPC) ──► Lightbridge OPA ──► PostgreSQL
        ├─► ExtProc sidecar (AI Gateway — token counting, cost, routing)
        │     └─► Phoenix OTel Collector ──► Phoenix (traces) + Alloy/Tempo
        ├─► Lua filter (response hook — cost metadata)
        └─► Upstream backends
              ├─► DeepInfra (deepinfra-01 / deepinfra-02) — most text models
              └─► Fireworks (fw-01 / fw-02) — multimodal models

        Envoy access logs ──► Usage OTel Collector ──► Lightbridge (billing) + Alloy/Loki
```

> **Note:** LiteLLM (models-proxy) is no longer in the request path. All models route
> directly to DeepInfra or Fireworks via `AIGatewayRoute` and `AIServiceBackend`.

---

## Issues Found and Addressed

---

### Issue 1 — Debug logging active in production

**File:** `charts/core-gateway/templates/envoy-proxy.yaml`

**Root cause:**
```yaml
# Before
logging:
  level:
    default: debug
```
Envoy at `debug` level logs every header, routing decision, filter event, and connection
lifecycle event for every request. Under any meaningful load this burns significant CPU
on log serialization and I/O flush per request, causing CPU throttling on Envoy pods and
adding 10–80ms of latency depending on load.

**Fix applied:**
```yaml
# After
logging:
  level:
    default: warn
```

**Rationale:** `warn` surfaces real problems (connection failures, config errors) without
the per-request overhead of debug output. Zero risk change — no request behaviour is
altered, only what Envoy writes to stdout.

---

### Issue 2 — Envoy pod CPU limit too low

**File:** `charts/core-gateway/templates/envoy-proxy.yaml`

**Root cause:**
```yaml
# Before
limits:
  cpu: "1000m"   # 1 vCPU per pod
```
With debug logging enabled (Issue 1), 1 vCPU per pod was being CPU-throttled under
moderate load. Even after fixing logging, 1 vCPU is lean for a gateway handling auth
checks, Lua execution, OTel serialisation, and response body inspection concurrently.

**Fix applied:**
```yaml
# After
limits:
  cpu: "2000m"   # 2 vCPU per pod
```

**Rationale:** Doubles headroom per pod without changing replica count. The request stays
on the same pod — more vCPU means less scheduling delay and fewer throttle events under
concurrent load.

---

### Issue 2b — ExtProc sidecar CPU limit too low

**File:** `charts/core-gateway/templates/gateway-config.yaml`

**Root cause:**
```yaml
# Before
resources:
  requests:
    cpu: "100m"
  limits:
    cpu: "512m"
    memory: "512Mi"
```
The ExtProc sidecar is the AI-specific brain of the gateway. Every request body and
response body passes through it for token counting, model routing decisions, cost
calculation (CEL expressions), and metadata population. At 512m CPU, this component
became the hardest bottleneck in the data path under concurrent load, especially for
long streaming responses where it holds state for the entire stream duration.

**Fix applied:**
```yaml
# After
resources:
  requests:
    cpu: "500m"
  limits:
    cpu: "2000m"
    memory: "512Mi"
```

**Rationale:** Raised the limit to match the Envoy pod itself. The ExtProc processes
every AI request inline — it should never be the bottleneck when the Envoy pod has
headroom. The request value was also raised from 100m to 500m so Kubernetes schedules
the pod on a node with realistic CPU available.

---

### Issue 3 — Streaming responses cut off mid-stream (30s timeout)

**File:** `charts/core-gateway/templates/backendtrafficpolicy.yaml`

**Root cause:**
```yaml
# Before
retry:
  numRetries: 5
  perRetry:
    timeout: 30s
  retryOn:
    httpStatusCodes:
      - 500
      - 502
      - 503
      - 504
      - 404       # retrying 404 is wrong
```
The `perRetry.timeout: 30s` killed any upstream response that took longer than 30
seconds — which is the normal case for complex code generation or architecture analysis.
Envoy would cut the stream, then retry (up to 5 times), causing users to see their
generation start, die at ~30 seconds, and restart from scratch. The 404 retry entry
compounded this: a model-not-found error would be retried 5 times, each waiting up to
30s, for a maximum client wait of 150 seconds before getting a failure.

**Fix applied:**
```yaml
# After
timeout:
  http:
    requestTimeout: 600s
retry:
  numRetries: 1
  perRetry:
    timeout: 300s    # 5 minutes — covers even very long LLM responses
  retryOn:
    httpStatusCodes:
      - 500
      - 502
      - 503
      - 504
      # 404 removed — a missing model should never be retried
```

**Rationale:** The `perRetry.timeout` needs to be longer than the longest reasonable
LLM response. 300s (5 minutes) covers the full range of models in the stack. `numRetries`
reduced to 1 — a single retry is appropriate for transient errors; multiple retries on
LLM calls amplify load on already-stressed backends. The top-level `requestTimeout: 600s`
acts as the absolute ceiling so no connection is held open forever.

---

### Issue 4 — `debug {}` exporter on both OTel collectors

**File:** `charts/core-gateway/templates/otel.yaml`

**Root cause:**
```yaml
exporters:
  debug: { }   # present on both phoenix and usage collectors
```
Both OTel collectors were printing every trace and every access log record to pod stdout
synchronously. Under load this created significant I/O pressure on the collector pods,
accelerated batch queue buildup, and contributed to the backpressure chain described
in Issue 6.

**Fix applied:** Removed `debug: {}` from both collectors and from both pipeline
`exporters` lists.

**Rationale:** The debug exporter exists for local development only. In production it
produces unbounded stdout volume proportional to traffic, with no operational benefit
that isn't already covered by the structured exports to Phoenix and Alloy.

---

### Issue 5 — OTel batch processor unconfigured (200ms default flush)

**File:** `charts/core-gateway/templates/otel.yaml`

**Root cause:**
```yaml
processors:
  batch: { }   # all defaults: send_batch_size=8192, timeout=200ms
```
The default 200ms batch timeout means data sits in the collector for up to 200ms before
being flushed downstream. Under light load this added a consistent 0–200ms tail to usage
log delivery. Under heavy load, the large default batch size (8192) caused the batch to
fill and block while waiting for the downstream export to complete.

**Fix applied:**
```yaml
processors:
  memory_limiter:
    check_interval: 1s
    limit_mib: 400
    spike_limit_mib: 100
  batch:
    send_batch_size: 512
    timeout: 5s
```

**Rationale:** Smaller batch size (512) means each batch is cheaper to process and export.
Longer timeout (5s) reduces export frequency under light load — fewer round trips to
Lightbridge and Alloy. The `memory_limiter` added as the first processor in both pipelines
acts as a circuit breaker: it starts dropping data before the collector OOMKills, which
would lose data entirely and leave Envoy without a log sink. `memory_limiter` must always
be first in the processor chain.

---

### Issue 6 — OTel collectors block on slow downstream exporters

**File:** `charts/core-gateway/templates/otel.yaml`

**Root cause:** Without `sending_queue`, the OTel batch processor hands data directly to
the exporter and waits for acknowledgment. If Lightbridge (the billing backend) was slow
or restarting, the export call blocked the batch processor. This caused a backpressure
chain:

```
Lightbridge slow
  → usage-collector export blocks
    → batch processor stalls
      → usage-collector gRPC receiver backs up
        → Envoy's internal access log queue fills
          → Envoy worker threads experience backpressure
```

**Fix applied — phoenix collector (traces):** In-memory `sending_queue` with 1000-batch
capacity added to both exporters. Traces are best-effort observability data — losing
them during an outage is acceptable.

```yaml
sending_queue:
  enabled: true
  queue_size: 1000
retry_on_failure:
  enabled: true
  initial_interval: 5s
  max_interval: 30s
  max_elapsed_time: 300s
```

**Fix applied — usage collector (billing logs):** Disk-backed `file_storage` queue. Usage
records are billing data — they must not be lost during a Lightbridge restart or outage.
A 2Gi PVC was added for the queue storage. The collector now writes to disk immediately
upon receiving from Envoy, then exports from disk to Lightbridge and Alloy in background
goroutines. Lightbridge can be unreachable for an extended period; the collector will
drain the backlog in order once it recovers.

```yaml
extensions:
  file_storage/queue:
    directory: /var/otel/storage
    timeout: 10s
    compaction:
      on_start: true
      on_rebound: true
      rebound_needed_threshold_mib: 100

exporters:
  otlphttp/lightbridge_usage:
    sending_queue:
      enabled: true
      storage: file_storage/queue   # disk-backed
      queue_size: 5000
```

**Rationale for the split approach:** The phoenix (traces) and usage (billing) collectors
serve fundamentally different contracts. Traces are best-effort — missing one has no
business impact. Usage records are financial records — losing them means unbilled usage.
They warrant different durability guarantees and the additional cost of a PVC.

---

### Issue 7 — Client-side buffer and missing downstream timeout

**File:** `charts/core-gateway/templates/client-traffic-policy.yaml`

**Root cause:**
```yaml
# Before
connection:
  bufferLimit: 500Mi   # 500MB per downstream connection
# no requestTimeout
```
A 500Mi buffer per client connection means a burst of 50 concurrent clients could
theoretically allocate 25GB of Envoy RAM in buffers alone before routing a single byte.
The absence of a downstream request timeout meant stalled or very slow clients could
hold an Envoy worker thread open indefinitely.

**Fix applied:**
```yaml
# After
connection:
  bufferLimit: 64Mi    # generous for multimodal (images) while safe under load
http:
  requestTimeout: 620s # 20s above the backend ceiling; only fires for hung connections
```

**Rationale:** 64Mi is chosen specifically because the stack handles image inputs.
A 4K image base64-encoded is ~10MB; 64Mi comfortably accommodates several large images
in one request while removing the risk of RAM exhaustion under load. The `requestTimeout`
of 620s is deliberately set 20 seconds above the backend's 600s `requestTimeout` so it
acts purely as a safety net for truly hung connections — it will never fire for a normal
streaming response.

---

### Issue 8 — No connection pool or TCP keepalive for external backends

**File:** `charts/core-gateway/templates/backendtrafficpolicy.yaml`

**Root cause:** No `tcpKeepalive` or `circuitBreaker` configuration on the gateway-level
`BackendTrafficPolicy`. Without keepalive, idle connections to DeepInfra and Fireworks
time out and close. The next request after any quiet period pays the full TLS handshake
cost (100–300ms) synchronously on the worker thread, adding directly to the user's
response latency. Without connection pool limits, burst traffic opens unlimited parallel
TLS connections simultaneously, competing for worker threads and potentially overwhelming
the provider's connection limits.

**Fix applied:**
```yaml
tcpKeepalive:
  time: 120s      # probe after 2 minutes idle
  interval: 30s   # probe every 30s
  probes: 3       # close after 3 missed probes

circuitBreaker:
  maxConnections: 200
  maxParallelRequests: 200
  maxPendingRequests: 100
  maxRequestsPerConnection: 0   # 0 = reuse indefinitely
```

**Rationale:** `tcpKeepalive` ensures connections stay warm through quiet periods —
the TLS handshake cost is paid once at warmup, not on every request. `maxRequestsPerConnection: 0`
means Envoy reuses each connection for as long as the provider keeps it open, minimising
renegotiations. The `circuitBreaker` limits prevent a traffic spike from opening 200+
simultaneous TLS connections; instead, requests queue (up to 100 pending) and are served
as connections become available. When `maxPendingRequests` is reached, Envoy returns 503
immediately rather than silently queueing — this gives clients a fast, actionable signal
rather than a timeout.

---

## Issues Found — Not Yet Addressed

---

### Pending A — Both DeepInfra backends share the same API key

**File:** `charts/ai-models/values.yaml`

```yaml
deepinfra-01:
  secretRef:
    name: deepinfra-api-key-only   # same key
deepinfra-02:
  secretRef:
    name: deepinfra-api-key-only   # same key
```

**Problem:** DeepInfra rate-limits and throttles at the API key level. When `deepinfra-01`
is throttled and Envoy fails over to `deepinfra-02`, it hits the exact same account quota.
Both backends fail simultaneously. The HA setup is an illusion for rate-limit scenarios.
Fireworks correctly uses separate keys (`fireworks-api-key-01` / `fireworks-api-key-02`)
and should be used as the model.

**Fix needed:** Provision a second DeepInfra API key and assign it to `deepinfra-02`.

---

### Pending B — Access log field audit

**File:** `charts/core-gateway/templates/envoy-proxy.yaml`

The access log currently serializes 30+ fields per AI request. Each field is a synchronous
lookup (`%DYNAMIC_METADATA(...)%`, `%REQ(...)%`) executed during request finalization.
Several fields appear to be debug-only (e.g., `downstream_local_address`, `upstream_local_address`,
`requested_server_name`, `upstream_cluster`) and likely not consumed by Lightbridge for
billing. Additionally, PII fields (`lc_user_email`, `lc_user_name`, `x-forwarded-for`)
are logged on every request.

**Fix needed:** Coordinate with the Lightbridge team to audit exactly which fields their
`/v1/otel/logs` endpoint consumes. Remove unused fields to reduce per-request
serialization work and reduce data flowing through the OTel pipeline.

---

### Pending C — No per-model timeout tuning

**File:** `charts/ai-models/templates/backendtrafficpolicy.yaml`

All models inherit the global 300s `perRetry.timeout` and 600s `requestTimeout`. A
reranker call (`qwen3-reranker-8b`) should never take 300 seconds — if it does, it has
failed. Long timeout windows mean slow failure detection: when DeepInfra is degraded,
users wait the full timeout window before receiving an error.

**Fix needed:** Add per-model or per-model-kind timeout overrides in the `ai-models`
`BackendTrafficPolicy`. Suggested groupings:
- Embedding / reranker models: `perRetry.timeout: 30s`
- Standard text models: `perRetry.timeout: 120s`
- Large reasoning models (Kimi, DeepSeek): `perRetry.timeout: 300s`

---

### Pending D — HTTP listener has no authentication

**File:** `charts/core-gateway/templates/gateway.yaml` + `charts/kuadrant-policies/templates/securitypolicy.yaml`

The `SecurityPolicy` (Authorino ext-authz) only targets the `api-https` listener
(`sectionName: api-https`). The HTTP listener on port 80 is completely unprotected —
no authentication, no billing, no rate limiting. Any traffic on port 80 bypasses the
entire auth chain and reaches backends unchecked.

**Fix needed:** Either remove the HTTP listener entirely (redirect to HTTPS at the LB
level), or apply the same `SecurityPolicy` to the `http` section. The former is
preferred — there is no reason to allow unencrypted AI API traffic.

---

## Future Next Steps

These go beyond configuration changes and represent architectural improvements worth
planning for.

---

### 1. Separate DeepInfra API keys (Pending A above)
Immediate. Low effort, high impact. One new API key, one secret, one values change.

---

### 2. Per-model timeout tuning (Pending C above)
Low effort, meaningful improvement to failure detection speed. Template work in
`ai-models` chart.

---

### 3. HTTP listener lockdown (Pending D above)
Security and correctness fix. Remove port 80 or apply auth to it. Should be done before
any public exposure of the gateway.

---

### 4. HTTP/2 upstream connections to DeepInfra and Fireworks
Both providers support HTTP/2. Enabling it allows Envoy to multiplex multiple concurrent
requests over a single TLS connection, dramatically reducing the number of connections
needed under burst traffic and eliminating most of the TLS overhead even beyond what
keepalive solves. Requires verifying backend HTTP/2 support and enabling via
`BackendTrafficPolicy` or Backend resource annotation.

---

### 5. Envoy replica autoscaling (HPA)
Currently fixed at 2 replicas. A `HorizontalPodAutoscaler` targeting CPU utilisation
(~60% threshold) would allow the gateway to scale out during traffic spikes and scale in
during quiet periods. Given the 2 vCPU limit per pod and the mix of auth, Lua, OTel, and
request inspection work per request, autoscaling would directly address load-driven 5XX
errors.

---

### 6. Active health checking on backends
Currently there are no active health checks on DeepInfra or Fireworks backends. Envoy
only learns a backend is unhealthy when a real user request fails (passive health check).
Adding active health checks (`BackendTrafficPolicy.healthCheck`) means Envoy probes the
backends on a schedule and removes unhealthy endpoints from rotation before any user
is affected.

---

### 7. Authorino response caching
Every request goes through a 3-hop auth chain: Envoy → Authorino → Lightbridge OPA →
PostgreSQL. For the same API key, the auth result doesn't change between requests.
Authorino supports caching auth responses via `spec.response.cache`. Enabling this would
collapse the 3-hop chain into a local cache hit for repeat callers, significantly reducing
auth latency at scale.

---

### 8. Access log field reduction (Pending B above)
Coordinate with Lightbridge team. Potential to reduce per-request Envoy CPU work and
shrink the OTel pipeline payload by ~40–60% depending on how many fields are actually
consumed.

---

### 9. Separate observability keys per model family
Currently `deepinfra-01` and `deepinfra-02` share one API key (Pending A). Once that is
fixed, consider going further: separate keys per model family (text vs. embedding vs.
reasoning) to allow fine-grained quota monitoring and provider-side usage visibility.

---

## Summary Table

| # | Issue | File | Status | Impact |
|---|---|---|---|---|
| 1 | Debug logging in production | `envoy-proxy.yaml` | ✅ Fixed | CPU drain on every request |
| 2 | Envoy pod CPU limit (1 vCPU) | `envoy-proxy.yaml` | ✅ Fixed | CPU throttling under load |
| 2b | ExtProc sidecar CPU limit (512m) | `gateway-config.yaml` | ✅ Fixed | Inline AI processing bottleneck |
| 3 | Streaming responses cut at 30s | `backendtrafficpolicy.yaml` | ✅ Fixed | Users see generations restart |
| 4 | `debug {}` OTel exporter | `otel.yaml` | ✅ Fixed | I/O flood under load |
| 5 | Unconfigured OTel batch processor | `otel.yaml` | ✅ Fixed | 200ms latency variance |
| 6 | OTel blocking on slow downstream | `otel.yaml` | ✅ Fixed | Billing slowness → response slowness |
| 7 | No client buffer/timeout bounds | `client-traffic-policy.yaml` | ✅ Fixed | RAM exhaustion + hung threads |
| 8 | No connection pool / TCP keepalive | `backendtrafficpolicy.yaml` | ✅ Fixed | TLS reconnect cost per request |
| A | DeepInfra shared API key | `ai-models/values.yaml` | ⏳ Pending | Fake HA — both fail under throttle |
| B | Access log field audit | `envoy-proxy.yaml` | ⏳ Pending Lightbridge input | Per-request serialization overhead |
| C | No per-model timeout tuning | `ai-models/backendtrafficpolicy.yaml` | ⏳ Pending | Slow failure detection |
| D | HTTP port 80 bypasses auth | `gateway.yaml` + `securitypolicy.yaml` | ⏳ Pending | Security + unmetered traffic |
