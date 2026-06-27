# Rate-limit quota observability

> How to see **who is consuming the Envoy AI Gateway and how much of their budget**,
> read from the rate-limit service's **live counters in redis-ha**.
> Decision record: [ADR-0070](adr/0070-ratelimit-quota-observability.md).
> Dashboard: **AI Gateway → "AI Gateway — rate-limit quota"**.

## Why this exists

The gateway rate-limits every request against per-account budgets
([ADR-0021](adr/0021-burst-budget-billing-and-dual-plane-authconfigs.md) /
[ADR-0035](adr/0035-per-person-monthly-budget-and-free-50.md)): a per-model
`BackendTrafficPolicy` keyed on `x-account-id` enforces burst (req/min,
tokens/min) **and** a monthly micro-USD budget. The Lyft ratelimit service keeps
those counters in **redis-ha** (home-os `charts/home-apps/redis-ha`).

That current-window counter exists **nowhere else**. The cost dashboards
([ADR-0058](adr/0058-precompute-gateway-usage-metrics-to-mimir.md) Mimir,
[ADR-0046](adr/0046-per-user-attribution-otlp-envelope-repair.md)/
[0067](adr/0067-jwt-token-consumption-dashboard.md) Loki) answer "how much did X
spend *historically*". Only Redis answers "how close is X to being throttled
*right now*". This subsystem surfaces that.

## The Redis key shape (verified live)

```
converse-gateway/core-gateway/api-https_httproute/converse/<model>/rule/0/match/0/
  api_ai_camer_digital_..._rule-<N>-match-0_<x-account-id>_rule-<N>-match-1_..._<window>
```

| Part | Meaning |
|---|---|
| `…/converse/<model>/…` | the model (route path) |
| `rule-<N>-match-0_<x-account-id>` | the Distinct `x-account-id` value — a Keycloak `sub` UUID, or a named service caller (`benie-joy`, `koufan-king`). `x-billing-plan`/`x-ai-eg-model` are fixed Exact matches → masked constants, so **plan is the rule index, not a value**. |
| `rule-<N>` | the rule index → the plan. Plans iterate sorted (free, internal, pro, service): **`rule-2` = free monthly budget, `rule-7` = pro** (the only plans with a `monthlyBudgetUsd`; service/internal are uncapped). |
| trailing `<window>` | the 30-day budget bucket start (Unix epoch, a multiple of **2592000** = Lyft's MONTH unit). Value = micro-USD spent this window. The previous bucket lingers until TTL. |

Burst (per-minute) keys also exist but churn every minute and are not a budget
signal — they're deliberately not scraped.

Inspect live (read-only):

```bash
export KUBECONFIG=/Users/selast/dev/personal/hetzner-k8s/kubeconfig
PW=$(kubectl -n redis-system get secret redis-ha-redis-auth -o jsonpath='{.data.redis-password}' | base64 -d)
kubectl -n redis-system exec redis-ha-redis-0 -- sh -c \
  "redis-cli --tls --cacert /tls/ca.crt -a '$PW' --no-auth-warning -n 0 --scan --pattern '*rule-2-match-0*' | head"
```

## The two read paths (over the SAME keys)

### 1. Mimir leaderboard — the numbers

`observability` App-of-Apps child **`prometheus-redis-exporter`** (upstream
`prometheus-community/prometheus-redis-exporter`, ADR-0020/0056 child wiring in
`charts/observability/values.yaml`; chart values in
`ai-helm-values environments/prod/values/prometheus-redis-exporter.yaml`):

- `--check-keys` (`REDIS_EXPORTER_CHECK_KEYS=db0=*rule-2-match-0*,db0=*rule-7-match-0*`)
  SCANs the budget keys and exports each value as `redis_key_value`.
- The **ServiceMonitor `metricRelabelings`** (Alloy discovers it) rename it to
  **`gateway_ratelimit_spend_micro_usd`** and carve `account_id / model / plan /
  plane / window` out of the key, then **drop the raw key**.
- `window` is **kept as a label** — the lingering previous bucket must be a
  distinct series, else two windows collide on one series at monthly rollover →
  a duplicate-sample scrape error.

The dashboard's Mimir panels (`$window` single-select, newest default; `$plan` /
`$model` / `$account` multi filters) rank spend per account, per model, a sortable
account×model table, and the gauge over time. Value ÷1e6 → USD.

### 2. Redis census — the live "who's active now"

A `redis-datasource` `GrafanaDatasource` (`uid: redis-ratelimit`,
`ai-helm-values environments/prod/values/grafana.yaml`) → the HAProxy
master-router, used by one `tmscan` table for a **zero-scrape-lag** census
(account/model carved from the key by an `extractFields` regex transform).

> **Plugin TLS gotcha.** The `redis-datasource` plugin only dials TLS when
> `jsonData.tlsAuth: true` — it returns early otherwise (verified in
> `pkg/redis-client.go`: `if !TLSAuth { return }`). Despite the name it needs **no
> client cert** (redis-ha is `tls-auth-clients no`). `tlsSkipVerify: false` then
> verifies the server cert against the internal CA passed as
> `secureJsonData.tlsCACert: $__file{/etc/ssl/certs/internal-gateway-ca.pem}` —
> reusing the `self-signed-ca` bundle already mounted for the LLM plugin.

## Connectivity & secrets

Both paths connect to `redis-ha-haproxy.redis-system.svc:6379` (the master-router
the limiter writes to), **TLS-only** (`port 0` / `tls-port 6379`), verifying the
internal `self-signed-ca`. App-scoped deps (`ai-helm-values`):

- Exporter (`environments/{base,prod}/deps/prometheus-redis-exporter/`): a
  `redis-ha-redis-auth` ExternalSecret (`redis-password`), a
  `redis-exporter-redis-ca` cert (CA trust, mirrors the rate-limiter's
  `ratelimit-redis-ca`), and a Cilium policy (egress `redis-system:6379` + DNS,
  ingress `:9121` for Alloy).
- Grafana: a `grafana-redis-ratelimit` ExternalSecret (in `observability-secrets`,
  key `REDIS_RATELIMIT_PASSWORD`) + a Cilium egress to `redis-system:6379` added
  to `grafana-allow`.

The password is the existing `ssegning-aws prod/meta/test-app#redis_password`
(the same one the rate-limiter and redis-ha itself use).

## Scope & caveats

- **Raw consumption only.** No quota-% overlay: budget limits are static Helm
  config (`charts/ai-models` `rateLimitBudgeting.plans` + per-model overrides) and
  a user's plan isn't on the key, so a precise per-user "% of quota" isn't
  derivable here. A future enhancement could overlay the configured budget (plan
  from rule index + per-model overrides).
- **`rule-2 = free`, `rule-7 = pro`** is encoded in BOTH the exporter `check-keys`
  and the metricRelabelings. If a plan gains/loses a `monthlyBudgetUsd` or plan
  ordering changes in `charts/ai-model/templates/backendtrafficpolicy.yaml`, update
  both. Re-verify with a live `--scan` of the rule indices.
- **Forward-only** Mimir history (begins when the exporter deploys); the redis
  census is live.
- **Values-repo-first** ([ADR-0055](adr/0055-oci-charts-and-image-updater-writeback-to-values-repo.md)/0056):
  merge `ai-helm-values` before `ai-helm` or the exporter silently falls back to
  chart defaults (`ignoreMissingValueFiles`).

## Files

| Where | What |
|---|---|
| `charts/observability/values.yaml` | the `prometheus-redis-exporter` child |
| `charts/observability-dashboards/values.yaml` + `files/envoy-ai-gateway/ratelimit-quota.json` | the GrafanaDashboard CR + generated JSON |
| `tools/dashboards/src/dashboards/envoy_ai_gateway/ratelimit_quota.py` | the dashboard generator source |
| `ai-helm-values environments/prod/values/prometheus-redis-exporter.yaml` | exporter chart values (redis addr, TLS CA, check-keys, metricRelabelings) |
| `ai-helm-values environments/prod/values/grafana.yaml` | the `redis-datasource` plugin + `Redis` datasource |
| `ai-helm-values environments/{base,prod}/deps/prometheus-redis-exporter/` | exporter secret + CA cert + Cilium policy |
| `ai-helm-values environments/base/deps/observability-secrets/external-secrets.yaml` | `grafana-redis-ratelimit` ExternalSecret |
| `ai-helm-values environments/prod/deps/grafana/ciliumnetworkpolicy.yaml` | Grafana → redis-system egress |
