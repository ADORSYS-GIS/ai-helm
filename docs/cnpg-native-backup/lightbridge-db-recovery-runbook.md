# Lightbridge Database Recovery Runbook

A GitOps-based disaster recovery procedure for CloudNativePG clusters in the `converse` namespace.

## 📋 Overview

This runbook documents the recovery strategy for two CNPG clusters:

- `lightbridge-main-db` - Main PostgreSQL database
- `lightbridge-usage-db` - TimescaleDB for usage tracking

## 🎯 Recovery Approaches

Two approaches are documented based on your availability requirements:

| Approach | Downtime | Use Case |
|----------|----------|----------|
| **Alias Services (Parallel)** | Seconds | Planned recovery, data migration, zero-downtime maintenance |
| **In-Place Recovery** | Full restore time | Disaster recovery when cluster is completely gone |

### Key Concept: `bootstrap.recovery` Only Works at Cluster Creation

CNPG's `bootstrap` section is only evaluated when a cluster is **first created**. Modifying an existing cluster's spec to add `bootstrap.recovery` has no effect - CNPG ignores it for existing clusters.

```yaml
# This ONLY works during cluster creation
spec:
  bootstrap:
    recovery:
      source: backup-name
```

To trigger recovery, you must either:

1. Create a NEW cluster with a different name (Alias Services approach)
2. Delete the cluster AND PVCs, then recreate (In-Place approach)

---

## 🔧 Prerequisites

- ArgoCD managing the `ai-helm` repo
- Backup available in MinIO:
  - `s3://ai-ops-backups/lightbridge-main-db/`
  - `s3://ai-ops-backups/lightbridge-usage-db/`
- Secrets `lightbridge-cnpg-s3` exists in `converse` namespace
- barman-cloud plugin installed in `cnpg-system`

---

## Approach 1: Alias Services (Zero Downtime)

**Use this when:** The old cluster is still running but you need to recover from backup (data corruption, migration, planned recovery).

**Downtime:** Seconds (only during service selector switch)

### How It Works

```md

1. Old cluster keeps running (serving traffic)
2. Create NEW cluster with different name (-restore suffix)
3. Restore from backup into new cluster
4. Validate new cluster
5. Switch alias service selector (seconds downtime)
6. Delete old cluster
```

### Phase 1: Verify Backup Exists

```bash
# Check backup status in MinIO
mc ls myminio/ai-ops-backups/lightbridge-main-db/data/
mc ls myminio/ai-ops-backups/lightbridge-usage-db/data/

# Or check via kubectl (if backup CRs exist)
kubectl get backups -n converse -l postgresql.cnpg.io/cluster=lightbridge-main-db
kubectl get backups -n converse -l postgresql.cnpg.io/cluster=lightbridge-usage-db
```

### Phase 2: Create Restore Clusters

The restore cluster files are already defined:

- `docs/cnpg-native-backuplightbridge-main-db-restore.yaml`
- `docs/cnpg-native-backuplightbridge-usage-db-restore.yaml`

**Key differences from original cluster:**

| Setting | Original | Restore |
|---------|----------|---------|
| Cluster name | `lightbridge-main-db` | `lightbridge-main-db-restore` |
| `serverName` in plugins | `lightbridge-main-db` | `lightbridge-main-db-restore` |
| `bootstrap.recovery` | Not set | Configured |
| `externalClusters` | Not set | Points to backup |

**Important:** The `serverName` in `externalClusters.parameters` must use the **original** server name (where the backup was created), while `plugins.parameters.serverName` uses the new name for future WAL archiving.

Apply the restore clusters:

```bash
kubectl apply -f docs/cnpg-native-backup/lightbridge-main-db-restore.yaml
kubectl apply -f docs/cnpg-native-backup/lightbridge-usage-db-restore.yaml
```

Or commit and push for ArgoCD to sync:

```bash
git add docs/cnpg-native-backuplightbridge-main-db-restore.yaml docs/cnpg-native-backuplightbridge-usage-db-restore.yaml
git commit -m "feat(db-recovery): create restore clusters"
git push
```

### Phase 3: Watch Recovery Progress

```bash
# Watch cluster creation
kubectl get clusters.postgresql.cnpg.io -n converse -w

# Watch pod creation
kubectl get pods -n converse -l cnpg.io/cluster=lightbridge-main-db-restore -w
kubectl get pods -n converse -l cnpg.io/cluster=lightbridge-usage-db-restore -w
```

Wait for:

- `lightbridge-main-db-restore` → Ready
- `lightbridge-usage-db-restore` → Ready

### Phase 4: Validate Data

```bash
# Check cluster status
kubectl get cluster lightbridge-main-db-restore -n converse -o yaml
kubectl get cluster lightbridge-usage-db-restore -n converse -o yaml

# Validate Main DB
kubectl exec -it lightbridge-main-db-restore-1 -n converse -- psql -U postgres -c "\dt"

# Validate Usage DB
kubectl exec -it lightbridge-usage-db-restore-1 -n converse -- psql -U postgres -d app -c "\dt"
kubectl exec -it lightbridge-usage-db-restore-1 -n converse -- psql -U postgres -d app -c "SELECT count(*) FROM usage_events;"

# Verify TimescaleDB
kubectl exec -it lightbridge-usage-db-restore-1 -n converse -- psql -U postgres -d app -c "SELECT extversion FROM pg_extension WHERE extname = 'timescaledb';"
```

### Phase 5: Switch Traffic

Update the alias service selectors in `docs/cnpg-native-backupvalues.yaml`:

```yaml
# For main-db
spec:
  selector:
    cnpg.io/cluster: lightbridge-main-db-restore  # Changed from lightbridge-main-db
    cnpg.io/instanceRole: primary

# For usage-db
spec:
  selector:
    cnpg.io/cluster: lightbridge-usage-db-restore  # Changed from lightbridge-usage-db
    cnpg.io/instanceRole: primary
```

Commit and push:

```bash
git add docs/cnpg-native-backupvalues.yaml
git commit -m "fix(db-recovery): switch alias services to restored clusters"
git push
```

### Phase 6: Verify Switch

```bash
# Check endpoints now point to restore cluster
kubectl get endpoints -n converse lightbridge-main-db-primary -o jsonpath='{.subsets[0].addresses[0].targetRef.name}'
kubectl get endpoints -n converse lightbridge-usage-db-primary -o jsonpath='{.subsets[0].addresses[0].targetRef.name}'
```

Should return:

- `lightbridge-main-db-restore-1`
- `lightbridge-usage-db-restore-1`

### Phase 7: Cleanup Old Cluster

After confirming the restore clusters are working:

```bash
# Delete old clusters
kubectl delete cluster lightbridge-main-db -n converse
kubectl delete cluster lightbridge-usage-db -n converse

# Remove old cluster definitions from Git
# (Remove from docs/cnpg-native-backupvalues.yaml)
```

### Phase 8: Final State

After recovery, the restore clusters become your new production clusters. The `-restore` suffix is just a naming convention - you can keep it or rename later.

**What's important:**
- PVCs now contain recovered data
- If pods are deleted, they will restart using existing PVC data (no re-recovery needed)
- The `bootstrap.recovery` setting is harmless - it only triggers on empty PVCs

**No need to rename** - the restore clusters work correctly as production clusters. Applications continue using the alias services (`lightbridge-main-db-primary`) which now point to the restored clusters.

---

## Approach 2: In-Place Recovery (With Downtime)

**Use this when:** The cluster is completely gone (deleted, PVCs lost) and you need to recover from backup.

**Downtime:** Full restore time (depends on backup size and network speed)

### How It Works

```
1. Delete cluster (and optionally PVCs)
2. Recreate cluster with bootstrap.recovery
3. CNPG restores from backup during creation
4. Validate and continue
```

### Phase 1: Verify Backup Exists

```bash
mc ls myminio/ai-ops-backups/lightbridge-main-db/data/
mc ls myminio/ai-ops-backups/lightbridge-usage-db/data/
```

### Phase 2: Delete Failed Cluster

**Option A: Clean Recovery (Delete Everything)**

```bash
# Delete the cluster
kubectl delete cluster lightbridge-main-db -n converse

# Delete PVCs
kubectl delete pvc -n converse -l postgresql.cnpg.io/cluster=lightbridge-main-db

# Wait for cleanup
kubectl get cluster,po,pvc -n converse -l postgresql.cnpg.io/cluster=lightbridge-main-db
```

**Option B: Keep PVCs (If Data Might Be Recoverable)**

```bash
# Delete only the cluster resource
kubectl delete cluster lightbridge-main-db -n converse

# PVCs remain intact - but you'll need new PVCs for recovery
# This is rarely useful for recovery scenarios
```

### Phase 3: Recreate Cluster with Recovery

In `docs/cnpg-native-backupvalues.yaml`, find the cluster definition and add `bootstrap.recovery`:

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: lightbridge-main-db  # SAME NAME as original
  namespace: converse
  annotations:
    argocd.argoproj.io/sync-wave: "2"
spec:
  instances: 2
  imageName: ghcr.io/cloudnative-pg/postgresql:18.1-system-trixie
  storage:
    storageClass: linode-block-storage
    size: "5Gi"
  plugins:
    - name: barman-cloud.cloudnative-pg.io
      isWALArchiver: true
      parameters:
        barmanObjectName: lightbridge-main-db
        serverName: lightbridge-main-db  # ORIGINAL server name
  # ADD THIS SECTION FOR RECOVERY
  bootstrap:
    recovery:
      source: lightbridge-main-db-backup
  externalClusters:
    - name: lightbridge-main-db-backup
      plugin:
        name: barman-cloud.cloudnative-pg.io
        parameters:
          barmanObjectName: lightbridge-main-db
          serverName: lightbridge-main-db  # ORIGINAL server name
  postgresql:
    parameters:
      archive_timeout: "30min"
  resources:
    limits:
      cpu: 300m
      memory: 1Gi
    requests:
      cpu: 200m
      memory: 500Mi
```

### Phase 4: Commit and Push

```bash
git add docs/cnpg-native-backupvalues.yaml
git commit -m "fix(db-recovery): recreate cluster with bootstrap.recovery"
git push
```

### Phase 5: Watch Recovery

```bash
# Watch cluster creation
kubectl get clusters.postgresql.cnpg.io -n converse -w

# Watch pod creation
kubectl get pods -n converse -l cnpg.io/cluster=lightbridge-main-db -w
```

Wait for:
- Cluster status: `Ready`
- Pods: `lightbridge-main-db-1` running

### Phase 6: Validate Recovery

```bash
# Check cluster status
kubectl get cluster lightbridge-main-db -n converse -o yaml

# Validate data
kubectl exec -it lightbridge-main-db-1 -n converse -- psql -U postgres -c "\dt"

# Verify WAL archiving
kubectl get cluster lightbridge-main-db -n converse -o jsonpath='{.status.conditions[?(@.type=="ContinuousArchiving")]}'
```

### Phase 7: After Recovery

After successful recovery, the `bootstrap.recovery` setting is harmless and can be left in place. It only triggers on empty PVCs, so:

- Pods can be safely deleted and recreated
- New replicas will join using existing PVC data
- No data loss on pod restarts

**No need to remove the recovery configuration** - it won't cause re-recovery as long as PVCs have data.

---

## Approach 3: Point-in-Time Recovery (PITR)

**Use this when:** You need to recover to a specific moment — e.g., just before accidental data deletion, a bad migration, or data corruption at a known time.

**Downtime:** Depends on approach (combines with Alias Services for near-zero downtime, or In-Place for full restore time)

**Prerequisite:** WAL archiving must be enabled (it is — `archive_timeout: 30min`). The maximum data loss window is up to 30 minutes of WAL not yet archived.

### How It Works

PITR replays WAL segments on top of the most recent base backup up to a target you specify. CNPG automatically selects the closest base backup before your target and replays WAL from there.

```
Base Backup (2AM) ──── WAL segments ────► Target Time (e.g., 10:45 AM)
                        ▲
                  Replay stops here
```

### Understanding WAL File Names

WAL files in MinIO (under `wals/`) have 24-character hex names following PostgreSQL's naming convention:

```
0000000B  00000023  000000EF
────────  ────────  ────────
Timeline  LSN high  LSN low (segment number)
```

**Deriving the LSN:** Take the middle 8 and last 8 hex characters, separated by `/`, and append `000000`:

```
0000000B00000023000000EF  →  LSN 23/EF000000
```

Each segment covers 16 MiB of WAL data.

**Deriving the timestamp:** The "Last Modified" timestamp in MinIO is when the WAL was archived. With `archive_timeout: 30min`, WALs upload at roughly `:01` and `:31` past the hour. Transactions in that segment happened in the ~30 minutes before the upload timestamp. **Note:** MinIO's console shows timestamps in your browser's local timezone, not UTC. Convert to UTC before using as a `targetTime` (e.g., if your browser is GMT+1, subtract 1 hour).

**Deriving the XID:** Requires inspecting WAL contents with `pg_waldump` on a running pod:

```bash
kubectl exec -it lightbridge-main-db-1 -n converse -- \
  pg_waldump /var/lib/postgresql/data/pgdata/pg_wal/0000000B00000023000000EF 2>/dev/null | head -20
# Output includes tx: <XID>, lsn: <LSN> for each WAL record
```

**In practice, you rarely need to decode WAL filenames.** For most PITR scenarios, identify when the incident happened from application logs or alerts and use `targetTime` with a UTC timestamp a couple of minutes before the incident.

### Recovery Target Options

You can recover to one of these targets (choose **one**):

| Target | Field | Example | Use Case |
|--------|-------|---------|----------|
| **Timestamp** | `targetTime` | `"2026-05-22T10:45:00Z"` | Most common — recover to just before an incident |
| **Transaction ID** | `targetXID` | `"12345"` | Recover up to a specific transaction |
| **Named Restore Point** | `targetName` | `"before-migration-v42"` | Recover to a point created via `SELECT pg_create_restore_point('name')` |
| **LSN** | `targetLSN` | `"0/1234568"` | Recover to a specific WAL position |
| **Immediate** | `targetImmediate` | `true` | Recover to end of backup (consistent state, no WAL replay) |

Additional options:

| Option | Default | Description |
|--------|---------|-------------|
| `exclusive` | `false` | If `true`, stops **before** the target (exclusive). If `false`, includes the target (inclusive). |
| `backupID` | _(auto)_ | Force recovery from a specific base backup instead of letting CNPG auto-select. |

### Step-by-Step: PITR with Alias Services (Recommended)

#### 1. Determine the Target Time

Identify the exact moment you want to recover to. Use UTC timestamps in RFC 3339 format.

```bash
# Check when the incident happened — look at application logs, alerts, etc.
# Example: accidental DELETE happened at 10:47 AM UTC
# Target: recover to 10:45:00 UTC (2 minutes before)
TARGET_TIME="2026-05-22T10:45:00Z"
```

If you need to find a transaction ID instead:

```bash
# Check PostgreSQL logs for the problematic transaction
kubectl logs lightbridge-main-db-1 -n converse | grep -i "DELETE\|DROP\|TRUNCATE"
```

#### 2. Check WAL Coverage

Verify that WAL segments covering your target time exist in the backup:

```bash
# List available base backups
mc ls myminio/ai-ops-backups/lightbridge-main-db/server=lightbridge-main-db/base/

# List WAL files (check timestamps around your target)
mc ls myminio/ai-ops-backups/lightbridge-main-db/server=lightbridge-main-db/wals/

# Check the most recent backup status
kubectl get backups -n converse -l postgresql.cnpg.io/cluster=lightbridge-main-db \
  -o custom-columns='NAME:.metadata.name,STARTED:.status.beginWal,STOPPED:.status.endWal,TIME:.status.startedAt'
```

**Important:** Your target time must be:
- **After** the oldest available base backup
- **Before** the most recently archived WAL segment
- Within the 180-day retention window

#### 3. Create PITR Restore Cluster

Copy the restore template and add `recoveryTarget`:

```yaml
# lightbridge-main-db-restore.yaml — with PITR target
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: lightbridge-main-db-restore
  namespace: converse
  annotations:
    argocd.argoproj.io/sync-wave: "2"
spec:
  instances: 2
  imageName: ghcr.io/cloudnative-pg/postgresql:18.1-system-trixie
  storage:
    storageClass: linode-block-storage
    size: 5Gi
  resources:
    limits:
      cpu: 300m
      memory: 1Gi
    requests:
      cpu: 200m
      memory: 500Mi
  postgresUID: 26
  postgresGID: 26
  plugins:
    - name: barman-cloud.cloudnative-pg.io
      isWALArchiver: true
      parameters:
        barmanObjectName: lightbridge-main-db
        serverName: lightbridge-main-db-restore
  bootstrap:
    recovery:
      source: lightbridge-main-db-backup
      recoveryTarget:
        targetTime: "2026-05-22T10:45:00Z"   # <-- YOUR TARGET TIME (UTC, RFC 3339)
        # exclusive: false                    # include the target transaction (default)
        # backupID: "20260522T020000"          # optional: force a specific base backup
  externalClusters:
    - name: lightbridge-main-db-backup
      plugin:
        name: barman-cloud.cloudnative-pg.io
        parameters:
          barmanObjectName: lightbridge-main-db
          serverName: lightbridge-main-db
```

For usage-db (TimescaleDB), apply the same pattern:

```yaml
# lightbridge-usage-db-restore.yaml — with PITR target
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: lightbridge-usage-db-restore
  namespace: converse
  annotations:
    argocd.argoproj.io/sync-wave: "2"
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
  resources:
    limits:
      cpu: 300m
      memory: 1Gi
    requests:
      cpu: 200m
      memory: 500Mi
  postgresql:
    shared_preload_libraries:
      - timescaledb
  postgresUID: 70
  postgresGID: 70
  plugins:
    - name: barman-cloud.cloudnative-pg.io
      isWALArchiver: true
      parameters:
        barmanObjectName: lightbridge-usage-db
        serverName: lightbridge-usage-db-restore
  bootstrap:
    recovery:
      source: lightbridge-usage-db-backup
      recoveryTarget:
        targetTime: "2026-05-22T10:45:00Z"   # <-- YOUR TARGET TIME (UTC, RFC 3339)
  externalClusters:
    - name: lightbridge-usage-db-backup
      plugin:
        name: barman-cloud.cloudnative-pg.io
        parameters:
          barmanObjectName: lightbridge-usage-db
          serverName: lightbridge-usage-db
```

#### 4. Apply and Monitor

```bash
kubectl apply -f docs/cnpg-native-backup/lightbridge-main-db-restore.yaml
kubectl apply -f docs/cnpg-native-backup/lightbridge-usage-db-restore.yaml

# Watch recovery progress
kubectl get clusters.postgresql.cnpg.io -n converse -w

# Check recovery logs — look for "recovery stopping" at your target
kubectl logs lightbridge-main-db-restore-1 -n converse | grep -i "recovery\|consistent\|redo"
```

Expected log output when PITR succeeds:

```
LOG:  starting point-in-time recovery to "2026-05-22 10:45:00+00"
LOG:  consistent recovery state reached
LOG:  recovery stopping before commit of transaction ...
LOG:  redo done
```

#### 5. Validate the Recovery Point

This is the most critical step — confirm the data state matches your expectation:

```bash
# Connect to the restored cluster
kubectl exec -it lightbridge-main-db-restore-1 -n converse -- psql -U postgres

# Check that data deleted after your target time is present
# Check that data inserted after your target time is absent
# Example:
#   SELECT count(*) FROM my_table WHERE created_at < '2026-05-22T10:45:00Z';
#   SELECT count(*) FROM my_table WHERE created_at > '2026-05-22T10:45:00Z';  -- should be 0 or near-0
```

#### 6. Switch Traffic and Cleanup

Follow **Approach 1, Phases 5-8** (switch alias service selectors, verify, cleanup old cluster).

### Step-by-Step: PITR with In-Place Recovery

Same as Approach 2 above, but add `recoveryTarget` to the `bootstrap.recovery` section:

```yaml
spec:
  bootstrap:
    recovery:
      source: lightbridge-main-db-backup
      recoveryTarget:
        targetTime: "2026-05-22T10:45:00Z"
```

Then follow Approach 2, Phases 2-7.

### Using Named Restore Points (Proactive)

For planned risky operations (migrations, bulk deletes), create named restore points **before** the operation:

```bash
# Before running a migration
kubectl exec -it lightbridge-main-db-1 -n converse -- \
  psql -U postgres -c "SELECT pg_create_restore_point('before-migration-v42');"
```

Then recover to it:

```yaml
recoveryTarget:
  targetName: "before-migration-v42"
```

### PITR Limitations

- **Maximum data loss window:** Up to 30 minutes (the `archive_timeout` interval). WAL not yet archived at crash time is lost.
- **WAL gaps:** If WAL archiving was interrupted (e.g., S3 outage), recovery cannot proceed past the gap.
- **Forward only:** Once you recover to a point, you cannot "fast-forward" to a later point on the same cluster. Create a new restore cluster if you need a different target.
- **TimescaleDB:** PITR works with TimescaleDB but continuous aggregates may need manual refresh after recovery:

  ```bash
  kubectl exec -it lightbridge-usage-db-restore-1 -n converse -- \
    psql -U postgres -d app -c "CALL refresh_continuous_aggregate('my_aggregate', NULL, NULL);"
  ```

---

## 🔄 Rollback Procedure

### For Alias Services Approach

If something goes wrong after switching:

```bash
# Revert alias service selector to original cluster
# Edit docs/cnpg-native-backupvalues.yaml
# Change selector back to original cluster names:
#   cnpg.io/cluster: lightbridge-main-db
#   cnpg.io/cluster: lightbridge-usage-db

git add docs/cnpg-native-backupvalues.yaml
git commit -m "fix(db-recovery): rollback to original clusters"
git push
```

### For In-Place Recovery

If recovery fails:

```bash
# Delete failed recovery cluster
kubectl delete cluster lightbridge-main-db -n converse
kubectl delete pvc -n converse -l postgresql.cnpg.io/cluster=lightbridge-main-db

# Try alternative backup (if available)
# Modify externalClusters.parameters.serverName to point to specific backup time
```

---

## 📊 Backup Information

| Cluster | Backup Location | ObjectStore Name |
|---------|-----------------|------------------|
| lightbridge-main-db | s3://ai-ops-backups/lightbridge-main-db/ | lightbridge-main-db |
| lightbridge-usage-db | s3://ai-ops-backups/lightbridge-usage-db/ | lightbridge-usage-db |

**MinIO Endpoint:** https://s3.ssegning.me

---

## 📝 Application Connection Strings

Applications should connect using CNPG's built-in services:

```yaml
# Main DB (read/write)
DATABASE_URL: postgres://user:pass@lightbridge-main-db-rw.converse.svc.cluster.local:5432/app

# Main DB (read-only)
DATABASE_URL: postgres://user:pass@lightbridge-main-db-ro.converse.svc.cluster.local:5432/app

# Usage DB (read/write)
DATABASE_URL: postgres://user:pass@lightbridge-usage-db-rw.converse.svc.cluster.local:5432/app
```

**Service Types:**

- `lightbridge-main-db-rw` → Primary (read/write)
- `lightbridge-main-db-ro` → Replicas (read-only)
- `lightbridge-main-db-r` → Any replica (round-robin)

---

## 🆘 Emergency Contacts

- **Database Team:** [Contact]
- **Platform Team:** [Contact]
- **On-Call:** [Link to PagerDuty]

---

## 📝 Quick Reference

```bash
# Check cluster status
kubectl get clusters.postgresql.cnpg.io -n converse

# Check pods
kubectl get pods -n converse -l cnpg.io/cluster=lightbridge-main-db

# Check services
kubectl get svc -n converse | grep lightbridge

# Validate data
kubectl exec -it lightbridge-main-db-1 -n converse -- psql -U postgres -c "\dt"

# Check backup status
kubectl get backups -n converse

# Trigger manual backup
kubectl cnpg backup -n converse lightbridge-main-db --method=plugin --plugin-name=barman-cloud.cloudnative-pg.io

# Check WAL archiving
kubectl get cluster lightbridge-main-db -n converse -o jsonpath='{.status.conditions[?(@.type=="ContinuousArchiving")]}'

# List backups in MinIO
mc ls myminio/ai-ops-backups/lightbridge-main-db/data/
