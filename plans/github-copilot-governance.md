# Plan: GitHub Copilot governance connector (Rust + k8s)

> Turn `~/Downloads/github-copilot-governance-mvp.md` into something buildable on
> **this** platform. Source doc = the product shape; this plan = the shape it takes
> given ai-helm, ai-helm-values, home-remote, CNPG, Alloy/Mimir/Loki, grafana-operator
> and the ADR/governance process already in place.

**Status:** Proposed plan · **Date:** 2026-07-31 · **Maintainer:** @stephane-segning

> ⚠️ **Amended the same day by [`microsoft-foundry-governance.md`](./microsoft-foundry-governance.md).**
> A second connector spec arrived, which settles open question #4 below: there *will* be
> more than one provider. Three things change — the repo becomes
> **`lightbridge-governance`** (connectors as crates, not repos), the DB role becomes
> **`governance`**, and the **tenant/application/integration registry is built first**,
> before this connector, because retrofitting `tenant_id` under existing tables means
> rewriting every primary key. Copilot stays the **first connector to ship** (pull-based,
> our own org, no public endpoint, no LGTM changes) — it just lands on the registry
> rather than inventing its own identity model. Everything else below stands.

---

## 0. What I'd change from the source doc, and why

Five deviations. Everything else in the doc survives intact.

| # | Source doc says | This plan says | Why |
|---|---|---|---|
| 1 | Query layer = **Parquet on S3**, "no new database" | Query layer = **Postgres on the existing `lightbridge-main-db` CNPG cluster** (new `copilotgov` role + database). S3 keeps raw-archive/replay only. | It isn't a *new* database — it's a 30-line addition to `charts/lightbridge-db/values.yaml`, alongside the six roles already there (`repoauth`, `codeintel`, `coder`, `lakefs`, `mlflow`, `grafana_ro`). Barman backups to S3 already configured. Deletes an entire subsystem: no Parquet writer, no Arrow/DataFusion in Rust, no S3 query engine, no `normalize`+`publish-metrics` commands. Idempotent reprocessing becomes `ON CONFLICT DO UPDATE`. **And** Grafana reads it directly — see #3. |
| 2 | **Memcached** for query caching | **No cache service.** In-process `moka` in the API. | There is no memcached in this cluster and adding one is a whole chart + NetworkPolicy + ADR. The only alternative already deployed is redis-ha, which is TLS-only with an internal CA and a password — real wiring cost for a single-replica API serving 6-hourly-refreshed data. Installation tokens (1 h TTL) are per-process anyway. If the API ever needs >1 replica, revisit → redis-ha (LibreChat/ratelimit already prove the wiring). |
| 3 | Dashboards read **Mimir**; keep usernames out of labels | Dashboards 1–3 read the **Postgres datasource** (`uid: copilotgov`); only dashboard 4 reads Mimir. | Precedent exists: ADR-0063 already runs a read-only Postgres `GrafanaDatasource` (`uid: keycloak`) for exactly this reason. Usernames/repos/teams are *columns*, not Prometheus labels — the entire "keep cardinality low / avoid `username` labels" constraint evaporates for the business dashboards, and Mimir keeps only the ~10 low-cardinality *operational* metrics from Phase 8. |
| 4 | Separate **`Job/copilot-initial-backfill`** | No backfill Job. The CronJob's normal run reads the DB high-water mark and backfills up to 28 days when it's behind. | A one-shot `Job` is a bad GitOps citizen (immutable spec; re-running means deleting the object out-of-band, and selfHeal fights you). Self-healing backfill also makes the "recover when a report is published late" requirement fall out for free. |
| 5 | Team attribution needs a **manual mapping table**; native team report is enterprise-only | GitHub ships **`/orgs/{org}/copilot/metrics/reports/user-teams-1-day` at org scope**. Ingest it. Keep a mapping table only for *cost-center* / internal-user identity. | The doc is out of date on this. Caveat that survives: GitHub omits teams with <5 seated Copilot users. |

Plus one hard finding that changes Phase 1 — see §1.2.

---

## 1. GitHub side

### 1.1 One GitHub App, not two (for now)

Register **one** App in the `adorsys-gis` org:

```text
Name:        AI Governance – Copilot Metrics
Public:      no (org-internal for the MVP)
Webhook:     disabled          ← reports are polled; no webhook in the MVP
Permissions (Organization):
  Copilot metrics          Read
  Copilot seat management  Read
  Members                  Read
  Metadata                 Read
```

Committed as `github-app-manifest.json` in the new repo, exactly like
[`lightbridge-repo-auth`](https://github.com/ADORSYS-GIS/lightbridge-repo-auth) does.

**Not** requested: repository contents, issues, pull requests, code. **Deferred entirely:**
the billing App (`Administration: read` for AI-credit spend) — that's a *second, separate*
App registered in Sprint 3, so the metrics collector never holds org-admin.

### 1.2 ⚠️ Two prerequisites the source doc understates

1. **Three org permissions, not two.** The reports endpoints 400/403 without
   `Members: read` in addition to Copilot metrics + seat management.
2. **The org must enable the "Copilot metrics API access policy."** This is an org
   *setting*, not a permission — the App is correctly installed and still gets 403
   until an org owner flips it. Do this before Sprint 1, it costs a minute.

**Spike this on day 1** (~2 h, before any code): install a throwaway App with those
permissions against `adorsys-gis` and `curl` one report end-to-end. GitHub's public docs
describe the fine-grained permission ("View Organization Copilot Metrics") and the
OAuth/PAT scope (`read:org`) but do **not** state that App installation tokens are
accepted on `/copilot/metrics/reports/*`; community reports say they are, at org scope,
with the three permissions above. Enterprise scope definitively does **not** accept App
tokens — which is exactly why the MVP is org-scoped.

Fallback if the spike fails: a fine-grained PAT in `ssegning-aws`. Structurally cheap —
the collector's credential layer resolves to a bearer token either way — but it changes
whether we register an App at all, so we settle it first.

### 1.3 Endpoints (verified against GitHub docs, API version `2026-03-10`)

```http
GET /orgs/{org}/copilot/metrics/reports/organization-1-day?day=YYYY-MM-DD
GET /orgs/{org}/copilot/metrics/reports/users-1-day?day=YYYY-MM-DD
GET /orgs/{org}/copilot/metrics/reports/repos-1-day?day=YYYY-MM-DD
GET /orgs/{org}/copilot/metrics/reports/user-teams-1-day?day=YYYY-MM-DD
GET /orgs/{org}/copilot/metrics/reports/organization-28-day/latest
GET /orgs/{org}/copilot/metrics/reports/users-28-day/latest
GET /orgs/{org}/copilot/billing/seats?per_page=100&page=N
```

Headers: `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2026-03-10`.
Reports are **NDJSON behind short-lived signed URLs** — download in the same job run.
Data exists from 2025-10-10 and stays available ~1 year.

---

## 2. Repos

### 2.1 New: `ADORSYS-GIS/copilot-governance` (private)

Rust workspace, modelled directly on `lightbridge-repo-auth` (same edition, same
dependency set, same CI). **One repo, one image, two binaries.**

```text
copilot-governance/
├── Cargo.toml                       # workspace, resolver = "3", edition 2024
├── rust-toolchain.toml
├── crates/copilot-governance-core/  # github client, models, ingest, store (sqlx)
├── app/copilot-governance/          # axum API server        (bin)
├── app/copilot-govctl/              # collector CLI          (bin)
│     └── subcommands: sync-latest | sync-day | backfill | verify | status
├── migrations/                      # sqlx migrations
├── .docker/Dockerfile               # cargo-auditable → distroless, nonroot
├── github-app-manifest.json
├── docs/{auth-model,github-app-permissions,sysadmin-guide}.md
└── .github/workflows/{ci,docker,governance}.yml
```

Dependency baseline lifted verbatim from `lightbridge-repo-auth`'s workspace
`Cargo.toml` — it is already the house answer to every question here:

- `axum 0.8` + `tokio` + `mimalloc` (per your ask)
- `reqwest 0.13` `default-features = false` + `rustls`/`ring` — no OpenSSL in distroless
- `jsonwebtoken 10` with `features = ["rust_crypto"]` — ⚠️ v10 made the crypto backend a
  *required* feature choice; with neither selected, App-JWT signing panics at runtime.
  This is the exact trap repo-auth already hit; inherit the pin.
- `sqlx 0.8` (postgres, chrono, json, macros, migrate)
- `thiserror` for library errors, `anyhow` at the binary edge
- `tracing-subscriber` with the `json` feature — Phase 8's structured logs
- `clap` (derive + env) for the subcommands
- `utoipa` for the OpenAPI surface

New, not in repo-auth: `aws-sdk-s3` (or `object_store`) for the raw tier, `moka` for the
in-process cache, and the OTLP trace exporter (`opentelemetry-otlp`).

**⚠️ Build with `cargo-auditable`.** Without it Trivy scans zero Rust crates and reports
a meaningless green — the platform rule from `lakefs-proxy`.

Image: `ghcr.io/adorsys-gis/copilot-governance`, both bins in one layer.
CI: copy `docker.yml` (buildx + `docker/metadata-action` → `sha-<short>` tags + gha cache)
and `governance.yml`. Runners must be `runs-on: adorsys-gis-runner` — GitHub-hosted
runners are billing-blocked org-wide.

### 2.2 `ai-helm` (this repo) — charts live here, not in the code repo

Two shapes exist on this platform:

- `lightbridge-repo-auth` — chart lives in the *code* repo, ai-helm pins a commit SHA.
- `lakefs-proxy` — image in the code repo, **chart in ai-helm**.

**Take the `lakefs-proxy` shape.** It gets OCI chart publish, release-please versioning,
the `helm-lint` gate, and the ai-helm-values split for free; repo-auth's shape needs
ArgoCD read-creds for a private repo and a manual SHA bump on every deploy. Revisit only
if we ever ship this to customers who install the chart themselves.

New/changed in ai-helm:

```text
charts/copilot-governance/           # App-of-Apps orchestrator, 3 children (ADR-0019)
charts/copilot-governance-secrets/   # ESO leaf  (child, wave 0)
charts/copilot-governance-app/       # bjw-template leaf: Deployment + CronJob (wave 1)
charts/copilot-governance-auth/      # → upstream oauth2-proxy chart (wave 2)
charts/lightbridge-db/values.yaml    # + copilotgov role + Database + ESO password
charts/apps/values.yaml              # + the orchestrator entry (controlPlane: false)
tools/dashboards/src/dashboards/copilot/{overview,licenses,adoption,connector_health}.py
tools/dashboards/src/dashboards/_common.py          # + COPILOT_UID = "copilotgov"
tools/dashboards/src/dashboards/main.py             # + 4 entries in _DASHBOARD_MODULES
charts/observability-dashboards/values.yaml         # + folder `copilot` + 4 dashboards + alerts
charts/observability-dashboards/files/copilot/*.json # generated, committed
docs/adr/0111-github-copilot-governance-connector.md
docs/integrations/github-copilot-governance.md
```

Structurally this is **`longhorn-auth`/`homepage` with three children** — an established,
copy-able pattern (ADR-0019 App-of-Apps via plain Helm, `templates/applications.yaml`
iterating `.Values.children`).

`copilot-governance-app` carries no `templates/` dir (everything from `bjw-template`), so
CI lints it non-strict automatically. bjw-common already ships a `cronjob` controller
class, so one chart renders both the Deployment and the CronJob.

### 2.3 `ai-helm-values` (private) — everything deployed

```text
environments/prod/values/copilot-governance-app.yaml    # image tag, org list, schedule, knobs
environments/prod/values/copilot-governance-auth.yaml   # oauth2-proxy config
environments/prod/values/grafana.yaml                   # + GrafanaDatasource uid: copilotgov
environments/prod/deps/copilot-governance/
  ├── kustomization.yaml
  ├── certificate.yaml                                  # ingress TLS
  └── ciliumnetworkpolicy.yaml                          # egress lockdown (§5)
```

⚠️ **Values-repo-first, always.** These files must be on `ai-helm-values@main` *before*
the ai-helm change merges, or `ignoreMissingValueFiles` silently falls back to chart
defaults.

---

## 3. Runtime topology

Namespace **`governance`** (platform convention is short names — `converse`, `mlops`,
`coder`; not the doc's `ai-governance-connectors`).

```text
governance/
├── CronJob/copilot-sync          0 */6 * * *   concurrencyPolicy: Forbid
│                                 backoffLimit 4, activeDeadlineSeconds 1800
│                                 successfulJobsHistoryLimit 3 / failed 5
├── Deployment/copilot-api        axum, 1 replica, readOnlyRootFilesystem, nonroot
├── Deployment/copilot-auth       oauth2-proxy, reverse-proxy mode
├── Service ×2 (ClusterIP)
├── Ingress                       governance.ai.camer.digital → copilot-auth only
├── ExternalSecret ×N             (secrets child)
└── CiliumNetworkPolicy           (deps overlay)
```

Destination: **`home-remote`** (ordinary workload — not `controlPlane`, not
`homeCluster`). Project: `ai`, inherited.

Ingress TLS: `cert-home-cert-http` (**HTTP-01**). ⚠️ Not `cert-cloudflare` —
`ai.camer.digital` is NS-delegated to Route53, so a DNS-01 `Certificate` there reports
`Presented: true` and then stalls forever on `not yet propagated`. HTTP-01 is unaffected
by delegation.

Auth: oauth2-proxy against Keycloak, **role-restricted** (not any-authenticated-user) —
the ADR-0093 Longhorn precedent, appropriate because raw user-level Copilot data is
governance-admin material. ⚠️ `cookie-secret` must decode to exactly 16/24/32 bytes —
`openssl rand -hex 16`; a padded base64 (44 chars) crashloops.

### The data flow

```text
CronJob (every 6h)
  → mint installation token (1h, never persisted)
  → for day in [D-1, D-2, D-3]  (and up to D-28 when the DB is behind):
        GET report → follow signed URL → NDJSON
        ├─→ S3  s3://ssegning-k8s-state/copilot-governance/raw/org=…/day=…/*.ndjson
        └─→ Postgres  INSERT … ON CONFLICT (org, report_day, …) DO UPDATE
  → GET /copilot/billing/seats (paginated) → same two sinks
  → write manifest row + object
  → emit OTLP traces + push operational metrics

Deployment/copilot-api
  → SELECT from Postgres, moka-cached 5–15 min
  → /api/v1/copilot/{overview,adoption,seats,users,repositories,costs,pipeline-health}
  → /api/v1/connectors/github-copilot/status
  → /metrics  (scraped by ServiceMonitor)
```

S3: reuse the shared `ssegning-k8s-state` bucket at `nbg1.your-objectstorage.com`, own
prefix `copilot-governance/`, creds from `ssegning-aws` key `prod/meta/test-app`
(`s3_backup_cnpg_client_id` / `s3_backup_cnpg_secret`) — the same pattern LibreChat,
MLflow, Argo Workflows and the CNPG backups all use. Region `us-east-1` (Ceph-RGW).

### Postgres schema (sketch)

```sql
-- role/db added in charts/lightbridge-db/values.yaml, like `repoauth`/`codeintel`
copilot_org_daily(tenant_id, org, report_day PK…, active_users, engaged_users,
                  interactions, code_generations, code_acceptances,
                  loc_suggested, loc_added, loc_deleted, ai_credits, net_cost_micro, currency)
copilot_user_daily(tenant_id, org, provider_user_id, report_day PK…, last_activity_at,
                   interactions, code_generations, code_acceptances, ai_credits,
                   models jsonb, features jsonb, languages jsonb, ides jsonb)
copilot_repo_daily(tenant_id, org, repository, report_day PK…, coding_agent_activity,
                   code_review_activity, pull_request_activity)
copilot_user_teams(tenant_id, org, provider_user_id, team_slug, report_day PK…)
copilot_seat_snapshot(tenant_id, org, provider_user_id, snapshot_day PK…,
                      seat_assigned_at, last_activity_at, last_activity_editor,
                      seat_state, pending_cancellation_date)
identity_map(tenant_id, provider, provider_user_id, internal_user_id,
             team_id, cost_center_id, valid_from, valid_to, mapping_source)
ingest_manifest(tenant_id, org, report_day, report_type PK…, status, record_count,
                checksum, schema_version, started_at, completed_at)
```

Money in **integer minor units** (`net_cost_micro` = µ$), never floats — the house rule,
and the same unit the ratelimit spend metric already uses.

Sizing: ~500 seats × 365 days ≈ 200k rows/yr on the user table. Nothing.

Team attribution: `copilot_user_teams` comes straight from GitHub. `identity_map` exists
only to reach *internal* identity / cost-center — joined to Keycloak `user_entity` by
verified email, reusing the ADR-0063 read-only datasource. Never match on display name.

---

## 4. Observability

**Metrics are pull-based `ServiceMonitor`, not OTLP.** That is the platform contract:
Alloy runs `prometheus.operator.servicemonitors` cluster-wide → `prometheus.remote_write`
→ Mimir. Traces go OTLP to `alloy.observability.svc.cluster.local:4317`; logs are picked
up from pod stdout by Alloy's Kubernetes SD.

So the collector needs a metrics endpoint a CronJob pod can't serve. Two options — pick
**(a)**:

- **(a) The API Deployment owns the metrics.** The collector writes run outcomes to the
  `ingest_manifest` table; the API exposes `governance_connector_*` gauges/counters
  derived from it on `/metrics`, scraped by one ServiceMonitor. Always-scrapeable, no
  push gateway, and `last_success_timestamp` / `report_age_seconds` are naturally
  *derived* rather than remembered.
- (b) A Prometheus pushgateway. Rejected — new component, stale-metric semantics.

Metric names as the doc specifies (`governance_connector_sync_runs_total`,
`…_sync_errors_total`, `…_last_success_timestamp`, `…_report_age_seconds`,
`…_records_processed_total`, `…_s3_write_errors_total`,
`…_github_rate_limit_remaining`, `…_download_duration_seconds`,
`…_normalization_duration_seconds`, `…_unmapped_users`), labels limited to
`provider`, `tenant_id`, `organization_id`, `report_type`, `status`.

ServiceMonitor shape: copy `charts/inference-server/templates/servicemonitor.yaml`
(namespaceSelector + matchLabels + `argocd.argoproj.io/sync-wave: "1"`).

### Dashboards (Phase 9) — 4 modules, generated

Python generator only; hand-written JSON is a CI failure (`dashboards-drift`).

```text
tools/dashboards/src/dashboards/copilot/
  overview.py          → charts/observability-dashboards/files/copilot/overview.json
  licenses.py          → …/licenses.json
  adoption.py          → …/adoption.json
  connector_health.py  → …/connector-health.json
```

Each module exports `OUTPUT_PATH: str` and `build() -> dict`; register the four dotted
paths in `_DASHBOARD_MODULES` in `tools/dashboards/src/dashboards/main.py`; add
`COPILOT_UID = "copilotgov"` to `_common.py`; then `uv run dashboards build` **and commit
the JSON**.

Then in `charts/observability-dashboards/values.yaml`:

```yaml
folders:
  - name: copilot
    title: "GitHub Copilot governance"
    resyncPeriod: 5m          # ⚠️ REQUIRED — Grafana is stateless (ADR-0023)

dashboards:
  - name: copilot-overview
    folderRef: copilot
    file: files/copilot/overview.json
    resyncPeriod: 5m
  # … licenses, adoption, connector-health
```

⚠️ Omit `resyncPeriod` on the folder and the first Grafana pod roll silently wipes it;
the operator's cached `ApplySuccessful` status means it is never re-created, and every
`folderRef` dashboard sticks on `[400] folder not found`.

Dashboards 1–3 (`overview`, `licenses`, `adoption`) target `uid: copilotgov`, the new
read-only Postgres datasource. Dashboard 4 (`connector-health`) targets `mimir`.

Datasource, in `ai-helm-values` `environments/prod/values/grafana.yaml`, modelled on the
ADR-0063 `keycloak` one: `GrafanaDatasource`, `type: postgres`, pointing at the CNPG
`-ro` replica, credentials from ESO. Grant the Grafana role **SELECT only**, on the
reporting tables only. Grafana → CNPG egress needs a Cilium allow (the `observability`
namespace is default-deny-egress) — same overlay edit ADR-0063 already made for Keycloak.

### Alerts (Phase 10) — 5, in `charts/observability-dashboards/values.yaml`

Grafana unified alerting via grafana-operator; there is no `PrometheusRule` anywhere in
this repo. Compact authoring shape, one `ruleGroups` entry:

```yaml
  ruleGroups:
    - name: copilot-connector-health
      folderRef: copilot
      interval: 5m
      rules:
        - uid: cg-no-sync-36h
          title: Copilot connector — no successful sync in 36h
          datasourceUid: mimir
          expr: '(time() - max(governance_connector_last_success_timestamp)) or vector(0)'
          fromSeconds: 3600
          op: gt
          threshold: 129600
          for: 30m
          severity: critical
          summary: "..."
        # cg-report-stale-72h, cg-github-auth-failed, cg-write-errors, cg-unmapped-users-10pct
```

⚠️ Two house rules that bite: every expression needs `or vector(0)` (with
`noDataState: OK`, a no-data alert is permanently green — it never fires); and a
notification-policy route may only name an **enabled** contact point, or Grafana rejects
the *entire* policy tree with `[PUT /v1/provisioning/policies][400] receiver '…' does not
exist` and all delivery stops. Route to the existing `discord` contact point; don't add a
new one unless the Secrets-Manager property exists and shows `SecretSynced=True` first.

Aggregate by tenant/org. Never alert per user or per repository.

---

## 5. Security

The `governance` namespace is **new**, so — like `converse` and `mlops` — it inherits
**no** Cilium default-deny baseline and pods egress freely. Phase 11's "egress restricted
to GitHub API and S3" is therefore something we ship ourselves, in the deps overlay:

```yaml
# environments/prod/deps/copilot-governance/ciliumnetworkpolicy.yaml
egress:
  - toEndpoints: [kube-system/kube-dns]           # DNS
  - toFQDNs:
      - matchName: "api.github.com"
      - matchPattern: "*.githubusercontent.com"   # signed report downloads
      - matchPattern: "*.your-objectstorage.com"  # S3
  - toEntities: [cluster]                          # CNPG, Alloy OTLP
ingress:
  - fromEntities: [host, remote-node, health]      # ⚠️ kubelet probes
  - fromEntities: [cluster]                        # Traefik → auth → api
```

⚠️ Omit `fromEntities: [host, remote-node, health]` and kubelet probes fail — the pod
never goes Ready and it reads as a crash-loop. This has bitten the inference charts.
⚠️ A plain k8s `NetworkPolicy` `ipBlock` does **not** match on Cilium; it must be a
`CiliumNetworkPolicy`.

The signed-download host is a **spike output** — confirm it during §1.2 and pin the
`toFQDNs` list then rather than guessing.

Rest of Phase 11, all standard here:

- Dedicated ServiceAccount, `automountServiceAccountToken: false` (nothing talks to the API server).
- `runAsNonRoot`, `readOnlyRootFilesystem: true`, `capabilities: drop [ALL]`, `seccompProfile: RuntimeDefault`.
- No collector Ingress; the API is reachable only via oauth2-proxy.
- Secrets via ESO from `ssegning-aws`, **never `optional: true`** on a `secretKeyRef`
  env — env vars bind once at pod start and never refresh, so an optional ref lets a pod
  that beats ESO capture an empty credential and 401/403 forever. This is the context7
  `MCP_TOKEN` incident; required refs make the pod wait in `ContainerCreating` instead.
- Installation tokens minted per-need, never written to disk or DB.
- **Redaction is a type, not a discipline:** wrap tokens and signed URLs in a newtype
  whose `Debug`/`Display` print `<redacted>`, so a stray `tracing` field can't leak one.
- Audit every user-level API query (row in `audit_log`, or a structured log line with
  `actor` + `filters`).
- GHCR package will be private → the namespace needs its own `dockerconfigjson` pull
  secret (pull secrets are namespace-scoped; bjw-s resolves them from
  `defaultPodOptions.imagePullSecrets`, **not** `global.imagePullSecrets`).

---

## 6. Sequence

### Sprint 0 — Spike (~1 day, blocking)

- Verify App-installation-token access to `/copilot/metrics/reports/*` at org scope with
  the three permissions + the org policy toggle enabled (§1.2). Decide App vs PAT.
- Capture one real `organization-1-day`, `users-1-day`, `repos-1-day`,
  `user-teams-1-day` and `seats` payload → these fix the schema.
- Note the signed-URL download host → fixes the `toFQDNs` allowlist.

**Exit:** a checked-in fixture set and a go/no-go on the GitHub App.

### Sprint 1 — Working ingestion

Repo + `copilot-governance-core` + `copilot-govctl`; sqlx migrations; S3 raw writer;
CNPG role/database in `charts/lightbridge-db`; the three ai-helm charts + orchestrator
entry; deps overlay + values files in ai-helm-values; ServiceMonitor + `/metrics` +
`/api/v1/connectors/github-copilot/status`; OTLP traces.

**Exit:** the CronJob has been running unattended for 48 h; 28 days of Copilot data is in
Postgres *and* replayable from S3; re-running a day changes no row counts.

### Sprint 2 — Governance data & API

Seats + user-teams ingestion; identity map + Keycloak join; the seven query endpoints
with server-side filters and pagination; moka cache; the `copilotgov` GrafanaDatasource;
dashboards 1–4; the 5 alerts.

**Exit:** dashboard totals reconcile against the stored source reports for a spot-checked
day; alerts fire in a deliberate failure drill (revoke the credential, watch Discord).

### Sprint 3 — Product experience

oauth2-proxy gate + Keycloak role restriction; inactive-seat reclamation
*recommendations* (never automatic); cost-center attribution; the **second** billing App
+ AI-credit ingestion; raw-data retention/deletion job.

**Exit:** an admin connects, sees adoption + seat waste + spend, and exports it, with no
manual data handling.

### Explicitly out (from the doc, endorsed)

Raw prompt/code collection · VS Code interception · real-time claims · automatic seat
removal · automatic budget changes · enterprise billing creds · enterprise audit-log
streaming · ClickHouse · cross-provider benchmarking · productivity scoring.

---

## 7. Process obligations

- **ADR-0111** (next free number) — `docs/adr/0111-github-copilot-governance-connector.md`,
  covering: org-scope boundary, CNPG-over-Parquet, no-memcached, Postgres-datasource
  dashboards, the two-App billing split. Template is `docs/adr/template.md` — three bold
  metadata lines under the H1, **no YAML front-matter**, `Deciders: @stephane-segning`.
  Open as `Status: Proposed`, flip to `Accepted` when it lands, and update the index table
  in `docs/adr/README.md`. Accepted ADRs are immutable — supersede, never edit.
- **Docs:** `docs/integrations/github-copilot-governance.md` (consuming a specific
  product surface ⇒ `integrations/`), indexed in **both** `docs/README.md` and
  `docs/integrations/README.md`. Add to `docs/arc42.md` §5 (building blocks) and §9
  (decisions); add the topology to `docs/architecture.md`. If a durable gotcha emerges
  (it will — the org policy toggle is one), add a bullet to `CLAUDE.md`.
- **Every PR** (both repos) uses the governance template: AI Usage Declaration, a real
  source-of-truth link, Verification evidence. The `governance / governance-check` job
  fails a non-compliant body.
- **Conventional Commits** enforced by `commit-msg` hook + CI; scope = chart dir name.
  release-please owns the chart `MAJOR.MINOR` floor.
- **Verification loop** in ai-helm: `helm dep build` → `helm lint` → `helm template` →
  `uv run dashboards build && uv run dashboards check` → `ruff format/check`.

---

## 8. Open questions for you

1. **CNPG vs Parquet-on-S3** (§0 #1) — the biggest call. My recommendation is CNPG; it
   deletes the most code and unlocks direct Grafana SQL. Say the word if you'd rather
   hold the "no database" line, and I'll re-plan Phase 5/7 around `object_store` +
   DataFusion.
2. **Multi-tenant now or later?** The doc is written for a product ("a customer installs
   the app"), the MVP for our own org. `tenant_id` is in every table and prefix either
   way, but *if* multi-tenant is real, the App must be public and Sprint 1 needs an
   `installation` webhook + onboarding flow. Cheap now, expensive to retrofit.
   *(Carried into the Foundry plan's open question #2 — answer it once, for both.)*
3. **Hostname** — I assumed `governance.ai.camer.digital`. Fine, or something else?
4. ~~**Repo name**~~ — **settled** by the Foundry spec: one `lightbridge-governance`
   repo, connectors as crates. See the amendment note at the top.
5. **Which Keycloak role gates the API?** New (`copilot_governance_roles`) or an existing
   admin claim.
