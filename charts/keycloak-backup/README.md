# Keycloak Configuration Backup & Restore

A Helm chart for automated Keycloak configuration (realms, clients, users) backup and restore operations using the Keycloak Admin API with S3-compatible storage.

## Overview

This Helm chart provides a complete solution for backing up and restoring Keycloak configurations. It uses the Keycloak Admin API to export all realms and their configurations (including clients, roles, users, identity providers, etc.) to JSON format and upload to S3-compatible storage.

### Features

- **Automated Scheduled Backups**: CronJob-based automated backups using Keycloak Admin API
- **Single Realm Backup**: Option to backup only a specific realm
- **Multi-Realm Support**: Automatically discovers and backs up all realms when no specific realm is configured
- **Full Configuration Export**: Exports complete realm configurations including clients, roles, and users
- **On-Demand Restores**: Manual restore jobs triggered via Helm
- **S3-Compatible Storage**: Support for AWS S3, MinIO, and other S3-compatible services
- **RBAC Security**: Proper service accounts and role-based access control
- **Flexible Configuration**: Comprehensive configuration options via values.yaml

## Capabilities

### What Gets Backed Up

When you backup a Keycloak realm, the following configuration is exported:

- Realm settings (theme, security settings, internationalization)
- Identity providers configuration
- Client definitions (OAuth clients, service accounts)
- Client scopes
- Roles (realm roles and client roles)
- Groups
- Users (including attributes, credentials, and group memberships)
- Authentication flows
- Required actions
- User storage providers
- Authorization policies
- Event listeners

### Backup Modes

| Mode | Configuration | Behavior |
| ---- | ------------- | -------- |
| **All Realms** | `keycloak.realm: ""` (default) | Discovers and backs up all realms |
| **Single Realm** | `keycloak.realm: "my-realm"` | Only backs up the specified realm |

## Prerequisites

- Kubernetes 1.19+
- Helm 3.0+
- Keycloak instance running (accessible from the cluster)
- S3-compatible storage (AWS S3, MinIO, etc.)
- kubectl access to your cluster

## Installation

### 1. Create Required Secrets

#### Keycloak Admin Secret

```bash
kubectl create secret generic keycloak-admin \
  -n keycloak \
  --from-literal=username="admin" \
  --from-literal=password="your-admin-password" \
  --from-literal=hostname="keycloak"
```

Required keys:
- `username`: Keycloak admin username
- `password`: Keycloak admin password
- `hostname`: Keycloak service hostname (for cluster-internal access)

#### S3 Credentials Secret

```bash
kubectl create secret generic keycloak-s3 \
  -n keycloak \
  --from-literal=S3_BUCKET_NAME="your-bucket-name" \
  --from-literal=S3_REGION_NAME="us-east-1" \
  --from-literal=S3_ACCESS_KEY_ID="your-access-key" \
  --from-literal=S3_SECRET_ACCESS_KEY="your-secret-key"
```

Required keys:
- `S3_BUCKET_NAME`: S3 bucket name
- `S3_REGION_NAME`: AWS region
- `S3_ACCESS_KEY_ID`: AWS access key ID
- `S3_SECRET_ACCESS_KEY`: AWS secret access key

### 2. Install the Chart

#### Backup All Realms (Default)

```bash
helm install keycloak-backup ./keycloak-backup \
  --namespace keycloak \
  --set keycloak.secretName="keycloak-admin" \
  --set s3.secretName="keycloak-s3"
```

#### Backup a Specific Realm

```bash
helm install keycloak-backup ./keycloak-backup \
  --namespace keycloak \
  --set keycloak.secretName="keycloak-admin" \
  --set s3.secretName="keycloak-s3" \
  --set keycloak.realm="my-realm"
```

#### Custom Schedule

```bash
helm install keycloak-backup ./keycloak-backup \
  --namespace keycloak \
  --set keycloak.secretName="keycloak-admin" \
  --set s3.secretName="keycloak-s3" \
  --set controllers.cronjob.schedule="0 3 * * 0"  # Weekly on Sunday at 3 AM
```

### 3. Verify Installation

```bash
# Check CronJob status
kubectl get cronjob -n keycloak

# View scheduled backup logs
kubectl logs -l app.kubernetes.io/name=keycloak-backup -n keycloak --tail=50
```

## Configuration

### Full Configuration Options

| Parameter | Description | Default |
| --------- | ----------- | ------- |
| `controllers.cronjob.enabled` | Enable scheduled backup CronJob | `true` |
| `controllers.cronjob.schedule` | Cron schedule for backups | `"0 2 * * *"` |
| `controllers.cronjob.concurrencyPolicy` | Concurrency policy (Forbid, Replace, Allow) | `"Forbid"` |
| `controllers.cronjob.successfulJobsHistoryLimit` | Number of successful jobs to keep | `3` |
| `controllers.cronjob.failedJobsHistoryLimit` | Number of failed jobs to keep | `3` |
| `controllers.job.enabled` | Enable restore jobs | `true` |
| `restore.object` | S3 object key to restore (empty = no restore) | `""` |
| `keycloak.secretName` | Secret containing Keycloak admin credentials | `"keycloak-admin"` |
| `keycloak.realm` | Specific realm to backup (empty = all realms) | `""` |
| `keycloak.hostname` | Keycloak hostname for API access | `"keycloak"` |
| `s3.secretName` | Secret containing S3 credentials | `"keycloak-s3"` |
| `s3.prefix` | S3 prefix/path within bucket | `""` |

### values.yaml Example

```yaml
keycloak:
  secretName: "keycloak-admin"
  realm: "my-production-realm"  # Leave empty for all realms
  hostname: "keycloak.keycloak.svc.cluster.local"

s3:
  secretName: "keycloak-s3"
  prefix: "keycloak-backups"

controllers:
  cronjob:
    enabled: true
    schedule: "0 2 * * *"  # Daily at 2 AM
    successfulJobsHistoryLimit: 5
    failedJobsHistoryLimit: 3
```

## Usage

### Scheduled Backups

The CronJob runs automatically according to the configured schedule. Backups are saved to S3 with the naming pattern:

```
{realm}_{timestamp}.json.gz
```

Example: `my-realm_20240115_020000.json.gz`

```bash
# View backup files in S3
aws s3 ls s3://your-bucket-name/keycloak-backups/

# Download a backup
aws s3 cp s3://your-bucket-name/keycloak-backups/my-realm_20240115_020000.json.gz ./
```

### Manual Backup Trigger

```bash
# Create a backup job manually
kubectl create job -n keycloak --from=cronjob/keycloak-backup-backup manual-backup

# View logs
kubectl logs -n keycloak -l job-name=manual-backup --tail=100
```

### Restore from Backup

1. Find the backup file in S3:

```bash
aws s3 ls s3://your-bucket-name/keycloak-backups/
```

2. Trigger the restore:

```bash
helm upgrade keycloak-backup ./keycloak-backup \
  --namespace keycloak \
  --set restore.object="my-realm_20240115_020000.json.gz" \
  --set controllers.cronjob.enabled=false
```

3. Monitor the restore:

```bash
kubectl get job -n keycloak
kubectl logs -l app.kubernetes.io/name=keycloak-backup -n keycloak --tail=100
```

### Restore to Different Realm

To restore a backup to a different realm name, modify the restore script to extract the realm name from the backup file and create a new realm with the desired name.

## Architecture

The chart creates the following Kubernetes resources:

```
keycloak-backup-backup      # CronJob for scheduled backups
keycloak-backup-restore     # Job for on-demand restores (when restore.object is set)
keycloak-backup             # ServiceAccount for RBAC
keycloak-backup             # Role with secret, pod, and batch permissions
keycloak-backup             # RoleBinding
```

### Backup Process Flow

```
1. CronJob triggers at scheduled time
2. Pod starts using quay.io/keycloak/keycloak:24.0 image
3. Waits for Keycloak health endpoint to be ready
4. Authenticates to Keycloak Admin API
5. Fetches realm(s) configuration via GET /admin/realms/{realm}
6. Exports to JSON, compresses with gzip
7. Uploads to S3 bucket
8. Cleans up and exits
```

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
| ----- | ----- | -------- |
| Job fails immediately | Keycloak not accessible | Verify `keycloak.hostname` and network connectivity |
| Authentication fails | Wrong admin credentials | Verify `keycloak.secretName` contains correct credentials |
| S3 upload fails | Missing S3 credentials | Verify `s3.secretName` contains all required keys |
| Backup incomplete | Realm name mismatch | Check `keycloak.realm` value matches exactly |

### Debug Commands

```bash
# Check CronJob status
kubectl get cronjob keycloak-backup-backup -n keycloak

# Check last job status
kubectl get jobs -n keycloak -l app.kubernetes.io/name=keycloak-backup

# View pod logs
kubectl logs -n keycloak -l app.kubernetes.io/name=keycloak-backup --tail=200

# Describe job for errors
kubectl describe job keycloak-backup-restore -n keycloak

# Check secret exists
kubectl get secret keycloak-admin -n keycloak -o yaml
kubectl get secret keycloak-s3 -n keycloak -o yaml
```

### Enable Debug Logging

```bash
# Upgrade with verbose logging
helm upgrade keycloak-backup ./keycloak-backup \
  --namespace keycloak \
  --set controllers.cronjob.enabled=true \
  --debug
```

## Upgrading

### Upgrading the Chart

```bash
# Check current version
helm list -n keycloak

# Upgrade to new version
helm upgrade keycloak-backup ./keycloak-backup \
  --namespace keycloak \
  --reuse-values  # Preserve existing values
```

### Backup Retention

Configure S3 lifecycle policies for backup retention:

```json
{
  "Rules": [
    {
      "ID": "KeycloakBackupRetention",
      "Status": "Enabled",
      "Filter": {
        "Prefix": "keycloak-backups/"
      },
      "ExpirationInDays": 30,
      "NoncurrentVersionExpiration": {
        "NoncurrentDays": 7
      }
    }
  ]
}
```

## Security Considerations

1. **Secret Management**: Use external secret operators (e.g., External Secrets) for production
2. **RBAC**: The ServiceAccount has minimal permissions (read secrets, create jobs/pods)
3. **Network**: Ensure Keycloak is accessible from the namespace where the chart is deployed
4. **S3**: Use IAM roles with minimal S3 permissions (PutObject, GetObject)

## License

MIT License
