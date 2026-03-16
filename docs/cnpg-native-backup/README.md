# CNPG Backup and Restore With Barman Cloud Plugin

This document is a general guide to installing CloudNativePG (CNPG), installing the Barman Cloud plugin, and configuring S3-backed backups. It is independent from production-specific ArgoCD/Helm settings.

## Prerequisites
- Kubernetes cluster
- `kubectl`
- cert-manager installed in the cluster
- CNPG 1.26+ for Barman Cloud plugin compatibility

## Install CNPG Operator (kubectl)
Pick a CNPG version compatible with the Barman plugin (CNPG 1.26+). Example install:

```bash
kubectl apply --server-side -f \
  https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/release-1.26/releases/cnpg-1.26.3.yaml
```

## Install Barman Cloud Plugin (kubectl)
Install the plugin in the same namespace where CNPG is installed (typically `cnpg-system`):

```bash
kubectl apply -f https://github.com/cloudnative-pg/plugin-barman-cloud/releases/download/v0.11.0/manifest.yaml
```

## Optional: Install kubectl-cnpg Plugin
The `kubectl cnpg` plugin is optional but helpful for inspection and debugging.

```bash
# Krew
kubectl krew install cnpg

# Homebrew
brew install kubectl-cnpg
```

## Configure AWS S3 Secret
This secret holds S3 credentials for the Barman ObjectStore.

### Export credentials from your shell
This loads values from the current shell or falls back to AWS CLI default config.

```bash
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-$(aws configure get aws_access_key_id)}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-$(aws configure get aws_secret_access_key)}"
export AWS_REGION="${AWS_REGION:-$(aws configure get region)}"
export AWS_SESSION_TOKEN="${AWS_SESSION_TOKEN:-$(aws configure get aws_session_token)}"
export S3_BUCKET_NAME="your-bucket"
```

### Create the secret
Schema matches the keys below. If you are not using session tokens, omit that env var.

```bash
kubectl create secret generic cnpg-barman-s3 \
  --from-literal=s3_access_key_id="$AWS_ACCESS_KEY_ID" \
  --from-literal=s3_secret_access_key="$AWS_SECRET_ACCESS_KEY" \
  --from-literal=s3_region_name="$AWS_REGION" \
  --from-literal=s3_bucket_name="$S3_BUCKET_NAME"
```

Expected secret schema:

```yaml
apiVersion: v1
data:
  s3_access_key_id: ++++++++
  s3_bucket_name: ++++++++
  s3_region_name: ++++++++
  s3_secret_access_key: ++++++++
```

If you use session tokens, add `s3_session_token` to the secret and update the ObjectStore with `sessionToken`.

## Create an ObjectStore
Define where WAL archives and base backups are stored.

```yaml
apiVersion: barmancloud.cnpg.io/v1
kind: ObjectStore
metadata:
  name: my-s3-backup
spec:
  configuration:
    destinationPath: s3://your-bucket/cluster-backups/
    endpointURL: https://s3.eu-central-1.amazonaws.com
    s3Credentials:
      accessKeyId:
        name: cnpg-barman-s3
        key: s3_access_key_id
      secretAccessKey:
        name: cnpg-barman-s3
        key: s3_secret_access_key
      region:
        name: cnpg-barman-s3
        key: s3_region_name
```

Apply it:

```bash
kubectl apply -f objectstore.yaml
```

## Enable WAL Archiving in a Cluster
Attach the Barman plugin to the cluster and set `isWALArchiver: true`.

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: cluster-example
spec:
  instances: 3
  storage:
    size: 1Gi
  plugins:
    - name: barman-cloud.cloudnative-pg.io
      isWALArchiver: true
      parameters:
        barmanObjectName: my-s3-backup
        serverName: cluster-example
```

## Schedule Backups
Use `ScheduledBackup` with the plugin method.

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: ScheduledBackup
metadata:
  name: daily-backup
spec:
  immediate: true
  schedule: "0 2 * * *"
  cluster:
    name: cluster-example
  method: plugin
  pluginConfiguration:
    name: barman-cloud.cloudnative-pg.io
```

## Restore From Backup
Create a new cluster that bootstraps from the ObjectStore:

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: cluster-restore
spec:
  instances: 3
  bootstrap:
    recovery:
      source: source
  externalClusters:
    - name: source
      plugin:
        name: barman-cloud.cloudnative-pg.io
        parameters:
          barmanObjectName: my-s3-backup
          serverName: cluster-example
  storage:
    size: 1Gi
```

## Verify Backups
```bash
kubectl get scheduledbackups
kubectl get backups
```
