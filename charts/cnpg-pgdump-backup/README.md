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

### 1. Set up Test Environment

For testing purposes, you can set up a local PostgreSQL instance using the provided test manifests:

```bash
# Create test namespace
kubectl create namespace pgdump-test

# Deploy PostgreSQL test instance
kubectl apply -f how-it-works/

# Wait for PostgreSQL to be ready
kubectl wait --for=condition=ready pod -l app=postgres -n pgdump-test --timeout=300s

# Create S3 secrets (replace with your actual credentials)
kubectl apply -f how-it-works/secret.yaml
```

### 2. Create AWS S3 Secret

Create the S3 credentials secret using your actual AWS credentials:

```bash
kubectl create secret generic open-web-ui-s3 \
  -n pgdump-test \
  --from-literal=S3_BUCKET_NAME=kivoyo-backup-postgresdb-test \
  --from-literal=S3_REGION_NAME=eu-north-1 \
  --from-literal=S3_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
  --from-literal=S3_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
  --from-literal=AWS_SESSION_TOKEN="$AWS_SESSION_TOKEN" \
  --dry-run=client -o yaml | kubectl apply -f -
```

### 3. Install the Helm Chart

```bash
# Add the chart to your Helm repository or install from local directory
helm install cnpg-backup ./cnpg-pgdump-backup \
  --namespace pgdump-test \
  --set cnpg.secretName="litellm-pg-app" \
  --set s3.secretName="open-web-ui-s3"
```

## Configuration

### Key Configuration Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `controllers.cronjob.enabled` | Enable scheduled backups | `true` |
| `controllers.cronjob.schedule` | Cron schedule for backups | `"45 9 * * *"` |
| `controllers.job.enabled` | Enable restore jobs | `true` |
| `restore.object` | S3 object key for restore | `""` |
| `cnpg.secretName` | Secret containing CNPG connection details | `"litellm-pg-app"` |
| `s3.secretName` | Secret containing S3 credentials | `"open-web-ui-s3"` |
| `s3.prefix` | S3 prefix/path within bucket | `""` |

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

To perform a restore operation, install the chart with the `restore.object` parameter:

```bash
helm install cnpg-restore ./cnpg-pgdump-backup \
  --namespace pgdump-test \
  --set restore.object="backup/testdb_2026-01-22T13:32:02Z.sql.gz" \
  --set controllers.cronjob.enabled=false \
  --set cnpg.secretName="litellm-pg-app" \
  --set s3.secretName="open-web-ui-s3"
```

Or upgrade an existing release:

```bash
helm upgrade cnpg-backup ./cnpg-pgdump-backup \
  --set restore.object="backup/your-backup-file.sql.gz"
```

### Manual Job Creation

You can also create restore jobs manually by applying a Job manifest or using kubectl to create jobs based on the Helm template in `templates/job-restore.yaml`.

## Testing

### Verify Backup Operation

```bash
# Check if backup job completed successfully
kubectl get jobs -n pgdump-test

# View backup logs
kubectl logs job/manual-backup -n pgdump-test
```

### Verify Restore Operation

```bash
# Check database content after restore
kubectl exec -n pgdump-test postgres-XXXXX -- psql -U testuser -d testdb -c "SELECT * FROM test_table LIMIT 5;"
```

### Test Environment Cleanup

```bash
# Remove test PostgreSQL instance
kubectl delete -f how-it-works/

# Remove test namespace
kubectl delete namespace pgdump-test
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