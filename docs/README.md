# ai-helm documentation

Index of everything under `docs/`. Files are grouped by intent; if you don't
know where a topic lives, grep — file names are stable and descriptive.

> **Convention:** new docs go under one of the sections below. Long-form
> migration write-ups live in `docs/migrations/`. Operational subsystems with
> several files (backups, secrets, model gateway) get their own subdirectory
> with a local `README.md` that indexes the contents.

---

## Architecture & integration

How the system is wired and how to integrate against it.

| File | What it covers |
|---|---|
| [`observability-stack.md`](./observability-stack.md) | Mimir / Loki / Tempo / Alloy / Grafana topology, sync-wave ordering, data flow |
| [`observability-dashboards.md`](./observability-dashboards.md) | Per-subsystem dashboard inventory and instrumentation plan |
| [`observability-storage-retention.md`](./observability-storage-retention.md) | Retention windows, S3 bucket layout, cost trade-offs |
| [`alloy-servicemonitor-guide.md`](./alloy-servicemonitor-guide.md) | How Alloy discovers ServiceMonitors and PodMonitors; clustering gotchas |
| [`keycloak-audience-operations.md`](./keycloak-audience-operations.md) | OIDC audience claim management; full-scope-allowed implications |
| [`librechat-oidc-integration.md`](./librechat-oidc-integration.md) | LibreChat ↔ Keycloak OIDC wiring, claim mapping, role propagation |
| [`librechat-oidc-experiments.md`](./librechat-oidc-experiments.md) | Notes from earlier OIDC iterations — kept as historical record |
| [`librechat_headers_tracing_doc.md`](./librechat_headers_tracing_doc.md) | How LibreChat templated headers flow into downstream MCP/Converse calls |
| [`bifrost_comprehensive_report.md`](./bifrost_comprehensive_report.md) | Bifrost gateway evaluation report |
| [`service-endpoint-decommission.md`](./service-endpoint-decommission.md) | Decommission checklist for cluster-internal service endpoints |
| [`models-chart-docs/`](./models-chart-docs/) | `ai-models` chart deep-dive: cost tracking, rate-limit investigation, secret schema |

## Runbooks & operations

Step-by-step recipes for recurring or break-glass operations.

| File | When you'd open it |
|---|---|
| [`cnpg-native-backup/`](./cnpg-native-backup/) | CNPG `BarmanObjectStore` setup; `lightbridge-db` restore runbook + restore YAMLs |
| [`mongodb-restoration-guide.md`](./mongodb-restoration-guide.md) | Restore a MongoDB backup into the `librechat-db` StatefulSet |
| [`observability-fix-no-data-dashboards.md`](./observability-fix-no-data-dashboards.md) | Postmortem + fix for empty Grafana dashboards (Alloy clustering, OTLP fan-out) |
| [`gemini-patch-removal-guide.md`](./gemini-patch-removal-guide.md) | How to retire the LiteLLM gemini-patch ConfigMap once upstream catches up |
| [`secret-management/`](./secret-management/) | Bootstrap secret inventory, ExternalSecret reference patterns |

## Migrations

Permanent record of meaningful one-way changes (deletions, replatforms).

| File | What changed |
|---|---|
| [`migrations/phoenix-to-tempo.md`](./migrations/phoenix-to-tempo.md) | Arize Phoenix removed; LLM tracing now served by Grafana Tempo |

> When you make a one-way change (delete an app, swap a backing store, rename a
> public-facing host), add a file here. Future-you will not remember why.

## Repo-root patterns

Pattern docs that live at the repo root because they describe the repo itself,
not a subsystem. Linked here for discoverability.

- [`../SYNC_WAVE_PATTERN.md`](../SYNC_WAVE_PATTERN.md) — ArgoCD sync-wave ordering for the monitoring stack
- [`../MONITORING_FIX.md`](../MONITORING_FIX.md) — Postmortem for the `monitoring-quota` ownership race

> **Drift note:** the audit recommends moving both of these under `docs/`. They
> stay at root for now to preserve their git history; consider a future move
> with `git mv`.

## Stale / cleanup candidates

- `redirect_308_explained.md.resolved` — bogus extension, content is real. Rename to `.md`.
- `librechat-oidc-experiments.md` — exploratory; consider archiving under `docs/archive/` once the production OIDC setup is stable.
