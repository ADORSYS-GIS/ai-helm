# ADR-0070: Rate-limit quota observability — read the limiter's live counters from Redis

**Status:** Accepted
**Date:** 2026-06-27
**Deciders:** @stephane-segning

## Context

The Envoy AI Gateway rate-limits every request against per-account budgets
(ADR-0021/0035): a per-model `BackendTrafficPolicy` keyed on `x-account-id`
enforces burst (req/min, tokens/min) **and** a monthly micro-USD budget. The Lyft
ratelimit service stores those counters in **redis-ha** (home-os
`charts/home-apps/redis-ha`, consumed via `eg.yaml`), one key per descriptor
tuple. We had no view of this state. The existing cost dashboards (ADR-0058
Mimir metrics, ADR-0046/0064/0067 Loki) answer "how much did X spend *historically*"
— they do **not** hold the limiter's **current-window** counter, which is the only
thing that answers "how close is X to being throttled *right now*."

That state lives **exclusively in Redis**. Inspecting it live (read-only `SCAN`/
`GET` against db0 on the HAProxy master-router) confirmed the key shape:

```
converse-gateway/core-gateway/api-https_httproute/converse/<model>/rule/0/match/0/
  api_ai_camer_digital_..._rule-<N>-match-0_<x-account-id>_rule-<N>-match-1_..._<window>
```

- The descriptor with the actual value is `rule-<N>-match-0_<x-account-id>` —
  the Distinct `x-account-id` (a Keycloak `sub` UUID, or a named service caller
  like `benie-joy`). `x-billing-plan` / `x-ai-eg-model` are fixed Exact matches
  rendered as masked constants, so **the plan is encoded by the rule index**, not
  a descriptor value. The model is in the route path.
- Rule indices are stable (plans iterated sorted: free, internal, pro, service):
  **`rule-2` = free monthly budget, `rule-7` = pro** — the only two plans carrying
  a `monthlyBudgetUsd`. Verified live (211 free counters, 2 pro).
- The trailing `<window>` is the budget bucket start: a Unix epoch that is a
  multiple of **2592000** (Lyft's MONTH unit = 30 days). The key's value =
  micro-USD spent in that window. The previous bucket lingers until its TTL.

The Grafana Redis datasource plugin (`redis-datasource`) can `tmscan` keys but
**cannot list all key values sorted in one panel** — it has no scan+mget. So a
pure-datasource dashboard can show *who* is active live, but not a values
leaderboard. Co-designed with the maintainer: build **both** read paths, **raw
consumption only** (no quota-% overlay — the limit is static config and a user's
plan isn't on the key, so a precise per-user "% of quota" isn't derivable here).

## Decision

Add a **`AI Gateway — rate-limit quota`** dashboard fed by two read paths over the
**same** redis-ha keys, plus the wiring each needs. Chart logic lives in
`ai-helm`; all deployed config (values, datasource, deps) lives in `ai-helm-values`
(ADR-0055/0056), cut over **values-repo-first**.

1. **Mimir leaderboard (the numbers).** A new `observability` App-of-Apps child
   `prometheus-redis-exporter` (upstream `prometheus-community/prometheus-redis-exporter`
   6.26.0, `valuesFromRepo` + `depsOverlay`). It `--check-keys` the budget keys
   (`db0=*rule-2-match-0*,db0=*rule-7-match-0*`) and exports each value; the
   **ServiceMonitor `metricRelabelings`** rename `redis_key_value →
   gateway_ratelimit_spend_micro_usd` and carve `account_id / model / plan / plane
   / window` out of the 200-char key, dropping the raw key. `window` is **kept as
   a label** so the lingering previous bucket is a distinct series — otherwise two
   windows collide on one series at monthly rollover → a duplicate-sample scrape
   error. The dashboard's `$window` var (single-select, newest default) selects
   the current bucket; panels rank spend per account and per model.

2. **Redis census (the live "who's active now").** A `redis-datasource`
   `GrafanaDatasource` (`uid: redis-ratelimit`) → the HAProxy master-router, used
   by one `tmscan` table for a zero-scrape-lag census (account/model carved from
   the key by an `extractFields` regex transform). `tlsAuth: true` is what **enables
   the plugin's TLS dial** (it returns early without it — despite the name no client
   cert is needed; `tls-auth-clients no`), `tlsSkipVerify: false` verifies the
   server cert against the internal CA supplied via `secureJsonData.tlsCACert`
   (reusing the `self-signed-ca` bundle already mounted for the LLM plugin at
   `/etc/ssl/certs/internal-gateway-ca.pem`). Password via `envFromSecrets`.

Both connect to `redis-ha-haproxy.redis-system.svc:6379` (the master-router the
limiter writes to), TLS-only, verifying the internal CA. App-scoped deps
(`ai-helm-values`): the exporter gets a `redis-ha-redis-auth` ExternalSecret, a
`redis-exporter-redis-ca` cert (CA trust, mirrors `ratelimit-redis-ca`), and a
Cilium policy (egress `redis-system:6379` + DNS, ingress `:9121` for Alloy);
Grafana gets a `grafana-redis-ratelimit` ExternalSecret (in `observability-secrets`)
and a Cilium egress to `redis-system:6379` added to `grafana-allow`.

## Consequences

- **New capability.** Live per-account budget consumption is visible for the first
  time — the limiter's own current-window state, complementing the historical cost
  boards. "Who is using the gateway and how much" is answerable at a glance.
- **Forward-only + lag.** The Mimir metric begins when the exporter deploys; the
  redis census is live. Burst (per-minute) counters are deliberately **not** scraped
  (they churn every minute and aren't a budget signal).
- **Coupling to the rule-index → plan mapping.** `rule-2 = free`, `rule-7 = pro` is
  encoded in BOTH the exporter `check-keys` and the metricRelabelings. If a plan
  gains/loses a `monthlyBudgetUsd` or plan ordering changes in
  `charts/ai-model/templates/backendtrafficpolicy.yaml`, these shift — documented at
  both call sites and in `docs/ratelimit-quota-observability.md`.
- **No quota-% (deliberate).** Limits stay in static Helm config; the dashboard
  shows raw spend. A future enhancement could overlay the configured budget (plan
  from rule index + per-model overrides) if "% of quota" is wanted.
- **Cardinality bounded.** account × model × plan × plane × window (current +
  previous bucket) ≈ a few hundred series; the raw key label is dropped.
- **Cross-repo + values-first.** Merge `ai-helm-values` before `ai-helm` or the
  exporter's `ignoreMissingValueFiles` silently falls back to chart defaults
  (wrong redis address/no scan). The `redis_password`,
  `keycloak_grafana_ro_db_password`-style property already exists in
  `ssegning-aws prod/meta/test-app#redis_password` (same one the limiter uses).

## Alternatives considered

- **Redis datasource only (no exporter).** What was first asked for, but the plugin
  can't render a values leaderboard (no scan+mget) — only a live census. The
  maintainer chose to add the Mimir path for the sortable/historical leaderboard.
- **Reuse the existing Mimir/Loki cost data.** Rejected: it's historical spend, not
  the limiter's live current-window counter (the throttling signal).
- **A custom scraper/CronJob pushing clean metrics.** Rejected in favour of the
  off-the-shelf `prometheus-redis-exporter` (no custom image; parsing in
  ServiceMonitor metricRelabelings).
- **Skip-TLS-verify on both paths.** Rejected: the chart (exporter) and the plugin
  both support CA verification cleanly, and the internal CA is already available —
  no reason to weaken it (cf. the keycloak datasource's `sslmode: require`).
