# Observability datasource audit & fixes — 2026-06-07

Point-in-time investigation triggered by three Grafana Explore symptoms on the
Hetzner `home-remote` cluster:

- **Loki** shows only "specific useless logs"
- **Mimir** looks empty
- **Tempo** "fails at being reached"

…plus three "why is it shaped like this?" questions about the LGTM topology.
Everything below was verified live (`KUBECONFIG=…/hetzner-k8s/kubeconfig kubectl
-n observability …`) on 2026-06-07. The durable lessons are folded into
`docs/observability-stack.md`, `CLAUDE.md`, and user memory; this file is the
dated record of *what was wrong and why*.

---

## TL;DR — what was broken and the fix

| Symptom | Root cause | Fix | Where |
|---|---|---|---|
| **Tempo unreachable** | Datasource URL points at `:3100`; Tempo's HTTP API listens on **`:3200`** (`tempo-prom-metrics`). No `:3100` listener exists. | Datasource URL → `:3200` | chart (done) |
| **Loki useless logs** | Alloy's `stage.regex` parsed the **log line**, not the filename. Any line that mentions a `/var/log/pods/<ns>_<pod>_…/<container>/` path (Loki's own logs do, constantly) overwrote the stream's `namespace`/`pod`/`container` labels → every stream mislabeled. Logs *were* ingested, just unfilterable. Plus `loki-canary` spammed synthetic streams. | Labels from **Kubernetes service discovery** (`discovery.kubernetes` + `discovery.relabel`), not line-regex; disable `loki-canary`. | chart (done) |
| **Mimir empty** | The distributor's ingester ring has **zero** instances (`DoBatch: InstancesCount <= 0`), so every remote-write 500s. The ring is wedged: the Cilium default-deny-egress baseline blocked memberlist gossip when the pods first started (before the `allow-same-namespace` policy existed), and the pods never re-formed the ring. | One-time **restart of the Mimir pods** now that `allow-same-namespace` is in place. (Durable fix already deployed.) | **operational — gated** |

The Tempo + Loki fixes are chart changes in `charts/observability/values.yaml`.
The Mimir fix is a one-time cluster restart (no chart change) — see *Next steps*.

---

## Architecture answers (the "why" questions)

### Why 3 pods for Loki?

`deploymentMode: SingleBinary` runs Loki itself as **one** pod. The other two are
chart sidecars, not Loki replicas:

| Pod | What it is | Load-bearing? |
|---|---|---|
| `loki-0` | The single-binary Loki (all roles in one process, S3-backed). `read`/`write`/`backend` and every microservice component are at `replicas: 0`. | **Yes** |
| `loki-gateway` | nginx reverse proxy; the stable `/loki/api/*` endpoint Alloy writes to and Grafana reads from (chart default `gateway.enabled: true`). | Yes (entry point) |
| `loki-canary` | Synthetic SLA probe — writes a line/second and queries it back to measure ingest/read latency. | **No** — disabled in this fix. |

So it's now **2 pods** (store + gateway). The canary added a third and was the
bulk of the log noise.

### Why a lot of pods for Mimir?

`mimir-distributed` is, by design, **microservices** — each role is its own
workload even at `replicas: 1`. Running today (7 pods):

`distributor`, `ingester`, `querier`, `query-frontend`, `store-gateway`,
`compactor`, `nginx` (gateway).

Already trimmed to the floor for this chart (ADR-0024): `query_scheduler`,
`alertmanager`, `ruler`, `overrides-exporter`, `rollout-operator`, and all
memcached caches are disabled. **There is no monolithic/single-binary mode in
`mimir-distributed`** (unlike Loki) — that's the price of this chart. Fewer pods
would mean running Mimir monolithic (`-target=all`) via a different deployment,
which is a deliberate future decision, not a values tweak.

### Why both Mimir *and* Prometheus?

There is **no Prometheus server**. What looks like "Prometheus" is three
ecosystem pieces, none of which stores or queries metrics:

- `prometheus-operator-crds` — **CRDs only** (ServiceMonitor/PodMonitor/…). No
  operator, no Prometheus. They exist so workloads can declare scrape targets.
- `kube-state-metrics` — exports Kubernetes object state as metrics.
- `prometheus-node-exporter` — exports node hardware metrics.

**Alloy** reads the ServiceMonitor/PodMonitor CRDs, scrapes those exporters (plus
kubelet/cAdvisor/apiserver/CoreDNS), and **remote-writes to Mimir**. **Mimir is
the TSDB** — the Prometheus-compatible, S3-backed, long-term metric store that
*replaces* a Prometheus server. So the stack is "Prometheus ecosystem glue →
Alloy → Mimir," not two competing databases.

### Is Alloy really the only collector (logs + metrics + traces)?

**Yes**, confirmed from its running config. Alloy does exactly three things and
nothing else (no storage, no querying):

- **Metrics** → ServiceMonitor/PodMonitor discovery + kubelet/cAdvisor/apiserver/
  CoreDNS scrapes → `prometheus.remote_write` to Mimir.
- **Logs** → tails this node's `/var/log/pods` → `loki.write` to Loki.
- **Traces** → OTLP receiver (`:4317`/`:4318`) → `otelcol.exporter.otlp` to Tempo.
  The same OTLP receiver also fans logs→Loki and metrics→Mimir for in-cluster
  OpenTelemetry SDKs (e.g. the Envoy AI Gateway access-log path, ADR-0005).

It is correctly scoped as a pure collector. The only blemishes were the log
*labeling* (fixed here) and the noisy usage-report phone-home (now disabled).

---

## Evidence (live, 2026-06-07)

**Tempo** — service exposes `tempo-prom-metrics 3200` and the config has
`server: http_listen_port: 3200`. No `:3100`. The datasource pointed at `:3100`.

**Mimir** — Alloy and the distributor both log, continuously:

```
prometheus.remote_write … url=http://mimir-nginx…/api/v1/push
  err="server returned HTTP status 500 Internal Server Error:
       send data to ingesters: DoBatch: InstancesCount <= 0"
```

Startup memberlist logs (28h ago, before `allow-same-namespace`) show repeated
`fast-joining node failed … i/o timeout` against peers on `:7946`. The
`allow-same-namespace` NetworkPolicy (ingress **and** egress, `podSelector: {}`)
is only ~9h old — added after the pods last started — so the ring never
re-formed. Egress is now permitted; the pods just need to restart.

**Loki** — a flushed stream proved the mislabeling:

```
labels="{… container=\"oauth2-proxy\",
  filename=\"/var/log/pods/observability_loki-0_…/loki/0.log\",
  namespace=\"redis-system\", pod=\"redis-ha-redisinsight-…\" …}"
```

`filename` is `loki-0`'s own log, but `namespace/pod/container` are a *different*
pod's — because the regex matched a `/var/log/pods/…` path that appeared inside
Loki's log *content*.

---

## Next steps

### 1. Roll out the chart fixes (ArgoCD will reconcile)

Tempo datasource `:3200`, Loki discovery-based labeling, `loki-canary` off,
Alloy `enableReporting: false` + `NODE_NAME` env are all in
`charts/observability/values.yaml`. On sync:

- **Grafana** redeploys with the corrected Tempo datasource → Tempo reachable.
- **Alloy** redeploys; **watch this one** — the log pipeline was rewritten. After
  sync, confirm in Grafana Explore (Loki) that streams carry correct
  `namespace`/`pod`/`container`, and that volume looks sane.

### 2. Un-wedge the Mimir ring (one-time, gated — shared cluster)

After egress is confirmed open (it is), restart the ring members so they
re-join memberlist. Ingester first, then distributor:

```bash
export KUBECONFIG=/Users/selast/dev/personal/hetzner-k8s/kubeconfig
kubectl -n observability rollout restart statefulset/mimir-ingester
kubectl -n observability rollout status  statefulset/mimir-ingester
kubectl -n observability rollout restart deploy/mimir-distributor deploy/mimir-querier deploy/mimir-query-frontend
# verify: distributor logs stop emitting "InstancesCount <= 0", and
# Alloy stops logging remote_write 500s. Then Mimir fills in Grafana.
```

This is a workload-cluster write — run it deliberately, not via the agent.

### 3. Follow-ups (not blocking)

- Consider a startup guard so a future cold start can't wedge the ring again
  (e.g. confirm `allow-same-namespace` is part of the durable hetzner-k8s
  baseline — it should be, so a fresh deploy forms the ring on the first try).
- Mimir pod count is inherent to `mimir-distributed`; revisit monolithic Mimir
  only if the footprint becomes a problem.
