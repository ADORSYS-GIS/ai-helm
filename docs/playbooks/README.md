# Playbooks

Step-by-step runbooks, setup guides, and break-glass recipes — the docs you open
to **do** something. See the [docs index](../README.md) for the other categories.

| File | When you'd open it |
|---|---|
| [gateway-api-usage.md](gateway-api-usage.md) | You need the actual curl to hit a model through the public gateway — images, chat, vision, embeddings |
| [observability-stack.md](observability-stack.md) | Mimir / Loki / Tempo / Alloy / Grafana topology, sync-wave ordering, data flow |
| [observability-dashboards.md](observability-dashboards.md) | Per-subsystem dashboard inventory and instrumentation plan |
| [observability-storage-retention.md](observability-storage-retention.md) | Retention windows, S3 bucket layout, cost trade-offs |
| [observability-fix-no-data-dashboards.md](observability-fix-no-data-dashboards.md) | Postmortem + fix for empty Grafana dashboards |
| [alloy-servicemonitor-guide.md](alloy-servicemonitor-guide.md) | How Alloy discovers ServiceMonitors/PodMonitors; clustering gotchas |
| [grafana-operator-and-dashboards.md](grafana-operator-and-dashboards.md) | Grafana Operator install, dashboards-as-code |
| [python-dashboard-generation.md](python-dashboard-generation.md) | Generating dashboards from Python (grafana-foundation-sdk); the drift check |
| [gateway-capacity.md](gateway-capacity.md) | Envoy AI Gateway readiness/capacity; HPA right-size; load-test next steps |
| [keycloak-audience-operations.md](keycloak-audience-operations.md) | OIDC audience claim management |
| [keycloak-billing-provisioning-guide.md](keycloak-billing-provisioning-guide.md) | Exporting the billing-plan claim Keycloak → Envoy Gateway |
| [mongodb-restoration-guide.md](mongodb-restoration-guide.md) | Restore a MongoDB backup into the `librechat-db` StatefulSet |
| [service-endpoint-decommission.md](service-endpoint-decommission.md) | Decommission checklist for cluster-internal service endpoints |
| [opencode-sandboxing.md](opencode-sandboxing.md) | Why the opencode permission config is not a sandbox; containment options |
| [cnpg-reconcile-stall.md](cnpg-reconcile-stall.md) | CNPG Managed role password not reconciled after secret change |
| [lakefs-sso.md](lakefs-sso.md) | LakeFS Keycloak SSO via the `lakefs-proxy` session shim (ADR-0090): flow, config, admin-credential runbook, troubleshooting |
| [mlops-app-auth.md](mlops-app-auth.md) | Argo Workflows SSO/RBAC (`code:7` vs `code:5`, the impersonation-token name), the workflow-pod SA + `--auth-mode=client` programmatic path, MLflow OIDC (the plugin's own DB + the `OIDC_AUDIENCE` bearer gate), and reaching LakeFS from a workflow step |
