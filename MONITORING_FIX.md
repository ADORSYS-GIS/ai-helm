# Monitoring Stack Fix

## Issues Identified

1. **Memory Quota Exceeded**: Alloy and Grafana pods cannot start due to `monitoring-quota` having only 512Mi memory limit
2. **Quota Ownership Conflict**: The quota is owned by `ai-alloy` app but should be owned by `mimir` app
3. **Loki Template Error**: Missing `bucketNames` at the correct level in storage config
4. **Incorrect Sync Wave Order**: Alloy (collector) was deploying before Mimir/Loki (storage backends)

## Current State

```bash
# Current quota (WRONG - too low)
requests.memory: 512Mi
used: 370Mi (alloy 256Mi + tempo 64Mi + overhead)

# Desired quota (from mimir config)
requests.memory: 8Gi
```

## Root Cause Analysis

### Sync Wave Anti-Pattern (FIXED)
**Before:**
- Wave -2: Alloy (collector) ❌
- Wave -1: Mimir, Loki, Tempo (storage) ❌

**Problem:** Alloy deployed first and created the namespace with a 512Mi quota, preventing Mimir's correct 8Gi quota from being applied.

**After (CORRECT):**
- Wave -2: Mimir, Loki, Tempo (storage backends with quota) ✅
- Wave -1: Alloy (collector) ✅
- Wave 0: Grafana (visualization) ✅

### Why This Order Matters

1. **Storage backends must exist before collectors** - Alloy needs Mimir and Loki endpoints to send data to
2. **Namespace infrastructure (quotas) should deploy with the first app** - Mimir now creates the namespace with correct quota
3. **Collectors depend on storage** - Alloy config references `mimir-nginx` and `loki-gateway` services

This follows the standard monitoring architecture pattern:
```
Infrastructure (quotas/limits) → Storage (Mimir/Loki/Tempo) → Collection (Alloy) → Visualization (Grafana)
```

## Fixes Applied

### 1. ✅ Loki Storage Configuration Fixed
Moved `bucketNames` from under `s3` to the `storage` level to match Loki chart expectations.

### 2. ✅ Sync Wave Order Corrected
- Mimir: -1 → -2 (storage backend, creates namespace with correct quota)
- Loki: -1 → -2 (storage backend)
- Tempo: -1 → -2 (storage backend)
- Alloy: -2 → -1 (collector, now deploys after storage)
- Grafana: 0 (unchanged, visualization layer)

### 3. ⚠️ Quota Ownership Transfer Required (Manual Step)

The monitoring quota is currently tracked by ArgoCD as belonging to the `alloy` application:
```
argocd.argoproj.io/tracking-id: ai-alloy:/ResourceQuota:monitoring/monitoring-quota
```

But it's defined in the `mimir` application's `extraObjects` with the correct 8Gi limit.

## Manual Steps Required

### Recommended Approach: Clean Slate Deployment

Since the sync wave order has been corrected, the cleanest approach is to delete and redeploy in the correct order:

```bash
# 1. Delete the old quota (owned by alloy)
kubectl delete resourcequota monitoring-quota -n monitoring

# 2. Sync in the correct order (storage backends first)
argocd app sync mimir    # Wave -2: Creates namespace with correct 8Gi quota
argocd app sync loki     # Wave -2: Storage backend
argocd app sync tempo    # Wave -2: Storage backend

# 3. Wait for storage backends to be healthy
argocd app wait mimir --health
argocd app wait loki --health
argocd app wait tempo --health

# 4. Now sync the collector (depends on storage)
argocd app sync alloy    # Wave -1: Collector

# 5. Finally sync visualization
argocd app sync grafana  # Wave 0: Visualization

# 6. Verify the new quota
kubectl get resourcequota monitoring-quota -n monitoring -o yaml | grep -A 10 "spec:"
# Should show: requests.memory: 8Gi
```

### Alternative: Patch Existing Quota (If You Can't Redeploy)

### Alternative: Patch Existing Quota (If You Can't Redeploy)

```bash
# 1. Patch the quota to increase memory limit
kubectl patch resourcequota monitoring-quota -n monitoring --type=merge -p '
{
  "spec": {
    "hard": {
      "requests.cpu": "4",
      "requests.memory": "8Gi",
      "limits.cpu": "16",
      "limits.memory": "24Gi",
      "count/pods": "40"
    }
  }
}'

# 2. Update the tracking annotation to point to mimir
kubectl annotate resourcequota monitoring-quota -n monitoring \
  argocd.argoproj.io/tracking-id=mimir:/ResourceQuota:monitoring/monitoring-quota \
  --overwrite

# 3. Sync applications (they will now respect the new sync wave order)
argocd app sync mimir loki tempo alloy grafana
```

## Verification

After applying the fix, verify all pods are running:

```bash
# Check quota usage
kubectl get resourcequota monitoring-quota -n monitoring

# Expected output should show:
# requests.memory: 370Mi/8Gi (plenty of headroom)

# Check all monitoring pods
kubectl get pods -n monitoring

# All pods should be Running:
# - alloy-* (DaemonSet - one per node)
# - grafana-*
# - loki-*
# - mimir-*
# - tempo-*
```

## Root Cause

The issue occurred because of an **anti-pattern in sync wave ordering**:

1. **Alloy deployed first** (sync-wave -2) before storage backends
2. **Alloy created the namespace** and somehow a 512Mi quota was applied (possibly from an old config or default)
3. **Mimir deployed second** (sync-wave -1) but couldn't update the existing quota
4. **Mimir's correct 8Gi quota definition was ignored** because the resource already existed

### Why the Original Order Was Wrong

```
❌ WRONG: Collector → Storage
- Alloy (collector) at wave -2
- Mimir/Loki/Tempo (storage) at wave -1
- Problem: Collector has nowhere to send data, creates namespace prematurely
```

```
✅ CORRECT: Storage → Collector
- Mimir/Loki/Tempo (storage) at wave -2
- Alloy (collector) at wave -1
- Benefit: Storage backends exist with correct quota, collector can immediately send data
```

This follows the fundamental monitoring architecture principle:
**Infrastructure → Storage → Collection → Visualization**

## Prevention

1. ✅ **Sync wave order corrected** - Storage backends now deploy before collectors
2. ✅ **Quota ownership clarified** - Only Mimir defines the monitoring-quota
3. ✅ **Loki storage config fixed** - Template will now render correctly
4. 📝 **Document the pattern** - Storage must always precede collection in monitoring stacks
