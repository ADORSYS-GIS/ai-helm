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

### 3. Startup guard against a future ring wedge — DONE

Investigated and closed. Key finding: **`allow-same-namespace` is already
durable** — it is NOT a manual object as first suspected. It ships from *this*
repo via the `observability-secrets` child Application (sync-wave **-3**, so it
lands before the stores at wave -2):
`environments/base/deps/observability-secrets/allow-same-namespace.yaml`
(ingress **and** egress, `podSelector {}` ↔ same-ns). The
`networkpolicy-*.yaml` baseline in **hetzner-k8s** intentionally does *not* carry
it — putting a second copy there would mean two ArgoCD apps owning the same
NetworkPolicy (sync ping-pong), so that was explicitly **not** done.

So why did the ring still wedge? Ordering, not durability: the
`observability-secrets` app was **enabled ~9h ago, long after** the Mimir pods
(27h old) had started — so when those pods came up there was no
`allow-same-namespace`, they exhausted their join retries, and never re-formed.
On a genuine cold rebuild the wave ordering (-3 before -2) prevents this.

The residual risk is the wave-ordering *race* (wave -3 starting before -2 ≠ the
policy being fully in effect before -2 pods gossip). Closed with
**defense-in-depth in this repo**: Mimir `memberlist.rejoin_interval: 1m`
(+ `max_join_retries: 20`) in the `structuredConfig`. If the policy ever lands a
beat late, components periodically re-resolve the gossip-ring DNS and rejoin, so
a transient startup partition heals on its own within a minute — no manual
restart. (This guard would have auto-fixed the current incident a minute after
the secrets app was enabled.)

### 4. Post-rollout fallout (2026-06-07, same day)

After the first rollout, Mimir came up clean (ring re-formed, pods healthy), but
two more issues surfaced:

- **Loki Application went `Unknown` (ComparisonError).** Disabling `loki-canary`
  alone is invalid: the loki chart's `templates/validate.yaml` does
  `{{- if and (not .Values.lokiCanary.enabled) .Values.test.enabled }}{{- fail
  "Helm test requires the Loki Canary to be enabled" }}`, and `test.enabled`
  defaults to **true**. So the render failed and the app couldn't sync (the
  running `loki-0` was fine — it was a manifest-generation error, not a pod
  crash). Fixed by also setting **`test.enabled: false`** (we run no `helm
  test`). Verified against grafana/loki 7.0.0.

- **Metrics API `MissingEndpoints` — the ADR-0015 collision recurred.** The
  `v1beta1.metrics.k8s.io` APIService is `Available=False` because the running
  `metrics-server` pod is the **k3s-bundled** one (owner `k3s.cattle.io` addon,
  labels `k8s-app=metrics-server`), while the GitOps chart's Service selects
  `app.kubernetes.io/{name,instance}` → **zero endpoints**. The ai-helm
  `aii-metrics-server` app (kubernetes-sigs chart, 2 replicas) is stuck
  `Progressing` because the bundled Deployment squats the `metrics-server` name.
  This is **not an ai-helm bug** — it's hetzner-k8s ADR-0015's documented trap:
  `--disable metrics-server` is in cloud-init but only takes effect on
  (re)provision, so a CP node that restarted/restored without it re-enabled the
  bundled addon. Remediation (one-time, shared cluster — run deliberately):

  ```bash
  export KUBECONFIG=/Users/selast/dev/personal/hetzner-k8s/kubeconfig
  kubectl -n kube-system delete deployment metrics-server
  kubectl -n kube-system delete service    metrics-server
  # then hard-refresh the aii-metrics-server app so the chart re-owns both:
  kubectl --context admin@homeos -n argocd annotate application aii-metrics-server \
    argocd.argoproj.io/refresh=hard --overwrite
  ```

  ⚠️ If the bundled Deployment reappears within seconds, the k3s addon manager is
  still active on the live node → `--disable metrics-server` is NOT in effect
  there. The durable fix is to reprovision / `terraform … -replace` that CP node
  so it starts with the flag (ADR-0015), since `ignore_changes=[user_data]` keeps
  an existing CP on its old start args.

### 6. "Is Grafana showing real data?" — the network-policy gaps (2026-06-07)

With the stores healthy, an end-to-end check (querying Mimir/Loki directly + Alloy's
own `/metrics` + component health) showed:

- **Logs (Loki): ✅ working.** `namespace` label values are now real and correct
  (`converse`, `keycloak`, `envoy-gateway-system`, `kube-system`, …) — the
  discovery-based labeling fix landed.
- **Metrics (Mimir): ✗ near-empty** — only `up{job="apiserver"}` existed;
  `kube_pod_info`, `node_cpu_*`, `container_*`, every ServiceMonitor target = 0.
  Root cause (Alloy component health): `prometheus.operator.servicemonitors` /
  `podmonitors` **unhealthy** — `failed to configure informers: ... Get
  "https://10.43.0.1:443/api": i/o timeout`. **Alloy could not reach the
  Kubernetes API server.** The `default-deny-egress` baseline (allow-dns only)
  blocked it, and Alloy — unlike kube-state-metrics / grafana-operator — had **no
  `CiliumNetworkPolicy` granting API-server egress**. So discovery (nodes,
  ServiceMonitors, PodMonitors) and the kubelet/cAdvisor/apiserver-proxy scrapes
  all returned nothing; only the static apiserver target trickled.
- **Traces (Tempo): ✗ empty** — Alloy's OTLP receiver had `accepted_spans = 0`.
  `core-gateway-traces` (converse-gateway) and `keycloak-ha-otel` *are* pointed at
  `alloy.observability:4317`, but `observability`'s `default-deny-ingress` (+
  same-namespace-only allow) **dropped the cross-namespace OTLP** at Alloy's door.

**Fix — an Alloy deps overlay** (`environments/{base,prod}/deps/alloy/`, wired via
`depsOverlay` on the alloy child, same pattern as kube-state-metrics/grafana-operator):

- **Egress** `CiliumNetworkPolicy`: `toEntities: [kube-apiserver, cluster]` — API
  server for discovery + proxy scrapes, `cluster` for every in-cluster scrape
  target (CoreDNS pod IPs, cross-namespace app ServiceMonitors). + DNS.
- **Ingress**: OTLP `:4317`/`:4318` `fromEntities: [cluster]` so in-cluster
  collectors/SDKs can push traces/logs/metrics.
- Portable base k8s `NetworkPolicy` mirrors it (apiserver CIDRs patched per env +
  all-namespace pod egress + OTLP ingress) for non-Cilium clusters.

After this syncs: Alloy's operator informers go healthy → ServiceMonitor/PodMonitor
+ node discovery populate → kubelet/cAdvisor/ksm/node-exporter/apiserver metrics
flow to Mimir; OTLP spans reach Alloy → Tempo fills (once gateway traffic exists).

**Verify after sync:**
```bash
KUBECONFIG=…/hetzner-k8s/kubeconfig kubectl -n observability port-forward svc/mimir-nginx 3102:80 &
curl -s -H 'X-Scope-OrgID: anonymous' \
  'http://localhost:3102/prometheus/api/v1/query?query=count(up)'   # expect dozens, not 1
# Alloy component health should be all healthy:
POD=$(kubectl -n observability get po -l app.kubernetes.io/name=alloy -o name | head -1)
kubectl -n observability port-forward $POD 12345:12345 &
curl -s localhost:12345/api/v0/web/components | \
  python3 -c 'import sys,json;[print(c["localID"],c["health"]["state"]) for c in json.load(sys.stdin) if c["health"]["state"]!="healthy"]'
```

### 7. Dashboard fixes — "looks good but it's not" (2026-06-07)

With data flowing, the dashboards themselves had six distinct problems:

1. **Kubernetes views show only `observability/kube-state-metrics`.** The ksm
   ServiceMonitor scrape **overwrote the `namespace` label** with ksm's own
   namespace (the real value survived as `exported_namespace`), so every
   `kube_pod_info`/`kube_deployment_*` looked like it lived in `observability`.
   Root cause: `honorLabels` unset on the ksm ServiceMonitor. **Fix:**
   `prometheus.monitor.honorLabels: true` on the kube-state-metrics child —
   mandatory for ksm, which reports labels *about other* objects.

2. **"429 too many outstanding requests"** on dense dashboards (CloudNativePG):
   one dashboard load fires dozens of concurrent range queries; with the
   query-scheduler disabled, Mimir's query-frontend queues them and its default
   cap is only 100/tenant. **Fix:** `frontend.max_outstanding_per_tenant: 2048`
   + `querier.max_concurrent: 32` in the Mimir structuredConfig.

3. **"Datasource ${DS_PROMETHEUS} was not found"** across the Infrastructure
   folder (cert-manager, External Secrets, CNPG, …). These dashboards use the
   **nested** datasource form (`"datasource": {"type":…,"uid":"${DS_PROMETHEUS}"}`),
   but the grafana chart's string-form `datasource: Mimir` only rewrites the old
   single-line `"datasource": "...",` shape — so the `${DS_*}` input tokens
   survived. **Fix:** switch those dashboards to the chart's **list form**
   (`datasource: [{name: DS_PROMETHEUS, value: mimir}]`), which substitutes the
   token directly. Verified: list form → 0 unresolved tokens, 225 `uid:"mimir"`.
   Per-dashboard input names vary (cnpg also has `DS_EXPRESSION`→`__expr__`;
   external-secrets uses `DS_METRICS`). Dashboards backed by a datasource
   *template variable* (k8s-views, mimir-overview, envoy) were already fine and
   were left on the string form.

4. **CloudNativePG dashboard** = #2 (429) + #3 (DS_PROMETHEUS) compounded; both
   fixed above. (Its odd namespace pickers were the same `exported_namespace`
   relabel issue as #1, also fixed.)

5. **GitOps / ArgoCD dashboards empty — removed.** ArgoCD runs on the *separate*
   `admin@homeos` control-plane cluster, not on `home-remote` where the workloads
   (and this Grafana) live, so there are no `argocd_*` metrics here to show. The
   two ArgoCD dashboards + the GitOps file-provider folder were removed. (If
   ArgoCD self-monitoring is ever wanted, it belongs in an observability stack on
   the homeos cluster.)

6. **AI Gateway / per-user activity empty — expected, not a bug.** It is driven
   by gateway access-logs; with no user traffic through `api.ai.camer.digital`
   yet, there is nothing to show. Populates once requests flow.

**Round 2 (2026-06-08) — live verification against the running Grafana** (admin
API: fetch every dashboard, grep for unresolved `${DS_*}`; resolve each gnetId's
real title). Found the datasource-token fix worked for cnpg/cert-manager/redis/
otel-tempo, but three gnetIds were the *wrong dashboard or a partial mapping*:

- **External Secrets (21640)** uses BOTH `DS_METRICS` *and* `DS_PROMETHEUS` — only
  the first was mapped, so `${DS_PROMETHEUS}` survived. Mapped both → mimir.
- **gnetId 18030** ("tempo-operations") @ revision 1 is **not** a Tempo dashboard
  — it resolves to an **InfluxDB k6 board** (the mystery "PHB-CD3 CLOUD" panel).
  **Removed.**
- **gnetId 21048** ("alloy-metrics") returns **404** on grafana.com → never
  imported. **Removed** (the Alloy mixin isn't a single gnetId).
- **Traefik (17931)** is an InfluxDB dashboard (InfluxQL, not PromQL) — cannot
  render against Mimir. **Removed.** TODO: re-add Prometheus-native equivalents
  for Alloy / Tempo-ops / Traefik via GrafanaDashboard CRs when verified.

**AI Gateway / per-user (still empty) — pipeline is WIRED, just no gateway
traffic.** Confirmed end-to-end: `charts/core-gateway` EnvoyProxy `accessLog` →
`alloy.observability:4317` (OTLP), and OTLP logs DO now arrive in Loki
(`exporter="OTLP"` stream present after the ingress fix §6). But the dashboard
queries `{azp=~…} sum by (user_id)` and those labels only exist on **authenticated
requests through the gateway** (`api.ai.camer.digital`, Keycloak JWT → `x-oidc-*`
→ Alloy's `ai_gateway_user_attribution` extracts `user_id`/`azp`). The model was
tested via the **direct Caddy endpoint** (`qwen3-4b--poc.ssegning.com`), which
**bypasses the gateway**, so no per-user logs were produced. Send one authenticated
request through the gateway and the dashboard populates. Not a bug.

**CloudNativePG — "Database Namespace: converse" is CORRECT** (the only CNPG
`Cluster` is `lightbridge` in `converse`, and it IS scraped). The wrong
**"Operator Namespace: envoy-gateway-system"** is because the CNPG **operator**
(external, `cnpg-system`) is not scraped — it ships no ServiceMonitor in our
discovery, so the dashboard's operator-namespace variable matches the
controller-runtime metrics that *do* exist (Envoy Gateway's). Database panels
work; operator panels need a PodMonitor for the cnpg operator in `cnpg-system`
(optional — it's an externally-managed namespace).

### 8. Dashboard replacements for the removed boards (2026-06-08)

- **Traefik** → swapped to gnetId **17347** ("Traefik Official Kubernetes
  Dashboard", Prometheus-native, list-form `DS_PROMETHEUS`→mimir). Real value —
  the Traefik ingress is actively scraped.
- **Alloy & Tempo** → the upstream dashboards don't fit (Alloy ships *jsonnet
  only*; the Tempo mixins are distributed-oriented and assume per-component `job`
  labels our single-binary doesn't have). Importing them would just recreate
  empty boards. Instead, authored **purpose-built dashboards-as-code** as
  GrafanaDashboard CRs in `observability-dashboards` (folder "Collectors &
  Tracing"), targeting the **confirmed-present** series:
  - `alloy-collector` — running components, cluster peers, remote-write
    samples/s (+ failed/retried), Loki entries/s (+ dropped), OTLP accepted
    spans/logs, component-eval p95.
  - `tempo-single-binary` — live traces, spans received/discarded, blocklist
    length, query rate, request p95 by route, block flushes, S3 backend rate.

### 9. CNPG operator namespace — Alloy is already scraping; the operator lacks a PodMonitor

Re #4's "Operator Namespace: envoy-gateway-system": this is **not** an Alloy gap.
Alloy's `prometheus.operator.{servicemonitors,podmonitors}` discovers CRs
**cluster-wide**, proven by the CNPG *database* working — the CNPG `Cluster` CR
auto-creates `podmonitor/lightbridge-main-db` in `converse`, which Alloy scrapes.
The CNPG **operator** (`cnpg-system`, external) exposes `metrics:8080` but ships
**no** PodMonitor, so there's nothing to discover → the dashboard's
operator-namespace variable latches onto the controller-runtime metrics that *do*
exist (Envoy Gateway's). Fix belongs in **home-os** (the cnpg operator's owner):
enable its `podMonitorEnabled`. Not an ai-helm change — adding a PodMonitor into
the externally-managed `cnpg-system` from here would be cross-repo ownership.

### 10. Follow-ups (not blocking)

- Mimir pod count is inherent to `mimir-distributed`; revisit monolithic Mimir
  only if the footprint becomes a problem.
- Traces only appear once requests actually flow through the AI gateway (the
  trace source). An idle gateway → empty Tempo is expected, not a bug.
- Per-user AI-gateway dashboard: send an authenticated request through
  `api.ai.camer.digital` to populate (the direct Caddy endpoint bypasses it).
