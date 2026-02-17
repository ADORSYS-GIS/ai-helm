# Keycloak Backup Chart

A Helm chart for automated Keycloak database backup to S3-compatible storage using `kc.sh export`.

## Overview

This chart creates a CronJob that backs up Keycloak configurations:
- **Init Container**: Uses Keycloak image to export realm via `kc.sh export`
- **Main Container**: Uses AWS CLI to upload the backup to S3

## Installation

### 1. Create Required Secrets

```bash
# Keycloak Admin Secret
kubectl create secret generic keycloak-admin \
  -n keycloak \
  --from-literal=username=admin \
  --from-literal=password=<admin-password> \
  --from-literal=hostname=keycloak

# S3 Credentials Secret
kubectl create secret generic keycloak-s3 \
  -n keycloak \
  --from-literal=S3_BUCKET_NAME=your-bucket \
  --from-literal=S3_REGION_NAME=us-east-1 \
  --from-literal=S3_ACCESS_KEY_ID=<aws-key> \
  --from-literal=S3_SECRET_ACCESS_KEY=<aws-secret>

# Optional: Add session token for temporary credentials
kubectl patch secret keycloak-s3 -n keycloak --type='json' -p='[{"op": "add", "path": "/data/AWS_SESSION_TOKEN", "value": "<base64-encoded-token>"}]'
```

### 2. Install the Chart

```bash
helm install keycloak-backup ./keycloak-backup -n keycloak

# Custom schedule
helm install keycloak-backup ./keycloak-backup \
  -n keycloak \
  --set schedule="0 2 * * *"

# Backup specific realm
helm install keycloak-backup ./keycloak-backup \
  -n keycloak \
  --set keycloak.realm=my-realm
```

## Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `keycloak.imageTag` | Keycloak image tag | `24.0` |
| `keycloak.secretName` | Keycloak admin credentials secret | `keycloak-admin` |
| `keycloak.realm` | Realm to backup (empty for all) | `master` |
| `keycloak.hostname` | Keycloak service name | `keycloak` |
| `s3.prefix` | S3 prefix path | `""` |
| `s3.secretName` | S3 credentials secret | `keycloak-s3` |
| `s3.pathStyle` | Use S3 path-style addressing | `false` |
| `schedule` | Cron schedule | `0 2 * * *` |

## Architecture

```
CronJob
├── initContainer: exporter (quay.io/keycloak/keycloak:<tag>)
│   └── Runs kc.sh export with KC_CACHE_DIR
│   └── Writes realm_backup.json to emptyDir
│
└── container: uploader (amazon/aws-cli:2.15.0)
    └── Uploads to S3
```

## Troubleshooting

- **kc.sh build fails**: Ensure `KC_CACHE_DIR` is writable
- **S3 upload fails**: Verify S3 credentials and bucket permissions
- **API auth fails**: Verify Keycloak admin credentials
