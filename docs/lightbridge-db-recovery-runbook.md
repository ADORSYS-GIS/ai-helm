# Lightbridge Database Recovery Runbook

A GitOps-based disaster recovery procedure for CloudNativePG clusters in the `converse` namespace.

## 📋 Overview

This runbook documents the recovery strategy for two CNPG clusters:
- `lightbridge-main-db` - Main PostgreSQL database
- `lightbridge-usage-db` - TimescaleDB for usage tracking

## ⚠️ Important: CNPG Webhook Restriction

**READ THIS BEFORE STARTING RECOVERY**

CloudNativePG has an admission webhook that prevents enabling WAL archiver plugins when `barmanObjectStore` is configured in `externalClusters`. This causes the error:

```
spec.plugins: Invalid value: ["barman-cloud.cloudnative-pg.io"]: 
Cannot enable a WAL archiver plugin when barmanObjectStore is configured
```

**Solution: Two-Phase Deployment**

| Phase | Action | Plugins |
|-------|--------|---------|
| Phase 1 | Deploy restore cluster, recover from backup | **DISABLED** |
| Phase 2 | After recovery complete, enable WAL archiving | **ENABLED** |

This means:
1. Restore cluster deploys WITHOUT plugins → recovery succeeds
2. After validation, you uncomment plugins → WAL archiving enables
3. Then you can switch traffic

## 🎯 Recovery Strategy

The recovery follows a **create → validate → switch** pattern:

```
1. Create alias services (pointing to current healthy cluster)
2. Create restore clusters from backup (different names)
3. Validate data integrity
4. Enable WAL archiving (Phase 2 - due to CNPG webhook restriction)
5. Switch traffic via alias service selector
6. Cleanup old cluster
```

⚠️ **Important: CNPG Webhook Restriction**

Due to a CNPG admission webhook that blocks enabling WAL archiver plugins when `barmanObjectStore` is configured in externalClusters, recovery requires **two-phase deployment**:

- **Phase 1**: Deploy restore cluster WITHOUT plugins (allows recovery)
- **Phase 2**: After recovery is complete, enable WAL archiving by uncommenting plugins

This is documented in the Phase 2 and Phase 4 sections below.

## 🔧 Prerequisites

- ArgoCD managing the `ai-helm` repo
- Backup available in MinIO: `s3://ai-ops-backups/lightbridge-cnpg-backups/`
- Secrets `lightbridge-cnpg-s3` exists in `converse` namespace
- Barman-cloud plugin installed in `cnpg-system`

---

## Phase 1: Create Alias Services (Pre-Recovery)

Create stable alias services that apps will use. This should be done **before any recovery** to establish the pattern.

The alias services are defined in `charts/apps/values.yaml` under the lightbridge-backend application (rawResources section). They will be created automatically when ArgoCD syncs the application.

### Verify

```bash
kubectl get svc -n converse lightbridge-main-db-primary lightbridge-usage-db-primary
```

Expected output:
```
NAME                           TYPE        CLUSTER-IP     PORT(S)
lightbridge-main-db-primary    ClusterIP   10.x.x.x       5432/TCP
lightbridge-usage-db-primary   ClusterIP   10.x.x.x       5432/TCP
```

### Check Points To Current Cluster

```bash
kubectl get endpoints -n converse lightbridge-main-db-primary -o jsonpath='{.subsets[0].addresses[0].targetRef.name}'
kubectl get endpoints -n converse lightbridge-usage-db-primary -o jsonpath='{.subsets[0].addresses[0].targetRef.name}'
```

Should return:
- `lightbridge-main-db-1` (primary)
- `lightbridge-usage-db-1` (primary)

---

## Phase 2: Create Restore Clusters

When a cluster fails, create new clusters restored from backup.

### Step 1: Create Restore Manifest

⚠️ **IMPORTANT: CNPG Webhook Restriction**

Due to a CNPG webhook that blocks enabling WAL archiver plugins when barmanObjectStore is configured, you must use **two-phase deployment**:

- **Phase 1**: Deploy WITHOUT plugins (recovery only)
- **Phase 2**: After recovery is complete, enable WAL archiving

The restore manifests in this repo have plugins commented out by default.

Create `lightbridge-main-db-restore.yaml`:

```yaml
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
  # Phase 1: NO plugins - recovery only (webhook blocks plugins + barmanObjectStore conflict)
  # Phase 2 (after recovery): Uncomment below to enable WAL archiving
  # plugins:
  #   - name: barman-cloud.cloudnative-pg.io
  #     isWALArchiver: true
  #     parameters:
  #       barmanObjectName: lightbridge-barman-store
  #       serverName: lightbridge-main-db-restore
  bootstrap:
    recovery:
      source: lightbridge-main-db-backup
  externalClusters:
    - name: lightbridge-main-db-backup
      plugin:
        name: barman-cloud.cloudnative-pg.io
        parameters:
          barmanObjectName: lightbridge-barman-store
          serverName: lightbridge-main-db
```

Create `lightbridge-usage-db-restore.yaml`:

```yaml
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
  # Phase 1: NO plugins - recovery only (webhook blocks plugins + barmanObjectStore conflict)
  # Phase 2 (after recovery): Uncomment below to enable WAL archiving
  # plugins:
  #   - name: barman-cloud.cloudnative-pg.io
  #     isWALArchiver: true
  #     parameters:
  #       barmanObjectName: lightbridge-barman-store
  #       serverName: lightbridge-usage-db-restore
  bootstrap:
    recovery:
      source: lightbridge-usage-db-backup
  externalClusters:
    - name: lightbridge-usage-db-backup
      plugin:
        name: barman-cloud.cloudnative-pg.io
        parameters:
          barmanObjectName: lightbridge-barman-store
          serverName: lightbridge-usage-db
```

### Step 2: Commit and Push

```bash
git add charts/apps/lightbridge-main-db-restore.yaml charts/apps/lightbridge-usage-db-restore.yaml
git commit -m "feat(db-recovery): add restore clusters for lightbridge databases"
git push origin feat/lightbridge-db-recovery-runbook
```

### Step 3: Watch ArgoCD Sync

```bash
kubectl get clusters.postgresql.cnpg.io -n converse -w
```

Wait for:
- `lightbridge-main-db-restore` → Ready
- `lightbridge-usage-db-restore` → Ready

---

## Phase 3: Validate Data

### Step 1: Check Pods Running

```bash
kubectl get pods -n converse -l cnpg.io/cluster=lightbridge-main-db-restore
kubectl get pods -n converse -l cnpg.io/cluster=lightbridge-usage-db-restore
```

### Step 2: Validate Main DB

```bash
kubectl exec -it lightbridge-main-db-restore-1 -n converse -- psql -U postgres -c "\dt"
```

Expected: Tables from your application (check with app team)

### Step 3: Validate Usage DB

```bash
kubectl exec -it lightbridge-usage-db-restore-1 -n converse -- psql -U postgres -d app -c "\dt"
```

Expected: Tables including `usage_events`

### Step 4: Check Row Counts

```bash
# Usage DB specific check
kubectl exec -it lightbridge-usage-db-restore-1 -n converse -- psql -U postgres -d app -c "SELECT count(*) FROM usage_events;"
```

Compare with expected data (check with app team).

### Step 5: Verify TimescaleDB Extension

```bash
kubectl exec -it lightbridge-usage-db-restore-1 -n converse -- psql -U postgres -d app -c "SELECT extversion FROM pg_extension WHERE extname = 'timescaledb';"
```

---

## Phase 4: Enable WAL Archiving (Phase 2)

⚠️ **IMPORTANT**: This step is required due to CNPG webhook restriction.

The restore cluster was deployed WITHOUT plugins (Phase 1). Now that recovery is complete, you must enable WAL archiving.

### Step 1: Uncomment Plugins in Restore Manifests

Edit `charts/apps/lightbridge-main-db-restore.yaml`:

```yaml
# Change from:
# plugins:
#   - name: barman-cloud.cloudnative-pg.io

# To:
plugins:
  - name: barman-cloud.cloudnative-pg.io
    isWALArchiver: true
    parameters:
      barmanObjectName: lightbridge-barman-store
      serverName: lightbridge-main-db-restore
```

Edit `charts/apps/lightbridge-usage-db-restore.yaml` similarly.

### Step 2: Commit and Push

```bash
git add charts/apps/lightbridge-main-db-restore.yaml charts/apps/lightbridge-usage-db-restore.yaml
git commit -m "fix(db-recovery): enable WAL archiving on restored clusters"
git push
```

### Step 3: Verify WAL Archiving Enabled

```bash
kubectl get clusters.postgresql.cnpg.io -n converse lightbridge-main-db-restore -o jsonpath='{.status.conditions[?(@.type=="ContinuousArchiving")].status}'
# Should return: True

kubectl get clusters.postgresql.cnpg.io -n converse lightbridge-usage-db-restore -o jsonpath='{.status.conditions[?(@.type=="ContinuousArchiving")].status}'
# Should return: True
```

---

## Phase 5: Switch Traffic

### Option A: Update Alias Service Selector (Recommended)

Update `charts/apps/values.yaml` (lightbridge-backend application rawResources section):

Find the alias service definitions and update the selector:

```yaml
# For main-db
spec:
  selector:
    cnpg.io/cluster: lightbridge-main-db-restore
    cnpg.io/instanceRole: primary

# For usage-db
spec:
  selector:
    cnpg.io/cluster: lightbridge-usage-db-restore
    cnpg.io/instanceRole: primary
```

Commit and push:
```bash
git add charts/apps/values.yaml
git commit -m "fix(db-recovery): switch alias services to restored clusters"
git push
```

### Step 2: Verify Switch

```bash
# Check endpoints now point to restore cluster
kubectl get endpoints -n converse lightbridge-main-db-primary -o jsonpath='{.subsets[0].addresses[0].targetRef.name}'
kubectl get endpoints -n converse lightbridge-usage-db-primary -o jsonpath='{.subsets[0].addresses[0].targetRef.name}'
```

Should now return:
- `lightbridge-main-db-restore-1`
- `lightbridge-usage-db-restore-1`

### Step 3: Validate Applications

Check app logs for database connectivity:
```bash
kubectl logs -n converse -l app.kubernetes.io/instance=lightbridge -f
```

---

## Phase 5: Cleanup

### Option A: Rename Restore to Original (Recommended for Long-Term)

This renames the restore cluster to the original name for clean state.

**Step 1:** Delete old cluster from Git (values.yaml)
- Remove old cluster manifests from `charts/apps/values.yaml`
- Commit and push

**Step 2:** Rename restore cluster
- Edit restore manifest: `lightbridge-main-db-restore` → `lightbridge-main-db`
- Edit restore manifest: `lightbridge-usage-db-restore` → `lightbridge-usage-db`
- Update `serverName` in plugins to match new name
- Commit and push

**Step 3:** Update alias service selector back
- Point selector back to original cluster names
- Commit and push

### Option B: Keep Restore Clusters (Quick Recovery)

Keep restore clusters as the new production state:

**Step 1:** Update alias services selector (already done in Phase 4)

**Step 2:** Optionally rename in Git for clarity
- Rename files: `lightbridge-*-restore.yaml` → `lightbridge-*.yaml`
- Commit and push

---

## 🔄 Rollback Procedure

If something goes wrong after switching:

1. **Revert alias service selector:**
   ```bash
   # Edit charts/apps/templates/lightbridge-db-alias.yaml
   # Change selector back to original cluster names
   cnpg.io/cluster: lightbridge-main-db  # not lightbridge-main-db-restore
   cnpg.io/cluster: lightbridge-usage-db  # not lightbridge-usage-db-restore
   ```

2. **Commit and push** - ArgoCD will update services instantly

3. **Verify** - apps should reconnect to original cluster

---

## 📊 Backup Information

| Cluster | Backup Location | Server Name |
|---------|-----------------|-------------|
| lightbridge-main-db | s3://ai-ops-backups/lightbridge-cnpg-backups/ | lightbridge-main-db |
| lightbridge-usage-db | s3://ai-ops-backups/lightbridge-cnpg-backups/ | lightbridge-usage-db |

**MinIO Endpoint:** https://s3.ssegning.me

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

# Check services
kubectl get svc -n converse | grep lightbridge

# Check pods
kubectl get pods -n converse -l cnpg.io/cluster=lightbridge-main-db-restore

# Validate data
kubectl exec -it lightbridge-usage-db-restore-1 -n converse -- psql -U postgres -d app -c "SELECT count(*) FROM usage_events;"
```