# ADR-0083: Re-introduce Coder as App-of-Apps Orchestrator

**Status:** Accepted (updated 2026-07-15)
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
pattern** with two children (secrets + app; the dedicated CNPG child was
removed during review to avoid duplicating the lightbridge-main-db cluster):

- **`charts/coder/`** (orchestrator, v1.0.0) — renders two child `Application`
  CRs via plain Helm (secrets wave 0, app wave 2), targets `home-remote` via
  the ADR-0017 destination invariant guard. The conditional `db.enabled: false`
  block is kept as dead code so the template path exists if needed. Control
  plane deploys in-cluster to `argocd` namespace.
- **`charts/coder-secrets/`** (leaf, wave 0) — three ExternalSecrets for OIDC
  credentials (`coder-oidc`), the CNPG managed-role basic-auth Secret
  (`coder-db-role`), and the assembled connection URL (`coder-db-url`). No
  CNPG S3 backup creds (`coder-cnpg-s3`) — Coder does not have its own CNPG
  cluster. The DB password is URL-encoded via ESO's `urlquery` function.
- **No `charts/coder-db/`** — removed during review. Coder uses the existing
  `lightbridge-main-db` CNPG cluster in `charts/lightbridge-db` (converse
  namespace). A managed `coder` role, `coder` Database CR, and
  `coder-db-role` ExternalSecret are added to `charts/lightbridge-db/values.yaml`.
- **`charts/apps/values.yaml`** — `coder` entry with `controlPlane: true`,
  OCI chart float. LimitRange + ResourceQuota stay **commented** (not enabled
  — same as other namespaces).
- **Upstream Coder chart** (`oci://ghcr.io/coder/chart/coder` v2.33.7) deployed
  as a multi-source ArgoCD Application (wave 2) with `$values` valueFiles and
  a per-environment `depsOverlay` for the ingress `Certificate`. The values
  file is consumed via `ignoreMissingValueFiles: true` (repo convention —
  cut over ai-helm-values first).
- **Certificate strategy: HTTP-01 ACME** (standard platform pattern, issuer
  `cert-home-cert-http`). No wildcard — Coder uses path-based workspace apps
  (`CODER_DISABLE_PATH_APPS` defaults to false). This avoids the DNS-01/Cloudflare
  dependency that blocked the ADR-0027 era.
- **Keycloak OIDC** via the existing `coder` client in
  `charts/keycloak-baseline` with `coder_roles` protocol mapper mapping
  `admin`/`developer` client roles. Role mapping tested against prod
  Keycloak (`auth.verif.fyi`) — OIDC login works. `admin: owner` mapping
  may require a Coder Enterprise license (user was assigned `admin` in
  Keycloak but got `member` role in Coder).

Workload values and per-environment deps overlays live in the private
`ai-helm-values` repo (per ADR-0055/0056).

### Review-tracking note

The following items were raised in review (`@stephane-segning`) and addressed:
- URL-encode DB password (`| urlquery`) in coder-secrets `coder-db-url`.
- Connection URL targets `lightbridge-main-db-rw.converse.svc.cluster.local`
  (not `coder-db-rw.coder.svc.cluster.local`).
- `charts/coder-db/` removed entirely; resources moved to
  `charts/lightbridge-db/values.yaml`.
- `charts/coder/values.yaml`: `db.enabled: false`, all comments updated to
  two children.
- `charts/coder/Chart.yaml`: added `ai-helm.adorsys-gis.github.io/lint-mode: ci-values` annotation.
- `charts/coder/ci/coder-app.yaml`: removed `release: prometheus` label from
  ServiceMonitor; fixed YAML indentation.
- `charts/coder/templates/applications.yaml`: header comment updated.
- `charts/coder-secrets/values.yaml`: removed `coder-cnpg-s3` ExternalSecret
  (no own CNPG).
- `charts/lightbridge-db/values.yaml`: added `coder` managed role, `coder`
  Database CR, `coder-db-role` ExternalSecret.
- `charts/apps/values.yaml`: coder entry comment updated. LimitRange/ResourceQuota
  already commented — no change.
- `ai-helm-values`: CNP PG egress targets `lightbridge-main-db` in `converse`;
  removed coder-db S3 egress CNP. Production values file cleaned up.

## Consequences

**Positive**
- Coder re-introduction follows established, tested patterns — no new
  architectural concepts. The lightbridge pattern is now copy-paste ready for
  any future App-of-Apps workload.
- Uses existing lightbridge-main-db CNPG — no new CNPG cluster to manage,
  no S3 backup credentials needed, fewer CRDs.
- The Keycloak `coder` client, commented LimitRange/ResourceQuota, and
  integration spec were all usable as-is, validating the ADR-0027 decision
  to leave them in place.
- HTTP-01 ACME cert strategy avoids the Cloudflare DNS-01 dependency that
  blocked the original deployment — TLS certs issue automatically.
- OIDC integration tested against prod Keycloak — authentication confirmed
  working end-to-end.
- Local test instance validated at `http://192.168.4.142:32326` — Coder
  migrates and serves correctly against the lightbridge-main-db CNPG.

**Negative**
- Path-based workspace apps require `CODER_DISABLE_PATH_APPS` to remain
  `false` (default). No per-workspace subdomains — workspace URLs are
  path-based under `coder.ai.camer.digital`.
- OIDC role mapping (`admin: owner`) may not work without a Coder Enterprise
  license — user assigned `admin` in Keycloak but got `member` in Coder.
- The `ignoreMissingValueFiles: true` pattern means the `coder-app` child
  silently falls back to upstream chart defaults if the ai-helm-values file
  doesn't exist. Cut over values-repo-FIRST (this is the established repo
  convention — see CLAUDE.md).

**Neutral / follow-ups**
- Update `docs/coder-platform-integration.md` targetRevision from `2.31.9` to
  `2.33.7` (or current stable) and refresh stale sections.
- Create ADR-00XX for the wildcard certificate strategy (DNS-01 ACME) if
  workspace subdomain apps are needed later.
- Populate ASM properties: `coder_oidc_client_id`, `coder_oidc_client_secret`,
  `coder_db_password`.
- Restore the `coder_mcp` LibreChat MCP server entry and `CODERS_MCP_*` env
  vars (removed in ADR-0027) once Coder is live with MCP experiments enabled.
- The workspace template's OpenCode agent install script failed (`opencode: not
  found` in container) — investigate and fix for workspace readiness.

## Alternatives considered

- **No-op (keep Coder removed)** — rejected because AI agent orchestration is
  now a confirmed platform priority, and the integration doc + Keycloak client
  provide a ready path. The cost of re-introduction is low (0.25 FTE scaffolding
  + chart overhead) relative to manual workspace management.
- **ApplicationSet orchestrator** — rejected because Coder has a fixed,
  heterogeneous set of children (secrets, app) with different sync-waves,
  which maps cleanly to plain-Helm Application CRs. ApplicationSet is reserved
  for homogeneous fan-out to dynamically-counted leaves.
- **Single monolithic chart** — rejected because it would mix control-plane
  Application CRs with workload-level secrets and the upstream Coder chart.
  The App-of-Apps split gives independent sync-wave ordering, independent
  drift detection, and the ability to replace individual leaves without
  touching the orchestrator.
- **Dedicated coder-db CNPG cluster** — originally chosen but removed during
  review. Rejected because lightbridge-main-db is underutilized and a separate
  CNPG cluster adds backup S3 credentials, monitoring surface, and
  cluster-management overhead. The shared CNPG cluster with a dedicated
  `coder` role + database is sufficient.

## Related

- Commit: `<pending>`
- Docs: `docs/coder-platform-integration.md`, `coder-decision.md`
- Charts/files touched: `charts/coder/`, `charts/coder-secrets/`,
  `charts/lightbridge-db/`, `charts/apps/values.yaml`,
  `charts/keycloak-baseline/`,
  `environments/prod/values/coder-app.yaml`,
  `environments/base/deps/coder/`, `environments/prod/deps/coder/`
- Supersedes: ADR-0019 (original Coder App-of-Apps), ADR-0027 (Coder removal)
