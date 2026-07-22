# ADR-0085: Self-hosted MLOps platform — LakeFS + Argo Workflows + MLflow

**Status:** Accepted
**Date:** 2026-07-22
**Deciders:** @stephane-segning

## Context

The platform needed three new self-hosted MLOps components on `home-remote`:
**LakeFS** (data-lake version control), **Argo Workflows** (pipeline
orchestration), and **MLflow** (experiment tracking) — all gated behind the
platform's Keycloak IdP (`camer-digital` realm, `auth.verif.fyi`).

Three shared decisions needed to be made before any chart could be written:

1. **S3 backend.** The original ask referenced `s3.ssegning.me`, which this
   repo's own docs (`CLAUDE.md`) already document as retired — replaced by
   Hetzner Object Storage (`nbg1.your-objectstorage.com`, shared bucket
   `ssegning-k8s-state`, creds in `ssegning-aws` at `prod/meta/test-app`,
   properties `s3_backup_cnpg_client_id`/`s3_backup_cnpg_secret`). These are
   the SAME credentials Keycloak's and lightbridge's CNPG backups and
   LibreChat's S3 file storage already use for this bucket — confirmed by
   reading `charts/lightbridge-db/values.yaml` and
   `charts/librechat-app/templates/externalsecret-s3.yaml`.
2. **Auth per app.** Investigation (not assumption) found the three apps
   have materially different OIDC stories:
   - **LakeFS OSS has no functional native OIDC.** The `auth.oidc.*` config
     struct exists in the open-source binary's Go config, but
     `docs.lakefs.io/security/sso/` explicitly states the feature is
     deprecated in OSS and points to lakeFS Cloud/Enterprise instead.
   - **Argo Workflows has native OIDC** (`server.sso` in the upstream
     `argo-helm` chart) — a first-class, well-supported mechanism.
   - **MLflow's specific upstream chart** (`community-charts/mlflow`, image
     `burakince/mlflow`) bundles the `mlflow-oidc-auth` plugin natively
     (`oidcAuth` — a top-level chart key) — real per-user Keycloak identity
     + group-based RBAC inside MLflow itself, no fronting proxy needed. This
     was discovered mid-implementation (after the initial working
     assumption, confirmed with the user, was that MLflow also lacked
     native OIDC) — it is a materially better outcome than a proxy gate and
     was adopted instead.
3. **Metadata DB.** `charts/lightbridge-db/values.yaml` already carries this
   exact precedent three times over (`repoauth`, `codeintel`, `coder`): new
   apps get a managed CNPG role + `Database` CR on the existing
   `lightbridge-main-db` cluster instead of a dedicated CNPG cluster.
   ADR-0083 states the rationale directly: "no new CNPG cluster to manage,
   no S3 backup credentials needed, fewer CRDs."

## Decision

### Namespace and hostnames

A new `mlops` namespace on `home-remote`. Hostnames:
`lakefs.mlops.ai.camer.digital`, `argo-workflows.mlops.ai.camer.digital`,
`mlflow.mlops.ai.camer.digital`.

### S3 backend

Reuse the existing Hetzner Object Storage bucket `ssegning-k8s-state` and
the existing `prod/meta/test-app` credentials, with per-app prefixes:
`lakefs/` (LakeFS's default `storage_namespace`), `mlflow-artifacts/`
(MLflow's `artifactRoot.s3.path`), `argo-workflows-artifacts/` (Argo's
`artifactRepository.s3.keyFormat`). No new bucket, no new IAM credentials.

### Metadata DB

LakeFS and MLflow each get a managed role + `Database` CR added to
`charts/lightbridge-db/values.yaml` (mirroring the `coder` block exactly,
including a same-namespace `kubernetes.io/basic-auth` Secret for CNPG's
`passwordSecret`, separate from the app-facing connection secret). Argo
Workflows needs **no metadata DB at all** — Workflows/WorkflowTemplates are
Kubernetes CRs; it only needs the S3 artifact repository.

### Auth (per app, not uniform)

- **Argo Workflows** — native `server.sso`. Keycloak client `argo-workflows`
  (confidential, standard flow). The `argo_workflows_roles` claim (a
  `oidc-usermodel-client-role-mapper` clientScope, same mechanism as
  `coder`'s `coder_roles`) is read as the SSO "groups" claim via
  `customGroupClaimName`, giving a path to real RBAC without inventing a
  new claim shape. RBAC itself is kept **minimal for v1** — any
  authenticated `camer-digital` user gets the default namespace-scoped
  ServiceAccount; per-role (`admin`/`viewer`) `workflows.argoproj.io/rbac-rule`
  mapping is a named follow-up once real usage patterns emerge.
- **LakeFS** — a **dedicated** oauth2-proxy instance (own Keycloak client
  `lakefs-proxy`, own cookie secret — explicitly NOT shared with any other
  app, per direction) gating the whole app via a Traefik ForwardAuth
  Middleware. This is genuinely new territory for the repo (no prior
  oauth2-proxy/ForwardAuth precedent existed anywhere in `ai-helm`'s history
  — verified via `git log --all -S`). **Known, accepted limitation:**
  oauth2-proxy only gates network access to LakeFS's UI/API — it does not
  give LakeFS itself per-user Keycloak identity. LakeFS's own internal
  user/credential system (access-key/secret-key accounts) remains separate
  and untouched. See Consequences.
- **MLflow** — the bundled `mlflow-oidc-auth` plugin (`oidcAuth`, a
  top-level key in this specific chart's schema — NOT nested under `auth`,
  which is a schema-validation trap). Keycloak client `mlflow`. The
  `mlflow_roles` claim (same clientRoleMapping pattern as `coder`/
  `argo-workflows`) maps client roles `viewer`/`admin` to MLflow's
  `READ`/`MANAGE` permissions via `groupsAttribute`/`groupName`/
  `adminGroupName`. No fronting proxy — a materially better outcome than
  LakeFS's proxy-gated setup, and the reason the two apps aren't treated
  uniformly.

### Chart shape

Each app is an App-of-Apps orchestrator (`charts/coder` is the structural
template, ADR-0083):

- **`charts/lakefs`** (3 children): `lakefs-secrets` (wave 0) →
  `lakefs-auth` (wave 1, upstream `oauth2-proxy` chart) → `lakefs-app`
  (wave 2, upstream `https://charts.lakefs.io` chart).
- **`charts/argo-workflows`** (2 children, the lightest — no DB, no proxy):
  `argo-workflows-secrets` (wave 0) → `argo-workflows-app` (wave 1,
  upstream `https://argoproj.github.io/argo-helm` chart).
- **`charts/mlflow`** (2 children): `mlflow-secrets` (wave 0) →
  `mlflow-app` (wave 1, upstream `https://community-charts.github.io/helm-charts`
  chart).

Each has a matching `*-secrets` leaf chart (ExternalSecrets, values-driven,
copied verbatim from `charts/coder-secrets`'s fully generic template) and a
top-level `controlPlane: true` registration in `charts/apps/values.yaml`.
Workload values live in the private `ai-helm-values` repo (ADR-0056),
seeded values-repo-first per the established convention. Every upstream
chart choice, secret-schema key, and config value was verified by rendering
the actual reference values file against the real upstream chart (not
assumed from documentation alone) before being copied into
`ai-helm-values` — this caught two real schema mistakes during
implementation (MLflow's `oidcAuth` is top-level, not nested under `auth`;
MLflow's `extraEnvVars` is a map, not a list — both differ from LakeFS's
schema for the same-sounding keys).

## Consequences

**Positive**

- Zero new CNPG clusters, zero new S3 buckets/credentials — the mlops
  platform rides entirely on infrastructure this repo already operates and
  backs up.
- Argo Workflows and MLflow both get real per-user Keycloak identity with
  no new auth infrastructure (native OIDC in both cases, discovered rather
  than assumed).
- The App-of-Apps + `*-secrets` leaf pattern required zero new template
  code beyond adding an `auth` child block to the orchestrator template
  (LakeFS only) — everything else is a direct copy of the `coder`/
  `coder-secrets` shape.
- Verifying every reference values file against the real upstream chart
  before committing it caught schema mistakes that documentation-only
  review would have missed.

**Negative**

- **LakeFS's oauth2-proxy gate does not give LakeFS itself per-user
  Keycloak identity.** A user who clears the Keycloak gate still needs a
  separate LakeFS-native access-key/secret-key credential to actually use
  the LakeFS API/UI (created manually by a LakeFS admin, or via LakeFS's
  own self-service credential creation). This is a real, accepted product
  gap — not a design oversight — inherent to LakeFS OSS lacking a
  functional OIDC integration. Closing it fully would require either
  lakeFS Enterprise licensing or building a custom Remote Authenticator
  Service (a documented LakeFS extension point) — both out of scope here.
- Argo Workflows RBAC is intentionally shallow for v1 (one default
  ServiceAccount for all authenticated users) — a real gap if fine-grained
  per-role workflow permissions are needed before the follow-up lands.
- This introduces the repo's first oauth2-proxy/Traefik-ForwardAuth
  deployment — a new pattern to maintain, not a reuse of an existing one.

**Neutral / follow-ups**

- Populate ASM properties before merge: `lakefs_db_password`,
  `lakefs_encrypt_secret_key`, `lakefs_proxy_client_id`,
  `lakefs_proxy_client_secret`, `lakefs_proxy_cookie_secret`,
  `mlflow_db_password`, `mlflow_oidc_client_secret`,
  `argo_workflows_oidc_client_id`, `argo_workflows_oidc_client_secret`
  (all under `ai/camer/digital/prod/env`).
- Argo Workflows per-role RBAC (`admin`/`viewer` → distinct ServiceAccounts
  via `workflows.argoproj.io/rbac-rule`) once real usage patterns emerge.
- If per-user LakeFS identity becomes a real requirement, revisit lakeFS
  Enterprise licensing or a Remote Authenticator Service as a follow-up ADR.

## Alternatives considered

- **Dedicated CNPG clusters for LakeFS/MLflow** — rejected for the same
  reason ADR-0083 rejected it for Coder: more S3 backup credentials, more
  monitoring surface, more CRDs, for a database that the shared
  `lightbridge-main-db` cluster already has headroom for.
- **Shared oauth2-proxy instance across LakeFS and MLflow** — rejected per
  explicit direction: each gated app gets its own instance/client, so a
  compromise or misconfiguration of one doesn't affect the other, and each
  app's session/cookie lifecycle is independent.
- **oauth2-proxy in front of MLflow too** (the original, incorrect working
  assumption) — superseded mid-implementation once the bundled
  `mlflow-oidc-auth` plugin was found in the actual upstream chart schema.
  Kept as the documented reason the three apps aren't treated uniformly.
- **New S3 bucket / new IAM credentials per app** — rejected; user directed
  reuse of the existing shared bucket with per-app prefixes, consistent
  with how every other Hetzner Object Storage consumer in this repo already
  works.

## Related

- Commit: `<pending>`
- ADRs: builds on [0018](./0018-umbrella-apps-and-env-overlays.md) (umbrella/
  App-of-Apps pattern), [0019](./0019-coder-app-of-apps-orchestrator.md) /
  [0083](./0083-coder-re-introduction.md) (the direct structural template),
  [0055](./0055-oci-charts-and-image-updater-writeback-to-values-repo.md) /
  [0056](./0056-workload-values-in-ai-helm-values.md) (values-repo-first,
  OCI chart float), [0017](./0017-home-remote-destination-invariant.md)
  (destination guard).
- Charts/files touched: `charts/lakefs/`, `charts/lakefs-secrets/`,
  `charts/argo-workflows/`, `charts/argo-workflows-secrets/`,
  `charts/mlflow/`, `charts/mlflow-secrets/`, `charts/lightbridge-db/`,
  `charts/keycloak-baseline/`, `charts/apps/values.yaml`.
- `ai-helm-values`: `environments/prod/values/{lakefs-app,lakefs-auth,
  argo-workflows-app,mlflow-app}.yaml`,
  `environments/{base,prod}/deps/{lakefs,argo-workflows,mlflow}/`.
