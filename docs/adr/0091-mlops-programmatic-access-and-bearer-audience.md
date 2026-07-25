# ADR-0091: Gate MLflow bearer tokens on `aud`, and open a least-privileged programmatic path to Argo Workflows

**Status:** Accepted
**Date:** 2026-07-25
**Deciders:** @stephane-segning

Amends [ADR-0085](0085-mlops-platform-lakefs-argo-workflows-mlflow.md)'s auth
decision for MLflow and Argo Workflows (the ADR-0085 body stays as written —
ADRs are immutable once Accepted). ADR-0085 established *native OIDC, no
fronting proxy* for both apps and deliberately deferred RBAC detail as "kept
minimal for v1". Live verification of that v1 found one hole and two dead ends.

Runbook + troubleshooting: [`docs/playbooks/mlops-app-auth.md`](../playbooks/mlops-app-auth.md).

## Context

Three findings, all verified live against the running `mlops` namespace
(2026-07), none of them predictable from the charts:

1. **MLflow accepted any token from the realm.** A client-credentials token
   minted for the *unrelated* `testing-client` (`aud: ['coder','account']`, no
   `mlflow_roles` claim) got **HTTP 200** from
   `POST /api/2.0/mlflow/experiments/search` on the public ingress. The
   `mlflow-oidc-auth` plugin (v7.3.1) verifies the JWT signature against the
   Keycloak JWKS, but that JWKS is **realm-wide**; the plugin only asks for an
   audience check when `OIDC_AUDIENCE` is set
   (`config.py::_get_claims_options()` conditionally adds
   `{"aud": {"essential": True, "value": …}}`). It was unset. The
   `OIDC_GROUP_NAME` / `adminGroupName` gate does not cover this — it runs on
   the browser OIDC-callback path only, never on `Authorization: Bearer`. So
   the effective authorization boundary for the API was "holds any token from
   `camer-digital`", i.e. every service account in the platform.

2. **Every workflow step failed, silently, on `workflowtaskresults`.** The
   upstream chart's defaults are internally inconsistent:
   `workflow.rbac.create: true` renders a Role + RoleBinding, but
   `workflow.serviceAccount.create: false` means the SA that binding names is
   never created — and our values set no `workflow:` block at all. Live:
   `kubectl -n mlops get sa argo-workflow` → **NotFound**; RoleBinding
   `argo-workflows-workflow` referencing it anyway;
   `auth can-i create workflowtaskresults.argoproj.io
   --as=system:serviceaccount:mlops:default` → **no**. Workflow pods ran as
   `mlops/default`, and the executor sidecar reports each node's outcome by
   creating/patching a `workflowtaskresults`, so steps failed *even when their
   container exited 0*.

3. **Nothing could drive Argo Workflows programmatically.** With
   `server.authModes: [sso]`, a Kubernetes ServiceAccount token got
   `{"code":16,"message":"token not valid..."}` (HTTP 401). Reading
   `server/auth/mode.go` (v4.0.7): SSO mode matches **only** the prefix
   `Bearer v2:` — an *encrypted* JWE that argo-server itself mints in its own
   `/oauth2/callback` and that nothing else can produce. A plain
   `Bearer <token>` matches only the **Client** mode branch, which was
   disabled. No CI job, script, or scheduled task could submit or poll a
   Workflow at all.

A fourth question fell out of the same review: LakeFS OSS with `rbac: none`
supports exactly **one** credential (its credential-management API answers
`501 Not Implemented`), so "give workflows their own LakeFS key" is not
available — the only question is how that single key is consumed.

## Decision

**Adopt bearer-audience enforcement for MLflow, and open Argo Workflows'
client-mode API path behind a dedicated, short-lived-token-only ServiceAccount.**

- **MLflow** — set `oidcAuth.audience: "mlflow"` (renders `OIDC_AUDIENCE`).
  A token is accepted by the API only if it carries `mlflow` in `aud`. The
  realm side (an audience mapper on the `mlflow` client) is out-of-band, as
  the whole `camer-digital` realm is ([`keycloak-audience-operations.md`](../playbooks/keycloak-audience-operations.md)).
- **Argo workflow-pod identity** — set `workflow.serviceAccount.create: true`
  (`name: argo-workflow`, **no** token Secret) **and**
  `controller.workflowDefaults.spec.serviceAccountName: argo-workflow`.
  Creating the SA alone is necessary but not sufficient: Argo defaults a
  workflow pod to the namespace `default` SA, so without the workflow default
  every caller would have to remember `spec.serviceAccountName` forever.
- **Argo workflow-pod RBAC** — additionally enable
  `workflow.rbac.agentPermissions` and `workflow.rbac.artifactGC`. Both are
  two verbs on a single Argo-internal CRD, namespaced to `mlops`; both fail
  as silent hangs rather than clean 403s; and `artifactGC` additionally
  removes a destructive footgun (see Consequences).
- **Argo programmatic access** — set `server.authModes: [sso, client]` and add
  a dedicated `argo-workflows-ci` ServiceAccount + namespaced Role +
  RoleBinding in `environments/base/deps/argo-workflows/rbac.yaml`. **No
  long-lived token Secret is created for it**: callers mint a bound token with
  `kubectl -n mlops create token argo-workflows-ci --duration=30m`.
- **LakeFS from workflows** — **do not** copy or re-materialise the
  credential. Workflow steps mount the existing `lakefs-proxy-admin` Secret by
  explicit `secretKeyRef` (`optional: false`) and authenticate to
  `http://lakefs.mlops.svc.cluster.local:80` with HTTP Basic. This is
  documented, not templated — no example WorkflowTemplate ships.

## Consequences

**Positive**

- The MLflow API's authorization boundary becomes "a token minted *for
  MLflow*" instead of "a token minted for anything in the realm". Nothing
  legitimately used the Bearer path yet, so the hole closes with no
  user-visible regression, and the browser session path is untouched.
- Workflows actually run. A plain `argo submit` with no `serviceAccountName`
  now gets an identity that can report its own step results.
- `client` is the **least-privileged** of argo-server's three auth modes:
  the server builds a Kubernetes `rest.Config` from the caller's own token and
  acts *as that identity*, so ordinary namespaced RBAC decides every call and
  every call is attributable. (`server` mode — where all callers share
  argo-server's own SA and therefore its full permissions — is the dangerous
  one and stays off.)
- Enabling `workflow.rbac.artifactGC` up front avoids a *destructive* trap:
  Argo places a `workflows.argoproj.io/artifact-gc` finalizer on any Workflow
  declaring `spec.artifactGC`, and a GC pod that cannot reach its
  `workflowartifactgctasks` leaves that finalizer in place — the Workflow then
  sticks in `Terminating` until someone patches the finalizer off by hand.
  With `archiveLogs: true` writing a log tarball per pod into the shared
  `ssegning-k8s-state` bucket under a prefix with no lifecycle rule, artifact
  GC is the only thing that will ever delete any of it.
- One LakeFS credential stays one credential. No second copy to rotate, and
  the blast radius stays legible.

**Negative**

- **A Keycloak-side change is now load-bearing.** Any future token intended for
  the MLflow API must carry `mlflow` in `aud`. Forget the audience mapper and
  the call fails with an opaque 401 rather than "you need an audience".
- **Two auth modes on argo-server is a wider surface than one.** A caller with
  *any* valid ServiceAccount token in the cluster can now reach the Argo API —
  it will simply be authorized as that identity, so an SA with no `argoproj.io`
  permissions gets a clean 403. The security property rests entirely on
  namespaced RBAC being right.
- **Short-lived tokens are a workflow cost.** CI must call
  `kubectl create token` per run instead of reading a static Secret. This is
  deliberate; a `*.service-account-token` Secret is a never-expiring,
  effectively non-revocable credential.
- **The LakeFS key mounted into a workflow is effectively LakeFS root** and is
  *shared with the `lakefs-proxy` SSO shim* (ADR-0090). A workflow that leaks
  it compromises LakeFS entirely, and rotating it means updating the shim's
  ASM properties **and** deleting the shim pod (its env binds once at pod
  start). Mount it only into steps that genuinely talk to LakeFS.
- Nothing here fixes LakeFS's single-identity limitation — workflow writes are
  indistinguishable from human writes in the LakeFS audit trail, exactly as
  ADR-0090 already accepted for browsers.

**Neutral / follow-ups**

- SSO delegate RBAC (`argo-workflows-admin` / `argo-workflows-viewer`) is
  untouched and does **not** transfer to client mode — the two identity paths
  are independent by design, and `rbac.yaml` now says so at the top.
- `argo-workflows-ci` is namespaced-only on purpose: no
  `clusterworkflowtemplates`, no `workflowtaskresults` (that belongs to the
  workflow pod, not the submitter). A second automation consumer with
  different needs should get its **own** SA + Role rather than extra verbs on
  this one.
- Mapping `argo_workflows_roles` to distinct delegate SAs beyond
  admin/viewer remains the ADR-0085 follow-up it always was.

## Alternatives considered

- **Leave `OIDC_AUDIENCE` unset and rely on the group gate** — rejected: the
  group gate demonstrably does not run on the Bearer path. Verified live.
- **Front MLflow with an oauth2-proxy instead** — rejected: it would gate the
  browser path (already gated) and not the API path, which is the actual hole;
  it also reintroduces the double-login shape ADR-0085 removed.
- **`server.authModes: [sso, server]`** — rejected: `server` mode makes every
  API caller share argo-server's own ServiceAccount, which is broadly
  privileged. It would "work" with zero RBAC effort and destroy attribution.
- **Reuse the `argo-workflows-admin` SSO delegate as the CI identity** —
  rejected: client mode bypasses SSO RBAC delegation, so the delegate's rules
  are not what would apply anyway; and the delegate is intentionally
  UI-shaped (cluster-scoped `clusterworkflowtemplates`, Argo Events probes),
  which is more than CI needs.
- **Issue a long-lived `argo-workflows-ci.service-account-token` Secret** —
  rejected: it never expires and cannot be revoked without deleting the SA.
  Bound tokens from `kubectl create token` are the supported path.
- **Add `default` to `workflow.rbac.serviceAccounts` instead of creating an
  SA** — rejected: it grants the namespace's catch-all identity Argo
  permissions and leaves workflow pods unattributable.
- **Leave `agentPermissions`/`artifactGC` off until first needed** — the
  orthodox minimal-RBAC answer, rejected on failure-mode grounds: neither
  produces a 403 that points at the missing grant (one hangs, one wedges a
  finalizer), and each grant is two verbs on one Argo-internal CRD with no
  data access and no escalation surface.
- **Copy `lakefs-proxy-admin` into a workflow-scoped Secret** — rejected: it
  is the same credential either way, so it adds a rotation target and *hides*
  the fact that the shim shares it.
- **Ship an example `WorkflowTemplate` that mounts the LakeFS key** — rejected
  for now: a shipped template is a supported artifact that has to be
  maintained and would normalise mounting a root credential. Documented
  pattern first; template only if a real pipeline needs one.

## Related

- Amends: [ADR-0085](0085-mlops-platform-lakefs-argo-workflows-mlflow.md) (the mlops platform + per-app auth)
- Builds on: [ADR-0090](0090-lakefs-sso-via-lakefs-proxy-shim.md) (the shared LakeFS admin credential), [ADR-0056](0056-workload-values-in-ai-helm-values.md) (workload values in `ai-helm-values`)
- Docs: [`docs/playbooks/mlops-app-auth.md`](../playbooks/mlops-app-auth.md), [`docs/playbooks/lakefs-sso.md`](../playbooks/lakefs-sso.md), [`docs/playbooks/keycloak-audience-operations.md`](../playbooks/keycloak-audience-operations.md)
- Files touched: `ai-helm-values` `environments/prod/values/{mlflow-app,argo-workflows-app}.yaml` + `environments/base/deps/argo-workflows/rbac.yaml`; reference mirrors `charts/mlflow/ci/mlflow-app.yaml`, `charts/argo-workflows/ci/argo-workflows-app.yaml`
