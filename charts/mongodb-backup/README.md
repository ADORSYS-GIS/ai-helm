# MongoDB Backup Chart

A Helm chart for automated MongoDB database backup to S3-compatible storage using `mongodump`.

## Overview

This chart creates a CronJob that backs up MongoDB databases:

- **Init Container**: Uses MongoDB image to run `mongodump`
- **Main Container**: Uses AWS CLI to upload the backup to S3

## Installation

### 1. Create Required Secrets

```bash
# MongoDB Connection Secret (using URI for auth-less or authenticated connections)
kubectl create secret generic mongodb \
  -n mongodb \
  --from-literal=uri="mongodb://mongodb:27017"

# S3 Credentials Secret
kubectl create secret generic mongodb-s3 \
  -n mongodb \
  --from-literal=S3_BUCKET_NAME=your-bucket \
  --from-literal=S3_REGION_NAME=us-east-1 \
  --from-literal=S3_ACCESS_KEY_ID=<aws-key> \
  --from-literal=S3_SECRET_ACCESS_KEY=<aws-secret>

# Optional: Add session token for temporary credentials
kubectl patch secret mongodb-s3 -n mongodb --type='json' -p='[{"op": "add", "path": "/data/AWS_SESSION_TOKEN", "value": "<base64-encoded-token>"}]'
```

### 2. Install the Chart

```bash
helm install mongodb-backup ./mongodb-backup -n mongodb

# Custom schedule
helm install mongodb-backup ./mongodb-backup \
  -n mongodb \
  --set schedule="0 2 * * *"
```

## Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `mongo-backup.imageTag` | MongoDB image tag | `8.0` |
| `mongo-backup.secretName` | MongoDB connection secret | `mongodb` |
| `s3.prefix` | S3 prefix path | `""` |
| `s3.secretName` | S3 credentials secret | `mongodb-s3` |
| `s3.pathStyle` | Use S3 path-style addressing | `false` |
| `schedule` | Cron schedule | `0 2 * * *` |

## Architecture

```
CronJob
├── initContainer: exporter (mongo:7.0)
│   └── Runs mongodump with authentication
│   └── Writes mongo_backup.gz to emptyDir
│
└── container: uploader (amazon/aws-cli:2.17.0)
    └── Uploads to S3
```

## Troubleshooting

- **mongodump fails**: Ensure MongoDB credentials and connection are correct
- **S3 upload fails**: Verify S3 credentials and bucket permissions
- **Auth fails**: Verify MongoDB username/password and authenticationDatabase
