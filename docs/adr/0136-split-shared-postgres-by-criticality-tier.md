# ADR-0136: Stop letting authentication share a Postgres cluster with bulk-data tenants

**Status:** Proposed
**Date:** 2026-08-29
**Deciders:** @stephane-segning

**Relates to:** [ADR-0123](0123-mlops-dedicated-cnpg-cluster.md) (the same argument, made for the
`mlops` tenants, and the `charts/mlops-db` pattern this would copy),
[ADR-0085](0085-mlops-platform-lakefs-argo-workflows-mlflow.md) decision #3 ("new apps get a role +
`Database` CR on `lightbridge-main-db`"), [ADR-0083](0083-coder-re-introduction.md) (the
shared-cluster default this questions)

## Context

Incident, `hetzner-prod`, **2026-08-29 ~10:05 UTC**: `lightbridge-main-db` — the shared CNPG
cluster in the `converse` namespace — exhausted its volume. PostgreSQL died with
`PANIC: could not write to file`, **both** instances went down, and every tenant went with them:
`authz-idp` (**all logins for the platform**), `authz-api`, `authz-opa`, `lightbridge-mcp`,
`authz-budget`, `authz-usage`, `lightbridge-repo-auth`. `console-ui` has no database, so it stayed
up and served an application that failed every call it made.

Measured after recovery (`pg_database_size`), the reason a disk-space event became an
authentication outage:

| database | size | tenant |
|---|---|---|
| `codeintel` | **7447 MB** | lightbridge-code-intelligence (78% of all data) |
| `usage` | 1516 MB | authz-usage |
| `coder` | 47 MB | Coder |
| `lakefs` | 11 MB | residue, [ADR-0123](0123-mlops-dedicated-cnpg-cluster.md) cutover |
| **`app`** | **10 MB** | **lightbridge-authz — every credential on the platform** |
| `mlflow` | 10 MB | residue, [ADR-0123](0123-mlops-dedicated-cnpg-cluster.md) cutover |
| `mlflow_oidc` | 9590 kB | residue, [ADR-0123](0123-mlops-dedicated-cnpg-cluster.md) cutover |
| `governance` | 9238 kB | governance |
| `repoauth` | 8262 kB | lightbridge-repo-auth |
| `postgres` | 7838 kB | maintenance |

The asymmetry is the whole point. **The database that owns authentication is 10 MB, and it was
taken offline by a 7.4 GB neighbour it has no engineering relationship with.** Nothing connects
`app` to `codeintel` except a shared volume. Largest objects: `codeintel.webhook_deliveries`
5061 MB (of which `payload_json` alone is 4255 MB), `codeintel.code_chunks` 2317 MB,
`usage.usage_events` 1508 MB (of which the `attributes` jsonb is 902 MB and is **never read
back**). Growth: `webhook_deliveries` ~150 MB/day and **accelerating** — 28,111 rows/day last week
against a 13,338/day average since June, 2.1x — plus `usage_events` at ~100 MB/day. ~250 MB/day
combined.

**Correction to the record:** [#1059](https://github.com/ADORSYS-GIS/ai-helm/pull/1059)'s PR body
attributed the exhaustion to failing WAL archiving. That was wrong, and is corrected in a comment
on that PR. The cause was ordinary data growth: `pg_wal` held only 577 MB against 8.9 GB of `base`.
The same wrong claim is still written into `charts/lightbridge-db/values.yaml`'s storage comment
and should be corrected there (see follow-ups).

Recovery was two volume bumps: 5Gi→20Gi ([#1059](https://github.com/ADORSYS-GIS/ai-helm/pull/1059))
then 20Gi→40Gi ([#1060](https://github.com/ADORSYS-GIS/ai-helm/pull/1060)). ~30 GB free ≈ **122
days** at the combined burn — and less than that, since one of the two rates is accelerating. The
two bumps were not the same operation, and the difference is an argument in itself. CNPG **cannot
expand a PVC while its instances are down** — it cannot read pod status, and logs
`"PostgreSQL cannot proceed until the PVC group is enlarged"` — so the 20Gi bump had to be applied
by patching the PVCs directly and deleting both pods to trigger the filesystem resize. The 40Gi
bump, applied while healthy, was fully online and unattended. **Capacity problems are cheap to fix
early and manual surgery to fix late.**

**The constraint that forces a structural answer: PostgreSQL has no native per-database size
quota.** There is no `ALTER DATABASE ... SET size_limit`. You cannot cap `codeintel` at 4 GB and
leave `app` protected. "Just add a quota" is not on the table, so the only ways to bound one
tenant's blast radius are to give it a different filesystem (a tablespace on its own PVC) or a
different cluster.

Available mechanisms, verified today: the operator is **CNPG 1.30.0**
(`ghcr.io/cloudnative-pg/cloudnative-pg:1.30.0`), so declarative tablespaces (`spec.tablespaces`,
each backed by its own PVC, supported since CNPG 1.22) are available. `spec.storage` is
`{"resizeInUseVolumes": true, "size": "40Gi"}` and the `hcloud-volumes` StorageClass has
`allowVolumeExpansion: true`, so online growth works — when the pods are alive. **`walStorage` is
unset**, so WAL shares the data volume.

[ADR-0123](0123-mlops-dedicated-cnpg-cluster.md) already made exactly this argument, for the
`mlops` tenants, after a *connection*-exhaustion incident on this same cluster seven weeks ago. It
closed with: *"If a future tenant on `lightbridge-main-db` needs the same isolation argument (a
system of record whose loss is not a recoverable inconvenience), this ADR is the precedent to point
to."* This is that tenant, and the failure axis has simply moved from connections to bytes.

## Decision

**Split `lightbridge-main-db` by criticality tier, and move the small critical databases out
rather than the big ones.**

- New CNPG cluster for the **control-plane tier** — `app` (lightbridge-authz), `repoauth`, and
  `governance` — via a new leaf chart modelled directly on `charts/mlops-db`
  ([ADR-0123](0123-mlops-dedicated-cnpg-cluster.md)): `managed.roles` + per-tenant `Database` CRs,
  its own `ObjectStore`/`ScheduledBackup`/`PodMonitor`, its own S3 backup credentials.
- **The bulk tenants do not move.** `codeintel`, `usage` and `coder` stay on
  `lightbridge-main-db`, which keeps its 40Gi and its growth problem — bounded now to tenants whose
  loss is an inconvenience rather than a platform-wide authentication outage.

The direction matters more than the split. The three control-plane databases total **~28 MB**, so
their `pg_dump`/restore is seconds of work and their new cluster can be small and effectively flat
forever. Moving `codeintel` instead would mean relocating 7.4 GB. **Isolate the thing that is small
and critical, not the thing that is large and noisy** — that is the cheap direction, and it is the
opposite of where the disk pressure points.

Adopt a disk-usage **alert** on every CNPG cluster regardless of which option wins (see
Alternatives #5) — it is complementary, not an alternative.

**Sizing to confirm before implementation, not decided here:** 2 instances (this is not
[ADR-0123](0123-mlops-dedicated-cnpg-cluster.md)'s 3-instance case — the auth tier is small and
restores fast, and a 2-instance loss window matches what `lightbridge-main-db` already offers it
today), ~10Gi, and a connection budget derived from the actual `authz-*` pool settings rather than
copied. One caveat that must be checked first: `app` is only *flat* while its short-lived tables —
`exchange_refresh_tokens`, `device_authorizations`, `authorization_codes` — are swept of expired
rows. If no sweep exists, a 10 MB database is a 10 MB database only so far.

**Retention work is necessary either way and is not a substitute for this decision.**
[lightbridge-code-intelligence#637](https://github.com/ADORSYS-GIS/lightbridge-code-intelligence/issues/637)
(P0, `webhook_deliveries`) and
[lightbridge-authz#549](https://github.com/ADORSYS-GIS/lightbridge-authz/issues/549)
(P0, `usage_events`) fix *today's two tables*. Isolation fixes *the class of problem* — the next
bulk tenant will not be one of those two, and it will not have a retention ticket written for it in
advance.

## Consequences

**Positive**

- Authentication stops sharing fate with a bulk data store. A `codeintel` runaway becomes a
  degraded code-intelligence feature instead of a platform-wide login outage — the specific
  2026-08-29 failure cannot recur in that shape.
- The migration is genuinely cheap: ~28 MB of `pg_dump`, three connection-string repoints, no
  large-object rewrite, no exclusive locks held for any meaningful time.
- The control-plane cluster's capacity becomes predictable. It is sized against workloads that do
  not grow with traffic volume, so its headroom is a number that stays true.
- The pattern already exists and is in production. `charts/mlops-db` is seven weeks old and proven;
  this is a second instance of an established shape, not a new one.
- `lightbridge-main-db`'s remaining tenants get the whole 40Gi and the whole connection budget,
  which slightly extends the ~122-day runway on its own.

**Negative**

- A third CNPG cluster to operate, back up, monitor and restore-test — the same cost
  [ADR-0123](0123-mlops-dedicated-cnpg-cluster.md) accepted, and the same cost
  [ADR-0083](0083-coder-re-introduction.md)/[ADR-0085](0085-mlops-platform-lakefs-argo-workflows-mlflow.md)
  decision #3 originally chose the shared cluster to avoid. The "prefer one shared cluster" default
  is now down to bulk tenants only, and should probably be restated rather than left implied.
- A cutover with real (non-disposable) data, unlike LakeFS's in
  [ADR-0123](0123-mlops-dedicated-cnpg-cluster.md). It needs a maintenance window during which
  logins fail, an actual `pg_dump`/restore rather than a bare connection-string flip, and a
  rehearsed rollback. Small data does not make it zero-risk — it makes it short.
- New configuration is new ways to be wrong. A misrendered ExternalSecret or connection string on
  the auth tier is a login outage, i.e. exactly the failure this ADR is trying to prevent, arriving
  by a different route.
- `grafana_ro` reads across databases on the current cluster. Splitting means a second Grafana
  datasource, and any dashboard joining an auth-tier table to a bulk-tier one stops being
  expressible in one query. This needs checking before implementation — it is the most likely
  hidden coupling.

**Neutral / follow-ups**

- Disk-usage alerting on all CNPG clusters — do it regardless of the outcome here.
- Correct the WAL-archiving root-cause claim still written in
  `charts/lightbridge-db/values.yaml`'s storage comment. It is wrong, and it is the first thing the
  next person to read that file will believe.
- Reclaim the `lakefs`, `mlflow` and `mlflow_oidc` databases left behind by
  [ADR-0123](0123-mlops-dedicated-cnpg-cluster.md)'s cutover (~30 MB combined). Immaterial to
  capacity; just residue that should not outlive its ADR.
- Whichever option wins, `walStorage` is still unset on every cluster here. WAL sharing the data
  volume is a second, independent path to the same `PANIC`, and it was not the cause this time
  only because archiving happened to be working.
- If the split is adopted, `lightbridge-main-db` is misnamed — it becomes the bulk-data cluster,
  not the main one. Renaming a live CNPG cluster is not worth an outage; note it and move on.

## Alternatives considered

- **Status quo — one cluster, managed with headroom and retention discipline alone.** Rejected.
  It is the cheapest option and it is what was in place on 2026-08-29. It survives only while every
  tenant's retention behaves, forever, with no per-database quota available to enforce that and no
  structural reason the next bulk table will be one anybody has thought about. The 122-day runway
  is real, but it is a countdown, not a fix.
- **Per-tenant tablespaces on separate PVCs (CNPG `spec.tablespaces`).** The genuinely attractive
  cheaper option, and the strongest runner-up: it converts a global `PANIC` into a per-tenant write
  failure — a full tablespace fails writes for that tenant while the catalog, WAL and every other
  tenant keep working — with no second cluster to operate. Rejected as the primary answer for two
  concrete reasons. First, **it only works in the expensive direction.** The catalog and WAL live
  on the main data volume, so protecting them requires moving *the growth* elsewhere — that is
  `codeintel`'s 7.4 GB, and `ALTER TABLE ... SET TABLESPACE` is a full rewrite under an
  `ACCESS EXCLUSIVE` lock, not a config toggle. Putting only the 28 MB auth tier on its own
  tablespace protects nothing, because `codeintel` filling the main volume still kills the shared
  catalog. Second, **WAL is still shared** unless `walStorage` is split too, so one runaway WAL
  producer still takes everyone down. Worth keeping as the **interim** if a second cluster is not
  wanted now — it is a real improvement over the status quo, just a partial one.
- **A cluster per tenant.** Rejected as over-correction. Nine clusters to back up, monitor and
  restore-test to solve a problem that has exactly two shapes: things that must never go down, and
  things that grow without bound. Tiering gives most of the isolation for a small number of
  clusters; per-tenant gives the rest for an operational cost nobody will keep paying.
- **Monitoring and alerting only.** Rejected *as an alternative*, adopted *as a complement*. A
  disk-usage alert at 70/85% would have given days of warning before 2026-08-29 and made the
  recovery the online 40Gi operation rather than the manual PVC surgery the 20Gi one had to be.
  But an alert prevents nothing — it converts an outage into a page, and the page still lands on
  one person who then has to act before the volume fills. Do it either way; do not mistake it for
  isolation.
- **PgBouncer / a CNPG `Pooler` in front of the shared cluster.** Not applicable to this incident
  and noted only to close it off: it addresses connection exhaustion (the
  [ADR-0123](0123-mlops-dedicated-cnpg-cluster.md) incident), not bytes on disk. It was considered
  and deferred there for its own reasons; nothing here changes that.

## Related

- Incident recovery: [ai-helm#1059](https://github.com/ADORSYS-GIS/ai-helm/pull/1059) (5→20 GiB,
  outage recovery — note its PR body's WAL-archiving root-cause claim is wrong and corrected in a
  comment on that PR), [ai-helm#1060](https://github.com/ADORSYS-GIS/ai-helm/pull/1060) (20→40 GiB).
- Retention tickets (necessary either way, not a substitute):
  [lightbridge-code-intelligence#637](https://github.com/ADORSYS-GIS/lightbridge-code-intelligence/issues/637)
  + runbook [#638](https://github.com/ADORSYS-GIS/lightbridge-code-intelligence/pull/638),
  [lightbridge-authz#549](https://github.com/ADORSYS-GIS/lightbridge-authz/issues/549).
- Precedent: [ADR-0123](0123-mlops-dedicated-cnpg-cluster.md) (same argument, `mlops` tenants,
  connection axis), [ADR-0085](0085-mlops-platform-lakefs-argo-workflows-mlflow.md) decision #3
  (the shared-cluster rule this would further narrow),
  [ADR-0083](0083-coder-re-introduction.md) (its original rationale).
- Charts/files: `charts/lightbridge-db/` (the cluster under discussion; its live values come from
  the private `ai-helm-values` repo), `charts/mlops-db/` (the pattern a control-plane cluster would
  copy).
