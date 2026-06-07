# Observability Stack — LGTM Deployment Guide

**Scope:** Deploy and configure a complete observability stack with Grafana, Alertmanager, Tempo (traces), Mimir (metrics), and Loki (logs) via ArgoCD.

**Ticket deliverables covered:**
- Deploy Grafana with OAuth2 (Keycloak) and Apprise notifications
- Deploy Alertmanager for alerting
- Deploy Tempo for distributed tracing
- Deploy Mimir for metrics storage
- Deploy Loki for log aggregation
- Connect Alloy agents to the stack
- Storage & backup strategy, persistence, and retention policy documentation

---

## Table of Contents

1. [What Was Done](#what-was-done)
2. [Architectural Decisions](#architectural-decisions)
3. [Prerequisites (What Is Left To Do)](#prerequisites-what-is-left-to-do)
4. [Storage, Persistence & Retention Policies](#storage-persistence--retention-policies)
   - [Mimir](#mimir)
   - [Loki](#loki)
   - [Tempo](#tempo)
   - [Grafana](#grafana)
   - [How to Change Retention](#how-to-change-retention)
   - [How to Manually Force Compaction / Cleanup](#how-to-manually-force-compaction--cleanup)
   - [Disaster Recovery & Backup Strategy](#disaster-recovery--backup-strategy)
5. [Future Improvements](#future-improvements)
6. [Operational Runbooks](#operational-runbooks)

---

> ⚠️ **Parts of "What Was Done" below are historical** (Linode Object Storage,
> namespace `monitoring`, chart versions 5.3.0/6.6.0). The stack now lives in
> namespace `observability` on Hetzner Object Storage via the App-of-Apps
> orchestrator (`charts/observability`, ADR-0020); current chart versions are
> mimir-distributed 5.8.0 / loki 7.0.0 / tempo 1.24.4. For the *current* topology
> and the answers to "why N pods?", read the next section.

## Topology & component rationale (current)

The full collector → store → visualise pipeline, one collector (**Alloy**),
three stores (**Loki/Mimir/Tempo**), Grafana on top:

| Component | Pods | Role | Notes |
|---|---|---|---|
| **Alloy** | DaemonSet (1/node) | **The only collector** — metrics + logs + traces | Scrapes ServiceMonitor/PodMonitor + kubelet/cAdvisor/apiserver/CoreDNS → remote-write to Mimir; tails `/var/log/pods` → Loki; OTLP `:4317/:4318` → Tempo. No storage, no querying. |
| **Loki** | `loki-0` + `loki-gateway` | Log store (SingleBinary) + nginx entry point | `loki-canary` (synthetic SLA probe) is **disabled** — it was pure noise. All microservice roles at `replicas: 0`. |
| **Mimir** | 7 (distributor, ingester, querier, query-frontend, store-gateway, compactor, nginx) | Metric TSDB (Prometheus-compatible, S3) | `mimir-distributed` is microservices-only — **no monolithic mode**. Dead components/Alertmanager/caches already disabled (ADR-0024). |
| **Tempo** | `tempo-0` | Trace store (single binary) | HTTP API on **`:3200`**, not `:3100`. |
| **Grafana** | 1 | Visualisation | Stateless (ADR-0023); datasources provisioned in-chart. |
| Exporters/CRDs | `kube-state-metrics`, `node-exporter` (DaemonSet), `prometheus-operator-crds` | Metric sources + scrape-target CRDs | **There is no Prometheus server** — these are just sources; Alloy scrapes them and Mimir stores. |

**Why no Prometheus?** Mimir *is* the metrics database. `prometheus-operator-crds`
is CRDs only (ServiceMonitor/PodMonitor); kube-state-metrics and node-exporter are
exporters. Alloy scrapes; Mimir stores. No second TSDB.

**Datasource URLs (in-cluster):** Mimir `http://mimir-nginx.observability…/prometheus`,
Loki `http://loki-gateway.observability…`, Tempo
`http://tempo.observability…:3200`.

> A full point-in-time diagnosis of the 2026-06-07 datasource breakages (Tempo
> `:3100`→`:3200`, Loki mislabeling via line-regex, Mimir empty due to a wedged
> memberlist ring) lives in
> [`2026-06-07-observability-datasource-audit.md`](./2026-06-07-observability-datasource-audit.md).

---

## What Was Done

Four new ArgoCD Applications were added to `charts/apps/values.yaml`, plus an update to the existing Alloy collector:

### 1. Mimir (`mimir-distributed` chart)

- **Chart:** `grafana/mimir-distributed` at `5.3.0`
- **Mode:** Small-cluster — 1 replica per microservice component, zone replication disabled
- **Namespace:** `monitoring`
- **Sync wave:** `-1` (deploys before Grafana)
- **Components deployed:** ingester, distributor, querier, query-frontend, store-gateway, compactor, alertmanager, nginx gateway
- **Storage:** S3-compatible backend (configurable — currently points to Linode Object Storage; can be swapped to MinIO)
- **Buckets:** `converse-mimir-blocks`, `converse-mimir-alertmanager`, `converse-mimir-ruler`
- **Secrets required:** `mimir-s3` (keys: `MIMIR_S3_ACCESS_KEY_ID`, `MIMIR_S3_SECRET_ACCESS_KEY`)
- **ResourceQuota & LimitRange:** Expanded in `extraObjects` to accommodate the full LGTM stack (16 CPU limit, 24 Gi memory, 40 pods)

### 2. Loki (`loki` chart)

- **Chart:** `grafana/loki` at `6.6.0`
- **Mode:** SingleBinary — one pod, all roles in one process
- **Namespace:** `monitoring`
- **Sync wave:** `-1`
- **Storage:** S3-compatible backend
- **Buckets:** `converse-loki-chunks`, `converse-loki-ruler`
- **Secrets required:** `loki-s3` (keys: `LOKI_S3_ACCESS_KEY_ID`, `LOKI_S3_SECRET_ACCESS_KEY`)
- **Schema:** TSDB index (v13), 24h periods
- **Local persistence:** 10 Gi WAL buffer on `linode-block-storage`

### 3. Tempo (`tempo` chart)

- **Chart:** `grafana/tempo` at `1.9.0`
- **Mode:** Single binary (default for this chart)
- **Namespace:** `monitoring`
- **Sync wave:** `-1`
- **Storage:** S3-compatible backend
- **Bucket:** `converse-tempo-traces`
- **Secrets required:** `tempo-s3` (keys: `TEMPO_S3_ACCESS_KEY`, `TEMPO_S3_SECRET_KEY`)
- **Receivers:** OTLP (gRPC 4317, HTTP 4318), Jaeger (thrift_http 14268, gRPC 14250)
- **Metrics generator:** Enabled; writes span metrics to Mimir via `remoteWriteUrl`
- **Local persistence:** 5 Gi WAL on `linode-block-storage`

### 4. Grafana (`grafana` chart)

- **Chart:** `grafana/grafana` at `8.0.0`
- **Namespace:** `monitoring`
- **Sync wave:** `0` (deploys after backends)
- **Auth:** Keycloak OAuth2 (`CDigital` brand); basic login form kept as fallback during rollout
- **Secrets required:** `grafana-admin` (keys: `admin-user`, `admin-password`), `grafana-keycloak` (key: `client-secret`)
- **Unified alerting:** Enabled, pointing to Mimir's built-in Alertmanager
- **Ingress:** `grafana.ai.camer.digital` via Traefik, TLS via cert-manager (`cert-home-cert-http` issuer)
- **Pre-wired datasources:** Mimir (default), Loki, Tempo, Alertmanager (all with cross-linking: traceID in logs, traces-to-logs, service-map to metrics)
- **Dashboards:** Kubernetes cluster (7249), pods (6417), ArgoCD (14584), Loki logs (13639)
- **Persistence:** 2 Gi on `linode-block-storage` for UI-created dashboards and preferences

### 5. Alloy — Updated Collector Configuration

- **Controller:** Changed from `statefulset` to `daemonset` so each node can read its own `/var/log/pods`
- **Clustering:** Kept enabled — coordinates scrape target sharding across DaemonSet pods so no duplicate metrics
- **Mounts:** `varlog: true` (hostPath `/var/log/pods` for log collection)
- **Metrics:** Remote-writes to `http://mimir-nginx.monitoring.svc.cluster.local/api/v1/push`
- **Logs:** New pipeline: `local.file_match` → `loki.source.file` → `loki.process` (regex parses namespace/pod/container from path, JSON extracts `level`/`trace_id`) → `loki.write` to `http://loki-gateway.monitoring.svc.cluster.local/loki/api/v1/push`
- **Removed:** The `extraObjects` ResourceQuota/LimitRange from the Alloy block (now owned by Mimir to avoid ArgoCD ownership conflicts)

---

## Architectural Decisions

### Why not the `k8s-monitoring` chart?

The `k8s-monitoring` Helm chart is a **collection-only** chart. It deploys Alloy collectors, node_exporter, and kube-state-metrics — but it does **not** deploy any backend (Mimir, Loki, Tempo, or Grafana). Our ticket is about deploying backends, so `k8s-monitoring` would add zero value for the deliverables. We already have Alloy configured; we just needed the backends to exist at the other end of Alloy's `remote_write` URLs.

### Why Mimir in "small-cluster" mode instead of single-binary?

Mimir does not have a single-binary mode like Loki or Tempo. The `mimir-distributed` chart deploys microservices. For a small cluster, we set:
- 1 replica per component
- `zoneAwareReplication.enabled: false`
- `query_scheduler.enabled: false`

This keeps the deployment lean while still getting the production-grade architecture (separate ingester, querier, compactor, etc.). If the cluster grows, you only need to bump `replicas` and re-enable zone replication — no chart swap required.

### Why Alertmanager inside Mimir instead of a standalone deployment?

Mimir ships with a built-in Alertmanager that uses the same S3 backend for config storage. Grafana's unified alerting can talk to it directly via `http://mimir-nginx/alertmanager`. This saves us from running a 5th application and gives us multi-tenant alert config storage for free. If we ever need a standalone Alertmanager (e.g., for non-Mimir alert routing), we can add it later without conflict.

### Why Loki in SingleBinary mode?

Loki supports two deployment shapes:
- **SingleBinary:** One pod runs ingester, querier, distributor, etc. Perfect for small clusters.
- **SimpleScalable / Distributed:** Separate pods per role. Overkill for our size.

We disabled all distributed components (`ingester: {replicas: 0}`, etc.) and rely on the `singleBinary` block. The `gateway` (nginx) still provides a stable `loki-gateway` service endpoint for Alloy and Grafana.

### Why Alloy as a DaemonSet (not StatefulSet + DaemonSet split)?

Grafana's `k8s-monitoring` v3 uses five specialized Alloy instances (e.g., `alloy-logs` as DaemonSet + `alloy-metrics` as StatefulSet). For our 3–5 node cluster, this is operational overhead with no benefit.

Alloy's clustering protocol works in DaemonSet mode: pods discover each other and shard scrape targets automatically. One DaemonSet Alloy per node handles both metrics scraping (via ServiceMonitor discovery) and log tailing (via hostPath). We keep clustering enabled to prevent duplicate scrapes.

### Why S3 object storage instead of local PVCs for long-term data?

Metrics, logs, and traces grow unbounded. PVC-based storage would eventually fill up and require manual expansion or deletion. Object storage (S3/MinIO) provides:
- Elastic capacity
- Cheaper per-GB cost
- Built-in durability (replication)
- Easy backup/restore by copying buckets

Only write-ahead logs (WAL) and temporary compaction data live on local PVCs.

### Why single-tenant mode for Mimir and Loki?

Both Mimir (`multitenancy_enabled: false`) and Loki (`auth_enabled: false`) are configured as single-tenant. This means:
- No `X-Scope-OrgID` header required from Alloy or Grafana
- Simpler configuration and debugging
- All data lives in one logical tenant

If multi-tenancy is needed later (e.g., per-team billing or isolation), it can be enabled by flipping these booleans and updating Alloy's `external_labels` to include `__tenant_id__`.

---

## Prerequisites (What Is Left To Do)

Before the ArgoCD `apps` Application syncs successfully, the following must be in place:

### 1. S3 / Object Storage Buckets

Create these buckets in your S3 provider (MinIO, Linode, AWS, etc.):

| Bucket | Owner | Purpose |
|--------|-------|---------|
| `converse-mimir-blocks` | Mimir | TSDB blocks (compressed metric samples) |
| `converse-mimir-alertmanager` | Mimir | Alertmanager notification configs |
| `converse-mimir-ruler` | Mimir | Recording/alerting rules (currently disabled) |
| `converse-loki-chunks` | Loki | Compressed log chunks |
| `converse-loki-ruler` | Loki | Alert/recording rules (optional) |
| `converse-tempo-traces` | Tempo | Trace objects (Parquet / v2 formats) |

### 2. External Secrets (via ESO)

Provision these secrets in your secrets backend (Vault, AWS Secrets Manager, etc.) and ensure ESO syncs them into the `monitoring` namespace:

**`mimir-s3`**
```yaml
MIMIR_S3_ACCESS_KEY_ID:     <your-access-key>
MIMIR_S3_SECRET_ACCESS_KEY: <your-secret-key>
```

**`loki-s3`**
```yaml
LOKI_S3_ACCESS_KEY_ID:     <your-access-key>
LOKI_S3_SECRET_ACCESS_KEY: <your-secret-key>
```

**`tempo-s3`**
```yaml
TEMPO_S3_ACCESS_KEY: <your-access-key>
TEMPO_S3_SECRET_KEY: <your-secret-key>
```

**`grafana-admin`**
```yaml
admin-user:     admin
admin-password: <strong-random-password>
```

**`grafana-keycloak`**
```yaml
client-secret: <keycloak-client-secret>
```

### 3. Keycloak Client Configuration

Create a client named `grafana` in the `camer-digital` realm with:
- **Client ID:** `grafana`
- **Client Authenticator:** Client ID and Secret
- **Valid Redirect URIs:** `https://grafana.ai.camer.digital/login/generic_oauth`
- **Web Origins:** `https://grafana.ai.camer.digital`
- **Protocol:** `openid-connect`
- **Mappers:** Add a "roles" mapper so the `roles` claim appears in the ID token / userinfo response

### 4. DNS & Ingress

Ensure `grafana.ai.camer.digital` resolves to your cluster's Traefik ingress. The Grafana Application includes a Traefik `Ingress` with cert-manager TLS — no manual certificate creation needed.

### 5. S3 Endpoint Swap (If Using MinIO)

If you are using MinIO (`s3.ssegning.me`) instead of Linode Object Storage, update the following fields **before sync**:

- **Mimir** (`mimir.structuredConfig.common.s3.endpoint`)
- **Loki** (`loki.storage.s3.endpoint`)
- **Tempo** (`tempo.storage.trace.s3.endpoint`)

All three already have `s3ForcePathStyle: true` / `forcepathstyle: true` set, which is required for MinIO.

---

## Storage, Persistence & Retention Policies

### Mimir

#### What is stored where

| Location | Type | Purpose | Persistence |
|----------|------|---------|-------------|
| S3 bucket (`converse-mimir-blocks`) | Object storage | Compressed TSDB blocks (the actual metric data) | Permanent |
| S3 bucket (`converse-mimir-alertmanager`) | Object storage | Alertmanager configuration YAML | Permanent |
| S3 bucket (`converse-mimir-ruler`) | Object storage | Recording/alerting rules (when ruler enabled) | Permanent |
| Local PVC (ingester) | Block storage | Active WAL + head block (metrics received in last ~2h) | Ephemeral; flushed to S3 |
| Local PVC (compactor) | Block storage | Temporary compaction workspace | Ephemeral |

#### Retention policy

```yaml
mimir:
  structuredConfig:
    limits:
      compactor_blocks_retention_period: 90d
```

- **Default:** 90 days of metrics
- **How it works:** The compactor periodically scans blocks in S3 and deletes any block whose data is older than 90 days. The compactor also downsamples blocks over time (5m → 1h aggregation).
- **Ingestion guardrails:**
  - `ingestion_rate: 30000` samples/sec
  - `ingestion_burst_size: 50000`
  - `max_global_series_per_user: 2000000`

#### How to change retention

Edit `charts/apps/values.yaml` and modify:

```yaml
mimir:
  structuredConfig:
    limits:
      compactor_blocks_retention_period: 90d   # change to desired duration
```

Commit, push, and let ArgoCD sync. The compactor will pick up the new retention on its next compaction cycle (runs every few hours). No restart required.

To apply immediately, port-forward to the compactor and trigger a manual compaction (see [Operational Runbooks](#operational-runbooks)).

#### What happens when ingester PVC fills up?

The ingester WAL is bounded by the 2-hour head block window. Old data is flushed to S3 automatically. If the PVC is still filling, the ingester will back-pressure and reject new samples. The PVC size is not explicitly set in our values (relies on default storage class). If you see disk pressure warnings, add a `persistence` block to the ingester section or scale the ingester replicas.

---

### Loki

#### What is stored where

| Location | Type | Purpose | Persistence |
|----------|------|---------|-------------|
| S3 bucket (`converse-loki-chunks`) | Object storage | Compressed log chunks (Snappy + gzip) | Permanent |
| S3 bucket (`converse-loki-ruler`) | Object storage | Alert/recording rules (if enabled) | Permanent |
| Local PVC (`singleBinary.persistence`) | Block storage | WAL buffer + index cache | 10 Gi; ephemeral relative to S3 |

#### Retention policy

```yaml
loki:
  limits_config:
    retention_period: 90d
  compactor:
    retention_enabled: true
```

- **Default:** 90 days of logs
- **How it works:** The compactor (which runs inside the SingleBinary pod) scans the index for chunks older than 90 days and marks them for deletion. The S3 bucket lifecycle policy should also be configured to permanently delete these marked objects.

#### How to change retention

Edit `charts/apps/values.yaml`:

```yaml
loki:
  limits_config:
    retention_period: 90d   # change to desired duration
```

Then sync. The compactor will enforce the new retention on its next pass. If you want logs to be kept longer, increase this value and also ensure your S3 bucket has no conflicting lifecycle rule.

#### Log ingestion limits

```yaml
loki:
  limits_config:
    ingestion_rate_mb: 8
    ingestion_burst_size_mb: 16
```

These prevent a single noisy pod from saturating Loki. If you have high-volume log producers, raise these values.

---

### Tempo

#### What is stored where

| Location | Type | Purpose | Persistence |
|----------|------|---------|-------------|
| S3 bucket (`converse-tempo-traces`) | Object storage | Trace objects (Parquet or v2 format) | Permanent |
| Local PVC (`persistence`) | Block storage | WAL for recent traces before S3 flush | 5 Gi; ephemeral relative to S3 |

#### Retention policy

```yaml
tempo:
  retention: 720h   # 30 days
```

- **Default:** 30 days of traces
- **Why shorter than metrics/logs?** Traces are voluminous. A single request can generate dozens of spans. 30 days is typically sufficient for debugging production issues.
- **How it works:** Tempo's blocklist manager scans S3 blocks and deletes those whose `endTime` is older than 720 hours.

#### How to change retention

Edit `charts/apps/values.yaml`:

```yaml
tempo:
  retention: 720h   # e.g., 1440h for 60 days
```

Sync. Tempo will enforce the new retention on its next blocklist scan cycle.

---

### Grafana

#### What is stored where

| Location | Type | Purpose | Persistence |
|----------|------|---------|-------------|
| Local PVC (`persistence`) | Block storage | SQLite database (dashboards, users, preferences, alert rules) | 2 Gi; backed up manually |
| S3 (via Mimir/Loki/Tempo) | Object storage | All metric/log/trace data | Permanent |

Grafana itself does not store telemetry — it queries the backends. The PVC only holds:
- Dashboard definitions created via the UI
- User preferences and org memberships
- Alert rules (when not using Mimir ruler)

#### Retention / Backup

There is no automatic retention on the Grafana PVC because it is small and state is mostly config. For disaster recovery:

1. **Dashboards as code:** Pre-loaded dashboards are defined in `values.yaml` and restored automatically on reinstall.
2. **UI-created dashboards:** Export as JSON and commit to git, or back up the PVC with Velero / a CronJob.
3. **Alert rules:** If using Grafana's unified alerting (not Mimir ruler), rules are stored in the SQLite DB. Use the Grafana Alerting API to export them:
   ```bash
   curl -H "Authorization: Bearer $API_KEY" \
     http://grafana.ai.camer.digital/api/v1/provisioning/alert-rules
   ```

---

## How to Change Retention

The following table summarizes the single field to edit for each backend:

| Backend | Field in `values.yaml` | Default | Granularity |
|---------|------------------------|---------|-------------|
| **Mimir** | `mimir.structuredConfig.limits.compactor_blocks_retention_period` | `90d` | Day-level (e.g., `30d`, `180d`, `1y`) |
| **Loki** | `loki.limits_config.retention_period` | `90d` | Day-level (e.g., `7d`, `30d`, `1y`) |
| **Tempo** | `tempo.retention` | `720h` | Hour-level (e.g., `168h` = 7 days) |
| **Grafana** | PVC backup / dashboards-as-code | N/A | Manual |

### Step-by-step

1. Edit `charts/apps/values.yaml`
2. Change the relevant retention value
3. Commit and push
4. ArgoCD syncs automatically
5. The backend's compactor / blocklist manager picks up the new value on its next scheduled run (no restart needed)

---

## How to Manually Force Compaction / Cleanup

### Mimir

Port-forward to the compactor:

```bash
kubectl port-forward -n monitoring deploy/mimir-compactor 8080:8080
```

Trigger compaction manually (compaction also enforces retention):

```bash
curl -X POST http://localhost:8080/compactor/force-compaction
```

Check compactor ring status:

```bash
curl http://localhost:8080/compactor/ring
```

### Loki

Port-forward to the SingleBinary pod:

```bash
kubectl port-forward -n monitoring svc/loki 3100:3100
```

Check retention status:

```bash
curl http://localhost:3100/loki/api/v1/status/retention
```

Force a compaction/retention pass (requires admin API enabled):

```bash
curl -X POST http://localhost:3100/loki/api/v1/admin/compactor/compact
```

### Tempo

Tempo does not expose a manual compaction API. Retention is enforced automatically on the blocklist scan interval (default every few minutes). To verify which blocks are considered for deletion:

```bash
kubectl port-forward -n monitoring svc/tempo 3100:3100
curl http://localhost:3100/api/v1/status/tenantblocks
```

---

## Disaster Recovery & Backup Strategy

### Object Storage (S3 / MinIO) — Primary Data

All long-term data lives in object storage. The disaster recovery strategy is **bucket-level replication or snapshot**:

| Approach | Tool | Notes |
|----------|------|-------|
| **MinIO bucket replication** | MinIO Admin API | Set up site replication or bucket mirroring to a second MinIO cluster |
| **S3 cross-region replication** | Provider feature | If using Linode/AWS, enable bucket replication to a different region |
| **Rclone / mc mirror CronJob** | Kubernetes CronJob | Periodically `mc mirror` or `rclone sync` buckets to a secondary location |
| **Velero** | Velero + restic | Backs up PVCs (WAL) but not S3 data; use for Grafana PVC only |

#### Recommended: Rclone mirror CronJob

Create a CronJob in the `monitoring` namespace that runs nightly:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: observability-s3-backup
  namespace: monitoring
spec:
  schedule: "0 3 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: rclone
              image: rclone/rclone:latest
              command:
                - /bin/sh
                - -c
                - |
                  rclone sync s3-primary:converse-mimir-blocks s3-backup:converse-mimir-blocks
                  rclone sync s3-primary:converse-loki-chunks s3-backup:converse-loki-chunks
                  rclone sync s3-primary:converse-tempo-traces s3-backup:converse-tempo-traces
              envFrom:
                - secretRef:
                    name: rclone-config   # contains RCLONE_CONFIG_S3_PRIMARY_* and RCLONE_CONFIG_S3_BACKUP_*
          restartPolicy: OnFailure
```

### Write-Ahead Logs (PVCs)

The WAL PVCs (Mimir ingester, Loki singleBinary, Tempo) are **ephemeral from a DR perspective** — their only purpose is to buffer data before it is flushed to S3. If a pod is lost:
- **Mimir:** The ingester's WAL is replicated across ingesters (even with 1 replica, the ring handles handoff on restart). Unflushed data may be lost, but this is typically < 2 hours of recent samples.
- **Loki / Tempo:** Unflushed log chunks / traces in WAL are lost on pod deletion. In practice this is minutes of data.

To minimize WAL loss, ensure:
- PVCs use a storage class with `Retain` reclaim policy (not `Delete`)
- Velero backs up the `monitoring` namespace PVCs nightly

### Grafana SQLite Database

The Grafana PVC holds configuration, not telemetry. Backup strategies:

1. **Dashboards as code:** Keep all dashboards in `values.yaml` (already done for community dashboards). UI-created dashboards should be exported and committed.
2. **PVC snapshot:** Use your storage provider's snapshot feature or Velero:
   ```bash
   velero backup create grafana-pvc-backup --include-resources=pvc -n monitoring
   ```
3. **Database dump CronJob:**
   ```yaml
   apiVersion: batch/v1
   kind: CronJob
   metadata:
     name: grafana-db-backup
     namespace: monitoring
   spec:
     schedule: "0 2 * * *"
     jobTemplate:
       spec:
         template:
           spec:
             containers:
               - name: sqlite-backup
                 image: busybox
                 command:
                   - sh
                   - -c
                   - |
                     cp /var/lib/grafana/grafana.db /backups/grafana-$(date +%F).db
                 volumeMounts:
                   - name: grafana-storage
                     mountPath: /var/lib/grafana
                   - name: backup
                     mountPath: /backups
             volumes:
               - name: grafana-storage
                 persistentVolumeClaim:
                   claimName: grafana
               - name: backup
                 emptyDir: {}
             restartPolicy: OnFailure
   ```

### Restore Procedure

#### Complete stack rebuild

1. Re-install the ArgoCD `apps` Application (or re-create the namespace)
2. All backends will re-connect to the existing S3 buckets and re-hydrate their indices
3. Grafana will come up empty; restore dashboards from git or PVC snapshot
4. Re-create the ESO secrets if they were lost

#### Single backend restore (e.g., Mimir data corruption)

1. Scale the affected backend to 0 replicas
2. Restore the S3 bucket from backup (or delete corrupted blocks and let compactor clean up)
3. Delete the backend's PVCs to clear corrupted local state
4. Scale back up; the backend will rebuild its index from S3

---

## Future Improvements

### Network Policy Toggle

The monitoring namespace NetworkPolicy can be enabled or disabled via:

```yaml
global:
  monitoring:
    networkPolicy:
      enabled: true  # Set to false to disable
```

When enabled (default), the NetworkPolicy restricts:
- **Ingress:** From monitoring, traefik-system, and converse namespaces
- **Egress:** To kube-system (DNS), monitoring, converse, and external S3 endpoints (port 443)

Set `enabled: false` if you need to troubleshoot connectivity issues or run in environments where NetworkPolicies are not supported.

### 1. Enable Mimir Ruler for Recording Rules

Currently `ruler.enabled: false`. Enable it when you want to pre-aggregate expensive queries:

```yaml
ruler:
  enabled: true
  replicas: 1
```

This allows Grafana to define recording rules that Mimir evaluates periodically (e.g., `sum(rate(http_requests_total[5m]))` every 5 minutes). Rules are stored in the `converse-mimir-ruler` S3 bucket.

### 2. Add OpenCost for Kubernetes Cost Attribution

OpenCost reads metrics from Mimir and provides per-namespace, per-pod cost breakdowns. Add it as a new ArgoCD Application:

```yaml
- name: opencost
  source:
    repoURL: https://opencost.github.io/opencost-helm-chart
    chart: opencost
    targetRevision: 1.29.0
```

### 3. Replace Loki SingleBinary with SimpleScalable

When log volume exceeds what one pod can ingest/querie, migrate to:

```yaml
deploymentMode: SimpleScalable
# Define read, write, backend replicas separately
```

This requires no data migration — Loki's storage format is the same. Only the deployment topology changes.

### 4. Tempo Scalability — Tempo Distributed

The current `tempo` chart is the single-binary version. For higher trace volume, switch to `tempo-distributed`:

```yaml
- name: tempo
  source:
    chart: tempo-distributed
```

This separates distributors, ingesters, queriers, and compactors.

### 5. Grafana Alerting — Apprise Contact Point

After Grafana is up, configure Apprise as a contact point:

1. Go to **Alerting → Contact points → Add contact point**
2. Type: `Apprise`
3. Enter your Apprise API URL and notification channel
4. Add it to the default notification policy

This is a runtime UI action, not a Helm value. To codify it, use the Grafana Alerting Provisioning API or Terraform.

### 6. Metrics Deduplication & HA for Alloy

With Alloy as a DaemonSet + clustering, scrape target sharding prevents duplicates. For even higher availability, consider:
- Running Alloy as a StatefulSet again **only** for remote-write buffering (with ` WAL` enabled)
- Using the `prometheus.scrape` component with `forward_to` pointing to a local `prometheus.remote_write` with queue buffering

### 7. Log Retention by Stream / Tenant

Loki supports per-stream retention via overrides:

```yaml
loki:
  limits_config:
    retention_period: 90d
  compactor:
    retention_enabled: true
    retention_delete_delay: 2h
    retention_delete_worker_count: 150
```

For per-tenant overrides, add a `runtime_config` file and mount it as a ConfigMap.

### 8. Enable Trace-to-Metrics in Tempo

The `metricsGenerator` is already enabled and writes to Mimir. To generate service-level RED metrics from traces, ensure your services include standard OTel attributes (`service.name`, `http.method`, `http.status_code`).

### 9. S3 Lifecycle Policies

Configure lifecycle rules on all S3 buckets to transition old data to cheaper storage classes and eventually delete:

```json
{
  "Rules": [
    {
      "ID": "mimir-blocks-transition",
      "Status": "Enabled",
      "Filter": { "Prefix": "" },
      "Transitions": [
        { "Days": 30, "StorageClass": "STANDARD_IA" }
      ],
      "Expiration": { "Days": 95 }
    }
  ]
}
```

(The 5-day buffer after retention ensures compactor has time to delete before lifecycle expires.)

### 10. Monitoring the Monitoring Stack (Meta-Monitoring)

Create a `meta-monitoring` dashboard in Grafana that tracks:
- Mimir ingester WAL size and flush rate
- Loki chunk flush success rate and queue depth
- Tempo blocklist size and compaction duration
- Alloy scrape success rate and remote-write queue length

All these metrics are already exposed on `/metrics` endpoints and scraped by Alloy via `serviceMonitor.enabled: true` on each backend.

---

## Operational Runbooks

### Check if Mimir is accepting metrics

```bash
kubectl port-forward -n monitoring svc/mimir-nginx 8080:8080

# Check cluster status
curl http://localhost:8080/ready

# Check if distributors are receiving samples
curl http://localhost:8080/mimir/api/v1/status/buildinfo

# Remote-write health (from Alloy perspective)
kubectl logs -n monitoring -l app.kubernetes.io/name=alloy --tail=50 | grep "remote_write"
```

### Check if Loki is receiving logs

```bash
kubectl port-forward -n monitoring svc/loki-gateway 3100:3100

# Query the last 5 minutes of logs
curl "http://localhost:3100/loki/api/v1/query_range?query={job=\"kubernetes-pods\"}&limit=10&start=$(date -d '5 minutes ago' +%s)000000000&end=$(date +%s)000000000"
```

### Check if Tempo is receiving traces

```bash
kubectl port-forward -n monitoring svc/tempo 3100:3100

# Check Tempo ingester ring
curl http://localhost:3100/ring

# Search for recent traces
curl "http://localhost:3100/api/search?tags=service.name%3Dmy-service&limit=10&start=$(date -d '5 minutes ago' +%s)&end=$(date +%s)"
```

### Check Grafana data source health

Navigate to **Configuration → Data sources** in Grafana and click "Test" on each source. If Mimir/Loki/Tempo are unreachable, verify:
- Pods are running: `kubectl get pods -n monitoring`
- Services exist: `kubectl get svc -n monitoring`
- No NetworkPolicies blocking traffic

### Recover from a stuck ArgoCD sync

If Mimir's ResourceQuota conflicts with the old one from Alloy:

```bash
# Delete the old quota so Mimir's extraObjects can own it
kubectl delete resourcequota monitoring-quota -n monitoring

# Then re-sync in ArgoCD
argocd app sync apps --resource monitoring:ResourceQuota:monitoring-quota
```

### Rotate S3 credentials

1. Update the secret in your ESO backend (Vault, etc.)
2. Force ESO to resync: `kubectl delete externalsecret mimir-s3 -n monitoring`
3. The new secret will be recreated automatically
4. Rolling restart the backend to pick up new env vars:
   ```bash
   kubectl rollout restart deployment/mimir-distributor -n monitoring
   kubectl rollout restart deployment/mimir-ingester -n monitoring
   # ... repeat for all Mimir components
   ```

### Scale Mimir components

Edit `values.yaml`, bump `replicas`, commit, and ArgoCD syncs. Example for ingester:

```yaml
ingester:
  replicas: 3
  zoneAwareReplication:
    enabled: true
```

When zone replication is enabled, ensure your nodes are labeled with topology zones (`topology.kubernetes.io/zone`).

---

## Appendix: Quick Reference — Values.yaml Field Map

| Concern | File | Lines | Field |
|---------|------|-------|-------|
| Alloy controller type | `values.yaml` | 157 | `controller.type: daemonset` |
| Alloy remote_write URL | `values.yaml` | 171-173 | `prometheus.remote_write.default.endpoint.url` |
| Alloy Loki write URL | `values.yaml` | 226-228 | `loki.write.default.endpoint.url` |
| Mimir retention | `values.yaml` | 320 | `mimir.structuredConfig.limits.compactor_blocks_retention_period` |
| Mimir S3 endpoint | `values.yaml` | 300 | `mimir.structuredConfig.common.s3.endpoint` |
| Mimir resource quota | `values.yaml` | 417-429 | `mimir.extraObjects` (ResourceQuota, LimitRange) |
| Monitoring NetworkPolicy | `values.yaml` | 445-517 | `mimir.extraObjects` (conditional on `global.monitoring.networkPolicy.enabled`) |
| NetworkPolicy toggle | `values.yaml` | 25-27 | `global.monitoring.networkPolicy.enabled` |
| Loki retention | `values.yaml` | 584 | `loki.limits_config.retention_period` |
| Loki S3 endpoint | `values.yaml` | 575 | `loki.storage.s3.endpoint` |
| Loki schema date | `values.yaml` | 563 | `loki.schemaConfig.configs[0].from` |
| Tempo retention | `values.yaml` | 670 | `tempo.retention` |
| Tempo S3 endpoint | `values.yaml` | 677 | `tempo.storage.trace.s3.endpoint` |
| Grafana domain | `values.yaml` | 761-762 | `grafana.ini.server.domain` |
| Grafana Keycloak secret | `values.yaml` | 758 | `envFromSecrets` |
| Grafana datasources | `values.yaml` | 793 | `datasources.datasources.yaml.datasources` |
| Grafana ingress | `values.yaml` | 910 | `ingress.hosts[0]` |
