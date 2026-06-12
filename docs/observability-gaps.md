# Observability gap inventory — every service we run, and what observes it

**Date:** 2026-06-12 (live audit of `home-remote` / hetzner-prod)
**Ticket:** [#354](https://github.com/ADORSYS-GIS/ai-helm/issues/354) (reconnaissance), epic [#341](https://github.com/ADORSYS-GIS/ai-helm/issues/341)
**Companions:** [observability-dashboard-research.md](observability-dashboard-research.md) (#355 — *which dashboards to adopt for the gaps*; this doc is *what exists and what's missing*), [ADR-0045](adr/0045-scrape-first-dashboard-sourcing.md) (sourcing policy), [ADR-0046](adr/0046-per-user-attribution-otlp-envelope-repair.md) (per-user repair)

## How to read this

- **Logs are universal**: every pod's stdout/stderr reaches Loki via the
  Alloy DaemonSet (`namespace`/`pod`/`container`/`service_name`/`level`
  labels). The tables therefore only call out logs when something *beyond*
  pod logs exists (e.g. access logs) or when logs are the *only* signal.
- **Metrics** = series actually queryable in Mimir today (verified against
  the job list — 13 jobs, 9 monitor CRs cluster-wide).
- **Traces**: only the gateway emits traces into Tempo today.
- **Criticality**: `critical` = auth/data-plane/billing path (outage = the
  platform is down or money is wrong); `high` = user-facing or stateful;
  `medium` = supporting; `low` = auxiliary.
- **Priority**: P0 = this sprint / epic-critical, P1 = key service
  unmonitored, P2 = opportunistic. "—" = no action wanted (signal
  adequate for the service's role).

## 1. Gateway & auth plane

| Service (ns) | Crit | Metrics | Dashboard | Gap → action | Prio |
|---|---|---|---|---|---|
| Envoy data plane (`envoy-gateway-system`) | critical | ✅ PodMonitor (`envoy_*`, incl. per-cluster `*_ratelimit_*` counters) | ✅ 24459 + access-log per-user board (ADR-0046, rollout v05) | none | — |
| envoy-gateway controller | high | ✅ PodMonitor | ✅ 24460 | none | — |
| **envoy-ratelimit** | critical (budget enforcement, ADR-0021/0035) | ❌ own service; ✅ Envoy-side `ratelimit_ok/over_limit/error` counters already in Mimir | ❌ | small custom board off existing Envoy counters (no community board exists — verified) | **P1** |
| **Authorino** (`kuadrant-policies-main`, `converse-gateway`) | critical (auth boundary) | ❌ (exposes auth-server + controller metrics, unscraped) | ❌ | add scrape + small custom board (no community board exists — verified) | **P1** |
| **Keycloak** (`keycloak-ha-app`) | critical | ❌ (KC 26 micrometer metrics not enabled/scraped) | ❌ | enable `metrics-enabled=true` on the Keycloak CR + ServiceMonitor (check ns ingress NetworkPolicy for the Alloy scrape) + adopt gnetId 23338 | **P1** |
| Keycloak OTel collector (`keycloak-ha-otel`) | medium | ⚠️ collector self-metrics on :8888, unscraped | ❌ | ⚠️ **finding: its only pipeline is traces → `debug` exporter — Keycloak traces are received and DROPPED.** Rewire exporter → Alloy (`alloy.observability:4317`) → Tempo, or remove the collector | P2 |
| ai-gateway-controller / AIEG extproc + mcpproxy (`envoy-ai-gateway-system`) | critical (every AI request + MCP session) | ❌ (no `gen_ai_*`/`ai_gateway_*` series in Mimir — verified) | ❌ | logs-only today (incl. `component=mcp-proxy`); token visibility comes from access logs (ADR-0046), so residual gap = extproc/mcpproxy internal health. Revisit if AIEG exposes a metrics endpoint | P2 |
| authorino-operator, keycloak-operator | low | ❌ | ❌ | operator pod logs suffice | — |

## 2. Converse application plane (`converse`, `converse-mcp`)

| Service | Crit | Metrics | Dashboard | Gap → action | Prio |
|---|---|---|---|---|---|
| librechat-app | critical (the chat product) | ❌ (no native Prometheus endpoint) | ❌ | no community board; product-level visibility already flows through the gateway per-user board. Optional later: log-derived error/latency board | P2 |
| **librechat-app-db** (MongoDB StatefulSet) | high (stateful) | ❌ | ❌ | deploy `mongodb_exporter` + Percona repo dashboard JSON (grafana.com MongoDB boards are stale — research §4) | **P1** |
| librechat-search (Meilisearch) | medium | ❌ (metrics behind experimental flag) | ❌ | defer; gnetId 21442 identified if ever wanted | P2 |
| lightbridge-main-db (CNPG) | high | ✅ PodMonitor | ✅ 20417 (cluster-level) | none (operator-level metrics live in `cnpg-system`, external — see §6) | — |
| lightbridge-api-main, lightbridge-mcp | medium | ❌ | ❌ | logs + gateway-side visibility suffice for now | P2 |
| converse-ui, models-info, librechat-opencode-wellknown | low (static/nginx serve) | ❌ | ❌ | uptime via kube-state-metrics + gateway; nothing app-specific needed | — |
| MCP servers: brave-search, terraform (mcpo) | medium | ❌ | ❌ | logs only; no MCP rate-limit descriptors by design (ADR-0038) | P2 |
| MCP proxies: context7, refero (Caddy), firecrawl (openresty) | medium | ❌ (Caddy/nginx metrics not enabled) | ❌ | enable Caddy admin metrics if wanted; boards 20802/22870 identified. Known failure modes are log-diagnosable (`MCP_TOKEN` length-0, ADR-0040/0041) | P2 |

## 3. Model serving (HOME GPU cluster — ADR-0022, **not** this cluster)

| Service | Crit | Metrics | Dashboard | Gap → action | Prio |
|---|---|---|---|---|---|
| model-serving-qwen3-5 (llama.cpp, **LIVE**) | high | ⚠️ `llama-server /metrics` exists **on the home cluster** — no path into this Mimir | ❌ | **blocked on a remote-write/federation decision (needs its own ADR)** — no dashboard work until then (ADR-0045 §4). No community llama.cpp board exists → will be custom | P1 (decision) / P2 (build) |
| model-serving-qwen3-4b (vLLM, standby/disabled) | n/a | n/a | ❌ | nothing while disabled; vLLM boards 23991/24756 verified for when it matters | — |

## 4. Observability stack itself (`observability`)

| Service | Crit | Metrics | Dashboard | Gap → action | Prio |
|---|---|---|---|---|---|
| Alloy (DaemonSet — the single ingest path) | critical | ✅ ServiceMonitor | ✅ custom `alloy-collector` | none | — |
| **Loki** | high | ❌ (chart `monitoring.serviceMonitor` not enabled) | ⚠️ 14055 imported, **dead** | enable the self-scrape → board comes alive with zero dashboard work | **P0** |
| **Mimir** | high | ❌ (`metaMonitoring.serviceMonitor` not enabled) | ⚠️ 17607 imported, **dead** | enable the self-scrape → board comes alive | **P0** |
| Tempo | medium | ✅ ServiceMonitor | ✅ custom `tempo-single-binary` + 23242 | none | — |
| Grafana, grafana-operator | medium | ✅ ServiceMonitors | ❌ dedicated | scraped; no board needed beyond k8s views | — |
| kube-state-metrics, node-exporter | high (feed everything) | ✅ | ✅ (k8s views ×4, via honorLabels fix) | none | — |
| loki-gateway, mimir-nginx | medium | ❌ (nginx) | ❌ | covered indirectly by the stores' own metrics once P0 lands | — |

## 5. Platform & supporting (this repo)

| Service | Crit | Metrics | Dashboard | Gap → action | Prio |
|---|---|---|---|---|---|
| core-gateway-traces-collector (`converse-gateway`) | medium | ❌ (collector self-metrics unscraped) | ❌ | add to a future collectors board if trace loss is ever suspected | P2 |
| mail (`mail-system`) | medium | ❌ | ❌ | logs suffice | P2 |
| apprise-api (`monitoring`) | low (alert egress) | ❌ | ❌ | logs suffice; alert-delivery failures surface in grafana logs | — |
| ARC gh-runners (controller `arc-systems` + 3 scale sets) | medium (CI capacity) | ❌ (controller exposes metrics upstream, unscraped) | ❌ | opportunistic: scrape the gha-rs-controller if runner starvation becomes a question | P2 |
| **knative-serving** (6 deployments) + knative-operator | ❓ | ❌ | ❌ | ⚠️ **finding: ADR-0029 dropped KServe/Knative for model serving, yet knative-serving still runs here.** Confirm whether anything depends on it; if not, decommission (removes 8 unmonitored deployments) rather than monitor it. Boards 18032/14589 only if it stays | P2 (investigate first) |

## 6. Externally-owned (recorded for completeness — actions are cross-repo)

| Service | Owner | State here | Action (elsewhere) |
|---|---|---|---|
| redis-ha (`redis-system`) | home-os | board 19157 imported, **dead** | add redis-exporter in home-os `charts/home-apps/redis-ha` |
| Traefik (`traefik`) | external install | board 17347 imported, **dead** | enable metrics + ServiceMonitor |
| cert-manager (kube-system) | home-os `charts/cert` | board 20340 imported, **dead** | enable ServiceMonitor in home-os |
| external-secrets (`external-secrets`) | external install | board 21640 imported, **dead** | enable metrics + ServiceMonitor |
| CNPG operator + barman plugin (`cnpg-system`) | external install | cluster-level DB metrics ✅; operator metrics ❌ | optional operator scrape |
| Cilium (CNI) | hetzner-k8s | no scrape/board here | official boards 16611/16612/16613 once hetzner-k8s scrapes it |
| opentelemetry-operator, hcloud-csi, metrics-server, CoreDNS | external / k3s | CoreDNS ✅ (board live); rest logs-only | — |

## 7. Priority ranking (rollup)

- **P0** — Mimir self-scrape, Loki self-scrape (each revives an
  already-imported board; zero dashboard work). *The per-user usage
  dashboard was the third P0 and is fixed — see §8.*
- **P1** — Keycloak (metrics + ServiceMonitor + gnetId 23338);
  envoy-ratelimit custom board (counters already in Mimir); Authorino
  (scrape + custom board); MongoDB (`mongodb_exporter` + Percona board);
  model-serving remote-write **decision** (ADR needed before any build).
- **P2** — everything else marked P2 above, plus the two findings:
  Keycloak traces dropped at the `debug` exporter; knative-serving
  decommission-or-document.
- **Cross-repo** — §6 items (home-os / hetzner-k8s / external installs).

## 8. Special focus: the user/usage dashboard (#357)

State at audit: **dead since rollout** — the epic's source-of-truth link
(`envoy-ai-gateway-per-user`) showed no data. Root cause: Envoy's OTel
access-log sink emits fields as OTLP *attributes*; Alloy stored
`{"attributes":{...}}` and the ADR-0005 label promotion never fired. The
underlying data was intact (21 distinct users with real token totals
re-queried via the nested form).

**Fixed** via [ADR-0046](adr/0046-per-user-attribution-otlp-envelope-repair.md)
(Alloy envelope flatten + `user_id`/`azp`/`model` labels +
`service_name=envoy-ai-gateway` anchor), merged in
[#383](https://github.com/ADORSYS-GIS/ai-helm/pull/383), rolling out with
tag `release-2026.06.12-v05`. Post-rollout validation:
[per-user-observability.md](per-user-observability.md) § "Verifying it
works".

## 9. Method (repeatable)

```bash
# Workload inventory (every service in §1–§6)
kubectl get deploy,sts,ds -A
kubectl get ns

# What is actually scraped
kubectl get servicemonitors,podmonitors -A
kubectl port-forward -n observability svc/mimir-nginx 8081:80 &
curl -s 'http://localhost:8081/prometheus/api/v1/label/job/values' -H 'X-Scope-OrgID: anonymous'

# Logs / streams
kubectl port-forward -n observability svc/loki-gateway 3100:80 &
curl -s 'http://localhost:3100/loki/api/v1/label/service_name/values?...'

# Traces plumbing
kubectl get opentelemetrycollectors -A
kubectl get opentelemetrycollector -n keycloak -o jsonpath='{.items[0].spec.config}'
```

Dashboard-adoption evaluation (criteria, verified gnetIds, alternatives)
lives in [observability-dashboard-research.md](observability-dashboard-research.md).
