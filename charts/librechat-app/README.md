# `librechat-app` — leaf

LibreChat application + its MongoDB store, bundled in one Application
because they share lifecycle (LibreChat's runtime state lives in Mongo;
pairing them in one sync means one ArgoCD apply brings up the pair).

**ADR:** [`0014`](../../docs/adr/0014-split-librechart-and-opencode-wellknown.md)
**Orchestrator:** [`librechart`](../librechart/)

## What it renders

Via the bjw-s `app-template@4.6.2` subchart (alias `librechat`):

- `Deployment` (LibreChat, 2 replicas, HPA 1-4, PodDisruptionBudget minAvailable 1)
- `Service` (ClusterIP, port 3080 → 3080)
- `Ingress` (Traefik, `ai-v2.camer.digital`, `/`)
- `ConfigMap` (`librechat-config`) carrying the `librechat.yaml` config
  (mounted at `/app/librechat.yaml`)
- `LimitRange` + `ResourceQuota` for the `converse` namespace
- `HorizontalPodAutoscaler` (CPU 70% / memory 80% targets)
- `NetworkPolicy` (allow-all today — audit-flagged for refinement)

Via the `mongodb@1.7.6` subchart (alias `db`):

- MongoDB `StatefulSet` (1 replica, 30Gi PVC, auth disabled)
- Headless + load-balanced Services

Plus this chart's own templates:

- `_mongo_uri.tpl` — builds `MONGO_URI` from the release name + replica count
- `templates/configmap.yaml` — wraps the `config` block as the
  `librechat-config` ConfigMap
- `templates/pdb.yaml` — PDB for the MongoDB pod (selector uses
  `{{ .Release.Name }}`, audit-fixed from the hardcoded `librechat`)

## Required Secrets (out of scope; managed by ESO via ai-ops-secrets)

| Secret | Keys |
|---|---|
| `librechat-config` | `creds_key`, `creds_iv`, `jwt_secret`, `jwt_refresh_secret` |
| `librechat-openid-config` | `client_id`, `client_secret`, `session_secret` |
| `librechat-meili-config` | `MEILI_MASTER_KEY` (also consumed by `librechat-search`) |
| `librechat-main-config` | `converse_openai_api_key` |
| `librechat-mcp-cd-credentials` | `client_id`, `client_secret` |
| `librechat-mcp-github` | `client_id`, `client_secret` |
| `librechat-mcp-coder-credentials` | `client_id`, `client_secret` |
| `librechat-s3-config` | `s3_region_name`, `s3_access_key_id`, `s3_secret_access_key`, `s3_bucket_name` |
| `librechat-websearch-config` | `serper_api_key`, `firecrawl_api_key`, `jina_api_key` |

## Cross-chart references

- `MEILI_HOST: http://librechat-search:7700` — points at the
  [`librechat-search`](../librechat-search/) sibling. Service name comes
  from the AppSet child's release name (set by the orchestrator).
- `MONGO_URI: <built by _mongo_uri.tpl>` — points at the local Mongo
  in this same Application.

## Verifying

```bash
helm dep build .
helm template librechat-app . -n converse | grep -E "^kind:"
# → 13 K8s resources (Deployment, Service, Ingress, ConfigMap × 2,
#                     PDB × 2, HPA, LimitRange, ResourceQuota,
#                     StatefulSet, Service × 2, NetworkPolicy)
```

## See also

- `librechat.yaml` config (mounted from this chart's ConfigMap) — the
  full schema is in [LibreChat's docs](https://docs.librechat.ai/install/configuration/custom_config.html).
- [ADR-0014](../../docs/adr/0014-split-librechart-and-opencode-wellknown.md)
  for the pairing rationale.
