# AI Gateway — per-user activity dashboard

**File:** `per-user.json`
**Loki datasource UID:** `loki`
**Folder:** `AI Gateway` (provisioned by `charts/observability-dashboards/templates/folders.yaml`)
**Operator CR name:** `envoy-ai-gateway-per-user`

## What it shows

End-to-end per-user view of traffic through the Envoy AI Gateway, sliced by
Keycloak user (`user_id` = JWT `sub`), authorized party (`azp` = client_id),
and model.

| Panel | Question it answers |
|---|---|
| Requests / Unique users / Total tokens / p95 latency (stats row) | "What's happening right now, in one glance" |
| Requests per user / minute (stacked timeseries) | "Who's driving the volume, and when" |
| Top users by requests (table) | "Who are the heaviest callers right now" |
| Model distribution (pie) | "What models is the selected scope using" |
| Latency per user — p50 / p95 (timeseries) | "Is anyone seeing slow responses" |
| Failed requests per user (stacked bar) | "Where are the 5xx errors landing" |
| Token usage per user (timeseries) | "Who's burning tokens" |

## Variables

- **`azp`** — Keycloak client_id (`label_values(azp)`). Multi-select with All. Use to split human vs SA traffic (see `docs/authorino-service-account-bypass.md` for the SA allowlist).
- **`user_id`** — Keycloak user `sub` (`label_values({azp=~"$azp"}, user_id)`). Cascades from `azp`.
- **`model`** — `gen_ai_request_model` extracted from the access log JSON. Filters all panels.

## Data path

The dashboard relies on labels added by the per-user attribution pipeline:

```
JWT → Authorino response headers (x-oidc-user-id, x-oidc-azp; full x-oidc-* contract in ADR-0011)
    → Envoy access-log JSON (user_id, azp fields)
    → OTLP → Alloy (direct; the -usage collector was removed)
    → loki.process "ai_gateway_user_attribution"
    → Loki labels {user_id, azp}
```

If the dashboard is empty, walk that flow backwards using the
[troubleshooting matrix in `docs/per-user-observability.md`](../../../../docs/per-user-observability.md#troubleshooting).

## Editing

1. Open the dashboard in Grafana, make changes.
2. Settings → JSON Model → copy the JSON.
3. Replace `per-user.json` with the new content. **Strip** before committing:
   - `id` (Grafana assigns)
   - `__inputs` / `__elements` if a fresh import added them
   - Any cached `dashboard.version` bumps that don't reflect a real change
4. Keep `uid: envoy-ai-gateway-per-user` stable — changing it breaks bookmarks.
5. `helm template observability-dashboards charts/observability-dashboards` should diff cleanly.

## Adding panels

Add panel objects to the `panels` array. The dashboard uses a 24-column grid.
Current layout heights:

| Row y | Height | Width split |
|---|---|---|
| 0  | 4 | 6 + 6 + 6 + 6 (stats) |
| 4  | 9 | 24 (full-width timeseries) |
| 13 | 9 | 12 + 12 (table + pie) |
| 22 | 9 | 24 (latency timeseries) |
| 31 | 9 | 12 + 12 (errors + tokens) |
| 40 | — | next free row |

Anything you append should start at `y: 40` or rearrange existing panels.
