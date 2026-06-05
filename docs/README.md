# ai-helm documentation

Index of everything under `docs/`. Files are grouped by intent; if you don't
know where a topic lives, grep — file names are stable and descriptive.

> **Convention:** new docs go under one of the sections below. Long-form
> migration write-ups live in `docs/migrations/`. Operational subsystems with
> several files (backups, secrets, model gateway) get their own subdirectory
> with a local `README.md` that indexes the contents.

**Start here:** [`architecture.md`](./architecture.md) for the system map,
[`adr/README.md`](./adr/README.md) for every architectural decision,
[`../CONTRIBUTING.md`](../CONTRIBUTING.md) for how to ship a change.

---

## Architecture & integration

How the system is wired and how to integrate against it.

| File | What it covers |
|---|---|
| [`observability-stack.md`](./observability-stack.md) | Mimir / Loki / Tempo / Alloy / Grafana topology, sync-wave ordering, data flow |
| [`observability-dashboards.md`](./observability-dashboards.md) | Per-subsystem dashboard inventory and instrumentation plan |
| [`observability-storage-retention.md`](./observability-storage-retention.md) | Retention windows, S3 bucket layout, cost trade-offs |
| [`alloy-servicemonitor-guide.md`](./alloy-servicemonitor-guide.md) | How Alloy discovers ServiceMonitors and PodMonitors; clustering gotchas |
| [`grafana-operator-and-dashboards.md`](./grafana-operator-and-dashboards.md) | Grafana Operator install, dashboards-as-code, where dashboard JSON lives |
| [`keycloak-audience-operations.md`](./keycloak-audience-operations.md) | OIDC audience claim management; full-scope-allowed implications |
| [`librechat-oidc-integration.md`](./librechat-oidc-integration.md) | LibreChat ↔ Keycloak OIDC wiring, claim mapping, role propagation |
| [`librechat-oidc-experiments.md`](./librechat-oidc-experiments.md) | Notes from earlier OIDC iterations — kept as historical record |
| [`librechat_headers_tracing_doc.md`](./librechat_headers_tracing_doc.md) | How LibreChat templated headers flow into downstream MCP/Converse calls |
| [`authorino-service-account-bypass.md`](./authorino-service-account-bypass.md) | How service-account tokens skip OPA / external metadata in Authorino |
| [`per-user-observability.md`](./per-user-observability.md) | Per-user attribution: JWT → Authorino headers → Envoy access log → Loki `user_id`/`azp` labels |
| [`opencode-well-known.md`](./opencode-well-known.md) | opencode `.well-known/opencode` flow at `ai-v2.camer.digital`; prerequisites, plugin install, troubleshooting |
| [`architecture.md`](./architecture.md) | System-level map: ArgoCD topology, sync waves, auth flow, observability pipeline, glossary |
| [`arc42.md`](./arc42.md) | Formal arc42 architecture description (12 sections): goals, constraints, context, building blocks, runtime/deployment views, crosscutting concepts, risks, glossary |
| [`architectural-shift-main-to-magical-bohr.md`](./architectural-shift-main-to-magical-bohr.md) | The full `main → claude/magical-bohr-390242` shift: 8 shifts (two-cluster Hetzner topology, LiteLLM removal, JWT authz, LGTM observability, GitOps structure, secrets, scale, dual-plane gateway) |
| [`2026-currency-audit.md`](./2026-currency-audit.md) | Helm chart + Kubernetes API + tooling currency audit, mid-2026 |
| [`2026-hetzner-cutover.md`](./2026-hetzner-cutover.md) | Hetzner cutover change-log (ADR-0018/19/20, domain switch, per-cluster knobs) + live fix-verification status + open items |
| [`2026-self-hosted-gpu-inference.md`](./2026-self-hosted-gpu-inference.md) | Qwen3-4B on the home GPU via KServe + vLLM + LMCache, federated into the gateway as a public-FQDN backend (ADR-0022): VRAM math, manifests, security, runbook |
| [`python-dashboard-generation.md`](./python-dashboard-generation.md) | How dashboards are generated from Python (grafana-foundation-sdk), the drift check, layouts |

## Architecture Decision Records

The **why** behind every meaningful architectural choice. See
[`docs/adr/README.md`](./adr/README.md) for the full index, status legend, and
how to add a new ADR.
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

- `librechat-oidc-experiments.md` — exploratory; consider archiving under `docs/archive/` once the production OIDC setup is stable.
