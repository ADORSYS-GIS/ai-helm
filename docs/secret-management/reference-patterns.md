# Secret Synchronization Reference Patterns

This document provides reference patterns for application teams to synchronize secrets using External Secrets Operator. These patterns serve as templates that can be customized for specific use cases.

## Quick Start

### Prerequisites

1. External Secrets Operator is installed in the cluster
2. A ClusterSecretStore is configured (e.g., `aws-secrets-manager`, `azure-key-vault`)
3. Your namespace has permissions to access the secret store

### Basic Pattern

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: my-secret
  namespace: my-app
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secrets-manager  # Reference to ClusterSecretStore
    kind: ClusterSecretStore
  target:
    name: my-secret  # Name of the Kubernetes secret to create
    creationPolicy: Owner
  data:
    - secretKey: apiKey  # Key in the Kubernetes secret
      remoteRef:
        key: my-app/api-key  # Path in the secret store
        property: apiKey  # Property within the secret
```

## Pattern Catalog

### Pattern 1: Simple API Key

**Use Case:** Single API key or token for external service authentication.

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: api-key
  namespace: my-app
  labels:
    app.kubernetes.io/name: my-app
    app.kubernetes.io/component: secrets
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secrets-manager
    kind: ClusterSecretStore
  target:
    name: api-key
    creationPolicy: Owner
    template:
      type: Opaque
      metadata:
        labels:
          app.kubernetes.io/managed-by: external-secrets
  data:
    - secretKey: apiKey
      remoteRef:
        key: my-app/api-credentials
        property: apiKey
```

**Usage in Deployment:**
```yaml
env:
  - name: API_KEY
    valueFrom:
      secretKeyRef:
        name: api-key
        key: apiKey
```

---

### Pattern 2: Database Credentials

**Use Case:** Database connection credentials with multiple fields.

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: database-credentials
  namespace: my-app
  labels:
    app.kubernetes.io/name: my-app
    app.kubernetes.io/component: database
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secrets-manager
    kind: ClusterSecretStore
  target:
    name: database-credentials
    creationPolicy: Owner
    template:
      type: Opaque
      metadata:
        labels:
          app.kubernetes.io/managed-by: external-secrets
      data:
        # Individual fields
        host: "{{ .host }}"
        port: "{{ .port }}"
        username: "{{ .username }}"
        password: "{{ .password }}"
        database: "{{ .database }}"
        # Pre-built connection string
        connectionString: "postgresql://{{ .username }}:{{ .password }}@{{ .host }}:{{ .port }}/{{ .database }}"
  data:
    - secretKey: host
      remoteRef:
        key: my-app/database
        property: host
    - secretKey: port
      remoteRef:
        key: my-app/database
        property: port
    - secretKey: username
      remoteRef:
        key: my-app/database
        property: username
    - secretKey: password
      remoteRef:
        key: my-app/database
        property: password
    - secretKey: database
      remoteRef:
        key: my-app/database
        property: database
```

**Usage in Deployment:**
```yaml
env:
  - name: DB_HOST
    valueFrom:
      secretKeyRef:
        name: database-credentials
        key: host
  - name: DB_PORT
    valueFrom:
      secretKeyRef:
        name: database-credentials
        key: port
  - name: DB_USER
    valueFrom:
      secretKeyRef:
        name: database-credentials
        key: username
  - name: DB_PASSWORD
    valueFrom:
      secretKeyRef:
        name: database-credentials
        key: password
  - name: DATABASE_URL
    valueFrom:
      secretKeyRef:
        name: database-credentials
        key: connectionString
```

---

### Pattern 3: TLS Certificates

**Use Case:** TLS certificates for HTTPS endpoints.

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: tls-certificates
  namespace: my-app
  labels:
    app.kubernetes.io/name: my-app
    app.kubernetes.io/component: tls
spec:
  refreshInterval: 24h  # Longer refresh for certificates
  secretStoreRef:
    name: aws-secrets-manager
    kind: ClusterSecretStore
  target:
    name: tls-certificates
    creationPolicy: Owner
    template:
      type: kubernetes.io/tls  # Standard TLS secret type
      metadata:
        labels:
          app.kubernetes.io/managed-by: external-secrets
      data:
        tls.crt: "{{ .certificate }}"
        tls.key: "{{ .privateKey }}"
        ca.crt: "{{ .caCertificate }}"
  data:
    - secretKey: certificate
      remoteRef:
        key: my-app/tls-certificates
        property: certificate
    - secretKey: privateKey
      remoteRef:
        key: my-app/tls-certificates
        property: privateKey
    - secretKey: caCertificate
      remoteRef:
        key: my-app/tls-certificates
        property: caCertificate
```

**Usage in Ingress:**
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-app
  namespace: my-app
spec:
  tls:
    - hosts:
        - my-app.example.com
      secretName: tls-certificates
  rules:
    - host: my-app.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: my-app
                port:
                  number: 80
```

---

### Pattern 4: Configuration File

**Use Case:** Entire configuration file stored as a secret.

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: app-config
  namespace: my-app
  labels:
    app.kubernetes.io/name: my-app
    app.kubernetes.io/component: config
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secrets-manager
    kind: ClusterSecretStore
  target:
    name: app-config
    creationPolicy: Owner
    template:
      type: Opaque
      metadata:
        labels:
          app.kubernetes.io/managed-by: external-secrets
      data:
        config.yaml: |
          server:
            host: {{ .serverHost }}
            port: {{ .serverPort }}
          database:
            host: {{ .dbHost }}
            port: {{ .dbPort }}
            name: {{ .dbName }}
          api:
            openai_key: {{ .openaiKey }}
            gemini_key: {{ .geminiKey }}
  data:
    - secretKey: serverHost
      remoteRef:
        key: my-app/config
        property: serverHost
    - secretKey: serverPort
      remoteRef:
        key: my-app/config
        property: serverPort
    - secretKey: dbHost
      remoteRef:
        key: my-app/database
        property: host
    - secretKey: dbPort
      remoteRef:
        key: my-app/database
        property: port
    - secretKey: dbName
      remoteRef:
        key: my-app/database
        property: database
    - secretKey: openaiKey
      remoteRef:
        key: ai-platform/openai-api-key
        property: apiKey
    - secretKey: geminiKey
      remoteRef:
        key: ai-platform/gemini-api-key
        property: apiKey
```

**Usage in Deployment:**
```yaml
volumes:
  - name: config
    secret:
      secretName: app-config
volumeMounts:
  - name: config
    mountPath: /etc/app/config.yaml
    subPath: config.yaml
```

---

### Pattern 5: Multi-Source Secret

**Use Case:** Combine data from multiple secret sources into one secret.

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: combined-secrets
  namespace: my-app
  labels:
    app.kubernetes.io/name: my-app
    app.kubernetes.io/component: secrets
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secrets-manager
    kind: ClusterSecretStore
  target:
    name: combined-secrets
    creationPolicy: Owner
    template:
      type: Opaque
      metadata:
        labels:
          app.kubernetes.io/managed-by: external-secrets
  # Use dataFrom to extract all properties from multiple secrets
  dataFrom:
    - extract:
        key: my-app/database
    - extract:
        key: my-app/api-keys
```

---

### Pattern 6: Docker Registry Credentials

**Use Case:** Private container registry authentication.

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: docker-credentials
  namespace: my-app
  labels:
    app.kubernetes.io/name: my-app
    app.kubernetes.io/component: registry
spec:
  refreshInterval: 24h
  secretStoreRef:
    name: aws-secrets-manager
    kind: ClusterSecretStore
  target:
    name: docker-credentials
    creationPolicy: Owner
    template:
      type: kubernetes.io/dockerconfigjson  # Docker config secret type
      metadata:
        labels:
          app.kubernetes.io/managed-by: external-secrets
      data:
        .dockerconfigjson: |
          {
            "auths": {
              "registry.example.com": {
                "username": "{{ .username }}",
                "password": "{{ .password }}",
                "email": "{{ .email }}",
                "auth": "{{ .auth }}"
              }
            }
          }
  data:
    - secretKey: username
      remoteRef:
        key: my-app/docker-registry
        property: username
    - secretKey: password
      remoteRef:
        key: my-app/docker-registry
        property: password
    - secretKey: email
      remoteRef:
        key: my-app/docker-registry
        property: email
    - secretKey: auth
      remoteRef:
        key: my-app/docker-registry
        property: auth
```

**Usage in Service Account:**
```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: my-app
  namespace: my-app
imagePullSecrets:
  - name: docker-credentials
```

---

### Pattern 7: SSH Key Pair

**Use Case:** SSH private key for Git repository access.

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: ssh-key
  namespace: my-app
  labels:
    app.kubernetes.io/name: my-app
    app.kubernetes.io/component: git
spec:
  refreshInterval: 24h
  secretStoreRef:
    name: aws-secrets-manager
    kind: ClusterSecretStore
  target:
    name: ssh-key
    creationPolicy: Owner
    template:
      type: Opaque
      metadata:
        labels:
          app.kubernetes.io/managed-by: external-secrets
      data:
        id_rsa: |
          {{ .privateKey | toString }}
        known_hosts: |
          github.com ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQC...
  data:
    - secretKey: privateKey
      remoteRef:
        key: my-app/ssh-key
        property: privateKey
```

**Usage in Deployment:**
```yaml
volumes:
  - name: ssh-key
    secret:
      secretName: ssh-key
      defaultMode: 0600  # SSH keys require restricted permissions
volumeMounts:
  - name: ssh-key
    mountPath: /home/app/.ssh
    readOnly: true
```

---

### Pattern 8: OAuth Credentials

**Use Case:** OAuth client ID and secret for authentication.

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: oauth-credentials
  namespace: my-app
  labels:
    app.kubernetes.io/name: my-app
    app.kubernetes.io/component: auth
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secrets-manager
    kind: ClusterSecretStore
  target:
    name: oauth-credentials
    creationPolicy: Owner
    template:
      type: Opaque
      metadata:
        labels:
          app.kubernetes.io/managed-by: external-secrets
      data:
        client-id: "{{ .clientId }}"
        client-secret: "{{ .clientSecret }}"
        # Pre-built OAuth URL
        oauth-url: "https://oauth.example.com?client_id={{ .clientId }}&client_secret={{ .clientSecret }}"
  data:
    - secretKey: clientId
      remoteRef:
        key: my-app/oauth
        property: clientId
    - secretKey: clientSecret
      remoteRef:
        key: my-app/oauth
        property: clientSecret
```

---

### Pattern 9: Service-to-Service Authentication

**Use Case:** Shared secret for service-to-service authentication.

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: service-auth
  namespace: my-app
  labels:
    app.kubernetes.io/name: my-app
    app.kubernetes.io/component: auth
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secrets-manager
    kind: ClusterSecretStore
  target:
    name: service-auth
    creationPolicy: Owner
    template:
      type: Opaque
      metadata:
        labels:
          app.kubernetes.io/managed-by: external-secrets
      data:
        # Basic auth
        username: "{{ .username }}"
        password: "{{ .password }}"
        # Pre-encoded basic auth header
        auth-header: "Basic {{ .credentials | toString | b64enc }}"
  data:
    - secretKey: username
      remoteRef:
        key: shared/service-auth
        property: username
    - secretKey: password
      remoteRef:
        key: shared/service-auth
        property: password
    - secretKey: credentials
      remoteRef:
        key: shared/service-auth
        property: credentials
```

---

### Pattern 10: Environment Variables File

**Use Case:** Multiple environment variables from a single secret.

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: env-vars
  namespace: my-app
  labels:
    app.kubernetes.io/name: my-app
    app.kubernetes.io/component: config
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secrets-manager
    kind: ClusterSecretStore
  target:
    name: env-vars
    creationPolicy: Owner
    template:
      type: Opaque
      metadata:
        labels:
          app.kubernetes.io/managed-by: external-secrets
      data:
        # Generate .env file format
        .env: |
          {{- range $key, $value := . }}
          {{ $key }}={{ $value }}
          {{- end }}
  dataFrom:
    - extract:
        key: my-app/environment
```

**Usage in Deployment:**
```yaml
volumes:
  - name: env-file
    secret:
      secretName: env-vars
volumeMounts:
  - name: env-file
    mountPath: /etc/app/.env
    subPath: .env
```

## Advanced Patterns

### Template Functions

External Secrets supports Go template functions for data transformation:

```yaml
spec:
  target:
    template:
      data:
        # Base64 encoding
        encoded-value: "{{ .value | b64enc }}"
        
        # Lowercase
        lowercase: "{{ .value | lower }}"
        
        # String replacement
        replaced: "{{ .value | replace \"old\" \"new\" }}"
        
        # JSON parsing
        parsed: "{{ .jsonValue | fromJson | toJson }}"
        
        # Date formatting
        timestamp: "{{ now | date \"2006-01-02\" }}"
```

### Conditional Logic

```yaml
spec:
  target:
    template:
      data:
        config.yaml: |
          {{- if .production }}
          log_level: warn
          {{- else }}
          log_level: debug
          {{- end }}
```

### Data Transformation

```yaml
spec:
  target:
    template:
      data:
        # Combine multiple values
        connection-string: "postgres://{{ .user }}:{{ .password }}@{{ .host }}:{{ .port }}/{{ .database }}"
        
        # JSON structure
        config.json: |
          {
            "database": {
              "host": "{{ .dbHost }}",
              "port": {{ .dbPort }}
            },
            "api": {
              "key": "{{ .apiKey }}"
            }
          }
```

## Best Practices

### 1. Naming Conventions

| Resource | Convention | Example |
|----------|------------|---------|
| ExternalSecret | Match target secret name | `api-key` |
| Target Secret | Lowercase with hyphens | `api-key` |
| Remote Key | Hierarchical path | `my-app/api/key` |

### 2. Labels and Annotations

```yaml
metadata:
  labels:
    app.kubernetes.io/name: my-app
    app.kubernetes.io/component: secrets
    app.kubernetes.io/managed-by: external-secrets
  annotations:
    external-secrets.io/refresh-interval: "1h"
```

### 3. Refresh Intervals

| Secret Type | Recommended Interval |
|-------------|---------------------|
| API Keys | 1 hour |
| Database Credentials | 1 hour |
| TLS Certificates | 24 hours |
| Configuration | 1 hour |
| SSH Keys | 24 hours |

### 4. Security Considerations

- Use `creationPolicy: Owner` for ESO-managed secrets
- Set appropriate RBAC permissions
- Enable audit logging
- Never commit ExternalSecrets with hardcoded values

### 5. Monitoring

```yaml
# Prometheus metrics are available
# Monitor ExternalSecret status:
kubectl get externalsecrets -A

# Check for sync errors:
kubectl describe externalsecret <name> -n <namespace>
```

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Secret not created | Missing permissions | Check RBAC and IAM |
| Sync failed | Wrong remote key | Verify `remoteRef.key` |
| Template error | Invalid syntax | Check Go template syntax |
| Secret not updated | Low refresh interval | Increase `refreshInterval` |

### Debug Commands

```bash
# Check ExternalSecret status
kubectl get externalsecret <name> -n <namespace> -o yaml

# View sync events
kubectl describe externalsecret <name> -n <namespace>

# Check ClusterSecretStore
kubectl get clustersecretstore <name> -o yaml

# View operator logs
kubectl logs -n external-secrets-system -l app.kubernetes.io/name=external-secrets
```

## Related Documentation

- [Secret Management Strategy](./README.md)
- [Bootstrap Secrets Inventory](./bootstrap-secrets-inventory.md)
- [External Secrets Operator Docs](https://external-secrets.io)
- [Template Functions](https://external-secrets.io/latest/guides/templating/)
