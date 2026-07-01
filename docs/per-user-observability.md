# Per-user observability: JWT identity → Loki labels

Adds six Loki labels — `user_id`, `azp`, `model`, `email`, `display_name`,
and `billing_plan` — to every Envoy AI Gateway access log, so dashboards can
break down requests, latency, tokens, and cost by authenticated user.

> **Repaired 2026-06-12 (ADR-0046).** The original wiring assumed the access
> log JSON would arrive as the Loki line body. In reality Envoy's OTel sink
> delivers the fields as OTLP log **attributes**, and Alloy stored the line
> as `{"attributes":{...},"resources":{...}}` — so the label promotion never
> fired and the per-user dashboard was empty since rollout. Alloy now
> flattens the envelope and pins the stream name. This doc describes the
> repaired pipeline.

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
                                           │    x-oidc-iss, x-oidc-roles-realm,
                                           │    x-oidc-resource-access, x-oidc-scope,
                                           │    x-oidc-jti, x-oidc-email (PII), x-oidc-name (PII)
                                           ▼
                            ┌────────────────────────────────┐
                            │  Envoy access log — OTel sink  │
                            │  format.json fields become     │
                            │  OTLP log ATTRIBUTES; straight │
                            │  to alloy.observability:4317   │
                            │  (resource service.name =      │
                            │   envoy-ai-gateway)            │
                            └──────────────┬─────────────────┘
                                           ▼
                            ┌─────────────────────────────────┐
                            │  Alloy (observability ns)       │
                            │   otelcol.receiver.otlp →       │
                            │   otelcol.exporter.loki →       │
                            │   loki.process                  │
                            │     ai_gateway_user_attribution │
                            │   (ADR-0046: match gateway logs,│
                            │    flatten {"attributes":{…}} → │
                            │    line, promote labels, pin    │
                            │    service_name)                │
                            │   → loki.write.default          │
                            └──────────────┬──────────────────┘
                                           ▼
                            ┌────────────────────────────────┐
                            │  Loki                          │
                            │  gateway streams keyed by      │
                            │  {service_name=envoy-ai-gateway,│
                            │   exporter, cluster,           │
                            │   user_id, azp, model,         │
                            │   email, display_name,         │
                            │   billing_plan}                │
                            └──────────────┬─────────────────┘
                                           ▼
                            ┌────────────────────────────────┐
                            │  Grafana — per-user dashboards │
                            └────────────────────────────────┘
```

## The stored-line contract (ADR-0046)

For gateway access logs, the Loki line is the **flat** attributes object:

```json
{"user_id":"<sub>","azp":"opencode-cli","gen_ai.request.model":"glm-5p2",
 "gen_ai.usage.total_tokens":"49845","duration":"51042","response_code":"200", ...}
```

Querying rules that follow from it:

- `| json` sanitizes dotted keys to underscores: `gen_ai.usage.total_tokens`
  → `gen_ai_usage_total_tokens`.
- **Numeric fields are strings** (`"49845"`) and **absent fields are `"-"`**
  (Envoy's placeholder) — always guard unwraps:
  `| json | unwrap gen_ai_usage_total_tokens | __error__=""`.
- Anchor every query on `{service_name="envoy-ai-gateway"}` — it's pinned by
  Alloy (`stage.static_labels`), deterministic and cheap.
- Identity labels are **always present** (ADR-0052, supersedes the old
  blank-to-empty behaviour): an absent value is never stored empty — Loki drops
  empty labels, which would make the failure *invisible*. It resolves to a
  descriptive sentinel instead: `missing:<source>:<claim>` (Authorino — the
  token lacked the claim) or `unstamped:<field>` (Alloy — no header arrived).
  Both match `=~".+"`, so the Overall section counts them; the per-user *human*
  panels exclude `(missing|unstamped):.*`. See "Identity sentinels" below.
- Lines ingested **before** the repair keep the old nested shape under
  `service_name="unknown_service"` — query those with `attributes_`-prefixed
  field names if you ever need the history.

## Identity sentinels (ADR-0052)

An absent identity claim/header is **never** stored empty. It resolves to a
descriptive, source-qualified sentinel that names *what* is missing and *where*
it was lost — so an attribution gap is loud, not invisible:

| Sentinel | Set by | Meaning |
|---|---|---|
| `missing:keycloak:<claim>` | Authorino | external Keycloak token lacked the claim — a real token/client gap |
| `missing:github:<claim>` | Authorino | external GitHub Actions token — usually *expected* (GitHub OIDC carries no `email`/`preferred_username`/`scope`) |
| `missing:librechat:<claim>` | Authorino (internal plane) | a forwarded LibreChat user the app didn't forward that field for |
| `missing:service:<claim>` | Authorino (internal plane) | a non-human cron/SA caller (field legitimately absent) |
| `unstamped:<field>` | Alloy | no header arrived at all (request matched no AuthConfig response, or a plane that omits the field) |

> **Known callers are named, not sentinel'd (ADR-0068).** For callers whose
> identity is *known* even without a human email/jti, Authorino synthesizes a
> structured identity instead of a `missing:*` sentinel — `email = <resource>@<service>`
> and `jti = <kind>:<id>`:
>
> | Caller | email | jti |
> |---|---|---|
> | GitHub CI | `<owner/repo>@gh-runners` (e.g. `ADORSYS-GIS/ai-helm@gh-runners`) | `runid:<run_id>` (guarded → raw GitHub `jti` → `missing:github:jti`) |
> | LCI | `<owner/repo>@lightbridge-code-intelligence` (e.g. `vymalo/flutter-tools@lightbridge-code-intelligence`) | `runid:<task-id>` |
> | LibreChat user | the real forwarded email (`X-LibreChat-Email`) | `librechat:<x-librechat-user>` |
>
> These are **not** `missing:*`, so they are *not* excluded by the board's
> `(missing|unstamped):.*` filter — services are first-class named identities.
> The human/service split therefore stays on the `billing_plan` (`internal` for
> services) / `azp` labels, not the email string. Genuine gaps (a Keycloak human
> with no email, a raw cron/SA caller) still resolve to `missing:keycloak:*` /
> `missing:service:*`.

Rule of thumb: a `missing:`/`unstamped:` prefix marks an attribution gap, and
the shape tells you the layer — `missing:<source>:<claim>` is token-level
(Authorino), `unstamped:<field>` is header-level (gateway/Alloy). The external
source is told apart by the GitHub-only `repository` claim. Internal-plane
display names fall back to the caller's OWN identity (SA username / apiKey
Secret name) for non-forwarded services, so services are *named* in the Top-15;
LibreChat forwards `X-LibreChat-Name` (`charts/librechat-app`) so its users
resolve by real name. The per-user board's `_SELECTOR` adds
`email!~"(missing|unstamped):.*"` to keep sentinels out of the human panels
while they stay visible in Overall and as their own Top-15 row.

## Where each step lives

| Step | File | Change |
|---|---|---|
| Authorino emits the OIDC header set (ADR-0011) | `charts/apps/values.yaml` `security-policies.authConfigs.main.response.success.headers` | Entries `x-oidc-user-id`, `x-oidc-user-name`, `x-oidc-azp`, `x-oidc-iss`, `x-oidc-roles-realm`, `x-oidc-resource-access`, `x-oidc-scope`, `x-oidc-jti`, `x-oidc-email`, `x-oidc-name` |
| Envoy access log carries them through | `charts/core-gateway/templates/envoy-proxy.yaml` `telemetry.accessLog.settings[0]` | Fields `user_id` / `user_name` / `azp` in `format.json`; sink resource `service.name: envoy-ai-gateway`; sent directly to `alloy.observability:4317` (the old `-usage` OTel collector middleman was removed) |
| Alloy flattens the OTLP envelope + promotes labels | `charts/observability/values.yaml` alloy child `valuesObject` (`extraConfig`) | `loki.process "ai_gateway_user_attribution"`: `stage.match` on the `otel_envoy_accesslog` marker → extract `attributes` → `stage.output` (flatten) → map `^(-\|<nil>)$` → `unstamped:<field>` (ADR-0052) → promote `user_id`/`azp`/`model`/`email`/`display_name`/`billing_plan` → pin `service_name=envoy-ai-gateway` |
| LibreChat forwards the end-user identity (internal plane) | `charts/librechat-app/values.yaml` custom-endpoint `headers` | `X-LibreChat-User`/`-Email`/`-Role`/`-Name` → consumed by the internal AuthConfig into `x-account-id`/`x-oidc-*` (ADR-0021/0052) |
| Dashboard consumes the labels | `tools/dashboards/src/dashboards/envoy_ai_gateway/per_user.py` (generated → `charts/observability-dashboards/files/envoy-ai-gateway/per-user.json`) | Label-only stream selectors (per-user `_SELECTOR` excludes `(missing\|unstamped):.*`), `label_values(...)` variables, guarded unwraps |

## Label cardinality budget

Loki streams are O(N) on `(label set)` × `(distinct value combinations)`. We
promote six attribution fields to labels; everything else stays in the log
body and is queried with `| json | <field>=~"..."`.

| Field | Source attribute | Bound | Why labeled |
|---|---|---|---|
| `user_id` | `user_id` ← `x-oidc-user-id` (JWT `sub`) | One value per registered user | Primary attribution dimension; required for per-user dashboards |
| `azp` | `azp` ← `x-oidc-azp` (JWT `azp`) | One value per Keycloak client (~10–20) | Lets dashboards split human vs SA traffic and pivot by app |
| `model` | `gen_ai.request.model` ← `x-ai-eg-model` | One value per catalog model (~10–20) | Backs the dashboard's model variable + per-model splits without a body parse (ADR-0046) |
| `email` | `oidc_email` ← `x-oidc-email` (JWT `email`) | ≤ user_id granularity — adds no stream cardinality | Unique human-readable user identity; PII (stored in label index). Humans: 1:1 with user_id. Synthetic service emails (ADR-0068, e.g. `<repo>@gh-runners`) are **coarser** than user_id (one email per repo, while user_id = the GitHub `sub` carries repo+ref) — functionally determined by it, so no new streams. |
| `display_name` | `oidc_name` ← `x-oidc-name` (JWT `name`, e.g. "Kunga Derick") | 1:1 with user_id | Human-readable label for bar charts; first name extracted at query time via `label_replace` |
| `billing_plan` | `billing_plan` ← `x-billing-plan` | 4 distinct values (free/pro/service/internal) | Very cheap; enables tier segmentation in dashboards |

Fields intentionally **not** labeled:

| Field | Reason |
|---|---|
| `response_code` | ~15 values × user × model = large stream count for marginal query gain; queried via `\| json` instead |
| `user_name` (`preferred_username`) | Redundant with `email`; same cardinality, less unique |
| Request/trace IDs, token counts | Unbounded cardinality — would explode stream count |

If user count exceeds a few thousand and `{user_id}` cardinality becomes a
problem, options:
- Drop `user_id` from labels; keep it in the body and query against it.
- Hash to a fixed bucket count: `user_bucket = hash(sub) % 100`. Lose
  per-individual breakdown but keep aggregation.
- Run a separate Loki tenant for the gateway logs only (X-Scope-OrgID).

We are nowhere near these limits today.

## Service-account tokens

SAs get the same three headers as humans, with the following semantics:

| Header / label | Human token | SA token |
|---|---|---|
| `x-oidc-user-id` → `user_id` | Keycloak user UUID | The SA's internal user UUID (Keycloak auto-creates a user behind every SA client) |
| `x-oidc-user-name` (body only) | `alice` | `service-account-adorsys-gis-github-ci` |
| `x-oidc-azp` → `azp` | `converse-frontend` etc. | `adorsys-gis-github-ci`, `lightbridge-api-key`, … |
| `x-oidc-email` → `email` | `alice@example.com` | empty → no label |
| `x-oidc-name` → `display_name` | `Alice Lastname` | empty → no label |
| `x-billing-plan` → `billing_plan` | `free` / `pro` / `service` | `internal` |
| `x-oidc-resource-access` (body only) | `{"converse":["admin"],"phoenix":["admin"],...}` | `{"<sa-client-id>":["uma_protection"],"account":[...]}` |

To filter human-only or SA-only in dashboards, use the `azp` label and the
allowlist from `docs/authorino-service-account-bypass.md`:

```logql
# Human traffic only
{service_name="envoy-ai-gateway", azp!~"adorsys-gis-github-ci|lightbridge-api-key"}

# Service-account traffic only
{service_name="envoy-ai-gateway", azp=~"adorsys-gis-github-ci|lightbridge-api-key"}
```

## Verifying it works

```bash
# 1. Send a request with a real JWT (use kc-token from task #3)
HUMAN_TOKEN=$(kc-token --client-id converse-frontend ...)
curl -sv -H "Authorization: Bearer $HUMAN_TOKEN" \
  -H "X-AI-EG-Model: glm-5p2" \
  https://api.ai.camer.digital/v1/chat/completions \
  -d '{"model":"glm-5p2","messages":[{"role":"user","content":"hi"}]}'

# 2. In Grafana → Explore → Loki, query
{service_name="envoy-ai-gateway", azp=~".+"}
# Expect: lines tagged with your user_id, azp, and model labels.

# 3. Aggregate over time, by user
sum by (user_id) (count_over_time({service_name="envoy-ai-gateway"} [5m]))
```

If you see the JSON fields but no labels, Alloy's
`loki.process "ai_gateway_user_attribution"` stage didn't fire — typical
causes: the `stage.match` marker (`otel_envoy_accesslog`) missing from the
line, or the access log isn't reaching Alloy's OTLP receiver at all (Envoy
pushes access logs straight to `alloy.observability:4317` — the old
`-usage` OTel collector was removed; check the Alloy pod logs).

## LogQL queries for common dashboards

```logql
# Requests per user per minute (labels only — no body parse needed)
sum by (user_id) (
  count_over_time({service_name="envoy-ai-gateway"} [1m])
)

# Per-user p95 latency (duration is a string in the body — guard the unwrap)
quantile_over_time(0.95,
  {service_name="envoy-ai-gateway"} | json | unwrap duration | __error__="" [5m]
) by (user_id)

# Per-user total tokens
sum by (user_id) (
  sum_over_time(
    {service_name="envoy-ai-gateway"}
      | json
      | unwrap gen_ai_usage_total_tokens | __error__="" [1h]
  )
)

# Per-model usage by a specific user (model is a label now)
sum by (model) (
  count_over_time(
    {service_name="envoy-ai-gateway", user_id="<uuid>"} [1h]
  )
)

# Top 15 users by cost — first name via label_replace on display_name label
label_replace(
  topk(15, sum by (display_name) (
    sum_over_time(
      {service_name="envoy-ai-gateway", user_id=~".+"}
        | json | unwrap gen_ai_usage_custom_total_cost | __error__="" [$__range]
    )
  )),
  "given_name", "$1", "display_name", "^(\\S+).*"
)

# Filter by billing tier (billing_plan is a label — no body parse)
sum by (user_id) (
  count_over_time({service_name="envoy-ai-gateway", billing_plan="free"} [1h])
)

# Status code distribution (response_code is body-only — requires | json)
sum by (response_code) (
  count_over_time(
    {service_name="envoy-ai-gateway", user_id=~".+"}
      | json | response_code !~ "^(-|)$" [1h]
  )
)

# Look up a user by email (email is a label — fast, no body parse)
{service_name="envoy-ai-gateway", email="abonghoderick@gmail.com"}
```

## Resolving opaque `user_id` UUIDs → people (Keycloak datasource, ADR-0063)

The `email` / `display_name` labels only exist when the JWT carried the `email` /
`name` claims. A thin access token (no email/name) falls back to the
`missing:`/`unstamped:` sentinels, leaving the `user_id` UUID (the Keycloak
`sub`) as the only stable identifier — opaque on a dashboard.

To resolve those at query time, Grafana has a **read-only Postgres datasource
(`uid: keycloak`)** onto the Keycloak CNPG DB (ADR-0063). The generated
**`AI Gateway — user directory (identity attribution)`** dashboard
(`tools/dashboards/envoy_ai_gateway/user_directory.py`) uses it two ways:

- **Spend by user — resolved to identity** — a `-- Mixed --` table that
  OUTER-joins (`joinByField` on `user_id`) the Mimir `sum by (user_id)` spend to
  the Keycloak directory. A row with an **empty Name** is a non-human subject (a
  CI repo subject like `repo:ADORSYS-GIS/…:pull_request`, or an `internal-key-*`
  service) — those never resolve because they aren't Keycloak users.
- **Keycloak user directory** — the raw `user_id` → username/email/name lookup.

The datasource role (`grafana_ro`) is **least-privilege**: SELECT on the user +
token tables only (never `credential` hashes, client secrets, or federated
tokens — it is the auth DB). It also can't read the `realm` table, so queries
filter `user_entity.realm_id` by the **literal** internal id of the trusted
realm (`camer-digital` = `04793949-13aa-48ef-9d4d-1c60761f0c97`). The role +
GRANT live in **home-os** `charts/home-apps/keycloak-ha`; the datasource + egress
in **ai-helm-values**. This is a read-time resolver — it complements, but does
not replace, fixing thin tokens to carry the email/name claims.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Streams land as `service_name="unknown_service"` with a `{"attributes":...}` body | The `ai_gateway_user_attribution` stage isn't matching (the exact pre-ADR-0046 failure mode) | Check the Alloy config actually deployed (`stage.match` selector `{exporter="OTLP"} \|= "otel_envoy_accesslog"`); diff against `charts/observability/values.yaml` |
| `user_id` label missing on some requests, `azp` present | Request authenticated via a path that doesn't stamp `sub` | Was the request authenticated? Envoy logs `-` for absent headers and Alloy maps `-` → no label by design (unauthenticated traffic is intentionally unlabeled) |
| `user_id` label absent entirely on AI Gateway logs | Alloy stage isn't seeing the field | `kubectl logs -n observability daemonset/alloy` and look for parse errors; verify the flattened line contains `"user_id":` (not the header name `"x-oidc-user-id":`) |
| No gateway streams in Loki at all | Access log not reaching Alloy's OTLP receiver | Envoy exports straight to `alloy.observability.svc:4317`; check the deps overlay's OTLP ingress allow (`environments/*/deps/alloy/`) and the Alloy receiver logs. Remember only requests with `x-ai-eg-model` set are logged (`matches` condition) |
| Token/latency panels empty but request panels work | Unwrap failing on string/`-` values | Every unwrap needs the `\| __error__=""` guard (ADR-0046); fields are strings and absent values are `-` |
| SA tokens missing labels too | `auth.identity.sub` selector returns empty for some tokens | Some Keycloak realm configs hide `sub` on SA tokens. Switch the selector to `auth.identity.<claim-actually-present>` and update this doc |
| All requests label as same user | Authorino is using the wrong identity source | Confirm the AuthConfig `authentication.keycloak.jwt.issuerUrl` matches the realm issuing the tokens you're sending |
| `email` / `display_name` labels missing | JWT doesn't include `email` / `name` claims | Verify the Keycloak client has the `email` and `profile` scopes mapped; decode a live JWT at jwt.io and confirm `email` and `name` fields are present |
| `billing_plan` label missing | Rate-limit descriptor not stamped | The `x-billing-plan` header is set by Authorino's CEL descriptor (ADR-0021); missing means the request bypassed the rate-limit path or the AuthConfig CEL expression returned empty |

## Related

- `docs/adr/0046-per-user-attribution-otlp-envelope-repair.md` — the
  repair decision (flatten + label promotion + stream anchor)
- `docs/adr/0063-grafana-readonly-keycloak-datasource.md` — the read-only
  Keycloak Postgres datasource that resolves opaque `user_id` UUIDs → people
  (`tools/dashboards/envoy_ai_gateway/user_directory.py`)
- `docs/jwt-token-observability.md` (ADR-0067) — the per-JWT (`oidc_jti`)
  consumption + last-usages view, email from the JWT claim only; the
  `oidc_jti`-same-`| json`-extraction LogQL trap
  (`tools/dashboards/envoy_ai_gateway/jwt_tokens.py`)
- `docs/adr/0005-per-user-attribution-via-authorino-headers.md` — the original
  design this implements
- `docs/observability-dashboard-research.md` — the audit that found the break
- `docs/authorino-service-account-bypass.md` — how SA tokens differ
- `docs/observability-fix-no-data-dashboards.md` — the Alloy pipeline this
  extends
- `docs/grafana-operator-and-dashboards.md` — where the dashboards consuming
  these labels live
- `charts/observability/values.yaml` alloy child `extraConfig` — the
  `loki.process "ai_gateway_user_attribution"` stage
