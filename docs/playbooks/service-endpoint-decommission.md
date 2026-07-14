# `services.api.ai.camer.digital` Endpoint Decommission

## Summary

The internal `services.api.ai.camer.digital` endpoint has been decommissioned. Internal services (LibreChat) now communicate with the AI Gateway via HTTP directly through the Envoy proxy's Kubernetes service DNS.

## Rationale

LibreChat runs inside the cluster but was routing traffic through an external-facing HTTPS endpoint (`services.api.ai.camer.digital` → DNS → LoadBalancer → back into the cluster). This was an unnecessary round-trip. Internal cluster traffic should use `.svc.` DNS.

## Changes

| Component | Before | After |
|-----------|--------|-------|
| LibreChat RAG API URL | `https://services.api.ai.camer.digital/v1` | `http://envoy-...svc.cluster.local/v1` |
| LibreChat Converse URL | `https://services.api.ai.camer.digital/v1` | `http://envoy-...svc.cluster.local/v1` |
| Gateway `service-https` listener | Present (hostname: `services.api.ai.camer.digital`) | Removed |
| Gateway `http` listener | `allowedRoutes.from: Same` | `allowedRoutes.from: All` |
| HTTP-to-HTTPS redirect route | Present | Removed |
| `services` AuthConfig (API key auth) | Present | Removed |
| `CONVERSE_OPENAI_API_KEY` env var | Present | Removed |
| `converse-api-key` / `converse-api-key-dev` secrets | Present | Deleted from cluster |
| SecurityPolicy target | `api-https` + `service-https` | `api-https` only |

## Migration Steps

### 1. Code Changes (already done in this PR)

Files modified:

- `charts/librechart/values.yaml` — internal URLs, removed orphaned API key reference
- `charts/apps/values.yaml` — removed `serviceApiHostname`, removed `services` AuthConfig
- `charts/core-gateway/values.yaml` — removed `serviceApiHostname`
- `charts/core-gateway/templates/gateway.yaml` — removed `service-https` listener, changed HTTP listener to `from: All`
- `charts/core-gateway/templates/http-to-https-route.yaml` — deleted
- `charts/kuadrant-policies/templates/securitypolicy.yaml` — removed `service-https` target

### 2. Deploy (via ArgoCD)

Sync in order:

1. `security-policies` — removes `kuadrant-policies-services` AuthConfig, updates SecurityPolicy
2. `core-gateway` — removes `service-https` listener, removes redirect, updates HTTP listener
3. `librechat` — updates internal URLs, removes env var

### 3. Verify

```bash
# No service-https listener
kubectl get gateway -n converse-gateway core-gateway \
  -o jsonpath='{.spec.listeners[*].name}'
# Expected: http api-https

# Old endpoint fails
curl -k https://services.api.ai.camer.digital/v1
# Expected: DNS failure or connection refused

# New internal route works (from within cluster)
curl http://envoy-converse-gateway-core-gateway-c480b207.envoy-gateway-system.svc.cluster.local/v1
# Expected: 200 or 404 (not 301 redirect)

# Public endpoint still works
curl https://api.ai.camer.digital/v1
# Expected: 200
```

### 4. Cleanup (after deployment confirmed)

- Remove `services.api.ai.camer.digital` DNS record
- Confirm `core-gateway-service-tls` certificate is auto-deleted (cert-manager prunes it when the listener is removed)

## Rollback

To revert, restore the old values and sync ArgoCD in reverse order:
1. Sync `librechat` with old `services.api.ai.camer.digital` URLs
2. Restore `service-https` listener, `http-to-https-route.yaml`, and `serviceApiHostname` in core-gateway
3. Restore `services` AuthConfig and `service-https` SecurityPolicy target in security-policies
