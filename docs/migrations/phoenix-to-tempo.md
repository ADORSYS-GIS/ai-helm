# Migration: Arize Phoenix → Grafana Tempo

**Date:** 2026-05-24
**Status:** Completed in branch `claude/magical-bohr-390242`
**Scope:** LLM trace observability backend swap

## TL;DR

Arize Phoenix is **removed**. LLM call tracing is now served by the existing
Grafana Tempo deployment via the core-gateway OpenTelemetryCollector (renamed
`*-phoenix` → `*-traces`) → Alloy → Tempo path.

Phoenix's UI at `analytics.ai.camer.digital` no longer exists. Use Grafana at
the standard observability hostname and the Tempo datasource.

## Why

- Grafana Tempo already runs at sync-wave -2 in the `observability` namespace
  with persistent S3 storage and was receiving the same OTLP traces in parallel
  with Phoenix. Phoenix was redundant.
- Phoenix added its own Postgres, its own Keycloak client + scope + 3 groups,
  its own namespace (`converse-monitoring`), and its own ingress hostname —
  none of which Tempo+Grafana need.
- The audit flagged the gateway's OTLP endpoint as hardcoded to the Phoenix
  collector name, the PDB template as writing PDBs into the wrong namespace
  from a chart deployed elsewhere, and the secret name `pheonix-otel-key` as
  typo'd. Removal fixed all three for free.

## What changed in this repo

### `charts/core-gateway`

- **`templates/otel.yaml`** — first `OpenTelemetryCollector` renamed from
  `<fullname>-phoenix` to `<fullname>-traces`. Dropped the `PHOENIX_API_KEY`
  env var (and therefore the `pheonix-otel-key` Secret reference) and the
  `otlphttp/phoenix` exporter. The collector now exports traces only to
  `otlp/alloy` (forwarded to Tempo) and `debug`.
- **`templates/gateway-config.yaml`** — `OTEL_EXPORTER_OTLP_ENDPOINT` updated
  from a hardcoded `http://core-gateway-phoenix-collector.converse-gateway:4318`
  to a templated `http://{{ include "core-gateway.fullname" $ }}-traces-collector.{{ .Release.Namespace }}.svc.cluster.local:4318`.
- **`templates/pdb.yaml`** — deleted. Both PDBs in this file targeted Phoenix
  workloads (`phoenix` and `phoenix-postgresql`) in the `converse-monitoring`
  namespace, which is not where this chart is deployed. Cross-namespace writes
  from a tenant chart were an audit-flagged anti-pattern.

### `charts/apps/values.yaml`

- The Phoenix `Application` block (chart
  `oci://registry-1.docker.io/arizephoenix/phoenix-helm`, release `phoenix`,
  ingress `analytics.ai.camer.digital`, destination namespace
  `converse-monitoring`) was deleted in its entirety. Replaced with a comment
  explaining the migration.

### `charts/keycloak-baseline/values.yaml`

- `clientScopes.phoenix` — removed (including its `phoenix_role` protocol mapper)
- `clients.phoenix` — removed (rootUrl `https://analytics.ai.camer.digital`, with
  its three client roles `admin`/`user`/`viewer`)
- `groups.phoenixAdmin`, `phoenixUser`, `phoenixViewer` — removed
- `- phoenix` references in **every other** client's `defaultClientScopes` and
  `optionalClientScopes` lists — stripped from `converse`, `librechat`,
  `selfServiceMcpApi`, `converseFrontend`, `testingClient`, `adorsysGisGithubCi`

### `docs/`

- `observability-dashboards.md` §2.4 Phoenix → §2.4 "LLM tracing (Tempo)"
- `observability-fix-no-data-dashboards.md` — references to "Phoenix collector"
  updated to "traces collector (formerly `*-phoenix`)"
- `keycloak-audience-operations.md` — `phoenix` removed from the client list
  and from the example audience array

## What needs out-of-band cleanup (not in this repo)

These resources exist in the cluster and will become orphaned once this branch
merges. They cannot be removed by ArgoCD reconciliation alone.

| Resource | Namespace | Why orphaned |
|---|---|---|
| `Secret/converse-phoenix-keycloak` | `converse-monitoring` | Held the Phoenix Keycloak client secret. Sourced from `ai-ops-secrets.git`. |
| `Secret/pheonix-otel-key` | `core-gateway` | Phoenix OTLP API key. Typo'd name; no longer referenced. |
| `PVC` for `phoenix-postgresql` | `converse-monitoring` | Phoenix's Postgres data. |
| `Namespace/converse-monitoring` | (cluster-scoped) | Whole namespace was Phoenix-only; safe to delete after the above. |
| Phoenix client + secret entry | `ai-ops-secrets.git` repo | The `converse-phoenix-keycloak` entry there is now dead config. |
| DNS record `analytics.ai.camer.digital` | DNS provider | No longer routes anywhere. |

### Cleanup sequence

```bash
# 1. Confirm ArgoCD shows the phoenix Application as missing (after this PR merges)
argocd app list | grep phoenix          # should return nothing

# 2. Remove the phoenix entry from ai-ops-secrets.git in a separate PR

# 3. Delete the orphaned secrets
kubectl delete secret converse-phoenix-keycloak -n converse-monitoring
kubectl delete secret pheonix-otel-key -n core-gateway     # (or wherever core-gateway is)

# 4. Delete the Postgres PVC (after taking a final snapshot if you want one)
kubectl delete pvc -n converse-monitoring -l app.kubernetes.io/instance=phoenix

# 5. Delete the namespace once empty
kubectl get all,pvc,secret -n converse-monitoring  # should be near-empty
kubectl delete namespace converse-monitoring

# 6. Remove the analytics.ai.camer.digital DNS record at your DNS provider
```

## Where LLM observability lives now

- **Datasource:** Grafana, Tempo datasource (uid `tempo`, URL
  `http://tempo.observability.svc.cluster.local:3100`).
- **Path:** Gateway → `<fullname>-traces` OTel collector → Alloy
  (`alloy.observability.svc:4317`) → Tempo.
- **Dashboards:** TBD — first per-user Envoy AI Gateway dashboard ships as
  part of the dashboards refactor (Grafana Operator + JSON-in-git). See
  `docs/grafana-operator-and-dashboards.md` when that lands.

## Rollback (if absolutely needed)

`git revert` on the phoenix-removal commit restores the chart-side state.
You would then need to:
- Re-create the `converse-phoenix-keycloak` Secret (sourced from
  `ai-ops-secrets.git`) and the `pheonix-otel-key` Secret in `core-gateway`.
- Wait for ArgoCD to reconcile the Phoenix Application and the keycloak realm
  back to a phoenix-aware state.
- Re-add the DNS record.

There is no plan to roll back; this entry exists for completeness.
