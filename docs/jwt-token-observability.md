# JWT-token-level consumption (the `oidc_jti` view)

**Status:** live (2026-06-27). **ADR:** [0067](./adr/0067-jwt-token-consumption-dashboard.md). **Dashboard:** `AI Gateway — JWT tokens x consumption` (uid `envoy-ai-gateway-jwt-tokens`).

The person-level boards ([`per-user-observability.md`](./per-user-observability.md),
[`keycloak-identity-datasource.md`](./keycloak-identity-datasource.md)) answer
"who spent what". This one answers a sharper question: **per individual JWT
(access token) — what did it consume, and when was it last used** — with the
email taken **from the JWT claim only**, never the Keycloak directory.

## Why Loki (not Mimir)

The JWT id `oidc_jti` and the JWT email `oidc_email` are written by Envoy into
the access log. Alloy's `ai_gateway_user_attribution` stage (ADR-0046) promotes
`email` to a **Loki stream label**, but **`oidc_jti` stays a body field** — it is
deliberately **not** a Mimir metric label, because every access token is a new id
→ unbounded cardinality (ADR-0064 rejected promoting it). So per-`jti`
aggregation can only come from **Loki**, where the body field lives. The
precomputed Mimir metrics (ADR-0058) that the cost boards use can't do it.

| Field | Where | Used for |
|---|---|---|
| `oidc_jti` | Loki access-log **body** | the JWT id — the row key (extract via `\| json`) |
| `email` | Loki stream **label** (from `oidc_email`) | the JWT email — `=~"$email"` filter + grouping |
| `model` | Loki stream **label** | `=~"$model"` filter |
| `gen_ai.usage.total_tokens` / `…custom_total_cost` | Loki body (dotted keys) | consumption (unwrap) |

## Email from the JWT only

The `email` axis is the Loki label Alloy promotes from the JWT `oidc_email`
claim — the Keycloak datasource is **not** involved here (that's deliberate: this
is the JWT's own view). A token with no email claim shows its **sentinel** —
`missing:github:email`, `missing:lightbridge:email`, `missing:service:email`,
`unstamped:email` — which honestly marks CI / service / unclaimed tokens rather
than papering over the gap. To de-sentinel those you'd fix the *token* (always
stamp `x-oidc-user-name`/email), not this dashboard.

## The LogQL contract (the load-bearing detail)

```logql
sum by (oidc_jti, email) (
  sum_over_time(
    {service_name="envoy-ai-gateway", email=~"$email", model=~"$model"}
    | json oidc_jti, cost=`["gen_ai.usage.custom_total_cost"]`
    | oidc_jti!="" | unwrap cost | __error__=""
    [$__range]
  )
)
```

- ⚠️ **Extract `oidc_jti` in the SAME `| json` that the outer `sum by` groups
  on.** Extracting only the unwrap field (e.g. `| json cost=…`) leaves `oidc_jti`
  unextracted → it collapses to `-` and every token merges into one bogus row.
  (This bit during development; it's the #1 trap.)
- **Dotted usage keys** (`gen_ai.usage.total_tokens`) aren't valid bare LogQL
  field names → use the backtick-quoted bracket form `field=["dotted.key"]`.
  Flat keys (`oidc_jti`, `response_code`) extract by bare name.
- **Every `unwrap` needs `| __error__=""`** — values are strings and absent ones
  are `"-"`; without the guard the whole query fails (ADR-0046).
- **Range queries only.** The Loki Grafana plugin doesn't substitute `$__range`
  in *instant* queries → silent no-data. Use `query_type: range` (the generator's
  `_loki_target` pins it). The timeseries uses `$__auto` for per-step buckets.
- **Cost is micro-USD → `÷1e6`** before the `currencyUSD` unit.

## The panels

`tools/dashboards/envoy_ai_gateway/jwt_tokens.py` (ADR-0008) →
`charts/observability-dashboards/files/envoy-ai-gateway/jwt-tokens.json`:

- **Stats** — distinct JWTs / cost / tokens / requests over the range.
- **Top JWTs by cost** and **by tokens** — `topk(20)` bargauge, legend
  `<email> · <jti>`.
- **Cost per JWT over time** — timeseries (reuses `_sum_by_jti('cost',
  window="$__auto")` — one source of truth for the per-jti cost query).
- **Last usages** — a Loki **logs** panel of recent requests, newest first,
  `line_format`'d to `email · jti · model · rc · tokens · µ$`.

Filters: `email` (from the JWT), `model`. Default range **6h** (access-token
timescale).

## Cardinality

`oidc_jti` is high-cardinality in theory (one per access token) but small in
practice — access tokens are reused across many requests, so live there are only
~a handful of distinct `jti`/hour. `sum by (oidc_jti, email)` therefore stays well
under Loki's 500-series cap at 6h. If usage scales: narrow the range or `topk`.
Do **not** promote `jti` to a Mimir label — ADR-0064 stands.

## Verify live

```bash
export KUBECONFIG=/path/to/hetzner-k8s/kubeconfig
AU=$(kubectl -n observability get secret grafana-admin -o jsonpath='{.data.admin-user}' | base64 -d)
AP=$(kubectl -n observability get secret grafana-admin -o jsonpath='{.data.admin-password}' | base64 -d)
kubectl -n observability port-forward svc/grafana 13000:80 &
LQ=http://localhost:13000/api/datasources/proxy/uid/loki/loki/api/v1
NOW=$(python3 -c 'import time;print(int(time.time()*1e9))')
# top JWTs by cost (real jti + email; sentinels for thin tokens)
curl -s -u "$AU:$AP" -G "$LQ/query" --data-urlencode \
 'query=topk(5, sum by (oidc_jti, email) (sum_over_time({service_name="envoy-ai-gateway"} | json oidc_jti, cost=`["gen_ai.usage.custom_total_cost"]` | oidc_jti!="" | unwrap cost | __error__="" [6h]))) / 1e6' \
 --data-urlencode "time=$NOW"
```
