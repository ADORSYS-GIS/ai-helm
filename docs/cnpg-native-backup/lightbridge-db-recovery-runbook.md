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
kubectl apply -f docs/cnpg-native-backuplightbridge-main-db-restore.yaml
kubectl apply -f docs/cnpg-native-backuplightbridge-usage-db-restore.yaml
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
