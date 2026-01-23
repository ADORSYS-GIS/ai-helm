# CNPG PostgreSQL Backup & Restore

A Helm chart for automated PostgreSQL backup and restore operations using CloudNativePG (CNPG) clusters with S3-compatible storage.

## Overview

This Helm chart provides a complete solution for backing up and restoring PostgreSQL databases running in CloudNativePG clusters. It uses the [`postgresql-backup-s3`](https://github.com/itbm/postgresql-backup-s3) Docker image to handle backup and restore operations directly to/from S3-compatible storage.

### Features

- **Automated Scheduled Backups**: CronJob-based automated backups
- **On-Demand Restores**: Manual restore jobs triggered via Helm
- **S3-Compatible Storage**: Support for AWS S3, MinIO, and other S3-compatible services
- **CloudNativePG Integration**: Designed for CNPG cluster environments
- **RBAC Security**: Proper service accounts and role-based access control
- **Flexible Configuration**: Comprehensive configuration options via values.yaml

## Prerequisites

- Kubernetes 1.19+
- Helm 3.0+
- CloudNativePG cluster running PostgreSQL
- S3-compatible storage (AWS S3, MinIO, etc.)
- kubectl access to your cluster

## Quick Start

### 1. Create an AWS S3 Bucket

1. Log in to the AWS Management Console.
2. Navigate to the S3 service.
3. Click "Create bucket".
4. Enter a unique bucket name (e.g., `my-postgres-backup-test`).
5. Choose a region (e.g., `us-east-1`).
6. Keep default settings and create the bucket.
7. Export the bucket name and region as environment variables:

```bash
export S3_BUCKET_NAME="my-postgres-backup-test"
export S3_REGION_NAME="us-east-1"
```

### 2. Set up Test Environment

For testing purposes, set up a local PostgreSQL instance using the provided test manifests:

```bash
# Create test namespace
kubectl create namespace pgdump-test

# Deploy PostgreSQL test instance
kubectl apply -f how-it-works/

# Wait for PostgreSQL to be ready
kubectl wait --for=condition=ready pod -l app=postgres -n pgdump-test --timeout=300s

# Populate the database with test data
# Uncomment the configmap in how-it-works/configmap.yaml
kubectl apply -f how-it-works/configmap.yaml

# Create PostgreSQL connection secret
kubectl apply -f how-it-works/secret.yaml
```

### 3. Create AWS S3 Secret

Create the S3 credentials secret using your actual AWS credentials and the exported bucket name:

```bash
# Export your AWS credentials as environment variables
export AWS_ACCESS_KEY_ID="your-access-key-id"
export AWS_SECRET_ACCESS_KEY="your-secret-access-key"
export AWS_SESSION_TOKEN="your-session-token"  # optional

kubectl create secret generic open-web-ui-s3 \
  -n pgdump-test \
  --from-literal=S3_BUCKET_NAME="$S3_BUCKET_NAME" \
  --from-literal=S3_REGION_NAME="$S3_REGION_NAME" \
  --from-literal=S3_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
  --from-literal=S3_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
  --from-literal=AWS_SESSION_TOKEN="$AWS_SESSION_TOKEN" \
  --dry-run=client -o yaml | kubectl apply -f -
```

### 4. Install the Helm Chart for Backup

Install the Helm chart to enable scheduled backups (schedule set to every minute for testing):

```bash
helm install cnpg-backup ./cnpg-pgdump-backup \
  --namespace pgdump-test \
  --set controllers.cronjob.schedule="* * * * *" \
  --set cnpg.secretName="litellm-pg-app" \
  --set s3.secretName="open-web-ui-s3"
```

### 5. Test Backup Operation

Wait for the scheduled backup to run (or trigger manually if needed), then verify:

```bash
# Check backup job status
kubectl get jobs -n pgdump-test

# View backup logs
kubectl logs -l app.kubernetes.io/name=cnpg-pgdump-backup -n pgdump-test --tail=50

# Verify backup file in S3 (check AWS console or use AWS CLI)
aws s3 ls s3://$S3_BUCKET_NAME/ --recursive
```

### 6. Prepare for Restore Test

To test restore, empty the database and then restore from backup:

```bash
# Delete the configmap to stop populating data
kubectl delete configmap postgres-initdb -n pgdump-test

# The deployment.yaml already has the initdb mount commented out, so re-apply to ensure
kubectl apply -f how-it-works/deployment.yaml

# Wait for PostgreSQL to restart (it will be empty now)
kubectl wait --for=condition=ready pod -l app=postgres -n pgdump-test --timeout=300s

# Verify database is empty
kubectl exec -n pgdump-test postgres-XXXXX -- psql -U testuser -d testdb -c "SELECT COUNT(*) FROM test_table;"
# Should return 0 rows
```

### 7. Test Restore Operation

1. Find the backup file name from your S3 bucket (via AWS console or CLI).
2. Export the backup file name as an environment variable:

```bash
export BACKUP_FILE_NAME="path/to/your/backup/file.sql.gz"
# Example: export BACKUP_FILE_NAME="backup/testdb_2026-01-22T13:32:02Z.sql.gz"
```

3. Upgrade the Helm chart to trigger restore:

```bash
helm upgrade cnpg-backup ./cnpg-pgdump-backup \
  --namespace pgdump-test \
  --set restore.object="$BACKUP_FILE_NAME" \
  --set controllers.cronjob.enabled=false \
  --set cnpg.secretName="litellm-pg-app" \
  --set s3.secretName="open-web-ui-s3"
```

4. Verify restore:

```bash
# Check restore job status
kubectl get jobs -n pgdump-test

# View restore logs
kubectl logs -l app.kubernetes.io/name=cnpg-pgdump-backup -n pgdump-test --tail=50

# Verify data is restored
kubectl exec -n pgdump-test postgres-XXXXX -- psql -U testuser -d testdb -c "SELECT COUNT(*) FROM test_table;"
# Should return 10000 rows
```

## Configuration

### Key Configuration Options

| Parameter                      | Description                               | Default            |
| ------------------------------ | ----------------------------------------- | ------------------ |
| `controllers.cronjob.enabled`  | Enable scheduled backups                  | `true`             |
| `controllers.cronjob.schedule` | Cron schedule for backups                 | `"45 9 * * *"`     |
| `controllers.job.enabled`      | Enable restore jobs                       | `true`             |
| `restore.object`               | S3 object key for restore                 | `""`               |
| `cnpg.secretName`              | Secret containing CNPG connection details | `"litellm-pg-app"` |
| `s3.secretName`                | Secret containing S3 credentials          | `"open-web-ui-s3"` |
| `s3.prefix`                    | S3 prefix/path within bucket              | `""`               |

### PostgreSQL Connection Secret

Your CNPG secret should contain these keys:

- `host`: PostgreSQL server hostname
- `port`: PostgreSQL server port
- `dbname`: Database name
- `username`: PostgreSQL username
- `password`: PostgreSQL password

### S3 Credentials Secret

Your S3 secret should contain these keys:

- `S3_BUCKET_NAME`: S3 bucket name
- `S3_REGION_NAME`: AWS region
- `S3_ACCESS_KEY_ID`: AWS access key ID
- `S3_SECRET_ACCESS_KEY`: AWS secret access key
- `AWS_SESSION_TOKEN`: AWS session token (if using temporary credentials)

## Usage

### Scheduled Backups

The chart creates a CronJob that runs automated backups according to the configured schedule:

```bash
# Check backup cronjob
kubectl get cronjob -n pgdump-test

# Check backup job logs
kubectl logs -l app.kubernetes.io/name=cnpg-pgdump-backup -n pgdump-test
```

### Manual Restore

To perform a restore operation, set the `restore.object` parameter to the S3 key of your backup file:

```bash
# Export the backup file name from your S3 bucket
export BACKUP_FILE_NAME="path/to/your/backup/file.sql.gz"

# Install the chart for restore
helm install cnpg-restore ./cnpg-pgdump-backup \
  --namespace pgdump-test \
  --set restore.object="$BACKUP_FILE_NAME" \
  --set controllers.cronjob.enabled=false \
  --set cnpg.secretName="litellm-pg-app" \
  --set s3.secretName="open-web-ui-s3"
```

Or upgrade an existing release:

```bash
helm upgrade cnpg-backup ./cnpg-pgdump-backup \
  --set restore.object="$BACKUP_FILE_NAME"
```

### Manual Job Creation

You can also create restore jobs manually by applying a Job manifest or using kubectl to create jobs based on the Helm template in `templates/job-restore.yaml`.

## Testing

For detailed testing steps including backup and restore verification, see the [Quick Start](#quick-start) section above.

### General Verification Commands

#### Check Job Status

```bash
# List all jobs
kubectl get jobs -n pgdump-test

# Get detailed job information
kubectl describe job <job-name> -n pgdump-test
```

#### View Logs

```bash
# View logs for backup/restore jobs
kubectl logs -l app.kubernetes.io/name=cnpg-pgdump-backup -n pgdump-test --tail=100

# View logs for a specific job
kubectl logs job/<job-name> -n pgdump-test
```

#### Verify Database Content

```bash
# Connect to PostgreSQL and check data
kubectl exec -n pgdump-test postgres-XXXXX -- psql -U testuser -d testdb -c "SELECT COUNT(*) FROM test_table;"

# List tables
kubectl exec -n pgdump-test postgres-XXXXX -- psql -U testuser -d testdb -c "\dt"
```

#### Verify S3 Backup Files

```bash
# List backup files in S3 (requires AWS CLI configured)
aws s3 ls s3://$S3_BUCKET_NAME/ --recursive
```

### Test Environment Cleanup

```bash
# Remove test PostgreSQL instance
kubectl delete -f how-it-works/

# Remove test namespace
kubectl delete namespace pgdump-test

# Remove Helm release
helm uninstall cnpg-backup -n pgdump-test
```

## Architecture

The chart creates the following Kubernetes resources:

- **CronJob**: Scheduled backup operations
- **Job**: On-demand restore operations (when `restore.object` is set)
- **ServiceAccount**: RBAC service account for S3 access
- **Role & RoleBinding**: RBAC permissions for ConfigMap access
- **Secrets**: Referenced for database and S3 credentials

## Troubleshooting

### Common Issues

1. **Backup Job Fails**: Check S3 credentials and bucket permissions
2. **Restore Job Fails**: Verify backup file exists in S3 and database credentials
3. **Connection Issues**: Ensure CNPG cluster is accessible and secrets are correct

### Debug Commands

```bash
# Check pod status
kubectl get pods -n pgdump-test

# View detailed logs
kubectl logs -l app.kubernetes.io/name=cnpg-pgdump-backup -n pgdump-test --tail=100

# Check secrets
kubectl describe secret litellm-pg-app -n pgdump-test
kubectl describe secret open-web-ui-s3 -n pgdump-test
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.
