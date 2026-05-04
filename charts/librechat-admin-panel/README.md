# LibreChat Admin Panel Helm Chart

A Helm chart for deploying the LibreChat Admin Panel using the bjw-s app-template.

## Description

The LibreChat Admin Panel is a standalone browser-based management interface for LibreChat. It connects to the same database as LibreChat and provides a GUI for:

- Configuration management through dynamic schema-driven forms
- Role and group override management
- User and group administration
- Authentication via local accounts or OpenID SSO

## Architecture Overview

### Chart Structure

This chart uses a **dependency-based** architecture rather than defining templates directly. It leverages two Helm dependencies:

```
librechat-admin-panel/
├── Chart.yaml          # Defines dependencies
├── values.yaml         # Configuration values
└── charts/             # Cached dependencies (after helm dependency build)
    ├── common-2.31.4.tgz
    └── app-template-4.6.2.tgz
```

### Dependencies Explained

#### 1. app-template (alias: admin-panel)

**Repository:** https://bjw-s-labs.github.io/helm-charts

The **bjw-s app-template** is a generic Helm chart that generates all standard Kubernetes resources based on configuration. It's maintained by bjw-s (a popular community chart maintainer).

**Why bjw-s app-template?**
- Pre-built templates for Deployment, Service, Ingress, ConfigMaps, PVCs, etc.
- No need to write repetitive Kubernetes manifests
- Well-maintained and widely used in the community
- Supports advanced features like probes, persistence, ingress class, etc.

**What it generates for this chart:**
- **Deployment** (`controllers.main`): A Kubernetes Deployment managing the admin panel pods
- **Service** (`service.main`): A ClusterIP service exposing port 3000
- **Ingress** (`ingress.main`): An Ingress resource for external access via Traefik
- **Pod resources**: Liveness, readiness, and startup probes

#### 2. common (Library Chart)

**Repository:** `file://../common` (local dependency)

The **common** chart is a **library chart** (type: library). Library charts don't create deployed resources themselves - they provide reusable template functions and helper definitions that other charts can use.

**Why include common?**
- Provides helper templates used by app-template (e.g., `common.tpl` functions)
- Contains utility functions for generating names, labels, selectors
- Enables DRY (Don't Repeat Yourself) pattern across Helm charts

**Important:** When a chart is marked as `type: library`, its templates are automatically available to any chart that depends on it. **You do NOT need to use `include` to access these templates** - they're rendered automatically as part of the dependency's templates.

### How Helm Dependencies Work

When you add a dependency in `Chart.yaml`:

```yaml
dependencies:
  - name: app-template
    version: '4.6.2'
    alias: admin-panel
```

Helm automatically:
1. Downloads and caches the dependency chart
2. Renders all templates from the dependency
3. Includes them in the final manifest output

**You do NOT need to manually include or call dependency templates.** The app-template's templates are rendered as if they were part of this chart.

The alias (`admin-panel`) is used as a prefix in `values.yaml` to avoid naming conflicts and provide clarity:

```yaml
admin-panel:           # This is the alias from Chart.yaml
  controllers:
    main:
      ...
```

## Resource Documentation

### Deployment (`controllers.main.type: deployment`)

**Why Deployment?**
- The admin panel is a stateless web application
- Requires managed pods with rolling update strategy
- Single replica is sufficient for this use case (configured via `replicas: 1`)
- Supports easy scaling if needed in the future

**Configuration:**
```yaml
controllers:
  main:
    type: deployment
    strategy: RollingUpdate    # Zero-downtime updates
    replicas: 1                 # Single instance
```

### Service (`service.main`)

**Why ClusterIP?**
- Internal cluster communication only
- Admin panel doesn't need to be exposed externally via NodePort/LoadBalancer
- External access is handled by the Ingress (Traefik)
- Most secure option for internal-only services

**Configuration:**
```yaml
service:
  main:
    enabled: true
    type: ClusterIP           # Internal only, exposed via Ingress
    controller: main          # Links to the deployment
    ports:
      http:
        enabled: true
        port: 3000            # Container port
        targetPort: 3000     # Pod port
```

### Ingress (`ingress.main`)

**Why Ingress with Traefik?**
- Exposes HTTP/HTTPS routes to services
- Handles TLS termination via cert-manager
- Provides path-based routing
- Already configured in the cluster infrastructure

**Configuration:**
```yaml
ingress:
  main:
    enabled: true
    className: traefik        # Use Traefik ingress controller
    annotations:
      cert-manager.io/cluster-issuer: cert-home-cert-http
    hosts:
      - host: admin.127.0.0.1.nip.io
        paths:
          - path: /
            pathType: Prefix
            service:
              identifier: main
              port: http
    tls:
      - secretName: admin.ai.camer.digital-tls
        hosts:
          - admin.127.0.0.1.nip.io
```

### Probes (Liveness, Readiness, Startup)

**Why probes?**
- **Liveness**: Kubernetes restarts container if it's unresponsive (detects hung processes)
- **Readiness**: Traffic only sent to pods that are ready (handles startup time)
- **Startup**: Delays liveness check until application has started (for slow-starting apps)

All three probes point to `/` endpoint (root path) since the admin panel serves its UI there.

### Environment Variables

| Variable | Purpose | Why |
|----------|---------|-----|
| `PUID`/`PGID` | Run as non-root user | Security - avoid running as root |
| `TZ` | Timezone | Consistent logging timestamps |
| `PORT` | Application port | Container listens on 3000 |
| `SESSION_SECRET` | Encryption key for sessions | Required for secure session handling |
| `VITE_API_BASE_URL` | Browser-facing API URL | OAuth redirects, frontend API calls |
| `API_SERVER_URL` | Server-side API URL | Backend communication with LibreChat |
| `ADMIN_SSO_ONLY` | Force SSO login | Security setting |
| `ADMIN_SESSION_IDLE_TIMEOUT_MS` | Session timeout | 30-minute idle timeout |
| `SESSION_COOKIE_SECURE` | Secure cookies | HTTPS-only cookies |

## Session Secret Management

### Current Implementation

The `SESSION_SECRET` is **not generated within the chart**. It must be created externally:

```bash
# Create the secret manually before deployment
kubectl create secret generic librechat-admin-panel-secret \
  --from-literal=session_secret="$(openssl rand -base64 32)"
```

The secret is then referenced in `values.yaml`:

```yaml
env:
  SESSION_SECRET:
    secretKeyRef:
      name: librechat-admin-panel-secret
      key: session_secret
```

### Why No secret.yaml Template?

There is no `templates/secret.yaml` file because:
1. **Security**: Random secrets should not be stored in Git/helm charts
2. **Idempotency**: Helm can't reliably generate random values on each install without causing conflicts on upgrades
3. **External management**: Secrets are typically managed separately (SealedSecrets, External Secrets Operator, etc.)

**Alternative approaches** (not currently implemented):
- Use a post-install hook to generate the secret
- Integrate with External Secrets Operator
- Use Vault for secret management

## Prerequisites

- LibreChat instance running v0.8.5 or later
- Kubernetes 1.19+
- Helm 3.2.0+
- Traefik ingress controller
- cert-manager for TLS

## Installation

### 1. Build Dependencies

```bash
helm dependency build ./charts/librechat-admin-panel
```

### 2. Create Required Secret

```bash
kubectl create secret generic librechat-admin-panel-secret \
  --from-literal=session_secret="$(openssl rand -base64 32)"
```

### 3. Install with Helm

```bash
helm install librechat-admin-panel ./charts/librechat-admin-panel \
  -f ./charts/librechat-admin-panel/values.yaml
```

### Upgrade

```bash
helm upgrade librechat-admin-panel ./charts/librechat-admin-panel \
  -f ./charts/librechat-admin-panel/values.yaml
```

### ArgoCD Deployment

Add the chart to your ArgoCD application or use it as part of your existing app-of-apps pattern.

## Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `global.librechat.version` | LibreChat version | `v0.8.5` |
| `admin-panel.ingress.main.enabled` | Enable ingress | `true` |
| `admin-panel.ingress.main.hosts[0].host` | Ingress hostname | `admin.127.0.0.1.nip.io` |
| `admin-panel.service.main.type` | Service type | `ClusterIP` |
| `admin-panel.controllers.main.type` | Controller type | `deployment` |
| `admin-panel.controllers.main.replicas` | Number of replicas | `1` |
| `admin-panel.controllers.main.containers.main.image.repository` | Container image | `ghcr.io/clickhouse/librechat-admin-panel` |
| `admin-panel.controllers.main.containers.main.image.tag` | Image tag | `latest` |
| `admin-panel.controllers.main.containers.main.image.pullPolicy` | Pull policy | `Always` |
| `admin-panel.controllers.main.containers.main.env.VITE_API_BASE_URL` | Browser API URL | `https://admin.127.0.0.1.nip.io` |
| `admin-panel.controllers.main.containers.main.env.API_SERVER_URL` | Server API URL | `http://librechat-librechat.librechat.svc.cluster.local:3080` |
| `admin-panel.controllers.main.containers.main.resources.limits.cpu` | CPU limit | `500m` |
| `admin-panel.controllers.main.containers.main.resources.limits.memory` | Memory limit | `1Gi` |
| `admin-panel.controllers.main.containers.main.resources.requests.cpu` | CPU request | `250m` |
| `admin-panel.controllers.main.containers.main.resources.requests.memory` | Memory request | `512Mi` |

## Important Notes

- The admin panel requires `SESSION_SECRET` with at least 32 characters
- `VITE_API_BASE_URL` is used by the browser for OAuth redirects
- `API_SERVER_URL` is used server-side to reach LibreChat API (can differ from VITE_API_BASE_URL in K8s)
- The admin panel shares the same MongoDB database as LibreChat
- ArgoCD will watch this chart and auto-deploy changes

## Resources

- [LibreChat Admin Panel GitHub](https://github.com/ClickHouse/librechat-admin-panel)
- [LibreChat Documentation](https://www.librechat.ai/docs/features/admin_panel)
- [bjw-s App Template Documentation](https://bjw-s-labs.github.io/helm-charts/docs/app-template/)
- [bjw-s Common Library Documentation](https://bjw-s-labs.github.io/helm-charts/docs/common-library/)