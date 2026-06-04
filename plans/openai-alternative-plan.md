# Plan: turn the OpenAI-compatible endpoint into a concrete OpenAI alternative

> Make `api.ai-v2.camer.digital` a product an engineer would reach for *instead
> of* `api.openai.com` — same SDKs, predictable quota and billing, full usage
> observability, and capacity for **~2000 sustained / ~5000 peak concurrent
> clients**. Grounded in what already shipped on `claude/magical-bohr-390242`
> (see the [architectural-shift](../docs/architectural-shift-main-to-magical-bohr.md)
> and [arc42](../docs/arc42.md)).

**Status:** Proposed plan · **Date:** 2026-06-04 · **Maintainer:** @stephane-segning

---

## 0. What "concrete OpenAI alternative" means here

A developer should be able to:

```python
from openai import OpenAI
client = OpenAI(base_url="https://api.ai-v2.camer.digital/v1", api_key="cd-...")
client.chat.completions.create(model="glm-5", messages=[...], stream=True)
```

…and get: drop-in SDK compatibility, a self-service key, a known model catalog
with pricing, enforced per-plan quota, a monthly invoice they can reconcile, a
usage dashboard, and a status page. Everything below closes the gap between
"works for us internally" and "a thing strangers can rely on."

The platform is already ~70% there: the Envoy AI Gateway, dual-plane AuthConfigs
(ADR-0021), per-model budget policies, the `/v1/models/info` catalog (ADR-0015),
and the LGTM stack exist. This plan finishes the product surface, hardens the
capacity story, and builds the usage observability.

---

## 1. Target capacity & the Envoy sizing model

### 1.1 Requirement restated

- **2000 clients minimum**, **~5000 clients average/peak** — concurrent,
  long-lived (opencode agents, CI fan-out, SSE/token streams).
- "Client" = a laptop/runner holding 1–2 HTTP/2 connections and multiplexing
  many concurrent requests over each.

### 1.2 Why HTTP/2 multiplexing is the whole game

Sockets, not requests, are the scarce resource. With HTTP/2:

| Quantity | Value | Source |
|---|---|---|
| Conns per client | 1–2 | client behaviour |
| Streams (in-flight reqs) per conn | up to 1000 | `clientTrafficPolicy.http2.maxConcurrentStreams` |
| 5000 clients × 2 conns | 10 000 connections | well under `connectionLimit: 100000` |
| Theoretical in-flight ceiling | 10 000 × 1000 = 10M streams | bounded by backend + budget limits, not Envoy |

So 5000 clients is **~10k sockets** — comfortable. The real ceiling is CPU for
TLS + ext_authz + proxying, which is why the data plane autoscales.

### 1.3 Data-plane sizing (already configured, validate + tune)

Current (`charts/core-gateway/values.yaml`):

```yaml
envoyProxy:
  hpa: { minReplicas: 3, maxReplicas: 20, cpuUtilization: 60 }
  resources: { requests: {cpu: "1", memory: 512Mi}, limits: {cpu: "4", memory: 2Gi} }
  topologySpread: { enabled: true, maxSkew: 1 }
  shutdown: { drainTimeout: 60s, minDrainDuration: 15s }
clientTrafficPolicy:
  http2: { maxConcurrentStreams: 1000, initialStreamWindowSize: 1Mi, initialConnectionWindowSize: 16Mi }
  connection: { connectionLimit: 100000, closeDelay: 1s }
  bufferLimit: 500Mi
  tcpKeepalive: { probes: 3, idleTime: 5m, interval: 30s }
backendTrafficPolicy:
  loadBalancer: { type: LeastRequest }
  circuitBreaker: { maxConnections: 50000, maxPendingRequests: 50000, maxParallelRequests: 50000 }
  outlierDetection: { consecutive5XxErrors: 5, baseEjectionTime: 30s, maxEjectionPercent: 50 }
  compression: [Gzip]
```

**Sizing rule of thumb** (Envoy at ~5–10k req/s per core for proxy+TLS, far less
under ext_authz): budget **~1 vCPU per ~1500 active streaming clients**. For 5000
peak that's ~3–4 fully-loaded replicas at the 4-CPU limit; HPA headroom to 20 is
~5–6× that. **Action items:**

- [ ] **Raise `minReplicas` to 4** so a node drain during peak never drops below
  the 5000-client serving floor (3 replicas × 4 CPU is the bare minimum at peak).
- [ ] **Lower HPA target to 50%** CPU — ext_authz + TLS latency degrades before
  CPU saturation; scaling earlier protects p95.
- [ ] **Add a memory-based HPA metric** (large buffers × many streams can pressure
  memory before CPU) — scale at 70% of the 2Gi limit.
- [ ] **Set `connectionLimit` headroom check**: 100k is fine for 5000×2; document
  the recompute if the fleet 10×'s.
- [ ] **Pin Envoy concurrency** (`--concurrency` = CPU limit) so the worker count
  matches the 4-CPU limit, not the node's core count.

### 1.4 The auth path is the hidden bottleneck

Every request hits Authorino (ext_authz gRPC). Already: `replicas: 2`, JWKS
`ttl: 3600`. **Actions:**

- [ ] **HPA Authorino** (min 2, max 8) — it's per-request and stateless; today
  it's a static 2.
- [ ] **Cache JWT verification results** keyed on the token `jti` for the token
  lifetime so repeated calls from the same session skip re-verification.
- [ ] **Co-locate** Authorino with the Envoy pods (pod topology / same nodes) to
  cut ext_authz RTT.
- [ ] Track `auth_request_duration` as an explicit SLO (target p95 < 10 ms).

### 1.5 Load validation (do this *before* claiming the number)

The artillery suites already exist (`plans/artillery/`). **Actions:**

- [ ] Re-run `artillery-gateway-load.yml` against Hetzner at 2000, then 5000
  virtual clients with realistic streaming bodies (not single-shot).
- [ ] Measure: p50/p95/p99 added gateway latency, Authorino p95, HPA replica
  count at steady 5000, error rate, and per-replica memory under full streams.
- [ ] Compare with/without Gzip and with/without ext_authz to attribute cost.
- [ ] Publish the report under `plans/artillery/reports/` and gate the capacity
  claim on it. **No capacity guarantee ships without this data.**

---

## 2. Grafana: full observability of usage

The attribution pipeline (JWT → `x-oidc-*` → Envoy access log → Alloy → Loki
labels `user_id`/`azp`, ADR-0005) and the metering counters (ADR-0021) are the
substrate. This builds the *product-facing* usage observability on top.

### 2.1 Metrics to emit (Mimir counters, via Alloy from access logs)

| Metric | Labels | Use |
|---|---|---|
| `llm_requests_total` | `user_id, org_id, plan, model, status` | request volume, error rate, RPS |
| `llm_tokens_total` | `user_id, org_id, plan, model, direction{prompt,completion}` | token usage, the billing base |
| `llm_cost_micro_usd_total` | `user_id, org_id, plan, model` | spend, charge-back |
| `llm_request_duration_seconds` (histogram) | `model, plan` | latency SLO, per-model |
| `llm_ttft_seconds` (histogram) | `model` | **time-to-first-token** — the UX metric for streaming |
| `llm_ratelimit_denied_total` | `user_id, org_id, plan, reason{burst,budget}` | quota friction, upsell signal |
| `llm_active_streams` (gauge) | `model` | concurrency, capacity headroom |

> **Cardinality guard** (ADR-0005 budget): `user_id` and `org_id` are bounded
> (registered users/orgs). `model` and `plan` are small. Keep `user_name`,
> `jti`, and request IDs **out of labels** — body-only, queried with `| json`.

### 2.2 Dashboards (generated in `tools/dashboards/`, ADR-0008)

All as Python → `grafana-foundation-sdk` → `GrafanaDashboard` CRs, drift-checked.

1. **Platform overview** — total RPS, active streams, error rate, p95 latency,
   TTFT, replica count, top models, top orgs. The "is it healthy + how loaded"
   screen.
2. **Per-user usage** (extends existing per-user work) — for a `user_id`:
   requests, tokens (prompt/completion), cost, rate-limit denials, model mix,
   request log (from Loki). Self-service: a user sees their own.
3. **Per-org billing** — month-to-date spend vs budget (gauge + burn-down),
   per-model breakdown, projected end-of-month, the 80%-budget alert state,
   per-user split within the org.
4. **Capacity & SLO** — HPA replicas vs target, CPU/mem per replica, Authorino
   latency, connection count vs limit, stream concurrency, circuit-breaker trips,
   outlier ejections. The "do we need to scale" screen.
5. **Model health** — per-model: availability (outlier ejections), upstream
   latency, error rate by provider, TTFT, token throughput. Drives the catalog's
   "degraded" badges.
6. **Quota & abuse** — top rate-limited users, sudden spend spikes, anomalous
   token ratios (prompt-stuffing), new-key first-use. Feeds alerts.

### 2.3 Alerting (Grafana/Alertmanager)

- [ ] Org at **80% / 100%** of monthly budget (ADR-0021) → notify + (at 100%)
  the budget bucket already denies.
- [ ] Error rate > 2% for 5 min (per model) → page.
- [ ] TTFT p95 regression > 2× 7-day baseline → page.
- [ ] HPA at `maxReplicas` for > 10 min → capacity warning (raise max or add
  nodes).
- [ ] Authorino p95 > 25 ms → auth-path warning.
- [ ] Spend anomaly: a user's hourly spend > 5× their 7-day hourly mean.

### 2.4 Traces (Tempo, already wired)

- [ ] Ensure each `/v1/chat/completions` span chains gateway → Authorino →
  upstream, with `model`, `plan`, `tokens`, `cost` as span attributes. Exemplars
  link the latency histogram to a trace from Grafana.

---

## 3. Product surface — what makes it a *concrete* alternative

### 3.1 API compatibility (OpenAI SDK drop-in)

| Endpoint | Status | Action |
|---|---|---|
| `POST /v1/chat/completions` (+ `stream`) | shipped | verify SSE framing matches OpenAI exactly (`data: [DONE]`, chunk shape) |
| `GET /v1/models` | shipped | ensure shape == OpenAI `{object:"list", data:[...]}` |
| `GET /v1/models/info` (OpenRouter shape) | shipped (ADR-0015) | keep pricing/context in sync with backend specs |
| `POST /v1/embeddings` | **gap** | add an embedding backend + route (RAG/search needs it) |
| `POST /v1/completions` (legacy) | optional | add if clients need it |
| `POST /v1/moderations` | optional | add a moderation model route for safety claims |
| `POST /v1/responses` (new OpenAI API) | **gap** | evaluate — agents increasingly target it |
| `GET /v1/usage` (per-key usage) | **gap** | expose from Mimir counters — table-stakes for a paid API |
| Error envelope (`{error:{message,type,code}}`) | verify | normalize gateway/auth errors to OpenAI's shape so SDK retry logic works |
| `Retry-After` on 429 | **gap** | emit on budget/burst denials so SDKs back off correctly |

**Actions:**

- [ ] Add an **embeddings model** (`ai-models` list entry + backend) — highest-
  value gap; unblocks RAG and the self-hosted search story.
- [ ] **Normalize the error envelope** to OpenAI's `{error:{...}}` shape across
  Authorino denials, rate-limit denials, and upstream errors (a small Envoy
  response-mutation / Lua-free `HTTPRouteFilter`), with `Retry-After`.
- [ ] **`/v1/usage`** read endpoint backed by Mimir (or Redis month-to-date) so a
  key holder can query their own consumption programmatically.

### 3.2 Self-service: keys, plans, billing

This is the difference between "internal gateway" and "product."

- [ ] **Self-service key portal.** Keycloak already issues identity; add a small
  portal (or extend LibreChat admin) where a user: creates/revokes API keys (`cd-…`
  prefix), sees usage, sees their plan, sees month-to-date spend. Keys map to a
  Keycloak identity so the existing AuthConfig path validates them unchanged.
- [ ] **Re-enable key revocation enforcement.** `enforce-valid-key` is currently
  commented out (the SA-skip marker is preserved). A real API needs revocation —
  re-enable as a lightweight check (Redis-backed allowlist of active key `jti`s,
  *not* the old OPA dependency that caused the outage).
- [ ] **Land the Keycloak `billing_plan` + `org` mappers** (ADR-0021 external
  dependency). Until then everyone is `free` and org budgets can't bucket — the
  single biggest blocker to real billing.
- [ ] **Plans as a product.** Today: `free`/`pro`/`service`/`internal`. Make
  `free`/`pro` user-selectable; add a `team`/`enterprise` tier with higher burst +
  budget. Tiers already live in `charts/ai-models/values.yaml` `rateLimitBudgeting`.
- [ ] **Invoicing.** Monthly job reads `llm_cost_micro_usd_total` per org → an
  invoice (PDF/CSV) + optional Stripe metered-billing push. Reconciles against the
  Grafana per-org dashboard.

### 3.3 Reliability & trust signals

- [ ] **Status page.** A public `status.ai-v2.camer.digital` driven by the Model
  Health dashboard (per-model up/degraded/down from outlier ejections + error
  rate). Strangers won't adopt without one.
- [ ] **Provider failover / multi-backend per model.** `ai-models-backends`
  already supports multiple backends; route a single logical model to ≥2 providers
  with `LeastRequest` + outlier detection so one provider outage doesn't take a
  model down. (e.g. `glm-5` → DeepInfra + Fireworks.)
- [ ] **Graceful degradation.** On budget exhaustion, return a clean 429 with a
  link to upgrade, not a generic gateway error.
- [ ] **Published rate limits + SLA** in docs, keyed to plan.

### 3.4 Safety & abuse (needed to open to strangers)

- [ ] Optional **moderation** pre-filter route for plans that require it.
- [ ] **Abuse detection** off the Quota & Abuse dashboard (token-stuffing, key
  sharing via geographic/`azp` anomaly).
- [ ] **Per-key IP allowlist** option (Cilium/Envoy) for enterprise tenants.

---

## 4. Roadmap (phased, dependency-ordered)

### Phase 0 — Prove the capacity (1–2 weeks)
- Re-run artillery at 2000 + 5000 on Hetzner; publish report (§1.5).
- `minReplicas: 4`, HPA target 50% + memory metric, Authorino HPA, Envoy
  `--concurrency` pin (§1.3–1.4).
- **Exit:** validated, documented 5000-client capacity with p95/TTFT numbers.

### Phase 1 — Usage observability (1–2 weeks, parallel with 0)
- Emit the §2.1 counters from access logs via Alloy.
- Ship the 6 dashboards (§2.2) and the §2.3 alerts.
- Wire trace attributes + exemplars (§2.4).
- **Exit:** "what did org X spend on model Y this month" answerable in Grafana;
  budget alerts firing.

### Phase 2 — Billing spine (2–3 weeks)
- Land Keycloak `billing_plan` + `org` mappers (unblocks everything).
- Re-enable key revocation (Redis allowlist, not OPA).
- Self-service key + usage portal.
- `/v1/usage` endpoint; monthly invoice job.
- **Exit:** a user can self-serve a key, see usage, and get an invoice.

### Phase 3 — API completeness (2 weeks)
- Embeddings endpoint + backend.
- Error-envelope normalization + `Retry-After`.
- SSE framing conformance test against the OpenAI Python + JS SDKs.
- **Exit:** OpenAI SDK works unmodified for chat + embeddings; SDK retry behaves.

### Phase 4 — Trust & resilience (2 weeks)
- Status page; multi-backend failover per model; published SLA/limits.
- Moderation route; abuse detection.
- **Exit:** an external developer can adopt it with the same confidence as a
  hosted API.

### Phase 5 — Scale-out hardening (ongoing)
- Mimir 6.0 migration (currently deferred — breaking).
- Multi-env (`staging`) overlay to validate before the deploy branch.
- Regional/second-cluster expansion if the fleet outgrows one Hetzner cluster.

---

## 5. Additional proposals (the "propose the rest" part)

Beyond Grafana + Envoy, these turn it from "an endpoint" into "a platform":

1. **Prompt/response caching** at the gateway (semantic or exact-match, Redis-
   backed) — cuts cost and latency, a real differentiator vs raw OpenAI. Bills the
   cache hit at $0 and shows the savings on the org dashboard.
2. **Streaming-aware load shedding** — when HPA is saturated, shed *new* low-plan
   requests with a 429 before degrading in-flight streams; protects paying tiers.
3. **Model aliases & routing policies** — a logical `default-fast` / `default-smart`
   alias that resolves per-plan to a concrete model, so clients don't hardcode
   providers and you can swap backends without client changes.
4. **Per-org dedicated rate-limit pools** for enterprise — isolate a tenant's
   burst so a noisy neighbour can't starve them (separate Redis descriptor space).
5. **Spend guardrails for users** (not just orgs) — a per-user monthly soft cap
   with an in-band warning header (`x-budget-remaining`) so clients can self-throttle.
6. **OpenAI-compatible batch API** (`/v1/batch`) for cheap async bulk — high-margin,
   easy on capacity (off-peak scheduling), and a clear cost-saver for customers.
7. **Audit log** (immutable, per-key) for enterprise compliance — derived from the
   same access-log stream, retained separately in Loki/object storage.
8. **Canary model rollout** — route a % of a model's traffic to a new provider/
   version, compare TTFT/error on the Model Health dashboard before full cutover.
9. **Client SDK + quickstart docs** — a thin published config (`base_url` + key
   minting) and a "5-minute quickstart" page; adoption is a docs problem as much
   as a tech one.
10. **Cost-aware routing** — when two backends serve the same model, prefer the
    cheaper one until its error rate/latency degrades (the budget data already
    exists to drive this).

---

## 6. Open dependencies & risks

| Item | Blocks | Owner |
|---|---|---|
| Keycloak `billing_plan`/`org` mappers | All per-org billing & plan tiers (ADR-0021) | Keycloak realm (`keycloak-baseline`) |
| Validated load test on Hetzner | Capacity guarantee | platform |
| Key-revocation re-enable without OPA | Real API security | security-policies |
| Cilium egress for any new backend/provider | New model availability | `hetzner-k8s` overlay |
| Embeddings backend selection | RAG/search + `/v1/embeddings` | platform |
| Stripe (or billing provider) integration | Invoicing | finance + platform |

---

## 7. Definition of done ("concrete OpenAI alternative")

- [ ] A stranger self-serves an API key and makes a streaming call with the stock
  OpenAI SDK, unmodified.
- [ ] 5000 concurrent clients sustained with a published, load-tested p95/TTFT.
- [ ] Chat + embeddings + `/v1/models(/info)` + `/v1/usage`, OpenAI error shape.
- [ ] Per-plan burst + per-org monthly budget enforced; 429 with `Retry-After`.
- [ ] Grafana shows usage/cost per user, per org, per model, in near-real-time;
  budget alerts fire at 80%/100%.
- [ ] A monthly invoice reconciles to the dashboards.
- [ ] A public status page reflects real model health.
- [ ] At least one model is multi-backend (no single-provider SPOF).
