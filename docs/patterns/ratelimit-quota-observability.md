# Rate-limit quota observability

> How to see **who is consuming the Envoy AI Gateway and how much of their budget**,
> read from the rate-limit service's **live counters in redis-ha**.
> Decision records: [ADR-0070](../adr/0070-ratelimit-quota-observability.md) (this
> subsystem), [ADR-0084](../adr/0084-ratelimit-plan-order-is-append-only.md) (plan
> index → plan name), [ADR-0111](../adr/0111-calendar-aligned-billing-period.md)
> (the `billing_period` label below).
> Dashboard: **AI Gateway → "AI Gateway — rate-limit quota"**.
>
> ⚠️ This doc predates the **#532 shared cross-model budget cutover**
> ([`docs/patterns/shared-cross-model-budget.md`](shared-cross-model-budget.md) —
> read that first for the full counter-key anatomy and its history). The key
> shape below has been updated to match the current **shared** (gateway-wide,
> not per-model) counter.

## Why this exists

The gateway rate-limits every request against per-account budgets
([ADR-0021](../adr/0021-burst-budget-billing-and-dual-plane-authconfigs.md) /
[ADR-0035](../adr/0035-per-person-monthly-budget-and-free-50.md)): a per-model
`BackendTrafficPolicy` keyed on `x-account-id` enforced burst (req/min,
tokens/min); the monthly micro-USD budget moved to a single **gateway-wide**
shared rule, one counter per (account, plan) spanning every model
([shared-cross-model-budget.md](shared-cross-model-budget.md)), and the burst
rules were switched off entirely on 2026-08-01 — so that shared monthly budget
is now the only cap enforced. The Lyft ratelimit service keeps these counters in
**redis-ha** (home-os `charts/home-apps/redis-ha`).

That current-window counter exists **nowhere else**. The cost dashboards
([ADR-0058](../adr/0058-precompute-gateway-usage-metrics-to-mimir.md) Mimir,
[ADR-0046](../adr/0046-per-user-attribution-otlp-envelope-repair.md)/
[0067](../adr/0067-jwt-token-consumption-dashboard.md) Loki) answer "how much did X
spend *historically*". Only Redis answers "how close is X to being throttled
*right now*". This subsystem surfaces that.

## The Redis key shape (verified live)

Since the #532 shared cross-model budget cutover the monthly-budget rule lives
on the **gateway-wide** `BackendTrafficPolicy` (`shared: true`), not a per-model
one — the key is keyed by **policy identity**, not route identity, so it no
longer carries a `/converse/<model>/` segment:

```
converse-gateway/core-gateway_converse-gateway/core-gateway/rule/<N>_...
  ..._rule-<N>-match-0_<x-account-id>_rule-<N>-match-1_..._rule-<N>-match-2_<billing_period>_<window>
```

(verified against a live key: `…rule-1-match-0_49534505-4c60-4550-83dd-7af22152cec6_rule-1-match-1_rule-1-match-1_rule-1-match-2_2026-07_1783296000`)

| Part | Meaning |
|---|---|
| `rule-<N>-match-0_<x-account-id>` | the Distinct `x-account-id` value — a Keycloak `sub` UUID, or a named service caller (`benie-joy`, `koufan-king`). `x-billing-plan`/`x-ai-eg-model` are fixed Exact matches → masked constants, so **plan is the rule index, not a value**. |
| `rule-<N>` | the rule index → the plan. ⚠️ **The index is the ONLY carrier of plan identity** (the plan is an `Exact` match ⇒ masked to a constant), and it is **positional**, so renumbering a rule ORPHANS its counter rather than migrating it. `monthlyBudget.plans` is an **append-only ordered list** ([ADR-0084](../adr/0084-ratelimit-plan-order-is-append-only.md): today `rule-0` = enterprise, `rule-1` = free, `rule-2` = pro); read the current index↔plan mapping off the rendered comment (`# rule/1 · free …`), never off alphabetical order or a hardcoded index — it has renumbered before. |
| `rule-<N>-match-2_<billing_period>` | the Distinct `x-billing-period` value — a calendar `YYYY-MM` string ([ADR-0111](../adr/0111-calendar-aligned-billing-period.md)), stamped on every request by a Lua `EnvoyExtensionPolicy`. Forces a **new** key at the real 1st-of-the-month, independent of where the `<window>` epoch below happens to land. |
| trailing `<window>` | the legacy 30-day budget bucket start (Unix epoch, a multiple of **2592000** = Lyft's MONTH unit). A pure function of wall-clock time, so it drifts off the calendar by ~5 days/year — `billing_period` above is what actually fixes that. Value = micro-USD spent this window. The previous bucket lingers until TTL. |

Burst (per-minute) keys used to exist alongside these but churned every minute
and were never a budget signal, so they were deliberately not scraped. ⚠️ **Since
2026-08-01 they don't exist at all**: every plan's `burst:` block is commented out
in `charts/ai-models/values.yaml`, so the per-model `BackendTrafficPolicy` now
emits no rules whatsoever (its budget rule had already moved to the gateway-wide
policy at the #532 cutover) and the shared monthly budgets below are the only
rate-limit counters in Redis. Keys written before ADR-0111
shipped have no `match-2` segment at all (no `billing_period`); they simply
age out on their existing TTL, same lenient handling `window` already gets
across every monthly rollover.

Inspect live (read-only):

```bash
export KUBECONFIG=/Users/selast/dev/personal/hetzner-k8s/kubeconfig
PW=$(kubectl -n redis-system get secret redis-ha-redis-auth -o jsonpath='{.data.redis-password}' | base64 -d)
kubectl -n redis-system exec redis-ha-redis-0 -- sh -c \
  "redis-cli --tls --cacert /tls/ca.crt -a '$PW' --no-auth-warning -n 0 --scan --pattern '*core-gateway/rule/*' | head"
```

## The two read paths (over the SAME keys)

### 1. Mimir leaderboard — the numbers

`observability` App-of-Apps child **`prometheus-redis-exporter`** (upstream
`prometheus-community/prometheus-redis-exporter`, ADR-0020/0056 child wiring in
`charts/observability/values.yaml`; chart values in
`ai-helm-values environments/prod/values/prometheus-redis-exporter.yaml`):

- `--check-keys` (`REDIS_EXPORTER_CHECK_KEYS=db0=*core-gateway/rule/*`) SCANs
  the gateway-wide shared-budget keys and exports each value as `redis_key_value`.
  ⚠️ Historically this scanned `*rule-2-match-0*,*rule-7-match-0*` (the
  **per-model** budget rules, pre-#532); those rules were gated off at the
  shared-budget cutover, so that pattern was reading dead counters — fixed in
  [ai-helm ADR-0084](../adr/0084-ratelimit-plan-order-is-append-only.md).
- The **ServiceMonitor `metricRelabelings`** (Alloy discovers it) rename it to
  **`gateway_ratelimit_spend_micro_usd`** and carve `account_id / plan / plane /
  window / billing_period` out of the key (no `model` — the shared key carries
  no route/model segment), then **drop the raw key**.
- `window` and `billing_period` are **both kept as labels**. `window` prevents
  the lingering previous 30-day bucket from colliding with the current one on
  the same series at rollover (→ a duplicate-sample scrape error); `billing_period`
  is the calendar-correct temporal marker ([ADR-0111](../adr/0111-calendar-aligned-billing-period.md)).
  Keys written before ADR-0111 shipped simply have no `billing_period` label.

The dashboard's Mimir panels (`$billing_period` single-select, newest calendar
month default; `$plan` / `$account` multi filters) rank spend per account and
per plan, a sortable account×plan table, and the gauge over time. Value ÷1e6 →
USD. **No `$model` filter** — the shared-budget key spans every model, so
per-model spend lives in the separate cost dashboards (ADR-0058/0046), not here.
The legacy `$window` variable was retired from the dashboard (ADR-0111); the
label still exists on the metric but is no longer user-facing.

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

> ⚠️ **Plugin INSTALL gotcha (found 2026-08-01, broke the whole census panel for
> hours before being caught).** Declaring `type: redis-datasource` in
> `datasources.yaml` is **not enough** — Grafana still needs the plugin
> **binary**. The upstream `grafana/grafana` chart's `plugins:` values key is
> what actually installs it (rendered into `GF_INSTALL_PLUGINS`, verified
> against the chart's own `templates/_pod.tpl` at the pinned `10.5.15`,
> `charts/observability/values.yaml`). Without it, the datasource *looks*
> correctly provisioned but every query fails at RUN time: Grafana logs
> `Could not find plugin definition for data source datasource_type=redis-
> datasource`, and the panel shows `Datasource redis-ratelimit was not found` /
> "No data" — no config error, no obvious hint. Confirmed live this had been
> broken since at least 2026-07-31T13:48Z, hit by several different real users,
> before anyone traced it back to the missing plugin. `redis-datasource` is
> Grafana-signed (`grafana.com/api/plugins/redis-datasource` →
> `signatureType: commercial`), so the fix is just adding it to `plugins:` in
> `ai-helm-values environments/prod/values/grafana.yaml` — no
> `GF_PLUGINS_ALLOW_LOADING_UNSIGNED_PLUGINS` override needed (check that
> signature field first if a future plugin addition here is unsigned).

> ⚠️ **`extractFields` schema gotcha (two silent-failure traps, both pre-dating
> the #532/#862 rewrites of this panel — invisible until the plugin-install
> bug above was fixed, since the datasource error short-circuited the
> transform pipeline before either could bite).** Verified against Grafana's
> own pinned-version source
> (`public/app/features/transformers/extractFields/{types,fieldExtractors}.ts`
> + `packages/grafana-data/src/text/string.ts` @ v12.3.1):
> 1. `format` must be the literal `FieldExtractorID` enum value `"regexp"` —
>    `"regex"` isn't registered (valid values: `json`\|`kvp`\|`auto`\|`regexp`\|
>    `delimiter`) and fails the WHOLE transform with "Error transforming data:
>    unknown extractor".
> 2. The pattern must be wrapped in `/…/` delimiters, like a JS regex literal —
>    `stringToJsRegex` checks only that the first character is `/`
>    (`stringStartsAsRegEx`); without matching delimiters the option is
>    **silently discarded** and Grafana falls back to its own built-in default
>    `/(?<NewField>.*)/`. No error at all — the table just renders one
>    "NewField" column holding the entire raw key instead of your named
>    capture groups.
>
> Fixed in `_panel_live_census()`, `tools/dashboards/src/dashboards/
> envoy_ai_gateway/ratelimit_quota.py`. Verified live in the browser (Grafana's
> panel-edit Transformations tab + a JS-console probe against real Redis keys)
> before applying the equivalent fix in source, not just reasoned about from
> the source code above.

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
- **The rule index → plan mapping is encoded in the exporter's metricRelabelings**
  (today: `rule-0` = enterprise, `rule-1` = free, `rule-2` = pro), kept in
  lockstep with the gateway-wide `BackendTrafficPolicy`'s `monthlyBudget.plans`
  ([ADR-0084](../adr/0084-ratelimit-plan-order-is-append-only.md) — an
  **append-only** ordered list; it has renumbered before when a plan was
  inserted rather than appended, silently resetting the whole fleet's budget).
  If a plan is ever appended, add its index to the relabelings. Re-verify with
  a live `--scan` of the rule indices, never off alphabetical order.
- **Forward-only** Mimir history (begins when the exporter deploys); the redis
  census is live. The `billing_period` label specifically only exists on keys
  written since ADR-0111 shipped (2026-07-31) — older, still-live keys carry no
  `billing_period` value until their TTL expires.
- **Values-repo-first** ([ADR-0055](../adr/0055-oci-charts-and-image-updater-writeback-to-values-repo.md)/0056):
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
| [`docs/patterns/shared-cross-model-budget.md`](shared-cross-model-budget.md) | the #532 shared-budget cutover + the full counter-key anatomy this doc's key shape summarizes |
| [`docs/adr/0111-calendar-aligned-billing-period.md`](../adr/0111-calendar-aligned-billing-period.md) | the `billing_period` label design + rationale |
