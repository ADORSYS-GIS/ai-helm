# CNPG Backup Strategy - Decision Required

> **Document Purpose**: Explain the CloudNativePG backup constraint and require hierarchy approval for the chosen implementation strategy.

---

## ⚠️ Critical Constraint (UPDATED)

CloudNativePG has an **admission webhook** that prevents having both:
- `externalClusters[].barmanObjectStore` (old style for restore)
- `externalClusters[].plugin` (for restore source)
- `spec.plugins` with WAL archiver enabled

**This is a hard limitation in CNPG - you cannot have both at the same time.**

### Error You'll See
```
spec.plugins: Invalid value: ["barman-cloud.cloudnative-pg.io"]: 
Cannot enable a WAL archiver plugin when barmanObjectStore is configured
```

---

## 🎉 Discovery (April 2026)

**The barman-cloud plugin works when using the new `ObjectStore` CRD approach!**

Successfully tested in local k3d environment:
- ✅ WAL Archiving enabled (`ContinuousArchiving: True`)
- ✅ Base backups stored in MinIO
- ✅ WAL files streamed to MinIO
- ✅ No webhook conflict!

### Working Configuration

```yaml
# 1. Create ObjectStore resource (new CRD)
apiVersion: barmancloud.cnpg.io/v1
kind: ObjectStore
metadata:
  name: my-cluster
  namespace: converse
spec:
  configuration:
    destinationPath: s3://ai-ops-backups/lightbridge-cnpg-backups/
    endpointURL: http://minio.minio.svc:9000
    s3Credentials:
      accessKeyId:
        name: lightbridge-cnpg-s3
        key: ACCESS_KEY_ID
      secretAccessKey:
        name: lightbridge-cnpg-s3
        key: ACCESS_SECRET_KEY

---
# 2. Create Cluster with plugins
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
  plugins:
    - name: barman-cloud.cloudnative-pg.io
      isWALArchiver: true
      parameters:
        barmanObjectName: my-cluster  # Must match ObjectStore name
        serverName: lightbridge-main-db

---
# 3. ScheduledBackup uses plugin method
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

### When the Conflict Occurs

The webhook conflict occurs when:
- ❌ Using `externalClusters[].barmanObjectStore` (old style for restore)
- ❌ Using `externalClusters[].plugin` (for restore source bootstrap)
- ✅ Using `ObjectStore` CRD + `spec.plugins` (WORKS!)

---

## Current Requirements

| Requirement | Supported? |
|-------------|------------|
| **Disaster Recovery** - Restore from existing backup | ✅ Yes (with ObjectStore) |
| **New Cluster with Continuous Backup** - WAL archiving enabled from start | ✅ Yes (tested!) |

---

## Available Strategies

### ☑ Strategy 1: ObjectStore CRD + Plugins (TESTED & WORKING)

Use the new `ObjectStore` CRD approach combined with `spec.plugins`.

| Aspect | Details |
|--------|---------|
| **Pros** | Full feature parity, WAL streaming, PITR, no CNPG conflict, tested |
| **Cons** | Requires ObjectStore CRD (new resource type) |
| **Complexity** | Low-Medium |
| **Effort** | 1-2 days to implement per cluster |
| **Status** | ✅ Tested successfully in k3d |

**How it works**:
```
CNPG Cluster + plugins → barman-cloud plugin → ObjectStore → MinIO/S3
```

---

### ☐ Strategy 2: External Barman Server

Deploy a standalone Barman server outside of CNPG that connects via PostgreSQL streaming replication.

| Aspect | Details |
|--------|---------|
| **Pros** | Full feature parity, WAL streaming, PITR |
| **Cons** | Additional infrastructure, separate server to manage |
| **Complexity** | Medium |
| **Effort** | 2-3 days to implement + documentation |

---

### ☐ Strategy 3: pgbackrest Alternative

Use pgbackrest instead of barman-cloud for backup (different mechanism).

| Aspect | Details |
|--------|---------|
| **Pros** | Native PostgreSQL tool, no CNPG webhook conflict |
| **Cons** | Different tool to learn/configure, separate deployment |
| **Complexity** | Medium |

---

### ☐ Strategy 4: Two-Phase Deployment

**DEPRECATED** - The ObjectStore approach makes this unnecessary.

---

### ☐ Strategy 5: Wait for CNPG Fix

This is a known CNPG limitation. Wait for a future version to support both.

| Aspect | Details |
|--------|---------|
| **Cons** | No timeline, blocks critical functionality |

---

## Personal Recommendation

**Strategy 1 (ObjectStore CRD + Plugins)** because:

1. ✅ Already tested and working in our environment
2. Supports both requirements (DR restore AND new clusters with continuous backup)
3. Native CNPG solution - no external infrastructure
4. Full features - WAL streaming, point-in-time recovery, compression
5. Uses the barman-cloud plugin (official CNPG solution)
6. Simpler than external Barman server

### Implementation Plan (Strategy 1)

1. Create `ObjectStore` resources for each cluster in `converse` namespace
2. Update Cluster specs to use `spec.plugins` with `isWALArchiver: true`
3. Update ScheduledBackup to use `method: plugin`
4. Remove old two-phase workaround from restore manifests
5. Test backup/restore in staging before production
6. Update documentation

---

## Decision Required

Please check the box for the chosen strategy:

- [x] **Strategy 1**: ObjectStore CRD + Plugins (TESTED & WORKING) ← Recommended
- [ ] **Strategy 2**: External Barman Server
- [ ] **Strategy 3**: pgbackrest Alternative
- [ ] **Strategy 4**: Two-Phase Only (accept limitation)
- [ ] **Strategy 5**: Wait for CNPG fix

**Approved by**: _________________  
**Date**: _________________

---

## Appendix: Current State

- **Test cluster successful**: `test-cnpg` in `test-cnpg` namespace
  - WAL Archiving: ✅ Enabled
  - Backup: ✅ Stored in MinIO
  - WAL streaming: ✅ Working
- **ObjectStore CRD installed**: ✅ (`objectstores.barmancloud.cnpg.io`)
- **barman-cloud plugin installed**: ✅ (`cnpg-barman-cloud` in `cnpg-system`)
- **Backup location**: `s3://ai-ops-backups/lightbridge-cnpg-backups/`
- **MinIO endpoint**: `http://minio.minio.svc:9000` (local k3d)

### Test Results

```
# Backup in MinIO
lightbridge-test/base/20260416T190208/backup.info
lightbridge-test/base/20260416T190208/data.tar
lightbridge-test/wals/... (multiple WAL files)

# Cluster status
ContinuousArchiving: True

# Restore test successful!
- Restored 3 users
- Restored 7 events (including post-backup inserts)
- Replication working between restore nodes
```

### Full Test Cycle (April 16, 2026)

1. **Create cluster with initdb + mock data**: ✅
   - Created `users` table with 3 users
   - Created `events` table with 5 initial events
   - Added 2 more events after backup

2. **Backup to MinIO**: ✅
   - ScheduledBackup completed successfully
   - Base backup stored in `s3://ai-ops-backups/test-cnpg/lightbridge-test/`
   - WAL files streaming to MinIO

3. **Restore from backup**: ✅
   - Created new cluster from backup
   - All 7 events restored (including post-backup inserts!)
   - Data integrity verified

4. **Continuous WAL archiving on restore cluster**: ✅
   - New WAL files being written to MinIO
   - `ContinuousArchiving: True`
