# LibreChat Admin Panel Helm Chart

A Helm chart for deploying the LibreChat Admin Panel using the bjw-s app-template.

## Description

The LibreChat Admin Panel is a standalone browser-based management interface for LibreChat. It connects to the same database as LibreChat and provides a GUI for:

- Configuration management through dynamic schema-driven forms
- Role and group override management
- User and group administration
- Authentication via local accounts or OpenID SSO

## Prerequisites

- LibreChat instance running v0.8.5 or later
- Kubernetes 1.19+
- Helm 3.2.0+
- ArgoCD (optional, for GitOps deployments)

## Installation

### Create Required Secret

First, create a secret for the session encryption key:

```bash
kubectl create secret generic librechat-admin-panel-secret \
  --from-literal=session_secret="$(openssl rand -base64 32)"
```

### Install with Helm

```bash
helm dependency update ./charts/librechat-admin-panel
helm install librechat-admin-panel ./charts/librechat-admin-panel \
  -f ./charts/librechat-admin-panel/values.yaml
```

### ArgoCD Deployment

Add the chart to your ArgoCD application or use it as part of your existing app-of-apps pattern.

## Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `admin-panel.ingress.main.enabled` | Enable ingress | `true` |
| `admin-panel.ingress.main.hosts[0].host` | Ingress hostname | `admin.ai.camer.digital` |
| `admin-panel.controllers.main.containers.main.image.repository` | Container image | `ghcr.io/clickhouse/librechat-admin-panel` |
| `admin-panel.controllers.main.containers.main.image.tag` | Image tag | `latest` |
| `admin-panel.controllers.main.containers.main.env.VITE_API_BASE_URL` | LibreChat API URL (browser-facing) | `https://ai.camer.digital` |
| `admin-panel.controllers.main.containers.main.env.API_SERVER_URL` | LibreChat API URL (server-side) | `http://chart-name-librechat:3080` |
| `admin-panel.controllers.main.replicas` | Number of replicas | `1` |

## Important Notes

- The admin panel requires `SESSION_SECRET` with at least 32 characters
- `VITE_API_BASE_URL` is used by the browser for OAuth redirects
- `API_SERVER_URL` is used server-side to reach LibreChat API (can differ from VITE_API_BASE_URL in K8s)
- The admin panel shares the same MongoDB database as LibreChat
- ArgoCD will watch this chart and auto-deploy changes

## Resources

- [LibreChat Admin Panel GitHub](https://github.com/ClickHouse/librechat-admin-panel)
- [LibreChat Documentation](https://www.librechat.ai/docs/features/admin_panel)
