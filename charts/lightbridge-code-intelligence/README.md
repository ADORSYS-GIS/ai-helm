# lightbridge-code-intelligence

Helm chart for **Lightbridge Code Intelligence** (repo: `vymalo/lightbridge-code-intelligence`) —
the GitHub-App code-review / repository-Q&A system. Modelled on the `librechat-app`
deployment pattern.

## Components

| Component | Workload | Image | Notes |
|---|---|---|---|
| Control plane | Deployment (`*-control-plane`) | `ghcr.io/vymalo/lightbridge-control-plane` | Rust/Axum trust boundary + `/auth/verify` authN surface + GitHub webhook |
| Web console | Deployment (`*-web`) | `ghcr.io/vymalo/lightbridge-web` | Next.js + better-auth; delegates authN to the control plane |
| Knowledge graph | StatefulSet (`*-neo4j`) | `neo4j:5.26-community` | Single instance, PVC-backed |
| Postgres / pgvector | **reused** | — | Uses the existing CNPG cluster `lightbridge-main-db` via a dedicated `codeintel` role + database |

## Database — reuse of `lightbridge-main-db`

This chart does **not** deploy Postgres. It reuses the CloudNativePG cluster
`lightbridge-main-db` (`charts/lightbridge-db`, namespace `converse`), which gains a
dedicated `codeintel` managed role + `codeintel` database in the same change. The control
plane assembles `DATABASE_URL` from `database.*` here plus the password from the
ESO-provisioned `lightbridge-codeintel-db-role` Secret.

> **pgvector is not enabled yet.** The CNPG image (`postgresql:18.4-system-trixie`) does not
> bundle the `vector` extension, so semantic search is deferred until the cluster image ships
> pgvector (or an ImageVolume is added) and the extension is declared on the `codeintel`
> database. The skeleton control plane does not use pgvector yet, so this does not block deploy.

## Secrets

App-owned `ExternalSecret`s resolve against the `ssegning-aws` `ClusterSecretStore`
(properties under `ai/camer/digital/prod/env`):

| Secret | Property | Consumed as |
|---|---|---|
| `lightbridge-ci-github` | `lightbridge_ci_github_webhook_secret` | `GITHUB_WEBHOOK_SECRET` |
| `lightbridge-ci-auth` | `lightbridge_ci_better_auth_secret` | `BETTER_AUTH_SECRET` |
| `lightbridge-ci-neo4j-auth` | `lightbridge_ci_neo4j_password` | Neo4j password |
| `lightbridge-codeintel-db-role` | `codeintel_db_password` | DB password (provisioned by `charts/lightbridge-db`) |

## Ingress

Traefik + cert-manager (`cert-home-cert-http`), librechat-style:

- Web console: `code-intelligence.ai.camer.digital`
- Control plane (webhook + authN): `code-intelligence-api.ai.camer.digital`

## Known follow-ups

- Publish `lightbridge-control-plane` / `lightbridge-web` images (CI in the app repo); the tags
  here are placeholders.
- Enable pgvector on the CNPG cluster.
- Migrate workload templates to `bjw-common` to match the app-chart convention if desired.
