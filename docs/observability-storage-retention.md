# Observability Stack — Storage, Persistence & Retention

> Covers the LGTM stack: **Grafana Alloy** (collector), **Mimir** (metrics),
> **Loki** (logs), **Tempo** (traces), **Grafana** (visualization).
> Cluster: `ai-helm` · Namespace: `monitoring`

---

## 1. Storage Architecture

### 1.1 Object Storage Backend

All three telemetry stores share a single S3-compatible bucket (`monitoring` on
`s3.ssegning.me`) with prefix-based namespace isolation:

| Store | S3 Prefix | Data Type |
|-------|-----------|-----------|
| Mimir | `blocks/` | Prometheus TSDB blocks |
| Mimir | `alertmanager/` | Alertmanager configs |
| Mimir | `ruler/` | Recording & alerting rules |
| Loki | `loki/` | Log chunks + TSDB indexes |
| Tempo | `tempo/` | Trace blocks |

S3 credentials are injected at runtime via Kubernetes secrets provisioned by
External Secrets Operator (ESO):

| Secret | Used by | Keys |
|--------|---------|------|
| `mimir-s3` | Mimir | `MIMIR_S3_ACCESS_KEY_ID`, `MIMIR_S3_SECRET_ACCESS_KEY` |
| `loki-s3` | Loki | `LOKI_S3_ACCESS_KEY_ID`, `LOKI_S3_SECRET_ACCESS_KEY` |
| `tempo-s3` | Tempo | `TEMPO_S3_ACCESS_KEY`, `TEMPO_S3_SECRET_KEY` |

### 1.2 Local Persistent Volumes

In addition to object storage, each stateful component uses a local PVC
(Linode Block Storage) as a write-ahead buffer and WAL:

| Component | PVC Size | Purpose |
|-----------|----------|---------|
| Mimir ingester | 10 Gi | In-memory series WAL before S3 upload |
| Loki single-binary | 10 Gi | TSDB index WAL + chunk cache |
| Tempo | 5 Gi | WAL for in-flight traces before S3 flush |
| Grafana | 2 Gi | Dashboard state, plugins, SQLite DB |

These PVCs are **not** the primary data store — they are buffers. All durable
data lives in S3. A PVC loss causes a brief gap in recent data but no
permanent data loss beyond the WAL window.

---

## 2. Retention & Compaction Configuration

All knobs below are explicitly set in `charts/apps/values.yaml` and commented
inline. This section describes what each one does, why it is set to its current
value, and what to change if requirements shift.

---

### 2.1 Metrics — Mimir

Configuration path: `mimir.structuredConfig.limits` and
`mimir.structuredConfig.compactor`

#### `compactor_blocks_retention_period: 90d`

**What it does:** Instructs the Mimir compactor to permanently delete TSDB
blocks from S3 once they are older than this duration. Blocks are first marked
for deletion, then removed after `deletion_delay` has elapsed.

**Set to 0d** to disable retention entirely (keep all data forever — not
recommended without a storage budget plan).

**Current value:** 90 days. Sufficient for capacity planning, incident
post-mortems, and trend analysis. Aligns with Loki for a consistent query
window across signal types.

---

#### `ingestion_rate: 30000`

**What it does:** Maximum number of samples per second the distributor will
accept from a single tenant. Requests exceeding this rate are rejected with
HTTP 429. This is a steady-state rate limit.

**Current value:** 30,000 samples/s. Appropriate for a small-to-medium cluster
with ~4 nodes and the current set of ServiceMonitors. Increase if you see
`err-mimir-ingestion-rate-limit` errors in the distributor logs.

---

#### `ingestion_burst_size: 50000`

**What it does:** Maximum instantaneous burst of samples allowed above the
steady-state `ingestion_rate`. Allows short spikes (e.g. a scrape interval
catching up after a pause) without triggering rate limiting.

**Current value:** 50,000 samples/s. Set to ~1.67× the ingestion rate, which
is a standard ratio. Increase proportionally if you raise `ingestion_rate`.

---

#### `max_global_series_per_user: 2000000`

**What it does:** Hard cap on the total number of active time series across all
ingesters for a single tenant. Once reached, new series are rejected. This
prevents cardinality explosions from unbounded label sets.

**Current value:** 2,000,000 series. Generous for the current workload. Monitor
actual cardinality via the Mimir overview dashboard in Grafana and reduce if
storage costs grow unexpectedly.

---

#### `out_of_order_time_window: 10m`

**What it does:** Allows the ingester to accept samples with timestamps up to
this duration behind the most recently ingested sample for the same series.
Without this, any sample arriving slightly late is rejected with
`err-mimir-sample-out-of-order`.

**Why it exists here:** Alloy runs as a DaemonSet and all pods scrape the same
ServiceMonitors. Due to clustering, one pod may send a `build_info` metric with
a timestamp a few seconds behind what another pod already ingested. This window
absorbs that skew.

**Current value:** 10 minutes. More than enough for the observed ~4s skew.
Do not set this too high (e.g. hours) as it increases ingester memory usage.

---

#### `compaction_interval: 1h`

**What it does:** How often the Mimir compactor wakes up to compact small
blocks into larger ones and enforce retention. More frequent compaction means
faster retention enforcement and smaller query fan-out, at the cost of more
S3 API calls.

**Current value:** 1 hour (Mimir default). Suitable for this scale. Reduce to
`30m` if you want faster retention enforcement; increase to `2h` to reduce S3
costs on high-volume deployments.

---

#### `deletion_delay: 12h`

**What it does:** After the compactor marks a block for deletion, it waits this
long before actually removing it from S3. This is a safety window — if a block
is accidentally marked for deletion (e.g. due to a bug or misconfiguration),
you have this window to intervene before data is permanently lost.

**Current value:** 12 hours. Balances safety with timely cleanup. Increase to
`24h` or `48h` if you want a longer recovery window; decrease to `1h` if
storage costs are a concern and you trust the compactor.

---

### 2.2 Logs — Loki

Configuration path: `loki.limits_config` and `loki.compactor`

#### `retention_period: 90d`

**What it does:** How long log chunks are kept in S3 before the Loki compactor
marks them for deletion. Requires `compactor.retention_enabled: true` to take
effect — without that flag, this setting is ignored entirely.

**Current value:** 90 days. Matches Mimir for a consistent cross-signal query
window. Reduce to `30d` if log volume is high and storage costs are a concern.

---

#### `ingestion_rate_mb: 8`

**What it does:** Maximum log ingestion rate in MB/s per tenant. Requests
exceeding this are rejected with HTTP 429.

**Current value:** 8 MB/s. Appropriate for the current cluster size. Increase
if Alloy logs show `rate limit exceeded` errors from the Loki gateway.

---

#### `ingestion_burst_size_mb: 16`

**What it does:** Maximum instantaneous burst above the steady-state
`ingestion_rate_mb`. Allows short spikes without triggering rate limiting.

**Current value:** 16 MB/s (2× the ingestion rate). Standard ratio.

---

#### `max_query_length: 0h`

**What it does:** Maximum time range a single Loki query can span. `0h` means
unlimited. Setting a value (e.g. `720h`) prevents runaway queries from scanning
the entire retention window and exhausting memory.

**Current value:** Unlimited. Acceptable for a small cluster with a single
operator. Set to `720h` (30 days) if you want to protect against accidental
full-history queries.

---

#### `max_entries_limit_per_query: 5000`

**What it does:** Maximum number of log lines returned by a single query.
Prevents the Grafana UI from being overwhelmed with results and protects the
Loki querier from excessive memory use.

**Current value:** 5,000 lines. Standard default. Increase to `10000` if
operators regularly need to page through large log windows.

---

#### `compactor.retention_enabled: true`

**What it does:** Master switch for Loki's time-based retention. When `false`,
the `retention_period` setting above has no effect and data accumulates
indefinitely. Must be `true` for retention to work.

---

#### `compactor.delete_request_store: s3`

**What it does:** Where Loki stores the list of pending delete requests. Must
match the object store type in use (`s3`, `gcs`, `azure`, etc.). If this
mismatches the actual storage backend, delete requests will fail silently.

---

#### `compactor.compaction_interval: 1h`

**What it does:** How often the Loki compactor runs to merge small index files
and process pending delete requests. More frequent = faster retention
enforcement; less frequent = fewer S3 API calls.

**Current value:** 1 hour. Matches Mimir for consistency.

---

#### `compactor.retention_delete_delay: 2h`

**What it does:** After the compactor marks chunks for deletion, it waits this
long before actually removing them from S3. Provides a safety window to cancel
accidental deletions.

**Current value:** 2 hours. Shorter than Mimir's 12h because log data is
generally less critical to recover than metrics. Increase to `12h` if you want
parity with Mimir.

---

#### `compactor.retention_delete_worker_count: 150`

**What it does:** Number of parallel workers the compactor uses to process
delete requests. Higher values speed up deletion of large volumes of expired
chunks at the cost of more S3 API calls and CPU.

**Current value:** 150 (Loki default). Reduce to `50` if you see S3 rate
limiting errors during compaction; increase if retention enforcement is lagging.

---

### 2.3 Traces — Tempo

Configuration path: `tempo.tempo`

#### `retention: 720h`

**What it does:** Top-level retention setting. How long trace blocks are kept
before Tempo's compactor removes them from S3. Equivalent to
`compactor_blocks_retention_period` in Mimir.

**Current value:** 720 hours (30 days). Shorter than metrics and logs because
raw trace data is significantly larger per unit of time. Traces are most
valuable for active incident investigation; 30 days covers the typical
post-incident review window. Increase to `2160h` (90 days) if compliance or
long-term performance analysis requires it.

---

#### `storage.trace.block.block_duration: 5m`

**What it does:** How long Tempo accumulates traces in memory before cutting a
new block and flushing it to S3. Shorter = more frequent flushes, lower memory
use, more S3 objects. Longer = fewer S3 objects, higher memory use, longer
gap before traces are queryable.

**Current value:** 5 minutes (Tempo default). Suitable for this scale. Increase
to `10m` or `15m` on high-volume deployments to reduce S3 object count.

---

#### `storage.trace.block.retention: 720h`

**What it does:** Block-level retention, mirrors the top-level `retention`
setting. Explicitly set here so the value is visible alongside other block
configuration and easy to change independently if needed.

**Current value:** 720 hours (30 days). Must match the top-level `retention`
value unless you intentionally want different behavior at the block level.

---

#### `storage.trace.wal.path: /var/tempo/wal`

**What it does:** Filesystem path for the Write-Ahead Log inside the Tempo pod.
Traces are written here first before being flushed to S3. This path lives on
the Tempo PVC (5 Gi).

---

#### `storage.trace.wal.ingestion_time_range_slack: 30s`

**What it does:** How much clock skew between the trace timestamp and the
current time Tempo tolerates before rejecting a span. Spans arriving more than
30s late are dropped.

**Current value:** 30 seconds. Standard default. Increase to `60s` if you see
spans being dropped due to clock drift between services.

---

## 3. Backup Strategy

### 3.1 Primary Backup: S3 Object Storage

The S3 bucket (`monitoring` on `s3.ssegning.me`) is the primary durable store
for all telemetry data. Backup strategy depends on the S3 provider's
capabilities:

**Recommended S3-level protections:**
- Enable **versioning** on the `monitoring` bucket to protect against
  accidental deletion or overwrite
- Enable **cross-region replication** if the provider supports it, or
  periodically sync to a second bucket using `rclone` or `aws s3 sync`
- Set a **lifecycle policy** to transition objects older than 90 days to a
  cheaper storage tier (e.g. Glacier-equivalent) if the provider supports it

### 3.2 Configuration Backup

All configuration is stored as code in this repository (`ai-helm`). ArgoCD
continuously reconciles the cluster state to match the repo. No separate
configuration backup is needed — a full stack restore is a `git clone` +
ArgoCD sync away.

### 3.3 PVC Failure Impact

Local PVCs (ingester WAL, Loki WAL, Tempo WAL) are **not backed up**. They
are ephemeral buffers. In a failure scenario:

| Component | PVC loss impact | Recovery |
|-----------|----------------|----------|
| Mimir ingester | Up to ~2h of uncompacted metrics lost | Restart; recovers from S3 |
| Loki single-binary | Recent unshipped index entries lost; short query gap | Restart; rebuilds from S3 |
| Tempo | In-flight traces in WAL (~30s) lost | Restart; all flushed S3 blocks safe |
| Grafana | Manually created dashboards lost | Provisioned dashboards restored on next sync |

---

## 4. Operational Notes

### 4.1 Monitoring the Stack Itself

- All components expose `ServiceMonitor` resources; Alloy scrapes them and
  pushes metrics to Mimir
- Loki canary (`loki-canary`) runs as a Deployment (1 replica) and
  continuously validates the log ingestion pipeline
- Tempo `metricsGenerator` derives RED metrics from traces and pushes them to
  Mimir, where they benefit from the full 90-day metrics retention

### 4.2 Known Limitations

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| Single S3 bucket for all stores | Prefix collision risk | Enforced by per-store prefixes; no overlap possible |
| No S3 bucket versioning confirmed | Accidental deletion is unrecoverable | Enable versioning on `monitoring` bucket |
| Mimir `replication_factor: 1` | No ingester HA; pod restart = brief gap | Acceptable for non-production; increase to 3 for HA |
| Loki single-binary mode | No horizontal scale | Migrate to SimpleScalable when log volume grows |
| Alertmanager datasource health check | Always shows red in Grafana UI | Known Grafana/Mimir incompatibility (no `/api/v2/status`); functionally working |

### 4.3 Scaling Triggers

| Signal | Threshold | Action |
|--------|-----------|--------|
| Mimir active series | > 1.5M | Increase `max_global_series_per_user` or add ingester replica |
| Loki ingestion rate | Sustained > 6 MB/s | Migrate to SimpleScalable mode |
| S3 storage cost | Growing faster than expected | Review retention periods; consider tiered storage |
| Ingester PVC utilization | > 70% | Increase PVC size or reduce WAL retention |
