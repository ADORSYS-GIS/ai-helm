# Bootstrap Secrets Inventory

This document provides a comprehensive inventory of bootstrap secrets required for GitOps platform bring-up. Bootstrap secrets are created once during platform initialization and enable GitOps operations before external secret stores are fully configured.

## Overview

Bootstrap secrets serve as the foundation for the platform's secret management:

1. **Purpose**: Enable GitOps operations and platform initialization
2. **Lifecycle**: Created once, optionally migrated to ESO management later
3. **Source**: Manual creation or migration from previous deployments
4. **Security**: Stored in Kubernetes secrets, referenced by ExternalSecret resources

## Bootstrap Secret Lifecycle

```mermaid
flowchart TD
    subgraph Init["Platform Initialization"]
        A[Manual Creation] --> B[Bootstrap Secrets<br/>in external-secrets-system]
    end

    subgraph ESO["External Secrets Operator"]
        B --> C[ClusterSecretStore<br/>References Bootstrap Secrets]
        C --> D[ExternalSecret CRDs<br/>in Application Namespaces]
    end

    subgraph Apps["Application Namespaces"]
        D --> E[Kubernetes Secrets<br/>Created/Updated by ESO]
        E --> F[Application Pods<br/>Mount Secrets]
    end

    subgraph Migration["Optional Migration"]
        G[External Secret Store<br/>e.g., AWS Secrets Manager]
        B -.->|Migrate| G
        G --> H[Updated ClusterSecretStore<br/>References External Store]
        H --> D
    end
```

## Secret Categories Overview

```mermaid
mindmap
  root((Bootstrap Secrets))
    GitOps Infrastructure
      argocd-gitops-repo
      argocd-webhook-secret
    Platform Authentication
      lightbridge-opa-auth
      authz-tls
    AI Model API Keys
      OpenAI API Keys
      Gemini API Keys
      Fireworks API Keys
      DeepInfra API Keys
      GCP Service Accounts
    API Keys & Tokens
      Converse API Keys
      Proxy API Keys
      MCP Tool Tokens
    Database Credentials
      PostgreSQL Credentials
      MongoDB Credentials
      Coder DB Credentials
    Backup Credentials
      S3 Backup Credentials
      Keycloak Backup

## Bootstrap Secret Categories

### Category 1: GitOps Infrastructure

Secrets required for ArgoCD to access Git repositories and manage deployments.

| Secret Name | Namespace | Type | Keys | Description |
|-------------|-----------|------|------|-------------|
| `argocd-gitops-repo` | argocd | Opaque | `sshPrivateKey`, `username`, `password` | Git repository access for ArgoCD |
| `argocd-webhook-secret` | argocd | Opaque | `secret` | Webhook secret for Git notifications |

### Category 2: Platform Authentication

Secrets for platform-level authentication and authorization.

| Secret Name | Namespace | Type | Keys | Description |
|-------------|-----------|------|------|-------------|
| `lightbridge-opa-auth` | converse | Opaque | `credentials` | Basic auth for OPA validation |
| `authz-tls` | converse-gateway | Opaque | `ca.crt`, `tls.crt`, `tls.key` | TLS certificates for authorization |

### Category 3: AI Model API Keys

API keys for AI model providers used by the LiteLLM proxy and other AI services.

| Secret Name | Namespace | Type | Keys | Description |
|-------------|-----------|------|------|-------------|
| `openai-api-key` | converse-proxy | Opaque | `apiKey` | OpenAI API key (converse-proxy) |
| `openai-api-key-01` | converse | Opaque | `apiKey` | OpenAI API key |
| `openai-api-key-02` | converse | Opaque | `apiKey` | OpenAI API key (backup) |
| `base-openai-apikey` | converse | Opaque | `apiKey` | Base OpenAI API key |
| `gemini-api-key` | converse-proxy | Opaque | `apiKey` | Google Gemini API key (converse-proxy) |
| `fireworks-api-key-01` | converse-proxy | Opaque | `apiKey` | Fireworks API key (converse-proxy) |
| `fireworks-api-key-01` | converse | Opaque | `apiKey` | Fireworks API key |
| `fireworks-api-key-02` | converse | Opaque | `apiKey` | Fireworks API key (backup) |
| `deepinfra-api-key-only` | converse | Opaque | `key` | DeepInfra API key |
| `gcp-service-account-key-01` | converse | Opaque | `key` | GCP Service Account key |
| `gcp-service-account-key-02` | converse | Opaque | `key` | GCP Service Account key (backup) |
| `google-ai-studio-api-key-01` | converse | Opaque | `key` | Google AI Studio API key |
| `google-ai-studio-api-key-02` | converse | Opaque | `key` | Google AI Studio API key (backup) |

### Category 4: API Keys & Tokens

API keys for external services and MCP tools.

| Secret Name | Namespace | Type | Keys | Description |
|-------------|-----------|------|------|-------------|
| `converse-api-key` | converse-gateway | Opaque | `key` | Converse Gateway API key |
| `converse-api-key-dev` | converse-gateway | Opaque | `key` | Converse Gateway API key (dev) |
| `proxy-api-key` | converse-proxy | Opaque | `key` | Proxy API key |
| `proxy-api-key-01` | converse-proxy | Opaque | `key` | Proxy API key |
| `context7-token` | converse-mcp | Opaque | `token` | Context7 token |
| `brave-token` | converse-mcp | Opaque | `token` | Brave Search token |
| `deepl-token` | converse-mcp | Opaque | `token` | DeepL token |
| `firecrawl-token` | converse-mcp | Opaque | `token` | Firecrawl token |

### Category 5: Platform Authentication

Secrets for platform-level authentication and authorization.

| Secret Name | Namespace | Type | Keys | Description |
|-------------|-----------|------|------|-------------|
| `lightbridge-opa-auth` | converse-gateway | Opaque | `credentials` | OPA validation credentials |
| `authz-tls` | converse-gateway | Opaque | `ca.crt`, `tls.crt`, `tls.key` | TLS certificates for authorization |

### Category 6: Database Credentials

Database connection credentials for platform services.

| Secret Name | Namespace | Type | Keys | Description |
|-------------|-----------|------|------|-------------|
| `lightbridge-main-db-app` | converse | Opaque | 11 keys | Main PostgreSQL credentials |
| `lightbridge-usage-db-app` | converse | Opaque | 11 keys | Usage DB credentials |
| `coder-db-credentials` | coder | Opaque | `username`, `password`, `database` | Coder database credentials |

### Category 7: Backup Credentials

Credentials for backup operations.

| Secret Name | Namespace | Type | Keys | Description |
|-------------|-----------|------|------|-------------|
| `backup-s3-credentials` | backup | Opaque | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | S3 backup credentials |
| `keycloak-backup-credentials` | keycloak | Opaque | `username`, `password` | Keycloak backup credentials |

## Detailed Secret Specifications

### GitOps Infrastructure

#### argocd-gitops-repo

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: argocd-gitops-repo
  namespace: argocd
  labels:
    app.kubernetes.io/part-of: argocd
    platform.ai.camer.digital/type: bootstrap
type: Opaque
stringData:
  # SSH private key for Git repository access (preferred)
  sshPrivateKey: |
    -----BEGIN OPENSSH PRIVATE KEY-----
    ...
    -----END OPENSSH PRIVATE KEY-----
  
  # HTTPS credentials (alternative to SSH)
  username: git-username
  password: ghp_xxxx  # Personal access token
```

**Creation Command:**
```bash
kubectl create secret generic argocd-gitops-repo \
  --from-file=sshPrivateKey=~/.ssh/id_rsa \
  -n argocd
```

#### argocd-webhook-secret

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: argocd-webhook-secret
  namespace: argocd
  labels:
    app.kubernetes.io/part-of: argocd
    platform.ai.camer.digital/type: bootstrap
type: Opaque
stringData:
  secret: <random-webhook-secret>
```

**Creation Command:**
```bash
kubectl create secret generic argocd-webhook-secret \
  --from-literal=secret="$(openssl rand -hex 32)" \
  -n argocd
```

### Platform Authentication

#### lightbridge-opa-auth

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: lightbridge-opa-auth
  namespace: converse
  labels:
    app.kubernetes.io/component: authorization
    platform.ai.camer.digital/type: bootstrap
type: Opaque
stringData:
  credentials: <base64-encoded-basic-auth>
```

**Creation Command:**
```bash
# Generate basic auth credentials
CREDENTIALS=$(echo -n "username:password" | base64)

kubectl create secret generic lightbridge-opa-auth \
  --from-literal=credentials="$CREDENTIALS" \
  -n converse
```

#### authz-tls

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: authz-tls
  namespace: converse-gateway
  labels:
    app.kubernetes.io/component: authorization
    platform.ai.camer.digital/type: bootstrap
type: Opaque
data:
  ca.crt: <base64-encoded-ca-certificate>
  tls.crt: <base64-encoded-tls-certificate>
  tls.key: <base64-encoded-tls-private-key>
```

**Creation Command:**
```bash
# If using cert-manager, this secret is created automatically
# For manual creation:
kubectl create secret generic authz-tls \
  --from-file=ca.crt=./ca.crt \
  --from-file=tls.crt=./tls.crt \
  --from-file=tls.key=./tls.key \
  -n converse-gateway
```

### AI Model API Keys

#### openai-api-key

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: openai-api-key
  namespace: converse
  labels:
    app.kubernetes.io/component: ai-models
    platform.ai.camer.digital/type: bootstrap
    ai.camer.digital/provider: openai
type: Opaque
stringData:
  apiKey: sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

**Creation Command:**
```bash
kubectl create secret generic openai-api-key \
  --from-literal=apiKey="sk-xxxxxxxx" \
  -n converse
```

#### gemini-api-key

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: gemini-api-key
  namespace: converse
  labels:
    app.kubernetes.io/component: ai-models
    platform.ai.camer.digital/type: bootstrap
    ai.camer.digital/provider: gemini
type: Opaque
stringData:
  apiKey: AIzaxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

**Creation Command:**
```bash
kubectl create secret generic gemini-api-key \
  --from-literal=apiKey="AIzaxxxxxxxx" \
  -n converse
```

#### fireworks-api-key-01

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: fireworks-api-key-01
  namespace: converse
  labels:
    app.kubernetes.io/component: ai-models
    platform.ai.camer.digital/type: bootstrap
    ai.camer.digital/provider: fireworks
type: Opaque
stringData:
  apiKey: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

**Creation Command:**
```bash
kubectl create secret generic fireworks-api-key-01 \
  --from-literal=apiKey="xxxxxxxxxxxx" \
  -n converse
```

### Database Credentials

#### librechat-mongodb-uri

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: librechat-mongodb-uri
  namespace: librechat
  labels:
    app.kubernetes.io/component: database
    platform.ai.camer.digital/type: bootstrap
type: Opaque
stringData:
  MONGO_URI: mongodb://username:password@mongodb:27017/librechat?authSource=admin
```

**Creation Command:**
```bash
kubectl create secret generic librechat-mongodb-uri \
  --from-literal=MONGO_URI="mongodb://user:pass@mongodb:27017/librechat" \
  -n librechat
```

#### coder-db-credentials

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: coder-db-credentials
  namespace: coder
  labels:
    app.kubernetes.io/component: database
    platform.ai.camer.digital/type: bootstrap
type: Opaque
stringData:
  username: coder
  password: <secure-password>
  database: coder
```

**Creation Command:**
```bash
kubectl create secret generic coder-db-credentials \
  --from-literal=username="coder" \
  --from-literal=password="$(openssl rand -base64 32)" \
  --from-literal=database="coder" \
  -n coder
```

### Backup Credentials

#### backup-s3-credentials

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: backup-s3-credentials
  namespace: backup
  labels:
    app.kubernetes.io/component: backup
    platform.ai.camer.digital/type: bootstrap
type: Opaque
stringData:
  AWS_ACCESS_KEY_ID: AKIAIOSFODNN7EXAMPLE
  AWS_SECRET_ACCESS_KEY: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
  AWS_REGION: us-east-1
```

**Creation Command:**
```bash
kubectl create secret generic backup-s3-credentials \
  --from-literal=AWS_ACCESS_KEY_ID="AKIAIOSFODNN7EXAMPLE" \
  --from-literal=AWS_SECRET_ACCESS_KEY="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY" \
  --from-literal=AWS_REGION="us-east-1" \
  -n backup
```

## Bootstrap Procedure

### Step 1: Prepare Namespaces

```bash
# Create required namespaces
kubectl create namespace argocd
kubectl create namespace converse
kubectl create namespace converse-gateway
kubectl create namespace librechat
kubectl create namespace backup
kubectl create namespace external-secrets-system
```

### Step 2: Create Bootstrap Secrets

Create a script to generate all bootstrap secrets:

```bash
#!/bin/bash
# bootstrap-secrets.sh

set -e

echo "Creating GitOps infrastructure secrets..."
kubectl create secret generic argocd-gitops-repo \
  --from-file=sshPrivateKey=~/.ssh/id_rsa \
  -n argocd

kubectl create secret generic argocd-webhook-secret \
  --from-literal=secret="$(openssl rand -hex 32)" \
  -n argocd

echo "Creating platform authentication secrets..."
CREDENTIALS=$(echo -n "admin:$(openssl rand -base64 24)" | base64)
kubectl create secret generic lightbridge-opa-auth \
  --from-literal=credentials="$CREDENTIALS" \
  -n converse

echo "Creating AI model API key secrets..."
kubectl create secret generic openai-api-key \
  --from-literal=apiKey="$OPENAI_API_KEY" \
  -n converse

kubectl create secret generic gemini-api-key \
  --from-literal=apiKey="$GEMINI_API_KEY" \
  -n converse

kubectl create secret generic fireworks-api-key-01 \
  --from-literal=apiKey="$FIREWORKS_API_KEY" \
  -n converse

echo "Creating database credential secrets..."
kubectl create secret generic librechat-mongodb-uri \
  --from-literal=MONGO_URI="$MONGO_URI" \
  -n librechat

echo "Creating backup credential secrets..."
kubectl create secret generic backup-s3-credentials \
  --from-literal=AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
  --from-literal=AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
  --from-literal=AWS_REGION="$AWS_REGION" \
  -n backup

echo "Bootstrap secrets created successfully!"
```

### Step 3: Verify Bootstrap Secrets

```bash
# List all bootstrap secrets
kubectl get secrets -A -l platform.ai.camer.digital/type=bootstrap

# Verify secret content (be careful with sensitive data)
kubectl get secret openai-api-key -n converse -o jsonpath='{.data.apiKey}' | base64 -d
```

## Migration to External Secrets Operator

After the platform is operational, migrate bootstrap secrets to External Secrets Operator management:

### Step 1: Store Secrets in External Store

Upload bootstrap secrets to your external secret store (AWS Secrets Manager, Azure Key Vault, etc.):

```bash
# AWS Secrets Manager example
aws secretsmanager create-secret \
  --name ai-platform/openai-api-key \
  --secret-string '{"apiKey":"sk-xxxx"}'

aws secretsmanager create-secret \
  --name ai-platform/gemini-api-key \
  --secret-string '{"apiKey":"AIzaxxxx"}'
```

### Step 2: Create ExternalSecret Resources

Create ExternalSecret resources to manage the secrets:

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: openai-api-key
  namespace: converse
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secrets-manager
    kind: ClusterSecretStore
  target:
    name: openai-api-key
    creationPolicy: Merge  # Merge with existing secret
  data:
    - secretKey: apiKey
      remoteRef:
        key: ai-platform/openai-api-key
        property: apiKey
```

### Step 3: Verify Migration

```bash
# Check ExternalSecret status
kubectl get externalsecret openai-api-key -n converse

# Verify secret is still valid
kubectl describe secret openai-api-key -n converse
```

## Secret Rotation

### Manual Rotation

For bootstrap secrets not yet managed by ESO:

```bash
# Update a secret
kubectl create secret generic openai-api-key \
  --from-literal=apiKey="new-api-key" \
  -n converse \
  --dry-run=client -o yaml | kubectl apply -f -

# Restart affected pods
kubectl rollout restart deployment/litellm -n converse
```

### Automatic Rotation (ESO Managed)

For secrets managed by External Secrets Operator:

1. Update the secret in the external store
2. ESO will automatically sync the new value
3. Configure deployment to watch for secret changes:

```yaml
spec:
  template:
    metadata:
      annotations:
        secret.kubernetes.io/refresh: "true"
```

## Security Checklist

- [ ] All bootstrap secrets use strong, unique values
- [ ] Secrets are created in correct namespaces
- [ ] RBAC permissions are properly configured
- [ ] Secrets are labeled with `platform.ai.camer.digital/type: bootstrap`
- [ ] Sensitive values are not logged or exposed
- [ ] Access to secrets is audited
- [ ] Secret rotation procedure is documented
- [ ] Backup of secret values is secured

## Related Documentation

- [Secret Management Strategy](./README.md)
- [Reference Patterns](./reference-patterns.md)
- [External Secrets Operator](https://external-secrets.io)
