# ADR-0139: Remove Coder, the MLOps stack and the self-hosted code interpreter

**Status:** Accepted
**Date:** 2026-10-18
**Deciders:** @stephane-segning

## Context

Three platform areas were built out over the summer and are now unused, while
the Hetzner cluster is full and their workloads hold roughly 7 GiB of reserved
memory (owner's figure) that other workloads cannot schedule into:

- **Coder** — the `coder` App-of-Apps (`coder-secrets` + `coder-app`), its
  workspace templates (`.coder/`, `terraform/coder` in `ai-helm-values`), a
  `coder` role + `coder` database on `lightbridge-main-db`, a Keycloak client,
  and a LibreChat `coder` MCP server + agent that talked to it
  ([ADR-0083](./0083-coder-re-introduction.md)).
- **MLOps** — LakeFS (+ the `lakefs-proxy` SSO shim), Argo Workflows and MLflow
  in the `mlops` namespace, their dedicated `mlops-main-db` CNPG cluster, and
  `webank-training` (Argo `WorkflowTemplate`s that need Argo Workflows and
  LakeFS) ([ADR-0085](./0085-mlops-platform-lakefs-argo-workflows-mlflow.md),
  [ADR-0123](./0123-mlops-dedicated-cnpg-cluster.md)).
- **The LibreChat code interpreter** — `charts/librechat-code-interpreter` in
  its own privileged `librechat-sandbox` namespace
  ([ADR-0122](./0122-self-hosted-code-interpreter.md)).

The owner's instruction (2026-10-18) was "remove librechat sandbox, mlops and
coder e2e".

## Decision

Remove all three end to end, as a hard cutover in one change (no flags, no
scaled-to-zero leftovers):

- Delete their entries from `charts/apps/values.yaml`
  (`librechat-code-interpreter`, `coder`, `lakefs`, `argo-workflows`, `mlflow`,
  `webank-training`) and their chart directories, the `.coder/` templates, the
  Coder MCP e2e suite, and the docs that described them as live.
- Remove every cross-reference: the `coder` role/Database/ExternalSecret in
  `charts/lightbridge-db`, the Keycloak clients and client scopes for coder,
  argo-workflows, lakefs-proxy and mlflow in `charts/keycloak-baseline`, the
  code-interpreter env/secrets and the Coder MCP credentials in
  `charts/librechat-app`, and the `librechat-sandbox` PodSecurity elevation.
- The matching values, deps overlays, Terraform and CI in
  `adorsys-gis/ai-helm-values` are removed by a companion PR.
- **Keep `gpu-priority-classes`**: it only renders two cluster-scoped
  `PriorityClass` objects consumed by `charts/inference`. Its (formal)
  destination namespace moves from `mlops` to `inference`, the namespace
  `charts/inference` deploys into, so it no longer depends on a namespace that
  is going away. The `mlops-training` class is kept as shipped; nothing requests
  it any more.

## Consequences

**Positive**
- Frees the reserved memory and removes four OIDC clients, two CNPG tenants'
  worth of connection pressure on `lightbridge-main-db`, and a privileged
  namespace from the attack surface.
- Fewer charts and Applications to render, lint, publish and keep current.

**Negative**
- Data is destroyed. Pruning the Applications removes the workloads and their
  rendered PVCs; the `mlops-main-db` CNPG `Cluster` is deleted with its PVCs
  (garbage-collected through owner references). Barman backups already in
  object storage are not touched.
- The `coder` database and role on `lightbridge-main-db` are **not** dropped by
  merging: a CNPG `Database` CR deleted by Argo prune follows the
  `databaseReclaimPolicy` that is already live on it (`retain`, the default),
  and removing a role from `managed.roles` does not drop it. Dropping them
  needs one manual `DROP DATABASE` / `DROP ROLE` (see the PR description).
- Namespaces `mlops`, `coder` and `librechat-sandbox` are created by
  `CreateNamespace=true`, not owned by Argo, and stay until deleted by hand.

**Neutral / follow-ups**
- External state git cannot remove (S3 prefixes, Secrets Manager properties,
  DNS names, Keycloak clients, Coder's GitHub OAuth app, Terraform state) is
  listed in the PR descriptions.
- Re-introducing any of these is a new ADR; history is in git.

## Alternatives considered

- **Scale to zero / `enabled: false` and keep the code** — rejected: leaves
  dormant charts, values and policies to keep current, and the owner asked for
  removal end to end.
- **Remove only the Applications, keep charts and docs** — rejected: dangling
  charts still render, lint and publish on every merge.
- **Two-step database drop (set `databaseReclaimPolicy: delete`, merge, then
  delete the CR)** — not done in this change: it would need a second PR in the
  middle of a destructive cutover, and retaining the `coder` database is the
  safer default until the owner confirms nothing in it is needed.

## Related

- Supersedes: [ADR-0083](./0083-coder-re-introduction.md),
  [ADR-0085](./0085-mlops-platform-lakefs-argo-workflows-mlflow.md),
  [ADR-0090](./0090-lakefs-sso-via-lakefs-proxy-shim.md),
  [ADR-0091](./0091-mlops-programmatic-access-and-bearer-audience.md),
  [ADR-0121](./0121-coder-workspace-url-exposure-strategy.md),
  [ADR-0122](./0122-self-hosted-code-interpreter.md),
  [ADR-0123](./0123-mlops-dedicated-cnpg-cluster.md),
  [ADR-0124](./0124-declarative-coder-template-management.md),
  [ADR-0131](./0131-coder-workspace-opencode-internal-sa-auth.md).
- Partially supersedes [ADR-0114](./0114-gpu-priority-preemption-over-a-serving-clock.md):
  the `webank-training` consumer is gone; the PriorityClass chart stays.
- Charts/files touched: `charts/apps/values.yaml`, `charts/lightbridge-db`,
  `charts/keycloak-baseline`, `charts/librechat-app`, `charts/gpu-priority-classes`.
