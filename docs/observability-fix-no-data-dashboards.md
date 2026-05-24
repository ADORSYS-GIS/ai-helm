# Observability Fix — "No Data" Dashboards

> Cluster: `ai-helm` · Namespace: `observability`
> Scope: fixing the communication gap between the observed components and the
> LGTM stack, so that everything currently deployed can actually be visualized.
> This is **issue 1** of the two-part observability work. Instrumenting the
> currently-unmonitored services (Lightbridge, LibreChat, etc.) is issue 2 and
> is tracked separately in `observability-dashboards.md`.

---

## 1. Root Cause Summary

The Grafana stack deployed correctly, but almost every dashboard showed `N/A`
or `No data`. There was no single bug — there were four distinct gaps, all on
the **collection** side of the pipeline. The stores (Mimir, Loki, Tempo) and
Grafana were fine; nothing was being fed into them correctly.

| # | Problem | Symptom it caused |
|---|---------|-------------------|
| 1 | **No cluster metric sources deployed.** Alloy only discovered ServiceMonitors. There was no kube-state-metrics, no node-exporter, and no kubelet/cAdvisor scrape anywhere in the repo. | The entire Kubernetes folder (Global/Nodes/Pods/Namespaces) and most of the Infrastructure folder had no `node_*`, `kube_*`, or `container_*` series to draw from — hence all `N/A`. |
| 2 | **Alloy clustering bug.** Alloy runs as a DaemonSet with clustering enabled globally, but `prometheus.operator.servicemonitors` had no `clustering {}` block. Every Alloy pod scraped every target and shipped duplicate samples. | Mimir rejected duplicate/out-of-order samples. The `out_of_order_time_window: 10m` in the Mimir config was a band-aid for exactly this. Even the stack's own dashboards (Mimir Overview, Alloy Metrics) were unreliable. |
| 3 | **Alloy never exposed its OTLP ports.** The Alloy config opened OTLP listeners on 4317/4318, but `alloy.extraPorts` was not set, so the Alloy Service did not expose them. | Nothing could send traces/logs to Alloy at `alloy.observability.svc:4317`. Tempo could never receive traces through Alloy. |
| 4 | **The existing OTel collectors did not forward to the stack.** The two `OpenTelemetryCollector` CRs in `core-gateway` (the traces collector — formerly named `*-phoenix`, since renamed to `*-traces` after the Phoenix removal — and the Lightbridge usage logs collector) exported only to Phoenix / Lightbridge. | Traces and logs flowing through those collectors never reached Tempo or Loki. |

### A note on `metrics-server` vs `kube-state-metrics`

These are **not** the same thing and one cannot replace the other:

- **metrics-server** (already deployed) serves the Kubernetes *Metrics API* —
  it is what powers `kubectl top` and the Horizontal Pod Autoscaler. It does
  **not** expose a Prometheus `/metrics` endpoint and cannot be scraped for
  dashboards.
- **kube-state-metrics** (added by this change) is a separate component that
  exposes the *state* of Kubernetes objects (`kube_pod_status_phase`,
  `kube_deployment_spec_replicas`, `kube_node_status_condition`, …) as
  Prometheus metrics. This is what the Kubernetes and Infrastructure dashboards
  actually query.

You need both, for different reasons.

### Why Loki logs worked but metrics did not

The log pipeline (`local.file_match` → `loki.source.file` → `loki.write`)
worked because each DaemonSet Alloy pod tails **its own node's**
`/var/log/pods` — there is no duplication to reject, and Loki is fed directly.
The metric pipeline depended on ServiceMonitor discovery (gap #2) and on metric
sources that were never deployed (gap #1), so it had almost nothing to send.

### Why Tempo was silent

Partly gap #3/#4 above, and partly **expected**: no service in the cluster is
emitting traces yet. End-to-end application tracing is issue 2 of this work.
After this change the *plumbing* exists — Alloy receives OTLP and forwards to
Tempo, and the core-gateway collectors fan out to Alloy — but Tempo will stay
quiet until services are actually instrumented.

---

## 2. Changes Made

All changes are GitOps — commit, push, and ArgoCD reconciles. No `kubectl apply`.

### 2.1 `charts/apps/values.yaml` — Alloy collector config

- **Added `clustering {}` to `prometheus.operator.servicemonitors`** and to a
  new `prometheus.operator.podmonitors` component. With clustering enabled,
  Alloy pods shard scrape targets between themselves instead of all scraping
  everything — this stops the duplicate-sample rejections.
- **Added PodMonitor discovery** (`prometheus.operator.podmonitors`). Several
  components (e.g. CloudNativePG) ship PodMonitors rather than ServiceMonitors;
  these were previously ignored entirely.
- **Added kubelet + cAdvisor scraping.** New `discovery.kubernetes "nodes"`,
  two `discovery.relabel` blocks, and two `prometheus.scrape` jobs. They scrape
  each node's kubelet through the API server proxy
  (`/api/v1/nodes/<node>/proxy/metrics` and `.../metrics/cadvisor`), so no
  kubelet host-certificate handling is needed. This supplies the
  `container_*` and `kubelet_*` series the Pods/Nodes dashboards need.
  - RBAC: the grafana/alloy chart's default ClusterRole (created by
    `rbac.create: true`) already grants `nodes/proxy`, so no extra RBAC was
    required.
- **Exposed the OTLP ports.** Added `alloy.extraPorts` for `4317` (gRPC) and
  `4318` (HTTP) so the Alloy Service actually routes OTLP traffic to the pods.
- **Extended the OTLP receiver to fan out all three signals.** The
  `otelcol.receiver.otlp` output now routes `traces → Tempo`, `logs → Loki`,
  and `metrics → Mimir` via two new exporters (`otelcol.exporter.loki`,
  `otelcol.exporter.prometheus`). Previously it handled traces only.

### 2.2 `charts/apps/values.yaml` — two new ArgoCD applications

- **`kube-state-metrics`** — `prometheus-community/kube-state-metrics` chart,
  namespace `observability`, sync-wave `-1`, `prometheus.monitor.enabled: true`
  so Alloy discovers its ServiceMonitor automatically.
- **`node-exporter`** — `prometheus-community/prometheus-node-exporter` chart
  (DaemonSet), namespace `observability`, sync-wave `-1`,
  `prometheus.monitor.enabled: true`.

> **Pin check before merging:** the chart versions (`kube-state-metrics 5.25.1`,
> `prometheus-node-exporter 4.39.0`) are conservative known-good pins. Bump them
> to the latest stable revision if you want — just keep them pinned, never
> `latest`.

### 2.3 `charts/core-gateway/templates/otel.yaml` — OTel collectors fan out to Alloy

- **Traces collector** (`*-traces`, formerly `*-phoenix`): added an `otlp/alloy`
  exporter pointing at `alloy.observability.svc.cluster.local:4317` and added it
  to the `traces` pipeline. Traces now go to Alloy → Tempo only (Phoenix has
  since been removed from the stack).
- **Usage collector** (`*-usage`, logs): same `otlp/alloy` exporter added to the
  `logs` pipeline. Logs now go to Lightbridge **and** to Alloy → Loki.

### 2.4 Envoy Gateway metrics — new PodMonitors

The Envoy Gateway and Envoy proxy dashboards were empty because nothing
scraped them. Envoy Gateway already exposes Prometheus metrics by default
(data plane on `:19001/stats/prometheus`, control plane on `:19001/metrics`),
so the only gap was discovery.

- **`charts/core-gateway/templates/podmonitors-observability.yaml`** (new) —
  two `PodMonitor`s in `envoy-gateway-system`: one selecting the managed Envoy
  proxy pods (`app.kubernetes.io/managed-by: envoy-gateway`,
  `app.kubernetes.io/name: envoy`) on `targetPort: 19001` path
  `/stats/prometheus`, and one selecting the controller (`control-plane:
  envoy-gateway`) on `targetPort: 19001` path `/metrics`. Alloy discovers these
  cluster-wide via `prometheus.operator.podmonitors`.
- **`charts/core-gateway/templates/envoy-proxy.yaml`** — added an explicit
  `telemetry.metrics.prometheus: {}` to the `EnvoyProxy` spec. This is the
  default, but stating it makes the scrape contract explicit.

### 2.5 CloudNativePG metrics — new PodMonitors

Each CNPG instance runs a metrics exporter on port `9187` (named `metrics`),
but no PodMonitor existed, so the CNPG dashboard had no data. `.spec.monitoring.
enablePodMonitor` is deprecated, so manual PodMonitors are used instead.

- **`charts/coder-db/values.yaml`** — added a `PodMonitor` for the `coder-cnpg`
  cluster (selector `cnpg.io/cluster: coder-cnpg`, port `metrics`).
- **`charts/apps/values.yaml`** (lightbridge resources list) — added
  `PodMonitor`s for `lightbridge-main-db` and `lightbridge-usage-db` (selector
  `cnpg.io/cluster: <name>`, port `metrics`).

---

## 3. How to Verify

Because changes are GitOps, push first and let ArgoCD sync (or
`argocd app sync apps`). Then work through the checks below.

### 3.1 New collectors are deployed and healthy

```bash
kubectl get pods -n observability
# expect: kube-state-metrics-* Running, node-exporter-* Running (one per node),
#         alloy-* Running (one per node), mimir-*, loki-*, tempo-*, grafana-* Running

kubectl get servicemonitor -n observability
# expect ServiceMonitors for kube-state-metrics and node-exporter to exist
```

### 3.2 Alloy is scraping and remote-writing successfully

```bash
# Alloy's own UI shows component health and target counts
kubectl port-forward -n observability ds/alloy 12345:12345
# open http://localhost:12345 — check prometheus.scrape.kubelet,
# prometheus.scrape.cadvisor, prometheus.operator.servicemonitors are all healthy

# Look for remote_write errors / sample rejections
kubectl logs -n observability -l app.kubernetes.io/name=alloy --tail=100 \
  | grep -Ei "remote_write|err-mimir|out-of-order|duplicate"
# expect: no sustained rejection errors after the clustering fix
```

### 3.3 Mimir is actually receiving series

```bash
kubectl port-forward -n observability svc/mimir-nginx 8080:80

# Should now return a non-trivial list including node_*, kube_*, container_*
curl -s -H "X-Scope-OrgID: anonymous" \
  "http://localhost:8080/prometheus/api/v1/label/__name__/values" \
  | tr ',' '\n' | grep -E "^\"(node_|kube_|container_)" | head

# Sanity query — should return data points
curl -s -H "X-Scope-OrgID: anonymous" \
  "http://localhost:8080/prometheus/api/v1/query?query=up" | jq '.data.result | length'
```

### 3.4 Grafana dashboards

In Grafana → **Connections → Data sources**, hit **Test** on Mimir, Loki, and
Tempo (Alertmanager showing red is a known cosmetic issue, see
`observability-storage-retention.md` §4.2). Then open:

- **Kubernetes / Views / Global** — CPU/memory/network by namespace should populate.
- **Kubernetes / Views / Pods** — per-pod CPU/memory should populate (cAdvisor).
- **Observability Stack / Mimir Overview** and **Alloy Metrics** — should populate.

### 3.5 OTLP path into Alloy

```bash
# Alloy Service must now expose 4317/4318
kubectl get svc alloy -n observability -o jsonpath='{.spec.ports[*].port}{"\n"}'
# expect to see 4317 and 4318 listed

# After the core-gateway collectors restart, confirm they can reach Alloy
kubectl logs -n <core-gateway-ns> -l app.kubernetes.io/component=opentelemetry-collector --tail=50 \
  | grep -Ei "alloy|export"
# expect: no connection-refused errors to alloy.observability.svc:4317
```

---

## 4. What This Does NOT Fix

These are deliberately out of scope for issue 1 and belong to issue 2
(service instrumentation) or are pre-existing notes in the other docs:

- **Tempo will still be mostly empty** until application services emit traces.
  The plumbing is now in place; the services are not instrumented yet.
- **Infrastructure dashboards that need a dedicated exporter** (Redis needs
  `redis-exporter`, etc.) will stay empty until that exporter is deployed.
  kube-state-metrics + node-exporter cover the Kubernetes-level dashboards, not
  every third-party app.
- **The stale `converse-*` bucket names** mentioned in `observability-stack.md`
  vs. the single `monitoring` bucket actually used in `values.yaml` — a
  documentation inconsistency worth cleaning up, but not a functional bug.
- **Live confirmation of Mimir/Loki/Tempo S3 health** — if dashboards are still
  empty after this change, the next suspect is backend pods crashlooping on S3
  credentials or a missing `monitoring` bucket. Check
  `kubectl logs -n observability -l app.kubernetes.io/name=mimir` for S3 errors.
