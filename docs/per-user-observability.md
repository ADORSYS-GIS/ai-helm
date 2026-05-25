# Per-user observability: JWT identity → Loki labels

Adds two Loki labels — `user_id` and `azp` — to every Envoy AI Gateway access
log, so dashboards can break down requests, latency, tokens, and cost by
authenticated user.

## End-to-end flow

```
                            ┌────────────────────────────────┐
  Client + JWT  ───POST───▶ │  Envoy AI Gateway (core-gw)    │
                            └──────────────┬─────────────────┘
                                           │  ext_authz: gRPC
                                           ▼
                            ┌────────────────────────────────┐
                            │  Authorino (kuadrant-policies) │
                            │  AuthConfig: api-https / main  │
                            └──────────────┬─────────────────┘
                                           │  on success, set headers
                                           │  (ADR-0011 x-oidc-* contract):
                                           │    x-oidc-user-id   ← auth.identity.sub
                                           │    x-oidc-user-name ← auth.identity.preferred_username
                                           │    x-oidc-azp       ← auth.identity.azp
                                           │    x-oidc-iss       ← auth.identity.iss
                                           │    x-oidc-roles-realm
                                           │    x-oidc-resource-access
                                           │    x-oidc-scope
                                           │    x-oidc-jti
                                           │    x-oidc-email     ← (PII)
                                           │    x-oidc-name      ← (PII)
                                           ▼
                            ┌────────────────────────────────┐
                            │  Envoy access log (JSON sink)  │
                            │   → OTLP → core-gw-usage-     │
                            │     collector (OpenTelemetryCo) │
                            └──────────────┬─────────────────┘
                                           │  otlphttp/lightbridge_usage  AND
                                           │  otlp/alloy
                                           ▼
                            ┌────────────────────────────────┐
                            │  Alloy (observability ns)      │
                            │   otelcol.receiver.otlp →      │
                            │   otelcol.exporter.loki →      │
                            │   loki.process                  │
                            │     ai_gateway_user_attribution │  ← extracts JSON
                            │   → loki.write.default          │     promotes labels
                            └──────────────┬─────────────────┘
                                           ▼
                            ┌────────────────────────────────┐
                            │  Loki                          │
                            │  streams keyed by              │
                            │  {namespace, pod, container,   │
                            │   level, user_id, azp}         │
                            └──────────────┬─────────────────┘
                                           ▼
                            ┌────────────────────────────────┐
                            │  Grafana — per-user dashboards │
                            └────────────────────────────────┘
```

## Where each step lives

| Step | File | Change |
|---|---|---|
| Authorino emits the OIDC header set (ADR-0011) | `charts/apps/values.yaml` `security-policies.authConfigs.main.response.success.headers` | Entries `x-oidc-user-id`, `x-oidc-user-name`, `x-oidc-azp`, `x-oidc-iss`, `x-oidc-roles-realm`, `x-oidc-resource-access`, `x-oidc-scope`, `x-oidc-jti`, `x-oidc-email`, `x-oidc-name` |
| Envoy access log carries them through | `charts/core-gateway/templates/envoy-proxy.yaml` `telemetry.accessLog.settings[0].format.json` | New fields `user_id` / `user_name` / `azp` |
| OTel collector forwards to Alloy | `charts/core-gateway/templates/otel.yaml` `-usage` collector | Unchanged — already forwards to `otlp/alloy` |
| Alloy promotes JSON fields to Loki labels | `charts/apps/values.yaml` Alloy `extraConfig` | New `loki.process "ai_gateway_user_attribution"` stage between `otelcol.exporter.loki` and `loki.write.default` |

## Label cardinality budget

Loki streams are O(N) on `(label set)` × `(distinct value combinations)`. We
promote two attribution fields to labels; everything else stays in the log
body and is queried with `| json | <field>=~"..."`.

| Field | Source | Bound | Why labeled |
|---|---|---|---|
| `user_id` | Keycloak JWT `sub` (UUID) | One value per registered user | Primary attribution dimension; required for per-user dashboards |
| `azp` | Keycloak JWT `azp` (client_id) | One value per Keycloak client (~10–20 today) | Cheap; lets dashboards split human vs SA traffic and pivot by app |
| `user_name` | `preferred_username` | One value per user | **Not labeled.** Carried in the body as a display field; query with `| json | user_name=~"alice.*"` when you need a human-readable filter. |

If user count exceeds a few thousand and `{user_id}` cardinality becomes a
problem, options:
- Drop `user_id` from labels; keep it in the body and query against it.
- Hash to a fixed bucket count: `user_bucket = hash(sub) % 100`. Lose
  per-individual breakdown but keep aggregation.
- Run a separate Loki tenant for the gateway logs only (X-Scope-OrgID).

We are nowhere near these limits today.

## Service-account tokens

SAs get the same three headers as humans, with the following semantics:

| Header | Human token | SA token |
|---|---|---|
| `x-oidc-user-id` | Keycloak user UUID | The SA's internal user UUID (Keycloak auto-creates a user behind every SA client) |
| `x-oidc-user-name` | `alice` | `service-account-adorsys-gis-github-ci` |
| `x-oidc-azp` | `converse-frontend` etc. | `adorsys-gis-github-ci`, `lightbridge-api-key`, … |
| `x-oidc-email` | `alice@example.com` | empty |
| `x-oidc-name` | `Alice Lastname` | empty |
| `x-oidc-resource-access` | `{"converse":["admin"],"phoenix":["admin"],...}` | `{"<sa-client-id>":["uma_protection"],"account":[...]}` |

To filter human-only or SA-only in dashboards, use the `azp` label and the
allowlist from `docs/authorino-service-account-bypass.md`:

```logql
# Human traffic only
{namespace="observability", azp!~"adorsys-gis-github-ci|lightbridge-api-key"}

# Service-account traffic only
{namespace="observability", azp=~"adorsys-gis-github-ci|lightbridge-api-key"}
```

## Verifying it works

```bash
# 1. Send a request with a real JWT (use kc-token from task #3)
HUMAN_TOKEN=$(kc-token --client-id converse-frontend ...)
curl -sv -H "Authorization: Bearer $HUMAN_TOKEN" \
  -H "X-AI-EG-Model: glm-5" \
  https://api.ai.camer.digital/v1/chat/completions \
  -d '{"model":"glm-5","messages":[{"role":"user","content":"hi"}]}'

# 2. In Grafana → Explore → Loki, query
{namespace="converse-gateway", azp=~".+"} | json | user_id != ""
# Expect: lines tagged with your user_id and azp.

# 3. Aggregate over time, by user
sum by (user_id) (count_over_time({namespace="converse-gateway"} | json [5m]))
```

If you see the JSON fields but no labels, Alloy's
`loki.process "ai_gateway_user_attribution"` stage didn't fire — typical
causes: typo in the field name in the access log JSON, or the access log
isn't reaching the `-usage-collector` (check the collector pod logs).

## LogQL queries for common dashboards

```logql
# Requests per user per minute
sum by (user_id) (
  count_over_time({namespace="converse-gateway"} | json [1m])
)

# Per-user p95 latency (duration field in the log body)
quantile_over_time(0.95,
  {namespace="converse-gateway"} | json | unwrap duration [5m]
) by (user_id)

# Per-user total tokens
sum by (user_id) (
  sum_over_time(
    {namespace="converse-gateway"}
      | json
      | unwrap gen_ai_usage_total_tokens [1h]
  )
)

# Per-model usage by a specific user
sum by (gen_ai_request_model) (
  count_over_time(
    {namespace="converse-gateway", user_id="<uuid>"}
      | json [1h]
  )
)
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `user_id` label present but empty | Authorino didn't set the header for this request | Was the request authenticated? Check Authorino logs — selector `auth.identity.sub` resolves to empty for unauthenticated requests |
| `user_id` label absent entirely on AI Gateway logs | Alloy stage isn't seeing the field | `kubectl logs -n observability daemonset/alloy` and look for parse errors; verify the access-log JSON contains `"user_id":` (not the header name `"x-oidc-user-id":`) |
| Header reaches the upstream but no Loki label | Access log not flowing through the OTel collector | Check the `-usage` collector pod logs; ensure it's healthy and exporting to `alloy.observability.svc:4317` |
| SA tokens missing labels too | `auth.identity.sub` selector returns empty for some tokens | Some Keycloak realm configs hide `sub` on SA tokens. Switch the selector to `auth.identity.<claim-actually-present>` and update this doc |
| All requests label as same user | Authorino is using the wrong identity source | Confirm the AuthConfig `authentication.keycloak.jwt.issuerUrl` matches the realm issuing the tokens you're sending |

## Related

- `docs/authorino-service-account-bypass.md` — how SA tokens differ
- `docs/observability-fix-no-data-dashboards.md` — the Alloy pipeline this
  extends
- `docs/grafana-operator-and-dashboards.md` — where the dashboards consuming
  these labels live (task #7)
- `charts/apps/values.yaml` Alloy `extraConfig` — the
  `loki.process "ai_gateway_user_attribution"` stage
