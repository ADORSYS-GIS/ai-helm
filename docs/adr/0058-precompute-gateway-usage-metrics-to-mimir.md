# ADR-0058: Precompute AI Gateway usage (cost/tokens/requests) as Mimir metrics, not live Loki log-scans

**Status:** Accepted
**Date:** 2026-06-25
**Deciders:** @stephane-segning
**Builds on:** [ADR-0005](./0005-per-user-observability.md), [ADR-0046](./0046-per-user-attribution-otlp-envelope-repair.md), [ADR-0008](./0008-python-dashboard-generation.md), [ADR-0028](./0028-self-hosted-model-pricing.md)/[ADR-0051]
**Relates to:** the Loki chunk/results cache enablement + the cost-dashboard taming (`ai-helm-values`)

## Context

The AI Gateway cost dashboards (ADR-0008 generators: `cost-by-model`,
`actor-consumption`, `user-tokens-cost`) query **Loki** with `unwrap` over the
Envoy access logs — `gen_ai.usage.custom_total_cost` (µ$) and
`gen_ai.usage.total_tokens`, grouped by the ADR-0046 attribution labels
(`model`, `azp`, `display_name`, `user_id`, `billing_plan`). A "cost per day for
a month" panel is therefore a **30-day log scan**.

On this cluster Loki's chunks live in **Hetzner Object Storage, which
rate-limits reads (`SlowDown`)**. A 30-day `unwrap` query is a burst of thousands
of `GetObject`s; with the boards defaulting to `now-30d` + 5-minute auto-refresh
they hammered the store continuously, tripped `SlowDown`, and **saturated Loki so
badly that every panel — and the pre-existing per-user board — showed "No data"**.

Two mitigations already shipped (in `ai-helm-values`):
1. **Loki chunk + results cache** (memcached) — absorbs repeated reads; recent
   ranges are fast again.
2. **Tamed the boards** — `now-7d` default + auto-refresh off — to stop the
   self-DoS.

But neither makes a month-of-logs scan viable: even a cold 6h/24h log-scan still
times out while the store is throttled, and a daily `[1d]` bar reads a full day
of chunks regardless of the dashboard range. **Interactive multi-day views are
fundamentally incompatible with log-scanning a rate-limited object store.**

## Decision

**Precompute the usage aggregates as Prometheus metrics in Mimir, and point the
dashboards at Mimir instead of Loki.** The dashboards then read cheap
time-series from Mimir's own TSDB — no object-store log reads at any range.

### Why Alloy `stage.metrics`, NOT Loki recording rules

The obvious "recording rules" implementation is the **Loki ruler**: schedule
LogQL recording rules and remote-write the results to Mimir. **Rejected** — the
ruler runs its LogQL queries *against Loki* every evaluation interval, i.e. it
would keep reading chunks from **the exact rate-limited object store we are
trying to stop hammering**. It re-creates the `SlowDown` problem on a timer.

Instead, emit the metrics **in-flight at ingestion** with Alloy's
`loki.process` `stage.metrics`. Alloy already parses every gateway access log in
the `ai_gateway_user_attribution` stage (ADR-0046) and already remote-writes
metrics to Mimir, so this computes the aggregates **with zero object-store
reads**. The generated counters inherit the entry's promoted label set
(`model`/`azp`/`display_name`/`user_id`/`email`/`billing_plan`/`service_name`),
confirmed in Alloy's source (`recordCounter(name, c, labels, v)` →
`ConstLabels: labels`), provided `stage.metrics` runs **after** `stage.labels`.

### Metric schema

Three counters (emitted only on matched gateway lines, inside the existing
`stage.match`):

| Metric (logical name) | Source field | Action | Meaning |
|---|---|---|---|
| `gen_ai_usage_cost_micro_usd` | `gen_ai.usage.custom_total_cost` | `add` | summed per-request cost, **micro-USD** (÷1e6 for USD, per ADR-0028/0051) |
| `gen_ai_usage_tokens` | `gen_ai.usage.total_tokens` | `add` | summed total tokens |
| `gen_ai_requests` | — (`match_all`) | `inc` | request count |

`source` values that are non-numeric (`"-"` for non-LLM / unstamped lines) fail
the float parse and are skipped — i.e. only real usage is counted. Cost/tokens
are extracted into the pipeline's *extracted map* only (NOT promoted as Loki
labels — they're unbounded numerics).

### How they reach Mimir (no extra component, no extra S3 reads)

`stage.metrics` exposes the counters on Alloy's `/metrics`. Alloy already runs
`prometheus.operator.servicemonitors "cluster"` (clustered), which discovers
**Alloy's own ServiceMonitor** (`serviceMonitor.enabled: true`) and scrapes each
pod's `/metrics` exactly once (clustering avoids duplicate samples), through
`global_sanitize` → `prometheus.remote_write` → Mimir. Per-pod scrape labels
keep the 4 DaemonSet pods' series distinct; counter resets on pod roll are
handled by PromQL `increase()`. Default metric prefix applies
(`loki_process_custom_…`) — the exact exposed name is confirmed post-deploy and
the dashboards/keep-rules reference that.

### Dashboard repoint (Part B)

Regenerate the three cost dashboards to query **Mimir** (`MIMIR_UID`) with PromQL
— e.g. cost-per-day-by-model becomes
`sum by (model) (increase(<metric>[1d])) / 1e6`, totals use `increase(...[$__range])`.
Then restore the `now-30d` default (and auto-refresh) — a month of metrics is
trivial for Mimir. The Loki/`unwrap` log path is kept available for ad-hoc raw
log inspection but is no longer the dashboards' data source.

> ⚠️ Recording-at-ingest only captures data **going forward** — the metrics have
> no history before this lands. Pre-cutover months stay in logs (slow). This is
> acceptable: cost tracking is forward-looking.

## Consequences

- Monthly/weekly cost views become instant and stop hammering the object store —
  the actual fix for the "No data" incident.
- New Mimir cardinality: ~(occurring `model × azp × user` combos) × 3 metrics ×
  (4 Alloy pods) — low thousands of active series; negligible for Mimir.
- `email`/`user_id`/`display_name` ride along as metric labels (already Loki
  labels; in-cluster only).
- Two sources of truth for "cost": the live logs (raw, slow) and the Mimir
  counters (aggregated, fast). The counters are derived, so logs remain
  authoritative for disputes.
- Phased rollout: Part A (this — emit + verify in Mimir) is render-/dashboard-
  neutral; Part B (repoint) follows once the metrics are confirmed flowing.

## Phase 3 — gamified app dashboards (captured here, NOT built yet)

A future, broader concept the maintainer wants once the metrics backbone exists.
A multi-panel "scoreboard for our apps" built on the same Mimir metrics (+ Tempo
traces + alerts), using Grafana visualizations we don't yet use:

- **dashboard-list** panel as the **entry-point hub** linking the others.
- **heatmap** of token usage per day (intensity by hour/day).
- **histogram** of per-day token usage (distribution).
- **candlestick** (e.g. daily cost open/high/low/close, or token bursts).
- **flame-graph** for users × tokens × channels (hierarchical share).
- **gauge** + **stat** tiles for headline usage/cost/budget-burn.
- **traces** panel (Tempo) showing data flow LibreChat → Envoy → Authorino → …
- **alert-list** panel surfacing firing/again alerts.
- **text** panels interleaved for explanations (the "gamified" narration) and a
  **news** panel pointing at the AI-governance site
  (<https://adorsys-gis.github.io/ai-governance/>).
- Candidates to add: bar-chart races / top-N leaderboards, geomap (if we ever
  carry region), state-timeline for model availability, status-history for
  gateway health, per-team budget-burn gauges.

Phase 3 is its own effort (likely its own ADR); listed here so the intent isn't
lost. It depends on Part B (metrics-backed dashboards) landing first.
