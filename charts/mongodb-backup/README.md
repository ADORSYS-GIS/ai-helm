# MongoDB Backup Chart

A Helm chart for automated MongoDB database backup to S3-compatible storage using `mongodump`.

## Overview

This chart creates a CronJob that backs up MongoDB databases:

- **Init Container**: Uses MongoDB image to run `mongodump`
- **Main Container**: Uses AWS CLI to upload the backup to S3

## Installation

### 1. Configure the MongoDB connection

Pass the connection string through the helm values mapping it to the `MONGODB_URI` environment variable, or use a `valueFrom: secretKeyRef` to load it securely.

### 2. Create Required S3 Secret

The default setup expects an S3 secret named `mongodb-s3` containing bucket info and credentials. You can customize the name/keys in `values.yaml` if needed.

```bash
# S3 Credentials Secret
kubectl create secret generic mongodb-s3 \
  -n mongodb \
  --from-literal=s3_bucket_name=your-bucket \
  --from-literal=s3_region_name=us-east-1 \
  --from-literal=s3_access_key_id=<aws-key> \
  --from-literal=s3_secret_access_key=<aws-secret>
```

### 3. Install the Chart

```bash
helm install mongodb-backup ./mongodb-backup -n mongodb

# Custom schedule and database
helm install mongodb-backup ./mongodb-backup \
  -n mongodb \
  --set mongodb-backup.controllers.main.cronjob.schedule="0 2 * * *" \
  --set mongodb-backup.controllers.main.containers.main.env.BACKUP_DATABASE="my_db"
```

## Architecture

```
CronJob
├── initContainer: exporter (mongo:8.0)
│   └── Runs mongodump with authentication
│   └── Writes mongo_backup.gz to emptyDir
│
└── container: main (amazon/aws-cli:2.17.0)
    └── Uploads to S3
```

## Troubleshooting

- **mongodump fails**: Ensure the `MONGODB_URI` is correctly passed to the initContainer.
- **S3 upload fails**: Verify S3 credentials and bucket permissions in the mapped secret.
