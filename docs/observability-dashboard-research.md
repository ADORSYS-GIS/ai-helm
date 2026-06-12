# Observability dashboard research — gaps, community options, recommendations

**Date:** 2026-06-12
**Tickets:** [#354](https://github.com/ADORSYS-GIS/ai-helm/issues/354) (reconnaissance) + [#355](https://github.com/ADORSYS-GIS/ai-helm/issues/355) (dashboard research), epic [#341](https://github.com/ADORSYS-GIS/ai-helm/issues/341)
**Decision records:** [ADR-0045](adr/0045-scrape-first-dashboard-sourcing.md) (sourcing policy) + [ADR-0046](adr/0046-per-user-attribution-otlp-envelope-repair.md) (per-user attribution repair)
**Companion (flagship fix):** [#357](https://github.com/ADORSYS-GIS/ai-helm/issues/357) — per-user usage dashboard

This report inventories what is actually scraped/ingested on the Hetzner
workload cluster (`home-remote`), audits every dashboard we already ship,
and evaluates open-source dashboards for each gap. All findings below were
verified **live against the cluster on 2026-06-12** (Mimir label API, Loki
label/series/query API, `ServiceMonitor`/`PodMonitor` inventory) and all
gnetIds were verified against the grafana.com API — see §6 for the
verification commands. Nothing in here is assumed from memory; this repo has
been burned by unverified gnetIds before (21048 → 404, 18030 → a k6 board,
17931 → InfluxDB — see the comments in `charts/observability/values.yaml`).

## 1. What the cluster actually collects today

### Metrics (Mimir) — 13 scrape jobs, total

| Source | Job(s) | Carrier |
|---|---|---|
| Kubernetes objects | `kube-state-metrics` | ServiceMonitor (observability) |
| Node hardware | `prometheus-node-exporter` | ServiceMonitor (observability) |
| Container runtime | `cadvisor`, `kubelet` | Alloy built-in scrape |
| API server | `apiserver` | Alloy built-in scrape |
| CoreDNS | `coredns` | Alloy built-in scrape |
| Envoy Gateway control plane | `envoy-gateway-system/core-gateway-envoy-gateway-controller` | PodMonitor |
| Envoy proxy data plane | `envoy-gateway-system/core-gateway-envoy-proxy` | PodMonitor |
| LightBridge CNPG cluster | `converse/lightbridge-main-db` | PodMonitor |
| Alloy, Grafana, grafana-operator, Tempo | own jobs | ServiceMonitors (observability) |

That is the **entire** metrics surface: 9 monitor CRs cluster-wide.
Notably **absent** from Mimir: Loki itself, **Mimir itself**, Keycloak,
Authorino, envoy-ratelimit, LibreChat, MongoDB, Meilisearch, Redis
(redis-system), Traefik, cert-manager, external-secrets, CNPG operator,
knative-serving, the MCP proxies, and everything on the home GPU cluster
(model serving). There are **no `gen_ai_*` / AI-gateway token metrics in
Mimir** — token usage exists only in Loki (access logs).

### Logs (Loki)

- Pod logs from every namespace via the Alloy DaemonSet
  (`discovery.kubernetes`-derived labels: `namespace`, `pod`, `container`,
  `service_name`, `level`).
- **One** OTLP-ingested stream: the Envoy AI Gateway access logs
  (`{exporter="OTLP", service_name="unknown_service"}` — `unknown_service`
  because the OTel sink sets no `service.name` resource). The per-request
  fields (`user_id`, `azp`, `gen_ai.*` tokens, `duration`,
  `response_code`, …) arrive **nested under an `attributes` JSON object**,
  and the `user_id`/`azp` Loki **labels promised by ADR-0005 do not exist**
  — the Alloy promotion stage looks for top-level keys. Root cause analysis
  and repair contract: ADR-0046; fix tracked in #357.

### Traces (Tempo)

Gateway traces via the `core-gateway-traces-collector` → Alloy → Tempo.
Keycloak also runs an OTel collector sidecar (`keycloak-ha-otel-collector`)
— traces only, no metrics pipeline.

## 2. Audit of dashboards we already ship

“Live” = its datasource series exist on this cluster today.

| Dashboard | Source | Status | Why |
|---|---|---|---|
| k8s-views global/nodes/pods/namespaces (15757/15759/15760/15758) | gnetId | **live** | ksm + cadvisor/kubelet scraped, `honorLabels` fixed 2026-06-07 |
| API server (15761), CoreDNS (15762) | gnetId | **live** | Alloy built-in jobs |
| Envoy Gateway overview (24460), Envoy proxy (24459) | gnetId | **live** | PodMonitors exist |
| CNPG (20417) | gnetId | **live** (cluster-level) | `lightbridge-main-db` PodMonitor; CNPG *operator* metrics not scraped (minor) |
| otel-tempo (23242) | gnetId | **live** | tempo job + traces flowing |
| Loki logs explorer (13639) | gnetId | **live** | Loki datasource, queries pod logs |
| alloy-collector, tempo-single-binary | ours (CRs) | **live** | targets verified at creation (2026-06-08) |
| **mimir-overview (17607)** | gnetId | **dead** | Mimir does not scrape itself — no `mimir` job exists |
| **loki-operational (14055)** | gnetId | **dead** | Loki not scraped — no `loki` job exists |
| **traefik (17347)** | gnetId | **dead** | Traefik (external install, `traefik` ns) exposes no scraped metrics here |
| **redis (19157)** | gnetId | **dead** | no redis-exporter; redis-ha is home-os-owned |
| **cert-manager (20340)** | gnetId | **dead** | cert-manager (home-os-owned, kube-system) not scraped |
| **external-secrets (21640)** | gnetId | **dead** | ESO (external install) not scraped |
| **envoy-ai-gateway-per-user** | ours (CR) | **dead** | ADR-0005 label-promotion never fired (OTLP `attributes` nesting) — ADR-0046 / #357 |

Half the imported boards are dead, and in every case the cause is a
**missing data source, not a bad dashboard**. This drives the core
recommendation: *fix scrapes before importing anything new* (§4).

## 3. Evaluation criteria

For each candidate community dashboard (per ticket #355):

1. **Metric coverage** — does it target metrics our deployment actually
   emits (exporter type, metric names verified against the board JSON)?
2. **Currency** — last revision date; avoids deprecated panel types
   (`graph`), Angular panels, old datasource forms.
3. **Community support** — downloads as a proxy, maintainer (official org
   board > personal upload).
4. **Stack compatibility** — Prometheus-native queries (renders against
   Mimir); datasource-input form must be handleable by our import path
   (string-form `datasource:` or list-form `DS_*` substitution — see the
   gotchas in `CLAUDE.md` / `charts/observability/values.yaml`).

## 4. Per-service findings and recommendations

Priorities: **P0** = epic-critical (usage visibility, stack self-health),
**P1** = key platform service unmonitored, **P2** = nice-to-have.

### P0 — fix what exists (no new dashboards needed)

| Service | Finding | Recommendation |
|---|---|---|
| **AI Gateway per-user usage** | No community equivalent exists (the board is bespoke: Loki-label attribution per ADR-0005/0011). Data verified present & accurate in Loki (21 distinct users, real token totals over 24 h) but unreachable by the current queries. | **Repair ours** (generated via grafana-foundation-sdk). Contract fix in ADR-0046, implementation #357. |
| **Mimir self-monitoring** | Board 17607 already imported, dead. mimir-distributed ships its own ServiceMonitor support (`metaMonitoring.serviceMonitor.enabled`). | **Enable the scrape**, keep the board. No new dashboard. |
| **Loki self-monitoring** | Board 14055 already imported, dead. The loki chart ships `monitoring.serviceMonitor.enabled`. | **Enable the scrape**, keep the board. Re-evaluate 14055 (2021-era) only if it renders poorly once data exists. |

### P1 — key services with no observability

| Service | Community options (verified) | Recommendation |
|---|---|---|
| **Keycloak** (auth boundary) | 10441 / 19659 / 17878 / 14607 all require the **aerogear metrics-SPI** we don't run. **23338 “Keycloak Troubleshooting” (2025)** and **14390 rev 7 (2025)** are micrometer-native (`http_server_requests_*`, `jvm_*`, `agroal_*`) — 23338 mirrors the **official** `keycloak/keycloak-grafana-dashboard` repo (capacity-planning + troubleshooting JSONs). | **Adopt 23338** (or the official repo JSONs via a GrafanaDashboard CR). Prereq: enable KC native metrics (`metrics-enabled=true` on the Keycloak CR) + a ServiceMonitor/PodMonitor; check ingress NetworkPolicy on the `keycloak` ns for the Alloy scrape. |
| **envoy-ratelimit** (budget enforcement, ADR-0021) | **Nothing on grafana.com** ("ratelimit" search: zero results). However Envoy *already exports* per-cluster `envoy_cluster_*_ratelimit_ok/over_limit/error` counters into Mimir today. | **Custom (small)** — a few panels on the existing Envoy metrics; optionally scrape the ratelimit service itself later. Good fit for the foundation-sdk pipeline. |
| **Authorino** (auth decisions) | **Nothing on grafana.com.** Authorino exposes its own metrics endpoints (auth-server + controller). | **Custom (small)** after adding a scrape; Kuadrant's repo examples can seed panel queries. |
| **MongoDB** (librechat-app-db) | 2583 (2020) and 12079 (2020) dominate but both predate current `mongodb_exporter` metric naming; no maintained modern board on grafana.com. Percona maintains current JSONs in `percona/grafana-dashboards`. | **Adopt-with-modification**: deploy `mongodb_exporter`, import the Percona JSON via a GrafanaDashboard CR (treat grafana.com IDs as stale). |

### P2 — secondary / opportunistic

| Service | Community options (verified) | Recommendation |
|---|---|---|
| **knative-serving** (KServe path) | 18032 “Revision HTTP Requests (Kserve)”, 14589 “Control Plane Efficiency” | Adopt **only after** confirming knative metrics are wanted on this cluster; needs a scrape first. |
| **MCP proxies (Caddy)** | 13460, 20802, 22870 all current-ish | Defer; requires enabling Caddy's metrics admin endpoint per proxy. Low traffic today. |
| **Meilisearch** (librechat-search) | 21442 (2024) | Defer; metrics behind an experimental Meilisearch flag. |
| **oauth2-proxy** | only 2017-era App-Metrics boards — useless | Custom-if-ever; not worth it now. |
| **vLLM / llama.cpp model serving** | vLLM: **23991 rev 3 (2025)**, 24756 “V2” (2026), 23856 “KServe vLLM”. llama.cpp (`llama-server /metrics`): **no usable community board**. | **Blocked on architecture, not dashboards**: model serving runs on the *home GPU cluster* (ADR-0022), which has no path into this Mimir. Needs a remote-write/federation decision (own ADR) first. Park the verified vLLM IDs for that day; the live llama.cpp model would need a small custom board. |

### Scrape-side fixes owned by OTHER repos (boards already imported here)

| Service | Action | Where |
|---|---|---|
| Redis (19157) | add redis-exporter to redis-ha | **home-os** (`charts/home-apps/redis-ha`) |
| Traefik (17347) | enable metrics + ServiceMonitor | external Traefik install |
| cert-manager (20340) | enable ServiceMonitor | **home-os** (`charts/cert`) |
| external-secrets (21640) | enable metrics + ServiceMonitor | external ESO install |
| Cilium (no board yet; official 16611/16612/16613 exist) | baseline CNI health | **hetzner-k8s** |

These are recorded here for completeness; they are not ai-helm changes.

## 5. Sequencing (the decisions — see ADR-0045 / ADR-0046)

1. **#357 / P0:** repair the per-user usage pipeline + dashboard (ADR-0046).
2. **P0 scrapes:** Mimir + Loki self-monitoring ServiceMonitors → two dead
   boards come alive with zero dashboard work.
3. **P1:** Keycloak metrics + 23338; envoy-ratelimit custom panels (data
   already in Mimir); Authorino scrape + small custom board; MongoDB
   exporter + Percona board.
4. **P2 & cross-repo:** as listed; model-serving observability needs its
   own remote-write ADR before any dashboard work.

## 6. How findings were verified (repeatable)

```bash
# Scrape inventory
kubectl get servicemonitors,podmonitors -A
kubectl port-forward -n observability svc/mimir-nginx 8081:80 &
curl -s 'http://localhost:8081/prometheus/api/v1/label/job/values' -H 'X-Scope-OrgID: anonymous'
curl -s 'http://localhost:8081/prometheus/api/v1/label/__name__/values' -H 'X-Scope-OrgID: anonymous'

# Loki labels / streams / line shape
kubectl port-forward -n observability svc/loki-gateway 3100:80 &
curl -s 'http://localhost:3100/loki/api/v1/labels?start=...&end=...'
curl -sG 'http://localhost:3100/loki/api/v1/query_range' \
  --data-urlencode 'query={service_name="unknown_service"}' --data-urlencode 'limit=3'

# gnetId verification (NEVER import unverified — see the 21048/18030/17931 incidents)
curl -s 'https://grafana.com/api/dashboards/<ID>'                       # exists? name? revision?
curl -sL 'https://grafana.com/api/dashboards/<ID>/revisions/<N>/download' \
  | grep -o '"expr": *"[^"]*"'                                          # metrics it actually queries
curl -s 'https://grafana.com/api/dashboards?orderBy=downloads&direction=desc&pageSize=6&filter=<term>'
```

## Related

- [ADR-0045](adr/0045-scrape-first-dashboard-sourcing.md) — the sourcing policy arising from this research
- [ADR-0046](adr/0046-per-user-attribution-otlp-envelope-repair.md) — the per-user attribution repair arising from §1
- [ADR-0005](adr/0005-per-user-attribution-via-authorino-headers.md) — the per-user attribution design ADR-0046 repairs
- [docs/per-user-observability.md](per-user-observability.md) — pipeline walkthrough
- [docs/2026-06-07-observability-datasource-audit.md](2026-06-07-observability-datasource-audit.md) — prior datasource audit
- [docs/grafana-operator-and-dashboards.md](grafana-operator-and-dashboards.md) — how dashboards ship
