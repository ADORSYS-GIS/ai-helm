# Keycloak Backup Chart

A Helm chart for automated Keycloak configuration backup using `kc.sh export` with S3-compatible storage.

## Overview

This Helm chart provides a complete solution for backing up Keycloak configurations. It uses:
- **Init Container** (Keycloak image): Exports realm configuration via `kc.sh export`
- **Main Container** (AWS CLI): Uploads the backup to S3

### Features

- **Automated Scheduled Backups**: CronJob-based automated backups
- **Init Container Pattern**: Keycloak container handles export, AWS CLI handles upload
- **Multi-Realm Support**: Backup specific realm or all realms
- **kc.sh Export**: Uses Keycloak's native export command for full configuration
- **S3-Compatible Storage**: Support for AWS S3, MinIO, and other S3-compatible services

## Installation

### 1. Create Required Secrets

```bash
# Keycloak Admin Secret
kubectl create secret generic keycloak-admin \
  -n keycloak \
  --from-literal=username=admin \
  --from-literal=password=your-password \
  --from-literal=hostname=keycloak

# S3 Credentials Secret
kubectl create secret generic keycloak-s3 \
  -n keycloak \
  --from-literal=S3_BUCKET_NAME=your-bucket \
  --from-literal=S3_REGION_NAME=us-east-1 \
  --from-literal=S3_ACCESS_KEY_ID=your-access-key \
  --from-literal=S3_SECRET_ACCESS_KEY=your-secret-key
```

### 2. Install the Chart

```bash
# Backup all realms
helm install keycloak-backup ./keycloak-backup -n keycloak

# Backup specific realm
helm install keycloak-backup ./keycloak-backup \
  -n keycloak \
  --set keycloak.realm=my-realm

# Custom schedule (every minute for testing)
helm install keycloak-backup ./keycloak-backup \
  -n keycloak \
  --set controllers.cronjob.schedule="* * * * *"
```

## Architecture

The backup job uses a multi-container architecture:

```
Job Pod
├── initContainer: exporter (quay.io/keycloak/keycloak:24.0)
│   └── Runs kc.sh export with KC_CACHE_DIR for writable cache
│   └── Writes realm_backup.json to shared emptyDir volume
│
└── container: uploader (amazon/aws-cli:2.15.0)
    └── Waits for export file
    └── Uploads to S3
```

## Configuration

| Parameter | Description | Default |
| --------- | ----------- | ------- |
| `keycloak.secretName` | Secret with admin credentials | `keycloak-admin` |
| `keycloak.realm` | Realm to backup (empty = all) | `""` |
| `keycloak.hostname` | Keycloak service name | `keycloak` |
| `s3.secretName` | S3 credentials secret | `keycloak-s3` |
| `s3.prefix` | S3 prefix path | `""` |
| `controllers.cronjob.schedule` | Cron schedule | `0 2 * * *` |

## How It Works

1. **Exporter Init Container**:
   - Creates writable Quarkus cache directory (`/tmp/quarkus-cache`)
   - Runs `kc.sh export --realm <realm> --file /exported/realm_backup.json --users realm_file --optimized`
   - Exits after export completes

2. **Uploader Container**:
   - Waits for `realm_backup.json` to appear in shared volume
   - Uploads file to S3 with timestamp filename
   - Filename format: `<realm>_<timestamp>.json` or `all-realms_<timestamp>.json`

## Troubleshooting

- **kc.sh build fails**: The chart sets `KC_CACHE_DIR` to a writable temp directory
- **S3 upload fails**: Verify S3 credentials in the secret
- **Init container stuck**: Keycloak may still be starting up. Check Keycloak pod logs

## Files

- `templates/cronjob-backup.yaml`: Backup CronJob with init/main containers
- `templates/job-restore.yaml`: Restore Job (placeholder)
- `values.yaml`: Default configuration
