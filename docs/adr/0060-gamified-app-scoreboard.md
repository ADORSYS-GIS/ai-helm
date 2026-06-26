# ADR-0060: Gamified "App Scoreboard" dashboard (Phase 3 of cost observability)

**Status:** Accepted
**Date:** 2026-06-26
**Deciders:** @stephane-segning
**Builds on:** [ADR-0058](./0058-precompute-gateway-usage-metrics-to-mimir.md) (the Mimir metrics backbone), [ADR-0059](./0059-grafana-unified-alerting-to-discord.md) (unified alerting), [ADR-0008](./0008-python-dashboard-generation.md) (dashboards-as-code), [ADR-0046](./0046-per-user-attribution-otlp-envelope-repair.md) (attribution labels), [ADR-0023](./0023-stateless-grafana.md) (stateless Grafana → operator CRs)
**Relates to:** [ADR-0028](./0028-self-hosted-model-pricing.md)/ADR-0051 (cost is µ$ ÷1e6)

> ⚠️ **Correction (2026-06-26) — see [ADR-0061](./0061-same-origin-proxy-for-grafana-news-feed.md).** The
> "news panel reads the governance repo's GitHub Atom feed … needs `github.com`
> egress" claim below is **wrong about the mechanism**: Grafana's news panel
> fetches its feed **client-side**, and GitHub's `.atom` sends no
> `Access-Control-Allow-Origin` header, so a direct browser fetch is CORS-blocked
> — it was never a server-side fetch, so the `github.com` pod-egress was both
> unnecessary and ineffective (and has been removed from Grafana's policy). The
> feed is now served **same-origin** under the Grafana host by a small Caddy
> proxy (`charts/governance-feed-proxy`, ADR-0061), so the panel loads with no
> CORS. The *decision* (a governance panel on the scoreboard) stands; only the
> delivery mechanism changed. The original body is left intact as the record.

## Context

ADR-0058 built the metrics backbone (Alloy `stage.metrics` →
`loki_process_custom_gen_ai_{usage_cost_micro_usd,usage_tokens,requests}` in
Mimir) and three cost dashboards (`cost-by-model`, `actor-consumption`,
`user-tokens-cost`). Its closing section captured a **Phase 3** the maintainer
wanted once the backbone existed: a single multi-panel *"scoreboard for our
apps"* — a gamified, at-a-glance view of who uses the platform, what it costs,
and how close we are to budget — built on the **same** Mimir metrics plus Tempo
traces and the ADR-0059 unified alerting, using Grafana visualizations the cost
dashboards don't (gauge, heatmap, histogram, alert-list, traces, news, text, a
dashboard-list hub).

Phase 3 was deferred until Part B (metrics-backed dashboards) landed. It has, so
this ADR builds the scoreboard.

## Decision

Add one generated dashboard, **`AI Gateway — App Scoreboard`** (uid
`envoy-ai-gateway-scoreboard`, source
`tools/dashboards/envoy_ai_gateway/scoreboard.py`, ADR-0008 generator), shipped
as a `GrafanaDashboard` CR via `charts/observability-dashboards` (so it survives
stateless-Grafana rolls like every other dashboard, ADR-0023). Panels, all on
existing data sources:

| Panel | Viz | Source | Reads |
|---|---|---|---|
| Monthly budget burn | **gauge** (% of `$budget`, thresholds 70/90) | Mimir | `cost[30d] ÷1e6 ÷ $budget × 100` |
| Spend / Budget remaining / Requests / Active actors | **stat** | Mimir | range + 30d aggregates |
| Top actors / Top models by spend | **bargauge** (`topk`) | Mimir | per-`display_name` / per-`model` |
| Per-actor spend distribution | **histogram** | Mimir | instant per-actor totals |
| Spend share by billing plan | **piechart** | Mimir | per-`billing_plan` |
| Token-usage intensity by client | **heatmap** | Mimir | hourly tokens per `azp` |
| Daily spend heartbeat | **timeseries bars** | Mimir | `cost[1d]` |
| Recent request traces | **traces** | Tempo | TraceQL `{}`, click → span flow |
| Firing & pending alerts | **alertlist** | Grafana unified alerting | ADR-0059 rules |
| AI Gateway dashboards | **dashlist** | — | tag `ai-gateway` (the hub) |
| AI governance — latest | **news** | RSS | governance repo commits Atom feed |
| Play fair | **text** (markdown) | — | governance narration + link |

### The budget is an editable dashboard variable

A `$budget` **textbox** variable (default `DEFAULT_MONTHLY_BUDGET = 3000`, real
AI-inference budget ~$2.5k rounded up for headroom) lets the "% of budget"
framing be tuned in the UI without regenerating. PromQL substitutes `$budget` as
a literal number, so the gauge expression
`100 × (sum(increase(cost[30d]))/1e6) / $budget` is valid. The window is a fixed
`[30d]` (a monthly budget), independent of the dashboard's time range.

### candlestick + flame-graph are deferred (data-shape, not effort)

ADR-0058's Phase-3 list named **candlestick** and **flame-graph**. Both are
deliberately **not built**: candlestick needs intra-day OHLC *tick* data and
flame-graph needs **Pyroscope-format profile frames** (level/value/self
hierarchy). We only have **daily counter aggregates** in Mimir — synthesising
OHLC from a single daily value, or a treemap-as-flamegraph, would be a fake
visualization that implies data we don't collect. If we ever add continuous
profiling (Pyroscope) or per-request tick storage, revisit with a new ADR. The
hierarchical "users × models × channels" share that flame-graph would have shown
is already served by the leaderboards + plan-share pie + the per-actor table on
the sibling `user-tokens-cost` board.

### The news panel reads the governance repo's GitHub Atom feed

The intent was a "news panel pointing at the AI-governance site". The MkDocs
site (`adorsys-gis.github.io/ai-governance`) exposes **no RSS/Atom feed**, so a
news panel aimed at it renders empty. Instead the panel reads
`github.com/ADORSYS-GIS/ai-governance/commits.atom` — real "governance
doctrine updates" that actually render — and a companion **text** panel carries
the governance narration + a direct link to the site. Grafana fetches the feed
**server-side**, so the Grafana pod needs **`github.com` egress**; added to the
prod deps `CiliumNetworkPolicy` in `ai-helm-values` (same pattern as the
ADR-0059 `discord.com` allow). ⚠️ **Values-repo-first:** that egress allow must
be on `ai-helm-values` `main` before this lands, or the news panel stays empty
under the deny baseline.

## Consequences

- One new dashboard, no new components, no new object-store reads — it rides the
  ADR-0058 metrics, the ADR-0059 alert state, and the existing Alloy→Tempo trace
  pipeline. New Mimir/Tempo load is negligible.
- Forward-only history (ADR-0058) applies: the gauge/leaderboards fill in from
  when the metrics began; older months stay in logs.
- The traces panel is empty if no traces are flowing (depends on Alloy OTLP →
  Tempo, observability audit §6); non-fatal.
- The dashboard-list hub ties the four AI-gateway boards together as the
  entry-point, so the scoreboard is the natural "front page".
- Future candidates (bar-chart races, geomap, state-timeline for model
  availability, per-team budget gauges) can be added to this board incrementally
  without a new ADR — only candlestick/flame-graph need the data-collection
  decision above.
