# ADR-0083: Re-introduce Coder as App-of-Apps Orchestrator

**Status:** Accepted
**Date:** 2026-07-13
**Deciders:** @stephane-segning

## Context

Coder was originally deployed as an App-of-Apps orchestrator (`charts/coder` →
`coder-db` + `coder-app`, ADR-0019) and later removed (ADR-0027, 2026-06-06)
because the workload wasn't needed, the wildcard cert for `*.coder-ai.camer.digital`
was stuck (SAN incompatible with ACME HTTP-01), Keycloak/admin secrets were
unprovisioned, and the Hetzner `coder-cnpg` database was unrecoverable.

Since removal, three orchestrator patterns have matured in this repo and now
serve as canonical references:
1. **lightbridge** (ADR-0026) — the direct successor of the Coder App-of-Apps
   pattern, with three children (secrets wave 0, CNPG db wave 1, app wave 2).
2. **observability** (ADR-0020) — larger App-of-Apps with ~10 children.
3. **ApplicationSet orchestrators** (`ai-models`, `librechart`, `mcps`) — for
   homogeneous fan-out leaves.

The stale integration spec (`docs/coder-platform-integration.md`) and the
Keycloak `coder` client in `charts/keycloak-baseline` were deliberately left
in place to ease re-introduction. The `coder-decision.md` document prescribes
conditional re-introduction when AI agent orchestration becomes a platform
priority and the certificate strategy is resolved — both conditions are now
met (see coder-decision.md for the full analysis).

## Decision

Re-introduce Coder as an App-of-Apps orchestrator following the **lightbridge
pattern** exactly:

- **`charts/coder/`** (orchestrator, v1.0.0) — renders three child `Application`
  CRs via plain Helm (not an ApplicationSet), targets `home-remote` via the
  ADR-0017 destination invariant guard. Control plane deploys in-cluster to
  `argocd` namespace.
- **`charts/coder-secrets/`** (leaf, wave 0) — ExternalSecrets for OIDC
  credentials, CNPG S3 backup creds, managed role password, and the assembled
  connection URL (ESO Go-template).
- **`charts/coder-db/`** (leaf, wave 1) — CloudNativePG Cluster (2 instances,
  PG 18.4-system-trixie, 5Gi, barman-cloud WAL archiver to Hetzner Object
  Storage), managed role `coder`, `Database` CR, `ScheduledBackup`,
  `PodMonitor`. Raw-resource leaf matching lightbridge-db.
- **`charts/apps/values.yaml`** — `coder` entry with `controlPlane: true`,
  OCI chart float. LimitRange + ResourceQuota uncommented for the `coder`
  namespace.
- **Upstream Coder chart** (`oci://ghcr.io/coder/chart/coder` v2.33.7) deployed
  as a multi-source ArgoCD Application (wave 2) with $values valueFiles and
  a per-environment `depsOverlay` for the ingress `Certificate`.

Workload values and per-environment deps overlays live in the private
`ai-helm-values` repo (per ADR-0055/0056).

## Consequences

**Positive**
- Coder re-introduction follows established, tested patterns — no new
  architectural concepts. The lightbridge pattern is now copy-paste ready for
  any future App-of-Apps workload.
- The Keycloak `coder` client, commented LimitRange/ResourceQuota, and
  integration spec were all usable as-is, validating the ADR-0027 decision
  to leave them in place.
- Local k3s testing confirmed the full stack works: CNPG cluster provisions,
  Coder migrates 115 tables into the managed database, first-user creation
  succeeds via API, and the dashboard loads.

**Negative**
- The wildcard certificate for `*.coder-ai.camer.digital` remains the primary
  blocker — DNS-01 ACME via Cloudflare is the recommended approach, but this
  ADR defers resolution to a follow-up. Without it, workspace apps functionality
  is limited.
- Keycloak OIDC integration was not tested locally (no local Keycloak realm).
  Production Coder startup depends on `coder_oidc_client_id` and
  `coder_oidc_client_secret` being populated in AWS Secrets Manager.
- The `coder-db` CNPG cluster reuses the shared `ssegning-k8s-state` Hetzner
  Object Storage bucket. Backup contention is possible if multiple clusters
  throttle (jobs:1, gzip compression mitigates this).

**Neutral / follow-ups**
- Update `docs/coder-platform-integration.md` targetRevision from `2.31.9` to
  `2.33.7` (or current stable) and refresh stale sections.
- Create ADR-00XX for the wildcard certificate strategy (DNS-01 ACME).
- Populate ASM properties: `coder_oidc_client_id`, `coder_oidc_client_secret`,
  `coder_db_password`.
- Restore the `coder_mcp` LibreChat MCP server entry and `CODERS_MCP_*` env
  vars (removed in ADR-0027) once Coder is live with MCP experiments enabled.

## Alternatives considered

- **No-op (keep Coder removed)** — rejected because AI agent orchestration is
  now a confirmed platform priority, and the integration doc + Keycloak client
  provide a ready path. The cost of re-introduction is low (0.25 FTE scaffolding
  + chart overhead) relative to manual workspace management.
- **ApplicationSet orchestrator** — rejected because Coder has a fixed,
  heterogeneous set of children (secrets, db, app) with different sync-waves,
  which maps cleanly to plain-Helm Application CRs. ApplicationSet is reserved
  for homogeneous fan-out to dynamically-counted leaves.
- **Single monolithic chart** — rejected because it would mix control-plane
  Application CRs with workload-level secrets, CNPG resources, and the upstream
  Coder chart. The App-of-Apps split gives independent sync-wave ordering,
  independent drift detection, and the ability to replace individual leaves
  (e.g., swap the DB leaf for an alternative Postgres operator) without touching
  the orchestrator.

## Related

- Commit: `<pending>`
- Docs: `docs/coder-platform-integration.md`, `coder-decision.md`
- Charts/files touched: `charts/coder/`, `charts/coder-secrets/`,
  `charts/coder-db/`, `charts/apps/values.yaml`,
  `environments/prod/values/coder-app.yaml`,
  `environments/base/deps/coder/`, `environments/prod/deps/coder/`
- Supersedes: ADR-0019 (original Coder App-of-Apps), ADR-0027 (Coder removal)
