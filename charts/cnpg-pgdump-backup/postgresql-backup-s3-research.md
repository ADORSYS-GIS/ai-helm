# PostgreSQL-Backup-S3 Docker Image Research

## Image Information

Based on the GitHub repository: https://github.com/itbm/postgresql-backup-s3

### Image Location
- **Registry**: GHCR (GitHub Container Registry)
- **Image Name**: `ghcr.io/itbm/postgresql-backup-s3`
- **Tags**: Various versions available (check repository for latest)

## Key Features

### Built-in Functionality
1. **PostgreSQL Backup**: Uses `pg_dump` for database backups
2. **S3 Upload**: Direct upload to S3-compatible storage
3. **Compression**: Built-in compression support
4. **Scheduling**: Supports `SCHEDULE` environment variable for internal scheduling
5. **Environment Variables**: Comprehensive configuration via environment variables

### Environment Variables

#### Required Variables
- `POSTGRES_HOST`: PostgreSQL server hostname
- `POSTGRES_PORT`: PostgreSQL server port
- `POSTGRES_USER`: PostgreSQL username
- `POSTGRES_PASSWORD`: PostgreSQL password
- `POSTGRES_DATABASE`: Database name to backup
- `S3_BUCKET`: S3 bucket name
- `AWS_ACCESS_KEY_ID`: AWS access key
- `AWS_SECRET_ACCESS_KEY`: AWS secret key

#### Optional Variables
- `S3_REGION`: AWS region (defaults to us-east-1)
- `S3_ENDPOINT`: Custom S3 endpoint (for MinIO, etc.)
- `S3_PREFIX`: Prefix/path within bucket
- `BACKUP_FILENAME`: Custom backup filename pattern
- `BACKUP_COMPRESSION`: Compression level (0-9)
- `BACKUP_FORMAT`: Format (plain, custom, directory, tar)
- `BACKUP_SINGLE_TRANSACTION`: Use single transaction for backup
- `BACKUP_NO_OWNER`: Exclude ownership information
- `BACKUP_NO_PRIVILEGES`: Exclude privilege information
- `BACKUP_VERBOSE`: Verbose output
- `SCHEDULE`: Cron schedule (we won't use this as we're using Kubernetes CronJob)
- `TIMEZONE`: Timezone for scheduling
- `RETENTION_DAYS`: Number of days to keep backups
- `AWS_S3_FORCE_PATH_STYLE`: Force path-style addressing
- `AWS_S3_SIGNATURE_VERSION`: S3 signature version

## Usage Patterns

### One-time Backup (Relevant for our use case)
```bash
docker run --rm \
  -e POSTGRES_HOST=postgres.example.com \
  -e POSTGRES_PORT=5432 \
  -e POSTGRES_USER=myuser \
  -e POSTGRES_PASSWORD=mypassword \
  -e POSTGRES_DATABASE=mydb \
  -e S3_BUCKET=my-bucket \
  -e AWS_ACCESS_KEY_ID=myaccesskey \
  -e AWS_SECRET_ACCESS_KEY=mysecretkey \
  ghcr.io/itbm/postgresql-backup-s3
```

### Restore
```bash
docker run --rm \
  -e POSTGRES_HOST=postgres.example.com \
  -e POSTGRES_PORT=5432 \
  -e POSTGRES_USER=myuser \
  -e POSTGRES_PASSWORD=mypassword \
  -e POSTGRES_DATABASE=mydb \
  -e S3_BUCKET=my-bucket \
  -e AWS_ACCESS_KEY_ID=myaccesskey \
  -e AWS_SECRET_ACCESS_KEY=mysecretkey \
  -e RESTORE_FILE=backup.sql.gz \
  ghcr.io/itbm/postgresql-backup-s3
```

## Benefits for Our Helm Chart

1. **Simplified Deployment**: No need for init containers to install dependencies
2. **Reduced Complexity**: Remove custom scripts ConfigMap
3. **Maintained Functionality**: All required features are built-in
4. **Better Maintenance**: Leveraging a maintained Docker image
5. **Consistent Behavior**: Standardized backup/restore process

## Implementation Strategy

### For Backup (CronJob)
- Use the image directly in the main container
- Set appropriate environment variables from secrets
- Remove init container for dependency installation
- Remove scripts ConfigMap volume mount

### For Restore (Job)
- Use the image directly in the main container
- Set `RESTORE_FILE` environment variable to specify which backup to restore
- Set appropriate environment variables from secrets
- Remove init container for dependency installation
- Remove scripts ConfigMap volume mount

## Configuration Mapping

### Current Implementation → New Implementation

#### Backup
- **Current**: Custom scripts with manual `pg_dump` and `aws s3 cp`
- **New**: Use image's built-in backup functionality via environment variables

#### Restore
- **Current**: Custom scripts with manual download and restore
- **New**: Use image's built-in restore functionality via `RESTORE_FILE` env var

## Notes

1. We will **NOT** use the `SCHEDULE` environment variable as we want Kubernetes to manage the scheduling via CronJob
2. Each backup will be treated as a one-time operation, even though the image supports internal scheduling
3. The image provides all the functionality we need, making our Helm chart simpler and more maintainable