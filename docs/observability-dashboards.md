# Observability Dashboards — Reference & Instrumentation Guide

> Cluster: `ai-helm` · Observability namespace: `observability`
> All dashboards are provisioned via the Grafana Helm chart in `charts/apps/values.yaml`.

---

## 1. Dashboard Inventory

### 1.1 Kubernetes Folder

These dashboards use the **dotdc modern Kubernetes set** (actively maintained,
current Grafana panel types, drill-down from cluster → namespace → node → pod).

| Dashboard | gnetId | What it shows | When to use |
|-----------|--------|---------------|-------------|
| K8s / Views / Global | 15757 | Cluster-wide CPU, memory, network, storage by namespace | First stop for any "cluster is slow" investigation |
| K8s / Views / Nodes | 15759 | Per-node CPU, memory, disk, network utilisation | Diagnosing node pressure, scheduling failures |
| K8s / Views / Pods | 15760 | Per-pod CPU/memory vs requests/limits, restarts | Identifying OOMKilled pods, resource over-provisioning |
| K8s / Views / Namespaces | 15758 | Resource consumption per namespace over time | Quota planning, cost attribution per team/service |
| K8s / System / API Server | 15761 | API server request rates, latency, error rates | Diagnosing kubectl slowness, controller backlogs |
| K8s / System / CoreDNS | 15762 | DNS query rates, latency, cache hit ratio | Diagnosing service discovery failures |

**Data source:** Mimir (Prometheus-compatible)
**Metrics origin:** Scraped by Alloy via `prometheus.operator.servicemonitors` from
kube-state-metrics and node-exporter (provided by the cluster).

---

### 1.2 Observability Stack Folder

Dashboards for monitoring the monitoring stack itself.

| Dashboard | gnetId | What it shows | When to use |
|-----------|--------|---------------|-------------|
| Mimir / Overview | 17607 | Ingestion rate, query rate, compactor health, S3 write latency | Diagnosing metric gaps, ingestion rejections |
| Alloy Metrics | 21048 | Alloy component throughput, WAL lag, remote write errors | Diagnosing metric collection failures |
| Loki / Operational | 14055 | Loki ingestion errors, memory/CPU vs limits, chunk flush rate | Diagnosing log gaps or Loki pod pressure |
| Loki / Logs Explorer | 13639 | Ad-hoc log search across all namespaces | General log investigation |
| Tempo / Operations | 18030 | Trace ingestion rate, block flush rate, query latency | Diagnosing trace gaps |
| OpenTelemetry + Tempo | 23242 | Service graph, RED metrics derived from traces | Understanding service dependencies and latency |

**Data sources:** Mimir (metrics), Loki (logs), Tempo (traces)

---

### 1.3 Infrastructure Folder

| Dashboard | gnetId | What it shows | When to use |
|-----------|--------|---------------|-------------|
| Traefik | 17931 | Request rate, error rate, latency per service/router | Diagnosing ingress issues, TLS errors |
| CloudNativePG | 20417 | PostgreSQL connections, replication lag, WAL activity, query latency | Diagnosing DB slowness, replication failures |
| Redis | 19157 | Memory usage, hit/miss ratio, connected clients, evictions | Diagnosing rate-limit backend issues |
| cert-manager | 20340 | Certificate expiry countdown, renewal success/failure rate | Proactive TLS certificate management |
| External Secrets | 21640 | Secret sync status, error rate per SecretStore | Diagnosing ESO sync failures |
| Envoy Gateway / Overview | 24460 | Gateway request rate, error rate, XDS update latency | Diagnosing AI gateway routing issues |
| Envoy / Proxy | 24459 | Per-upstream request rate, latency percentiles, active connections | Deep-dive into specific backend performance |

**Data source:** Mimir

---

### 1.4 GitOps Folder

| Dashboard | gnetId | What it shows | When to use |
|-----------|--------|---------------|-------------|
| ArgoCD / Operational | 19993 | App sync status, reconciliation errors, controller queue depth | Diagnosing sync failures, controller overload |
| ArgoCD / Applications | 19974 | Per-application health, sync history, resource counts | Tracking deployment state of individual apps |

**Data source:** Mimir

---

## 2. Currently Unmonitored Components

The following applications are deployed but have **no dashboards and no active
instrumentation** in the current stack. This section describes what to instrument
and how.

---

### 2.1 Lightbridge Backend (API, OPA, MCP, Usage)

**What it is:** The core authorization and billing service. Handles API key
validation, OPA policy evaluation, and usage tracking.

**Why it matters:** Every AI API request passes through Lightbridge. Latency
spikes or error rate increases here directly impact end users.

**Current state:** No metrics, no traces, no dashboards.

**Instrumentation plan:**

1. **Metrics** — The Lightbridge services are Rust/Actix apps. Add a
   `ServiceMonitor` pointing to each service's metrics endpoint (if the app
   exposes `/metrics` via the `metrics` feature of `actix-web-prom` or similar).
   If not yet instrumented, add `prometheus` crate metrics for:
   - Request rate and latency per endpoint (`http_requests_total`, `http_request_duration_seconds`)
   - OPA policy evaluation latency
   - API key validation cache hit/miss ratio
   - Active database connections

2. **Traces** — Configure the Lightbridge services to emit OTLP traces to
   `alloy.observability.svc.cluster.local:4317`. The `otel` section in each
   service's `config.yaml` already has `enabled: false` — flip it to `true`
   and set `otlp_endpoint: "http://alloy.observability.svc.cluster.local:4317"`.

3. **Dashboard** — Once metrics flow, use gnetId `19924` (Rust service metrics)
   or build a custom dashboard tracking:
   - API key validation rate and error rate
   - OPA policy decision latency (p50/p95/p99)
   - Usage DB write latency
   - Active connections per service

---

### 2.2 LibreChat

**What it is:** The AI chat frontend backed by MongoDB.

**Why it matters:** User-facing service. Slow responses or errors here are
immediately visible to end users.

**Current state:** No metrics, no traces, no dashboards.

**Instrumentation plan:**

1. **Metrics** — LibreChat is a Node.js app. Add `prom-client` and expose
   `/metrics`. Key metrics:
   - HTTP request rate and latency per route
   - Active WebSocket connections
   - MongoDB query latency (via `mongoose` instrumentation)
   - Message processing rate

2. **MongoDB** — Deploy `mongodb-exporter` as a sidecar or separate deployment
   pointing at `librechat-db-headless`. Use gnetId `7353` (MongoDB Overview)
   for the dashboard.

3. **Traces** — Add `@opentelemetry/sdk-node` to LibreChat and configure OTLP
   export to Alloy. This enables end-to-end trace correlation from the chat UI
   through to the AI model backend.

---

### 2.3 Converse UI (Frontend)

**What it is:** The React Native / Expo web frontend.

**Current state:** No metrics, no dashboards.

**Instrumentation plan:**

1. **Nginx metrics** — The frontend is served by nginx. Add a `nginx-exporter`
   sidecar and a `ServiceMonitor`. Use gnetId `12708` (NGINX Exporter) for the
   dashboard. Key metrics: request rate, error rate, active connections.

2. **Real User Monitoring (RUM)** — For frontend performance, consider adding
   Grafana Faro (open source RUM agent) to the Expo web build. This sends
   browser performance metrics and JS errors directly to the Alloy OTLP endpoint.

---

### 2.4 LLM tracing (Tempo)

**What it is:** LLM call traces collected by the core-gateway `-traces`
OpenTelemetryCollector, forwarded via Alloy into Tempo, queried in Grafana
(datasource `tempo`, `http://tempo.observability.svc.cluster.local:3100`).

**Previous state:** Until 2026-Q2 this role was served by Arize Phoenix at
`analytics.ai.camer.digital`. Phoenix has been removed; all LLM observability
now lives in Grafana on top of Tempo.

**Instrumentation plan:**

1. Use Grafana's built-in Tempo "Service Graph" + "Explore" for ad-hoc.
2. Build a saved dashboard tracking:
   - LLM trace ingestion rate (TraceQL `{ resource.service.name=~".+" } | rate()`)
   - Per-model latency p50/p95/p99
   - Error spans by model and backend

---

### 2.5 Coder

**What it is:** Cloud development environment platform.

**Current state:** No dashboards.

**Instrumentation plan:**

1. Coder exposes Prometheus metrics at `/metrics` on port 2112 by default.
   Add a `ServiceMonitor` targeting the `coder` service on port `2112`.

2. Use gnetId `19261` (Coder) for the dashboard. Key metrics:
   - Active workspaces
   - Build success/failure rate
   - Agent connection latency
   - Resource usage per workspace template

---

### 2.6 Envoy AI Gateway (AIEG)

**What it is:** The AI-specific gateway layer that routes requests to AI model
backends, handles token counting, and enforces rate limits.

**Current state:** Envoy Gateway dashboards are provisioned (24460, 24459) but
the AI Gateway extension (`aieg`) has its own metrics that are not yet captured.

**Instrumentation plan:**

1. Add a `ServiceMonitor` for the `ai-gateway-controller` service in
   `envoy-ai-gateway-system`.

2. Key metrics to track:
   - Token usage per model backend
   - Request routing decisions (which backend was selected)
   - Rate limit enforcement events
   - Backend health check failures

---

### 2.7 Authorino

**What it is:** The authentication/authorization proxy for the API gateway.

**Current state:** No dashboards.

**Instrumentation plan:**

1. Authorino exposes Prometheus metrics. Add a `ServiceMonitor` for the
   `authorino` service in `authorino-system`.

2. Key metrics:
   - Auth evaluation rate and latency per `AuthConfig`
   - Cache hit/miss ratio
   - External metadata fetch latency (the Lightbridge OPA calls)
   - Denial rate per policy

---

### 2.8 OpenCode K8s Agent

**What it is:** The AI-powered cluster health monitor CronJob.

**Current state:** Runs as a CronJob — no persistent metrics.

**Instrumentation plan:**

1. Push job completion/failure metrics to Mimir via the Alloy `pushgateway`
   pattern, or use a `ServiceMonitor` on a metrics endpoint if the agent
   exposes one.

2. Track:
   - Job run duration
   - Success/failure rate
   - Notification delivery success (via Apprise)

---

## 3. Instrumentation Priorities

| Priority | Component | Effort | Impact |
|----------|-----------|--------|--------|
| 🔴 High | Lightbridge (API + OPA) | Medium | Every API request passes through here |
| 🔴 High | Envoy AI Gateway metrics | Low | Token usage and routing visibility |
| 🟡 Medium | LibreChat + MongoDB | Medium | User-facing service health |
| 🟡 Medium | Authorino | Low | Auth latency directly affects API response time |
| 🟡 Medium | Coder | Low | ServiceMonitor already supported upstream |
| 🟢 Low | Converse UI (nginx) | Low | Frontend availability signal |
| 🟢 Low | OpenCode Agent | Low | Operational nicety, not critical path |

---

## 4. Quick Reference: Adding a New Dashboard

To add a dashboard to Grafana via the Helm chart, add an entry under the
appropriate folder in `charts/apps/values.yaml`:

```yaml
dashboards:
  infrastructure:          # folder name (must match dashboardProviders)
    my-dashboard:          # arbitrary key
      gnetId: 12345        # dashboard ID from grafana.com/grafana/dashboards
      revision: 3          # specific revision (always pin, never use latest)
      datasource: Mimir    # default datasource variable substitution
```

To add a new folder, add a provider entry under `dashboardProviders` and a
matching key under `dashboards`.

**Finding the right revision:** Go to `grafana.com/grafana/dashboards/<gnetId>`,
click "Revisions", and pick the latest stable one. Always pin the revision —
unpinned dashboards can silently change on Grafana pod restart.
