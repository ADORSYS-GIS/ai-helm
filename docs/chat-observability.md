# Phoenix-style chat observability (OpenInference traces in Tempo)

**Status:** live. **ADRs:** [0077](./adr/0077-phoenix-style-chat-dashboards.md)
(the dashboards) + [0078](./adr/0078-per-user-span-attribution-for-chat-content.md)
(per-user span attribution, supersedes 0077's decision to skip it).
**Dashboards:** `AI Gateway — chat overview` (uid `envoy-ai-gateway-chat-overview`),
`AI Gateway — chats by user` (uid `envoy-ai-gateway-chats-by-user`).

The cost/consumption boards ([`cost-observability.md`](./cost-observability.md),
[`per-user-observability.md`](./per-user-observability.md),
[`jwt-token-observability.md`](./jwt-token-observability.md)) answer "who spent
what". This pair answers Arize-Phoenix's question instead: **what did the
conversation actually say** — the request/response content, per chat turn.

## Where the content comes from

The AI Gateway ext-proc auto-instruments every OpenAI-compatible chat/
embeddings call using [OpenInference semantic conventions](https://github.com/Arize-ai/openinference/tree/main/spec)
(the same schema Phoenix itself uses) whenever it has an OTLP endpoint —
which it has had since `charts/core-gateway/templates/gateway-config.yaml`
set `OTEL_EXPORTER_OTLP_ENDPOINT` (added for the ext-proc's own
instrumentation, not deliberately for this). OpenInference **defaults to
capturing full request/response content**
(`OPENINFERENCE_HIDE_INPUTS`/`_HIDE_OUTPUTS` are opt-in, unset here). This
means Tempo has been holding full-content chat traces all along — confirmed
live against the cluster (`/api/search/tags`, `/api/traces/<id>`, 2026-07-07):

| Attribute | Holds |
|---|---|
| `openinference.span.kind` | `LLM` or `EMBEDDING` — the chat/embedding split |
| `llm.input_messages.N.message.{role,content}` | each input message, per turn |
| `llm.output_messages.N.message.{role,content}` | each output message |
| `input.value` / `output.value` | full raw request/response JSON |
| `llm.model_name` | requested model |
| `llm.token_count.{prompt,completion,total}` | token usage for the span |

No new logging was added to get this — these dashboards are the first thing
to surface a capability that was already running. This was also true in
Phoenix's era: both backends received the exact same OpenInference spans in
parallel (ADR-0002), so nothing about content access changed when Tempo
replaced Phoenix.

## Per-user identity on spans (ADR-0078)

Spans natively carry **no `user.id`/`user.email`**, and the Envoy access-log
JSON (Loki's identity source, [ADR-0046](./adr/0046-per-user-attribution-otlp-envelope-repair.md))
carries no `trace_id` — and a live span carries no `x-request-id` either. So
out of the box there is **no way to attribute a span to a person and no shared
key to join it to the user-bearing Loki logs**; the two datasets are disjoint.

ADR-0077 initially took this as "per-user content is impossible" and skipped
the fix. That was wrong framing — it's a *choice*, not a limit. The global
`chat-overview` never needed attribution (content is all there), but per-user
content is impossible *without* it. [ADR-0078](./adr/0078-per-user-span-attribution-for-chat-content.md)
reverses the decision and adopts the only mechanism that closes the gap: the
Envoy AI Gateway controller's generic header→span-attribute mapping

```yaml
# ai-helm-values environments/prod/values/aieg.yaml
controller:
  spanRequestHeaderAttributes: "x-oidc-user-id:user.id,x-oidc-email:user.email"
```

which tags each span with the Keycloak identity Authorino already stamps
(`x-oidc-user-id`/`x-oidc-email`, present at ext-proc time). The key is
confirmed in ai-gateway-helm **v1.0.0** (→ `--spanRequestHeaderAttributes=`
controller arg, rendered only when set). `chats-by-user` then filters Tempo by
`span.user.email = "$user"`.

**⚠️ Privacy.** This makes full chat content **directly attributable to a named
person** in Grafana. The content already existed in Tempo; this adds the who.
Deliberate, reviewed step (its own `ai-helm-values` PR). Applies to **new
ext-proc pods** — `chats-by-user`'s trace panel is "No data" until the change
deploys and pods roll; its Loki metadata log works meanwhile.

## The two dashboards

- **`chat-overview`** — no input. Loki/Mimir volume/cost/tokens/error-rate/
  latency (embeddings excluded via a `model!~` regex, see
  `EMBEDDING_MODEL_KEYS` in `tools/dashboards/src/dashboards/_common.py` —
  keep in sync with `kind: embedding` entries in `charts/ai-models/values.yaml`),
  plus a live Tempo trace-list panel (Grafana's native `type="traces"` panel,
  the same one `scoreboard.py` already uses) scoped to
  `{ resource.service.name = "core-gateway" && span.openinference.span.kind = "LLM" }`.
  Click a trace to see the full prompt/response — Grafana's built-in
  span-detail view already renders the OpenInference attributes above, no
  custom table needed.
- **`chats-by-user`** — a `$user` picker sourced from a raw-SQL query
  variable against the read-only Keycloak Postgres datasource
  ([ADR-0063](./adr/0063-grafana-readonly-keycloak-datasource.md); `__text`/
  `__value` column aliases), so it lists real people independent of recent
  traffic — not `label_values(email)` like `per_user.py`/`jwt_tokens.py`.
  ⚠️ For a Postgres datasource the variable's query model must carry
  **`rawSql`** — the generic `{query: "..."}` shape leaves Grafana with no SQL
  to run ("error when executing the sql query"); verified live via
  `/api/ds/query` (uid resolves regardless of `type: postgres` vs
  `grafana-postgresql-datasource`). Two views: a **Tempo trace feed** filtered
  by `span.user.email = "$user"` (click a trace for the full prompt/response —
  needs the ADR-0078 attribution deploy, "No data" until then) and a
  **per-request Loki log** (one row per chat: model/status/tokens/cost/latency,
  `email="$user"`, works immediately) — distinct from the
  `per_user`/`actor-consumption` rollup charts.

⚠️ **No raw user input is ever interpolated into SQL.** The `$user` variable's
*available options* come from a static-realm-id query; the *selected* value
only ever reaches a Loki label matcher — never a second SQL string — so
there's no SQL-injection surface from a manipulated `?var-user=` URL param.

## Not built: single-chat drill-down

There is still no LibreChat-conversation-level identifier anywhere in the
pipeline — LibreChat's internal Mongo `conversationId` is never forwarded
past LibreChat's own backend. A true "pick one chat, see its full turn-by-turn
trace" dashboard needs a new forwarded header (mirroring the existing
`X-LibreChat-User` pattern in `charts/librechat-app/values.yaml`) plus an
Authorino pass-through rule — out of scope for ADR-0077, revisit if wanted.

## Verify

```bash
export KUBECONFIG=/Users/selast/dev/personal/hetzner-k8s/kubeconfig
kubectl port-forward -n observability svc/tempo 3200:3200 &
curl -s "http://localhost:3200/api/search/tag/openinference.span.kind/values"
# {"tagValues":["EMBEDDING","LLM"]}
curl -s "http://localhost:3200/api/search/tag/user.email/values"
# empty BEFORE the ADR-0078 attribution deploys; once the ai-helm-values
# spanRequestHeaderAttributes change lands and ext-proc pods roll, new spans
# populate this with the Keycloak emails → chats-by-user's trace panel works.

# Read content on any trace (works regardless of attribution):
curl -s "http://localhost:3200/api/search?q=%7B%20span.openinference.span.kind%20%3D%20%22LLM%22%20%7D&limit=1" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['traces'][0]['traceID'])"
# then GET /api/traces/<id> and inspect the input.value / llm.input_messages.* attributes
```
