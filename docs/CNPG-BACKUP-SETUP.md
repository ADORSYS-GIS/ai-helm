# CNPG Backup - Setup Guide

> **Document Purpose**: Production implementation guide for CloudNativePG backup strategy.
> **Related Document**: See `docs/lightbridge-db-recovery-runbook.md` for disaster recovery procedures.
> **Status**: Awaiting Management Approval
> **Last Updated**: April 16, 2026

---

## Executive Summary

After testing in local k3d environment, we've validated a working backup solution for CloudNativePG that:
- ✅ Enables continuous WAL archiving
- ✅ Supports disaster recovery restore
- ✅ Uses official barman-cloud plugin
- ✅ No webhook conflicts

---

## The Solution: ObjectStore CRD + Plugins

### Why This Works

The CNPG webhook conflict occurs when using:
- ❌ `spec.backup.barmanObjectStore` (deprecated in-tree method)
- ❌ `externalClusters[].barmanObjectStore` (old restore style)

The solution uses:
- ✅ `ObjectStore` CRD (new Barman Cloud plugin architecture)
- ✅ `spec.plugins` with `isWALArchiver: true`
- ✅ `externalClusters[].plugin` only for restore (not live clusters)

---

## Implementation Steps

### Phase 1: Prerequisites (Already in Place)

| Component | Status | Notes |
|-----------|--------|-------|
| CNPG operator | ✅ | v0.27.1 in `cnpg-system` |
| barman-cloud plugin | ✅ | v0.5.0 in `cnpg-system` |
| ObjectStore CRD | ✅ | `objectstores.barmancloud.cnpg.io` |
| MinIO/S3 | ✅ | `s3://ai-ops-backups/lightbridge-cnpg-backups/` |

### Phase 2: Create S3 Credentials Secret

Create/update the secret in the `converse` namespace:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: lightbridge-cnpg-s3
  namespace: converse
type: Opaque
stringData:
  ACCESS_KEY_ID: <your-access-key>
  ACCESS_SECRET_KEY: <your-secret-key>
  # Add region if required by your S3 provider
  # region: us-east-1
```

### Phase 3: Create ObjectStore Resources

For each cluster, create an `ObjectStore` resource:

```yaml
# lightbridge-main-db-objectstore.yaml
apiVersion: barmancloud.cnpg.io/v1
kind: ObjectStore
metadata:
  name: lightbridge-main-db
  namespace: converse
spec:
  configuration:
    destinationPath: s3://ai-ops-backups/lightbridge-cnpg-backups/
    endpointURL: https://s3.ssegning.me
    s3Credentials:
      accessKeyId:
        name: lightbridge-cnpg-s3
        key: ACCESS_KEY_ID
      secretAccessKey:
        name: lightbridge-cnpg-s3
        key: ACCESS_SECRET_KEY
    wal:
      compression: gzip
```

```yaml
# lightbridge-usage-db-objectstore.yaml
apiVersion: barmancloud.cnpg.io/v1
kind: ObjectStore
metadata:
  name: lightbridge-usage-db
  namespace: converse
spec:
  configuration:
    destinationPath: s3://ai-ops-backups/lightbridge-cnpg-backups/
    endpointURL: https://s3.ssegning.me
    s3Credentials:
      accessKeyId:
        name: lightbridge-cnpg-s3
        key: ACCESS_KEY_ID
      secretAccessKey:
        name: lightbridge-cnpg-s3
        key: ACCESS_SECRET_KEY
    wal:
      compression: gzip
```

### Phase 4: Update Cluster Specs

Update each Cluster to include `spec.plugins`:

```yaml
# lightbridge-main-db Cluster (update existing)
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: lightbridge-main-db
  namespace: converse
spec:
  instances: 2
  imageName: ghcr.io/cloudnative-pg/postgresql:18.1-system-trixie
  storage:
    storageClass: linode-block-storage
    size: 5Gi
  # ADD THIS SECTION - enables WAL archiving
  plugins:
    - name: barman-cloud.cloudnative-pg.io
      isWALArchiver: true
      parameters:
        barmanObjectName: lightbridge-main-db
        serverName: lightbridge-main-db
```

```yaml
# lightbridge-usage-db Cluster (update existing)
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: lightbridge-usage-db
  namespace: converse
spec:
  instances: 2
  imageCatalogRef:
    apiGroup: postgresql.cnpg.io
    kind: ClusterImageCatalog
    name: lightbridge-usage-db
    major: 17
  storage:
    storageClass: linode-block-storage
    size: 10Gi
  postgresql:
    shared_preload_libraries:
      - timescaledb
  # ADD THIS SECTION - enables WAL archiving
  plugins:
    - name: barman-cloud.cloudnative-pg.io
      isWALArchiver: true
      parameters:
        barmanObjectName: lightbridge-usage-db
        serverName: lightbridge-usage-db
```

### Phase 5: Update ScheduledBackup

Update ScheduledBackup to use `method: plugin`:

```yaml
# lightbridge-main-db-scheduled-backup.yaml
apiVersion: postgresql.cnpg.io/v1
kind: ScheduledBackup
metadata:
  name: lightbridge-main-db-daily
  namespace: converse
spec:
  immediate: true
  schedule: "0 0 2 * * *"
  cluster:
    name: lightbridge-main-db
  method: plugin
  pluginConfiguration:
    name: barman-cloud.cloudnative-pg.io
```

```yaml
# lightbridge-usage-db-scheduled-backup.yaml
apiVersion: postgresql.cnpg.io/v1
kind: ScheduledBackup
metadata:
  name: lightbridge-usage-db-daily
  namespace: converse
spec:
  immediate: true
  schedule: "0 0 2 * * *"
  cluster:
    name: lightbridge-usage-db
  method: plugin
  pluginConfiguration:
    name: barman-cloud.cloudnative-pg.io
```

### Phase 6: Verify Deployment

Check that WAL archiving is enabled:

```bash
# Check cluster status
kubectl get cluster lightbridge-main-db -n converse -o jsonpath='{.status.conditions[?(@.type=="ContinuousArchiving")].status}'
# Expected: True

kubectl get cluster lightbridge-usage-db -n converse -o jsonpath='{.status.conditions[?(@.type=="ContinuousArchiving")].status}'
# Expected: True

# Check backup in MinIO
kubectl exec -n minio deploy/minio -- mc ls local/ai-ops-backups/lightbridge-cnpg-backups/lightbridge-main-db/base/
```

---

## Files to Create/Update

| File | Action | Description |
|------|--------|-------------|
| `charts/apps/lightbridge-main-db-objectstore.yaml` | Create | ObjectStore for main-db |
| `charts/apps/lightbridge-usage-db-objectstore.yaml` | Create | ObjectStore for usage-db |
| `charts/apps/lightbridge-main-db.yaml` | Update | Add plugins section |
| `charts/apps/lightbridge-usage-db.yaml` | Update | Add plugins section |
| `charts/apps/lightbridge-main-db-scheduled-backup.yaml` | Update | Use method: plugin |
| `charts/apps/lightbridge-usage-db-scheduled-backup.yaml` | Update | Use method: plugin |
| `docs/lightbridge-db-recovery-runbook.md` | Update | Remove two-phase workaround |

---

## Rollback Plan

If issues occur:

1. **Remove plugins** from Cluster spec (WAL archiving stops, backups still work)
2. **Revert** to ScheduledBackup with `method: barmanObjectStore` (deprecated but works)
3. **Monitor** cluster status with: `kubectl get cluster <name> -n converse -o jsonpath='{.status.conditions[*].type}'`

---

## Post-Implementation Verification

| Check | Command | Expected |
|-------|---------|----------|
| WAL Archiving | `kubectl get cluster -n converse <cluster> -o jsonpath='{.status.conditions[?(@.type=="ContinuousArchiving")].status}'` | `True` |
| Plugin Status | `kubectl get cluster -n converse <cluster> -o jsonpath='{.status.pluginStatus[*].name}'` | `barman-cloud.cloudnative-pg.io` |
| Backup Created | `kubectl exec -n minio deploy/minio -- mc ls local/ai-ops-backups/lightbridge-cnpg-backups/<cluster>/base/` | Backup files exist |
| WAL Streaming | `kubectl exec -n minio deploy/minio -- mc ls local/ai-ops-backups/lightbridge-cnpg-backups/<cluster>/wals/` | WAL files exist |

---

## Timeline Estimate

| Phase | Effort (Work Hours) | Duration (Calendar Time) |
|-------|---------------------|--------------------------|
| Phase 1: Prerequisites | 0 | Already done |
| Phase 2: Secrets | 0.5 hour | 1 hour |
| Phase 3: ObjectStore | 1 hour | 1 hour |
| Phase 4: Cluster updates | 1 hour | 1 hour |
| Phase 5: ScheduledBackup | 0.5 hour | 1 hour |
| Phase 6: Verification | 0.5 hour | 1 hour |
| **Total** | **~3.5 hours** | **~6 hours** |

---

## Approval Required

Please sign off on the implementation:

- [ ] **Approve** - Proceed with implementation
- [ ] **Approve with changes** - See notes below
- [ ] **Reject** - Do not proceed

**Approved by**: _________________  
**Date**: _________________  
**Notes**: _________________

---

## Appendix: Local Test Results

Full backup/restore cycle tested successfully on April 16, 2026:

1. Created cluster with initdb + mock data (3 users, 5 events)
2. Added 2 more events after backup
3. ScheduledBackup completed successfully
4. Restored to new cluster
5. All 7 events restored (including post-backup inserts!)
6. ContinuousArchiving status: True
7. Replication working between nodes
