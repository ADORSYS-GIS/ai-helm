# Cost observability: AI Gateway usage metrics, dashboards, alerting & the scoreboard

How we see — and bound — what the AI platform costs. This is the operator-facing
"how it works + how to run it" guide for the cost-observability subsystem; the
*why* behind each decision lives in the ADRs it links.

> **ADRs:** [0058](adr/0058-precompute-gateway-usage-metrics-to-mimir.md) (metrics
> backbone) · [0059](adr/0059-grafana-unified-alerting-to-discord.md) (alerting)
> · [0060](adr/0060-gamified-app-scoreboard.md) (scoreboard). Builds on
> [0005](adr/0005-per-user-attribution-via-authorino-headers.md)/[0046](adr/0046-per-user-attribution-otlp-envelope-repair.md)
> (per-user attribution), [0008](adr/0008-python-dashboard-generation.md)
> (dashboards-as-code), [0028](adr/0028-owned-hardware-model-pricing.md)/ADR-0051
> (pricing). Related ops docs: [`per-user-observability.md`](per-user-observability.md),
> [`observability-stack.md`](observability-stack.md),
> [`observability-storage-retention.md`](observability-storage-retention.md).

## 1. The problem this subsystem solves

Every AI-gateway request is attributed (ADR-0005/0046): after Authorino verifies
the Keycloak JWT, Envoy's access log carries the user/model/cost/tokens, Alloy
parses it, and the line lands in Loki with `user_id` / `azp` / `model` /
`display_name` / `billing_plan` labels and a `gen_ai.usage.*` body.

The naive way to report "cost per day this month" is a **30-day Loki `unwrap`
log-scan**. On this cluster Loki's chunks live in **Hetzner Object Storage, which
rate-limits reads (`SlowDown`)**. A month-of-logs scan is a burst of thousands of
`GetObject`s; with boards defaulting to `now-30d` + auto-refresh it hammered the
store continuously, tripped `SlowDown`, and **saturated Loki so every panel —
including the pre-existing per-user board — showed "No data."**

Two truths drive everything below:

- **`retained ≠ queryable`.** "30-day retention" is a *storage* promise, not a
  *query* promise. On a throttled object store the effective interactive window
  is the cache horizon (~12h), not the retention window.
- **Log-scanning a rate-limited store is fundamentally non-interactive.** You
  cannot fix a month-scale dashboard by tuning the query; you have to stop
  reading logs at query time.

## 2. The metrics backbone (ADR-0058)

**Precompute the aggregates as Prometheus metrics in Mimir; point the dashboards
at Mimir, not Loki.** Then a month view is cheap TSDB time-series — no object-store
reads at any range.

### Why Alloy `stage.metrics`, NOT a Loki recording rule

The obvious "recording rules" answer is the **Loki ruler** — but it runs its
LogQL *against Loki* every interval, i.e. it keeps reading the exact rate-limited
store we're trying to stop hammering. **It re-creates the `SlowDown` problem on a
timer.** Instead, emit the metrics **in-flight at ingestion**: Alloy already
parses every gateway access log (the `ai_gateway_user_attribution` stage,
ADR-0046) and already remote-writes to Mimir, so `loki.process` `stage.metrics`
computes the aggregates with **zero object-store reads**.

### The three counters

Emitted only on matched gateway lines, **after** `stage.labels` so they inherit
the promoted label set (`model`/`azp`/`display_name`/`user_id`/`email`/
`billing_plan`/`service_name`). Default metric prefix `loki_process_custom_`:

| Metric | Source field | Action | Meaning |
|---|---|---|---|
| `loki_process_custom_gen_ai_usage_cost_micro_usd` | `gen_ai.usage.custom_total_cost` | `add` | per-request cost, **micro-USD → ÷1e6 for USD** |
| `loki_process_custom_gen_ai_usage_tokens` | `gen_ai.usage.total_tokens` | `add` | total tokens |
| `loki_process_custom_gen_ai_requests` | — (`match_all`) | `inc` | request count |

Non-numeric source values (`"-"` for non-LLM lines) fail the float parse and are
skipped — only real usage counts. They reach Mimir via Alloy's existing
self-ServiceMonitor scrape (clustered → no duplicate samples); counter resets on
pod roll are handled by PromQL `increase()`.

> ⚠️ **Forward-only.** Recording-at-ingest captures data only from when it
> deployed (~2026-06-25). Pre-cutover history stays in logs (slow). Cost tracking
> is forward-looking; this is accepted.

> ⚠️ **`display_name` is the unifying "actor" axis** — a person for humans, the
> **repository** for CI. ⚠️ LibreChat agents/embeddings don't forward the
> end-user, so they fall back to `azp=internal-key-librechat` (see
> [`gateway-auth-ratelimit`](adr/0021-burst-budget-billing-and-dual-plane-authconfigs.md)).

## 3. What made it viable: caches + log-noise drops

Repointing to Mimir is necessary but not sufficient — two enablers shipped in
`ai-helm-values`:

- **Memcached caches, previously OFF** ("not needed at small scale" — wrong on a
  rate-limited store). Now on: Loki `chunksCache` (512) / `resultsCache` (256);
  Mimir `chunks-cache` (256) / `index-cache` (256) / `metadata-cache` (64) /
  `results-cache` (256) — `allocatedMemory` in MB, **~1.6 GB total** (Loki 768 +
  Mimir 832; pod memory is somewhat higher with overhead). In-memory → **no PVC**.
  Mimir's store-gateway reads metric blocks from the same bucket, so these matter
  for the 30d metric queries too (esp. `metadata-cache` cuts S3 LIST).
- **Log-noise drops at Alloy `discovery.relabel "pod_logs"`.** GitHub ARC runners
  were ~48% of ingest and the `observability` namespace ~28% (Loki/Alloy logging
  their *own* SlowDown — a self-amplifying loop). Dropped at discovery (files
  never tailed): `namespace=~"gh-runners.*|arc-systems"` + the noisy
  `observability/(loki|mimir|tempo)-.*`, `converse/librechat-app-db-.*`,
  `redis-system/redis-ha-(haproxy|redisinsight)-.*`. Lossless (CI logs live in
  GitHub's UI; everything stays in `kubectl logs`).

> ⚠️ **The Alloy `configMap.content` (River) is `tpl`'d by the upstream chart** →
> it must contain **zero** `{{ }}` sequences, even in `//` comments, or ArgoCD
> manifest-generation fails at sync time (the app goes `ComparisonError`, running
> pods keep the OLD config — *none of our local checks catch this*). Map a field
> to empty with `stage.replace { expression = "^-$"; replace = "" }`, never
> `stage.template`. Grep the content for `{{` (must be none) before committing.

## 4. The dashboards

All generated from Python (grafana-foundation-sdk, ADR-0008) under
`tools/dashboards/`; JSON ships as `GrafanaDashboard` CRs in
`charts/observability-dashboards` (survives stateless-Grafana rolls, ADR-0023).
Folder **AI Gateway**.

| Dashboard (uid) | Source | What it shows | Data |
|---|---|---|---|
| `envoy-ai-gateway-cost-by-model` | `cost_by_model.py` | cost × model, daily bars + totals/pie | Mimir |
| `envoy-ai-gateway-actor-consumption` | `actor_consumption.py` | one actor's (user **or** repo) consumption per month/day + which models | Mimir |
| `envoy-ai-gateway-user-tokens-cost` | `user_tokens_cost.py` | per-actor table (requests·tokens·cost) + daily breakdowns + leaderboards | Mimir |
| `envoy-ai-gateway-scoreboard` | `scoreboard.py` | the gamified hub (§5) | Mimir + Tempo + alerts |
| `envoy-ai-gateway-per-user` | `per_user.py` | raw per-user activity | **Loki** (unchanged) |

`per_user.py` stays Loki-backed for raw log inspection; the cost boards are
Mimir-backed. Shared PromQL helpers: `envoy_ai_gateway/_shared.py`. Counters →
`increase(metric[window])`; cost via `usd()` (÷1e6).

> ⚠️ **Daily bars use `increase(metric[1d])` pinned to a 1d step.** PromQL
> `increase()` over a window needs **≥2 samples inside it** — a counter sampled
> only at day boundaries yields empty bars. (This bit the backfill; see §7.)

## 5. The scoreboard (ADR-0060)

`envoy-ai-gateway-scoreboard` — the gamified "App Scoreboard," the entry-point
hub, on the **same** Mimir metrics + Tempo traces + ADR-0059 alert state, using
viz the cost boards don't:

- **budget-burn gauge** — `% of an editable $budget`. A **textbox** variable
  (`$budget`, default `DEFAULT_MONTHLY_BUDGET = 3000`; real budget ~$2.5k) drives
  it; PromQL substitutes `$budget` as a literal, so
  `100 × sum(increase(cost[30d]))/1e6 / $budget` is valid. Window fixed at `30d`
  (a monthly budget), independent of the dashboard range. Edit it in the UI to
  retune live. Reads >100% until usage settles (run-rate ~$5k) — that's the point.
  ⚠️ Enter a **positive number** — Grafana textbox variables have no input
  validation, so a blank / `0` / non-numeric `$budget` makes the gauge divide by
  it and render NaN/±Inf with no error. (No code guard is possible on a textbox
  var; this is the documented contract.)
- **stats** (spend / budget remaining / requests / active actors), **bargauge**
  leaderboards (top actors, top models), **histogram** (per-actor spend
  distribution), **pie** (spend share by billing plan), **heatmap** (hourly
  token-intensity per client; `calculate=false` → rows-from-series), **timeseries**
  (daily-spend heartbeat).
- **traces** (Tempo, TraceQL `{}`) — click a trace for the LibreChat → Envoy →
  Authorino → model flow; **alertlist** (firing/pending, ADR-0059);
  **dashlist** hub (tag `ai-gateway`); **news** + **text** (AI governance).

`alertlist` and `traces` have no dedicated SDK builder → built via the base
`dashboard.Panel` with `.type()` + `.options()`.

> ⚠️ **The governance news feed is served via a same-origin Caddy proxy (ADR-0061),
> not fetched directly.** Grafana's news panel fetches its feed **client-side**,
> and GitHub's `.atom` sends no `Access-Control-Allow-Origin` header → a direct
> fetch is CORS-blocked ("Error loading RSS feed"). It is **not** a pod-egress
> issue (the Grafana pod reaches github.com fine). So `charts/governance-feed-proxy`
> (a tiny Caddy) serves the feed at `https://grafana.<domain>/_governance.atom` —
> **same origin** as Grafana → no CORS, reusing Grafana's TLS. The proxy only ever
> serves that one fixed upstream path (`rewrite *`) and its egress is FQDN-pinned
> to github.com (deps overlay), so it's not an open proxy. The news panel's
> `feedUrl` points at that same-origin path.

**Deferred (documented in ADR-0060): candlestick + flame-graph.** They need
intra-day OHLC *tick* data / Pyroscope *profile-frame* data we don't collect;
synthesising them from daily counter aggregates would imply data we don't have.
"The panel exists" ≠ "your data fits its shape." Revisit only if we add
continuous profiling or per-request tick storage.

## 6. Alerting → Discord (ADR-0059)

Grafana unified alerting, provisioned as grafana-operator CRs in
`charts/observability-dashboards/templates/alerting*.yaml` (survives stateless
rolls). Compact values shape `{datasourceUid, expr, op, threshold, …}` →
template expands each into Grafana's A=query / B=reduce(last) / C=threshold model.

- **Contact point** `discord` — modern **`receivers[]`** form (top-level
  type/settings/valuesFrom are deprecated). Webhook from ESO (`ssegning-aws`
  property `grafana_discord_webhook_url` → Secret `grafana-discord-webhook`),
  injected with **`valuesFrom targetPath: url`** (relative to the receiver's
  settings — **not** `settings.url`, which writes `settings.settings.url` and
  never delivers).
- **Rules** (5 groups / 9 rules): gateway no-traffic / 5xx / p95, daily+monthly
  cost guardrails (on the §2 metric), component-down, pod-crashloop,
  node-not-ready / memory.

> ⚠️ Grafana needs **`discord.com` egress** (deps CiliumNetworkPolicy) or every
> notification times out (test contact point → HTTP 408; with it → 200).
> ⚠️ **No-traffic/absence rules need `or vector(0)`** else no-data →
> `noDataState: OK` stays green. ⚠️ **p95 baseline is ~40s** (LLM streaming is
> slow) → threshold **120s**, not 5s, or it fires 24/7. Calibrate against live
> values. ⚠️ `cost-monthly-burn` (currently $6000) is a budget knob — set it to
> the real monthly budget once usage settles.

## 7. The historical backfill (one-off, removed)

To recover history before the §2 metrics existed: a one-off Job (in `hack/`, not
ArgoCD-managed) per-day Loki-queried → cumulative OpenMetrics →
`promtool tsdb create-blocks-from openmetrics` → `mimirtool backfill` (needs Mimir
`limits.compactor_block_upload_enabled: true`). Recovered ~$1.2k (the cost field
only existed ~10 days back). Job + manifests **removed after success**
(recoverable from git history); uploaded blocks persist.

> ⚠️ **`written ≠ queryable`** (the write-path twin of `retained ≠ queryable`):
> uploaded blocks aren't immediately queryable — propagation order is **compactor**
> cleaner folds into `bucket-index.json.gz` → **store-gateway** re-syncs →
> **querier** refreshes. `rollout restart` all three **in that order**, else
> ~15–30 min. ⚠️ Emit cumulative samples **every 6h**, not just at day boundaries,
> or `increase[1d]` windows get <2 points → empty bars (§4).

## 8. Operator runbook

- **Add a dashboard:** create `tools/dashboards/.../<name>.py` (`build()` +
  `OUTPUT_PATH`), register it in `main._DASHBOARD_MODULES`, register the CR in
  `charts/observability-dashboards/values.yaml`, then
  `cd tools/dashboards && uv run dashboards build && uv run dashboards check` and
  commit the regenerated JSON (CI's `dashboards-drift` fails otherwise).
  `schemaVersion` is stamped centrally by `main._emit` from
  `_common.SCHEMA_VERSION` (the SDK has no `.schema_version()` setter).
- **Retune the budget:** edit the `$budget` textbox on the scoreboard (live), and
  set the `cost-monthly-burn` alert threshold in
  `charts/observability-dashboards/values.yaml` to match.
- **Tune alert thresholds:** edit `alerting.ruleGroups[].rules[]` in the same
  values file; re-check after a week of live firing.
- **"No data" on a cost board:** it queries **Mimir** now — check the metric
  exists (`count(loki_process_custom_gen_ai_requests)`), Alloy is scraping
  itself, and the range isn't before the forward-only start. *Don't* re-point it
  at Loki.
- **Backfilled data invisible:** §7 — `rollout restart` compactor →
  store-gateway → querier (in order).
- **Verify live (this is required before calling a dashboard "done"):** after
  merge, the `GrafanaDashboard` CR should appear on **home-remote**
  (`KUBECONFIG=…/hetzner-k8s/kubeconfig kubectl -n observability get grafanadashboard`)
  with an empty `NO MATCHING INSTANCES` column and a fresh `LAST RESYNC` —
  meaning grafana-operator matched it to the Grafana instance and pushed it in.

## 9. Cross-references

- Per-user attribution pipeline (JWT → headers → log labels):
  [`per-user-observability.md`](per-user-observability.md), ADR-0011/0046/0052.
- LGTM topology, sync waves, "why N pods?": [`observability-stack.md`](observability-stack.md),
  [`2026-06-07-observability-datasource-audit.md`](2026-06-07-observability-datasource-audit.md).
- Storage/retention/S3 layout: [`observability-storage-retention.md`](observability-storage-retention.md).
- Dashboards-as-code mechanics: [`python-dashboard-generation.md`](python-dashboard-generation.md).
- The "No data" postmortem that preceded this work:
  [`observability-fix-no-data-dashboards.md`](observability-fix-no-data-dashboards.md).
</content>
