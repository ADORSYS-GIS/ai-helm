# External Secrets Configuration Chart

This Helm chart configures External Secrets Operator (ESO) for the AI platform. It provides:

- ClusterSecretStore for bootstrap secrets
- RBAC (ServiceAccount, ClusterRole, ClusterRoleBinding)
- ExternalSecret resources for application secret synchronization

**Note:** This chart does NOT install the ESO operator. The operator is installed separately from the official upstream Helm chart.

## Prerequisites

- External Secrets Operator must be installed (see `charts/apps/values.yaml`)
- Kubernetes cluster with ArgoCD
- **Namespace `external-secrets-system` must be created manually before deploying this chart**

## Installation

This chart is deployed via ArgoCD as part of the apps umbrella chart. See `charts/apps/values.yaml` for the Application configuration.

### Manual Namespace Creation

```bash
kubectl create namespace external-secrets-system
```

## Configuration

### Values

| Parameter | Description | Default |
|-----------|-------------|---------|
| `namespace.name` | Namespace name | `external-secrets-system` |
| `clusterSecretStore.enabled` | Enable ClusterSecretStore | `true` |
| `clusterSecretStore.name` | ClusterSecretStore name | `bootstrap-secrets` |
| `clusterSecretStore.syncWave` | ArgoCD sync wave | `"1"` |
| `serviceAccount.create` | Create ServiceAccount | `true` |
| `serviceAccount.name` | ServiceAccount name | `external-secrets-bootstrap` |
| `serviceAccount.syncWave` | ArgoCD sync wave | `"0"` |
| `rbac.create` | Create RBAC resources | `true` |
| `rbac.clusterRole.name` | ClusterRole name | `external-secrets-bootstrap-reader` |
| `rbac.clusterRoleBinding.name` | ClusterRoleBinding name | `external-secrets-bootstrap-reader` |
| `rbac.clusterRoleBinding.syncWave` | ArgoCD sync wave | `"1"` |
| `externalSecrets` | ExternalSecret definitions | `{}` |

### Adding ExternalSecrets

To add a new ExternalSecret, add it to the `externalSecrets` section in values.yaml:

```yaml
externalSecrets:
  my-api-key:
    namespace: my-app-namespace
    secretName: my-api-key
    refreshInterval: 1h
    data:
      - secretKey: api-key
        remoteRef:
          key: my-api-key
          namespace: external-secrets-system
          property: api-key
```

## Bootstrap Secrets

Bootstrap secrets must be manually created before deploying this chart:

```bash
kubectl create namespace external-secrets-system

kubectl create secret generic my-api-key \
  --namespace=external-secrets-system \
  --from-literal=api-key=your-api-key
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    External Secrets Operator                     │
│  (Installed via ArgoCD from official upstream Helm chart)       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ClusterSecretStore                            │
│  (This chart - provides access to bootstrap secrets)            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ExternalSecret CRDs                           │
│  (This chart - synchronizes secrets to app namespaces)          │
└─────────────────────────────────────────────────────────────────┘
```

## Related Documentation

- [Secret Management Documentation](../../docs/secret-management/README.md)
- [Bootstrap Secrets Inventory](../../docs/secret-management/bootstrap-secrets-inventory.md)
- [Reference Patterns](../../docs/secret-management/reference-patterns.md)