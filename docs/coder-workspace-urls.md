# Enabling Public Workspace URLs in Coder

**Date:** 2026-07-31  
**Status:** Implementation guide

## Overview

Coder workspaces now support public wildcard subdomain URLs (e.g., `my-workspace.coder-ai.camer.digital`), enabled by the DNS-01 ACME wildcard certificate challenge.

## Required changes in `ai-helm-values`

The production values and cert overlays live in the private `adorsys-gis/ai-helm-values` repository. Apply the following changes there:

### 1. Update `environments/prod/values/coder-app.yaml`

Add/update these environment variables in the `coder.env` section:

```yaml
coder:
  env:
    # Wildcard workspace access — workspace agents and workspace ports reach
    # workspaces via wildcard subdomains.
    - name: CODER_WILDCARD_ACCESS_URL
      value: "*.coder-ai.camer.digital"

    # Path-based workspace apps disabled.
    # Workspaces are accessible only via wildcard subdomains.
    - name: CODER_DISABLE_PATH_APPS
      value: "true"
```

Update the ingress configuration:

```yaml
coder:
  ingress:
    host: "coder.ai.camer.digital"
    wildcardHost: "*.coder-ai.camer.digital"
    tls:
      enable: true
      secretName: coder-tls
      wildcardSecretName: coder-wildcard-tls
```

### 2. Create/update `environments/prod/deps/coder/certificate-wildcard.yaml`

Add a Certificate CR for the wildcard domain (in the `environments/prod/deps/coder/` kustomize overlay):

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: coder-wildcard-tls
  namespace: coder
spec:
  secretName: coder-wildcard-tls
  dnsNames:
    - "*.coder-ai.camer.digital"
  issuerRef:
    name: cert-cloudflare
    kind: ClusterIssuer
```

### 3. Update `environments/prod/deps/coder/kustomization.yaml`

Ensure the wildcard certificate is included in the kustomization resources:

```yaml
resources:
  - certificate.yaml          # Main coder.ai.camer.digital cert
  - certificate-wildcard.yaml # New: *.coder-ai.camer.digital wildcard cert
  - allow-same-namespace.yaml  # CiliumNetworkPolicy if needed
```

## Verification

After deploying the changes:

1. **Verify wildcard cert is issued:**
   ```bash
   kubectl -n coder get certificate coder-wildcard-tls
   kubectl -n coder get secret coder-wildcard-tls
   ```

2. **Test workspace access:**
   - Create a test workspace in Coder
   - Access it via the wildcard subdomain URL (check Coder UI for the assigned URL)
   - Verify the certificate is valid in the browser

3. **Check Coder logs:**
   ```bash
   kubectl -n coder logs -l app.kubernetes.io/name=coder
   ```
   Look for confirmation that `CODER_WILDCARD_ACCESS_URL` is configured.

## Rollback (if needed)

To revert to path-based workspace apps:

1. Remove `CODER_WILDCARD_ACCESS_URL` and `CODER_DISABLE_PATH_APPS` from `coder-app.yaml`
2. Remove `wildcardHost` and `wildcardSecretName` from the ingress config
3. Remove the wildcard certificate resource from the depsOverlay

## References

- ADR-0083: Coder re-introduction
- [Upstream Coder docs: Workspace access URLs](https://coder.com/docs/v2/latest/admin/workspace-management#workspace-access-urls)
