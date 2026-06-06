# ADR-0026: Split lightbridge into an App-of-Apps orchestrator; drop `opa` + `usage`

**Status:** Accepted
**Date:** 2026-06-06
**Deciders:** @stephane-segning

## Context

`lightbridge` (the authz backend, an external chart from
`adorsys-gis.github.io/lightbridge-authz`) was deployed as a **single flat
Application** (`lightbridge-backend`) with an ~800-line inline valuesObject that
bundled four components — `api` (main), `mcp`, `opa`, `usage` — **plus** the
CloudNativePG databases (`lightbridge-main-db`, `lightbridge-usage-db`) inline as
`rawRessources`. Two of those components are now dead weight:

- **`usage`** — its only job was feeding a billing/usage dashboard; **Grafana is
  the dashboard now**, so usage (and its separate TimescaleDB) is redundant.
- **`opa`** — OPA was removed from the auth path (ADR-0021, 2026-06-04): a valid
  Keycloak JWT is the authorization boundary. The standalone opa component +
  `lightbridge-opa-auth` are no longer used.

Mixing DBs, secrets, and the workload in one Application also means one
sync-wave/rollback granularity and a DB defined as `rawRessources` — out of step
with how `coder` (ADR-0019) and `observability` (ADR-0020) are now structured.

## Decision

**Refactor `lightbridge` into an App-of-Apps orchestrator mirroring `coder`
(ADR-0019), keeping only `api` (main) + `mcp` and dropping `opa` + `usage`.**

- **`charts/lightbridge`** (orchestrator, `controlPlane: true`) emits three child
  Applications via `templates/applications.yaml`:
  - **`lightbridge-secrets`** (sync-wave 0) → `charts/lightbridge-secrets`:
    ExternalSecrets for `lightbridge-api-client` (the api's `API_KEY_CLIENT_SECRET`)
    and `lightbridge-cnpg-s3` (barman creds).
  - **`lightbridge-db`** (sync-wave 1) → `charts/lightbridge-db`: the CNPG
    `lightbridge-main-db` Cluster + PodMonitor + daily ScheduledBackup.
  - **`lightbridge-app`** (sync-wave 2) → the external lightbridge chart (Source A)
    + the `environments/prod/deps/lightbridge-backend` cert overlay (Source B),
    with the **api+mcp-only** valuesObject.
- **Keep `mcp`** alongside `api`: LibreChat consumes `mcp.ai.camer.digital/mcp`
  and mcp shares the main DB. "main, not opa/usage" → drop opa+usage, retain mcp.
- **Backups move to Hetzner object storage.** The barman `ObjectStore` was pointed
  at the decommissioned `s3.ssegning.me`/`ai-ops-backups`; it now targets
  `s3://ssegning-k8s-state/lightbridge-main-db` @ `nbg1.your-objectstorage.com`
  (region `us-east-1`), creds from `ssegning-aws prod/meta/test-app` — the same
  pattern Keycloak's CNPG backup uses.
- Namespace stays **`converse`** (lightbridge is intertwined with LibreChat
  there). Only the `lightbridge-main-db` data is migrated (ADR-0025); the usage
  DB is discarded.

## Consequences

**Positive**
- Independent sync-wave / rollback / ArgoCD-UI surface per concern (secrets, DB,
  app), matching coder/observability. The DB is a proper leaf chart, not inline
  `rawRessources`.
- Drops two unused deployments + a whole TimescaleDB; backups are on Hetzner
  (no dependency on the dead `s3.ssegning.me`).

**Negative / risks**
- **DB ownership transfer is destructive if synced carelessly.** `lightbridge-main-db`
  moves from the flat app to the `lightbridge-db` child; when the flat
  `aii-lightbridge-backend` becomes the orchestrator, ArgoCD prunes its old
  resources (incl. the CNPG Cluster) before the child recreates it → **data loss**
  unless sequenced. Mitigation: with root auto-sync disabled (ADR-0025 cutover),
  **back up / migrate `lightbridge-main-db` before syncing** this change. The
  Linode→Hetzner main-db migration is exactly that repopulation step.
- `lightbridge-api-client` secret is **currently missing on-cluster** — populate
  `lightbridge_api_client_secret_id` under `ssegning-aws ai/camer/digital/prod/env`
  or the api stays unauthenticated for token-exchange.

**Neutral / follow-ups**
- The api/mcp `config.yaml` still carries an in-process `server.opa` listener +
  `${OPA_PASSWORD}` (kept verbatim from the upstream component config). It's
  vestigial (Authorino no longer calls it) but harmless; stripping it is a
  possible follow-up if a future ADR wants OPA fully gone from the binary config.
- A cosmetic LibreChat endpoint `iconURL` still points at `s3.ssegning.me`
  (unrelated to lightbridge) — re-host on Hetzner when convenient.

## Alternatives considered

- **Keep the flat app, just disable opa/usage in values** — rejected: leaves the
  DB as inline `rawRessources` and one sync granularity; doesn't match the
  coder/observability structure the repo standardised on.
- **Drop `mcp` too** — rejected: it's actively consumed by LibreChat and shares
  the main DB. (One-line re-toggle if that changes.)
- **Drop barman backups entirely** — rejected: lightbridge-main-db has a restore
  runbook; modernising the endpoint to Hetzner keeps backups working.

## Related

- Builds on: ADR-0019 (coder App-of-Apps pattern — the template), ADR-0020
- Relates to: ADR-0021 (OPA removal — why opa goes), ADR-0025 (Linode→Hetzner cutover, S3→Hetzner, the DB-migration sequencing)
- Charts: `charts/lightbridge`, `charts/lightbridge-db`, `charts/lightbridge-secrets`; `charts/apps/values.yaml` (flat `lightbridge-backend` → orchestrator)
