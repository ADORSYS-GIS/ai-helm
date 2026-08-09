# ADR-0123: Give the mlops namespace its own dedicated CNPG cluster

**Status:** Accepted
**Date:** 2026-08-09
**Deciders:** @stephane-segning

## Context

Incident, `hetzner-prod`, 2026-08-08/09: LakeFS's HTTP API started returning
`repository not found` / auth errors and falling back to rendering its
first-run `/setup` page. Root cause: `lightbridge-main-db`, the CNPG cluster
in `converse` LakeFS's metadata KV store lives on per ADR-0085's decision #3
("new apps get a managed CNPG role + `Database` CR on the existing
`lightbridge-main-db` cluster instead of a dedicated CNPG cluster"), ran out
of Postgres connections: `FATAL: sorry, too many clients already` (SQLSTATE
53300). `max_connections` was left at the CNPG default (100), shared by 7
tenant roles (`repoauth`, `codeintel`, `grafana_ro`, `coder`, `lakefs`,
`mlflow`, `governance`), each with its own client-side pool, no PgBouncer in
front. LakeFS itself contributed a 25-connection default pool it never
needed (Stage 1 of this incident's fix caps it to 5).

Stage 1 of the incident fix (this repo, `charts/lightbridge-db`, and
`ai-helm-values` `lakefs-app.yaml`) restored service by raising
`max_connections`/memory on the shared cluster and capping LakeFS's own pool.
That does not fix the underlying coupling: `lightbridge-main-db` carries two
`mlops`-namespace tenants (LakeFS and **MLflow**, both named directly in the
incident's own connection-exhaustion error) alongside four `converse`-owned
ones (`coder`, `governance`, `lightbridge-code-intelligence`, `repoauth`/
`codeintel`). Neither LakeFS's data-versioning plane nor MLflow's tracking
store are operated or reviewed by those `converse` tenants — a change to any
of them can take either mlops workload down with no warning (CNPG reports
`Cluster in healthy state` throughout; it tracks replication/pod health, not
per-tenant connection saturation, so nothing alerted).

## Decision

Supersede ADR-0085 decision #3 **for both `mlops`-namespace tenants**
(decisions #1 and #2 in that ADR — S3 backend, per-app auth strategy — are
unaffected and remain in force). Give the `mlops` namespace its own
dedicated CNPG cluster, `mlops-main-db`, via a new `charts/mlops-db` leaf
chart — a child of the `lakefs` App-of-Apps orchestrator purely because that
chart already carried the scaffolded-but-disabled `db` slot this fills, not
because LakeFS owns the cluster (mirrors `lightbridge-main-db` being a child
of `charts/lightbridge` while serving `coder`/`governance`/etc., none of
which Lightbridge owns either). Modelled on `lightbridge-main-db`'s
multi-tenant pattern (`managed.roles` + per-tenant `Database` CRs on one
bootstrapped cluster), not a single-owner CNPG initdb-bootstrap shortcut.

**LakeFS is fully cut over in this same change**: `lightbridge-main-db`'s
`lakefs` managed role, `Database` CR, and `lakefs-db-role` `ExternalSecret`
are removed (hard cutover — no dormant parallel path), and
`charts/lakefs-secrets`' connection string now points at `mlops-main-db`.

**MLflow is NOT cut over in this change.** A `mlflow` role and
`mlflow`/`mlflow_oidc` `Database` CRs are provisioned on `mlops-main-db`
— ready — but `charts/mlflow-secrets`' connection string still points at
`lightbridge-main-db`, and MLflow's role/Databases stay live there too. This
incident-response investigation found no evidence of write traffic (run
creation, metric/param logging, model-version/artifact calls) against
MLflow across its full available log history — only unauthenticated
scanner noise and one authenticated user's read-only `experiments/search`
polling — consistent with the platform roadmap's own note that automated
MLflow emission from training runs was still "follow-up work, not yet
wired" as of the last entry available to this investigation. That is
circumstantial, not a row count (this investigation does not read Secrets
or exec into pods, so it cannot query the database directly), and MLflow's
tracking history — unlike LakeFS's confirmed-disposable synthetic datasets —
has **not** been explicitly cleared as abandonable by the owner. Repointing
MLflow's connection with no migration path would make it start against an
empty database, silently orphaning whatever, if anything, exists in
`lightbridge-main-db`'s `mlflow`/`mlflow_oidc` databases today. Actually
cutting MLflow over is therefore a **separate, explicitly-gated follow-up**:
provisioning the destination is this ADR's decision; migrating and
repointing MLflow is not.

**Instance count: 3**, not the 2 that `lightbridge-main-db` and this repo's
other CNPG cluster otherwise use. This is a deliberate departure, not a
default: `lightbridge-main-db` is a general-purpose shared app database
where a 2-instance loss window is an acceptable, recoverable inconvenience
for its various tenants. `mlops-main-db` is the sole system of record for
every LakeFS dataset commit — and, once MLflow's migration is cleared, every
MLflow tracking run — this platform's model-training pipelines depend on.
Losing quorum here doesn't inconvenience one app, it makes the whole mlops
data plane unreadable. A third instance keeps one standby in reserve even
after a single node loss, which two instances cannot. The extra pod's
CPU/memory/storage cost is small at this cluster's size (see sizing below)
and is judged worth it for that asymmetry — now covering two tenants, the
argument is stronger, not weaker, than it was for LakeFS alone.

**Data migration: LakeFS none, MLflow not applicable (not cut over).** The
owner confirmed current LakeFS data is disposable ("we have no data yet, so
we can safely destroy everything") and hermetic-synthetic — the three
dataset commits published before this incident (`ds-document-recognizer`,
`ds-document-detector`, `ds-face-detector`) rebuild in ~1 minute each via
the existing Argo dataset-build workflows
(`docs/playbooks/fixed-lakefs-dataset-workflows.md` in `webank-models`).
`mlops-main-db`'s `lakefs` database starts empty; those three commits become
unreachable on LakeFS's cutover and are regenerated by re-running the
workflows, not restored. MLflow's data question is explicitly open — see
above; no migration decision is made by this ADR.

**Sizing**, deliberately not copied from `lightbridge-main-db`'s numbers,
and sized for the eventual two-tenant state (both roles/databases exist now
even though only LakeFS carries live traffic): LakeFS has a hard-capped
5-connection pool (Stage 1, `charts/lakefs` `lakefs-app.yaml`). MLflow runs
1 replica × 2 gunicorn workers
(`ai-helm-values` `environments/prod/values/mlflow-app.yaml`), each holding
its own SQLAlchemy pool; the upstream `community-charts/mlflow` chart
exposes no documented pool-size value in this repo's fixtures to cap it the
same explicit way LakeFS's `database.postgres.max_open_connections` is
capped, so this sizing uses a generous **worst-case estimate** (~15
connections/worker, not a verified figure) rather than a confirmed cap:
2 × 15 = 30. LakeFS (5) + MLflow worst case (30) + admin/monitoring/backup
headroom (~15) + margin ⇒ `postgresql.parameters.max_connections: "80"`.
Memory: worst case with Postgres's 4MiB `work_mem` default (unset here) is
80 × 4MiB ≈ 320MiB, plus per-backend base overhead (≈80 × 2MiB ≈ 160MiB) and
CNPG's own `shared_buffers` default (128MiB) — ≈608MiB worst case.
`resources.limits.memory: 1536Mi` (1.5Gi) / `requests.memory: 768Mi` covers
that with real headroom given the MLflow estimate above is unverified.
`storage.size: 4Gi` — bumped from an earlier LakeFS-only 2Gi now that a
second tenant's tracking tables live here too; still small relative to the
S3-resident object/artifact content both tenants actually reference, so it
does not need to scale with dataset or experiment volume.

**Follow-up required before MLflow's cutover**: confirm (with actual
database access, which this ADR's authors did not have) whether
`lightbridge-main-db`'s `mlflow`/`mlflow_oidc` databases hold data worth
migrating; if so, perform an explicit `pg_dump`/restore (or CNPG-native
backup/restore) into `mlops-main-db` as part of that follow-up, not a bare
connection-string flip. Confirm MLflow's actual SQLAlchemy/gunicorn
pool-size configuration option (from the upstream chart's real schema, not
guessed) and cap it explicitly the same way LakeFS's pool is capped.

## Consequences

**Positive**
- LakeFS's failure domain no longer includes `mlflow`/`coder`/`governance`/
  `lightbridge-code-intelligence` or any future tenant added to
  `lightbridge-main-db`.
- `lightbridge-main-db`'s connection budget is freed of one tenant
  (LakeFS) it never needed to carry, on top of Stage 1's fix, with the path
  clear to free a second (MLflow) once its migration is cleared.
- A 3-instance dedicated cluster gives both tenants a stronger durability
  posture than either had as one of seven roles on a 2-instance shared
  cluster with an effectively unbounded tenant count.
- The destination cluster, roles, and databases for MLflow's eventual
  cutover are provisioned and idle — that follow-up becomes a values change,
  not new infrastructure, once cleared.

**Negative**
- A second CNPG cluster to operate: its own `ObjectStore`/`ScheduledBackup`/
  `PodMonitor`, its own S3 backup credentials Secret, its own connection-
  string wiring. ADR-0083's original rationale for the shared-cluster
  pattern ("no new CNPG cluster to manage, no S3 backup credentials needed,
  fewer CRDs") is explicitly traded away here, for these two tenants,
  because the durability argument outweighs it for them specifically.
- The historical LakeFS KV state (three dataset commits) is not migrated —
  see Data migration above. Acceptable per the owner's explicit sign-off
  that current data is disposable; would NOT be acceptable once real
  (non-synthetic, non-rebuildable) datasets are versioned in LakeFS.
- MLflow keeps two roles/Database sets alive simultaneously (on
  `lightbridge-main-db`, live, and on `mlops-main-db`, idle) until its
  cutover — a small amount of duplicated CRD/Secret bookkeeping, deliberately
  accepted over guessing at a data-loss decision that isn't this ADR's to
  make.

**Neutral / follow-ups**
- MLflow's actual cutover (data migration decision + connection-string
  repoint + confirmed pool cap) is the immediate next step, gated on
  explicit clearance — see above.
- If a future tenant on `lightbridge-main-db` needs the same isolation
  argument (a system of record whose loss is not a recoverable
  inconvenience), this ADR is the precedent to point to rather than
  ADR-0083's "prefer the shared cluster" default.

## Alternatives considered

- **Keep the shared cluster, just tuned (Stage 1 only).** Rejected as the
  *permanent* answer: Stage 1 fixes the immediate connection exhaustion but
  leaves both mlops tenants' data planes coupled to every other tenant's
  future connection behaviour indefinitely. Stage 1 stands on its own as the
  correct immediate mitigation; this ADR is the follow-up that removes the
  coupling instead of re-tuning around it forever.
- **Add a CNPG `Pooler` (PgBouncer) in front of the shared cluster instead.**
  Considered in Stage 1 and deferred there (see that PR): that cluster is
  shared by tenants this incident response has no evidence about w.r.t.
  session-level Postgres features transaction-mode pooling can break. Also
  doesn't address the actual problem — both tenants' data would still be one
  connection storm away from unreadable, just with a different threshold.
- **2 instances, matching `lightbridge-main-db`.** Rejected — see Sizing/
  Decision above: the asymmetry in what's lost on a quorum failure (a
  general app database vs. the system of record for two mlops workloads)
  justifies the extra instance here specifically, not as a new blanket
  default.
- **Cut MLflow over in this same PR, alongside LakeFS.** Rejected: this
  investigation could not confirm MLflow's existing database is safely
  abandonable the way the owner explicitly confirmed for LakeFS's synthetic
  data, and deciding that unilaterally would risk silently orphaning real
  tracking history. Provisioning the destination now and gating the actual
  cutover on explicit clearance is the responsible middle ground between
  "do nothing for MLflow" and "guess that it's fine."
- **A brand-new, unaffiliated Application/orchestrator for `mlops-db`**
  instead of nesting it under `charts/lakefs`. Rejected for now as more
  structural change than this incident response needed: `charts/lakefs`
  already had the exact scaffolded-but-disabled `db` child slot this chart
  fills, and the "one arbitrary owning orchestrator, several unrelated
  tenants" shape already has a working precedent
  (`lightbridge-main-db`/`charts/lightbridge`). Revisit if the nesting
  becomes confusing in practice.

## Related

- Supersedes: ADR-0085 decision #3 (metadata DB) for LakeFS (cut over) and,
  pending its own follow-up, for MLflow (provisioned, not yet cut over).
  Decisions #1 (S3 backend) and #2 (per-app auth) are unaffected.
- Docs: `docs/adr/0085-mlops-platform-lakefs-argo-workflows-mlflow.md`
  (header note added), `docs/adr/0083-coder-re-introduction.md` (shared-
  cluster rationale this ADR departs from, for these two tenants).
- Charts/files touched: `charts/mlops-db/` (new; renamed from an
  earlier LakeFS-only `charts/lakefs-db` before MLflow's role/databases were
  added), `charts/lakefs/values.yaml` (`db.enabled: true`, renamed child),
  `charts/lakefs-secrets/values.yaml` (connection string → `mlops-main-db`),
  `charts/lightbridge-db/values.yaml` (removes the `lakefs` managed
  role/Database/Secret; `mlflow`'s stays, live, pending its own cutover),
  `charts/mlflow/values.yaml` (comment only — no functional change).
  `ai-helm-values` `environments/prod/values/{lakefs-app,mlflow-app}.yaml`
  are NOT changed by this ADR — the LakeFS connection-string move lives in
  `charts/lakefs-secrets`; MLflow's values file is untouched pending its
  cutover.
