# MLOps app auth — Argo Workflows SSO/RBAC + MLflow OIDC

**Live** in namespace `mlops` on `home-remote`: `argo-workflows.mlops.ai.camer.digital`
and `mlflow.mlops.ai.camer.digital`. Both authenticate against Keycloak
(`camer-digital` @ `auth.verif.fyi`) with their **own native OIDC** — no
fronting proxy. Decisions: [ADR-0085](../adr/0085-mlops-platform-lakefs-argo-workflows-mlflow.md)
(the platform) and [ADR-0091](../adr/0091-mlops-programmatic-access-and-bearer-audience.md)
(bearer-audience enforcement + the programmatic path).

> LakeFS is the odd one out — it has no OIDC at all and needs a session shim.
> It gets its own page: [`lakefs-sso.md`](./lakefs-sso.md) ([ADR-0090](../adr/0090-lakefs-sso-via-lakefs-proxy-shim.md)).

**Why these two share a page and LakeFS doesn't:** Argo Workflows and MLflow are
the *same* problem twice — a native OIDC integration whose traps are all about
getting the **claim shape** and the **identity the app then acts as** right, in
one namespace against one realm. Neither is long enough to carry a runbook of
its own, and their cross-cutting facts (the Keycloak clients, the realm-drift
warning) are identical. LakeFS is a different problem — a three-hop request
path, a first-party image, and a destructive credential runbook.

## Cross-cutting facts for the whole `mlops` namespace

⚠️ **`charts/keycloak-baseline` is NOT deployed or reconciled by anything.** No
ArgoCD Application, no keycloak-config-cli run, no `KeycloakRealmImport` CR. The
`camer-digital` realm is effectively **manually managed** — editing that chart
changes nothing on the cluster, and the chart may be silently wrong. Live client
ids for these apps are:

| App | Live Keycloak client | Claim it reads |
|---|---|---|
| Argo Workflows | `argo_workflows` | `argo_workflows_roles` (read as SSO "groups") |
| MLflow | `mlflow` | `mlflow_roles` |
| LakeFS (via oauth2-proxy) | `lakefs_proxy` | — (proxy only needs the login) |

**All three use underscores.** The chart used hyphens, which never matched
anything live. Treat the chart as documentation of intent, adjust Keycloak in
the admin console, and mirror changes back so the drift does not widen.

⚠️ **oauth2-proxy `cookie-secret` must decode to exactly 16/24/32 bytes** — use
`openssl rand -hex 16` (32 chars). A padded base64 (44 chars) crashes the proxy
at startup with `cookie_secret must be 16, 24, or 32 bytes to create an AES
cipher, but is 44 bytes`. (Relevant to LakeFS and Homepage, not to these two —
noted here because it bites once per new gated app.)

---

# Argo Workflows

Config: `ai-helm-values` `environments/prod/values/argo-workflows-app.yaml`
(reference copy `charts/argo-workflows/ci/argo-workflows-app.yaml`); RBAC +
CRD stubs: `environments/base/deps/argo-workflows/{rbac,argo-events-crd-stubs}.yaml`.

## Start here: THREE identities, and they share nothing

Almost every Argo permission bug in this namespace is really "I fixed the wrong
identity". There are three, they are independent, and a permission granted to
one does **not** reach the others:

| # | Identity | Who uses it | Where it is defined |
|---|---|---|---|
| 1 | `argo-workflows-admin` / `argo-workflows-viewer` | The **browser** (`--auth-mode=sso`) — argo-server *impersonates* one of these | `deps/argo-workflows/rbac.yaml` |
| 2 | `argo-workflow` | Every **workflow pod's** executor sidecar | the chart: `workflow.serviceAccount` in the values file |
| 3 | `argo-workflows-ci` | **Scripts / CI** (`--auth-mode=client`) — argo-server acts *as the caller* | `deps/argo-workflows/rbac.yaml` |

In particular: client mode **bypasses SSO RBAC delegation entirely**, so the
delegate SAs' rules are irrelevant to an API client, and vice versa.

## The one debugging fact that saves the most time

**`code:7` and `code:5` are different bugs.**

| Response | gRPC code | Means | Fix class |
|---|---|---|---|
| `{"code":7,"message":"…not allowed"}` | `PERMISSION_DENIED` | RBAC — the identity the server is acting as lacks the permission | RBAC / impersonation-token |
| `{"code":5,"message":"the server could not find the requested resource"}` | `NOT_FOUND` | The **CRD is not installed**. The resource *type* does not exist | Install/register the CRD — **no amount of RBAC helps** |

## How SSO actually resolves an identity

With `server.authModes: [sso]` + `server.sso.rbac.enabled: true`, argo-server
**impersonates the matched delegate ServiceAccount** and makes *every*
Kubernetes call as it. So the **delegate SA** — not the server's own SA — must
hold every permission the UI exercises. Delegates are selected by the
`workflows.argoproj.io/rbac-rule` annotation, `…/rbac-rule-precedence` numeric,
**higher wins**: `argo-workflows-admin` (`'admin' in groups`, precedence 10) and
`argo-workflows-viewer` (`true`, precedence 1) as the read-only catch-all.

`groups` here is the `argo_workflows_roles` claim, repointed via
`server.sso.customGroupClaimName` — a client-role mapper, not a Keycloak realm
group.

### ⚠️ The SSO token Secret **name** is load-bearing

Kubernetes ≥1.24 no longer auto-creates SA token Secrets, so each delegate needs
one — and argo-server looks it up by a **hardcoded, dot-separated** name:

```
<sa-name>.service-account-token        # argo-workflows-admin.service-account-token
```

This is argo-server's own convention, **not** the Kubernetes
`<sa>-token-xxxxx` pattern. A dash-named Secret produces the most misleading
failure in the stack: RBAC selection *succeeds* (the server logs
`selected SSO RBAC service account for user`) and then **every** request fails
`{"code":7,"message":"not allowed"}`, with the real cause only in the server log:

```
failed to get service account secret: secrets "argo-workflows-admin.service-account-token" not found
```

### ⚠️ Two permissions the chart's aggregate ClusterRoles don't give you

- **`clusterworkflowtemplates` is cluster-scoped.** A namespaced `RoleBinding`
  can **never** authorize it, no matter which ClusterRole it references. It needs
  a `ClusterRoleBinding`. Keep the ClusterRole to that **one** resource so
  namespaced workflows are not exposed cluster-wide.
- **`eventsources` / `sensors`** are Argo **Events** CRDs, omitted from the
  chart's aggregate admin/view ClusterRoles — yet the Workflows UI probes them
  unconditionally on the namespace page. Granting them is harmless whether or
  not Argo Events is installed.

Hence the explicit namespaced `Role`s in `rbac.yaml` (a superset of the chart's
namespaced permissions, plus `eventsources`/`sensors`) instead of binding the
aggregate ClusterRoles.

### ⚠️ Argo Events CRD stubs

We do not run Argo Events, so after RBAC was fixed the UI moved from `code:7` to
`code:5` — the *type* was missing, a 404, not a 403. Fix: register **minimal
placeholder CRDs** (`EventBus`, `EventSource`, `Sensor`, `v1alpha1`,
`x-kubernetes-preserve-unknown-fields`) so the UI's list calls return an empty
200. There is **no chart value or server flag** to hide that UI. If Argo Events
is ever deployed for real, its full CRDs supersede these (same names/group/version).

### ⚠️ `singleNamespace: true`

Adds `--namespaced` to server **and** controller, so they operate only in
`mlops`. Without it the server is cluster-scoped and the UI lists workflows
across **all** namespaces (`namespace=""`), which needs cluster-wide list
permission — but the delegate SAs are bound with **namespaced** RoleBindings, so
the UI fails `code:7 … not allowed to list workflows in namespace ""`. Verified
live: the delegates can list workflows in `mlops` but not `--all-namespaces`.

### ⚠️ `crds.install: false`

The chart's `crds.full: true` path installs CRDs through a **pre-install/upgrade
hook Job that `kubectl apply`s them from `raw.githubusercontent.com` at every
sync**. Under the default-deny-egress Cilium baseline that Job races FQDN-policy
programming, times out, and **fails the whole Application**. The 8 `argoproj.io`
CRDs are installed cluster-wide out-of-band instead.

Trade-off: a chart bump that changes CRD schemas will **not** auto-apply. Apply
them manually first, from a host with egress:

```bash
kubectl apply --server-side -f \
  https://raw.githubusercontent.com/argoproj/argo-helm/argo-workflows-<VER>/charts/argo-workflows/files/crds/full/
```

### One more live-found trap

`server.sso.scopes: [groups]` named a scope that does not exist on this client,
and Keycloak rejects the **whole** OIDC request (`invalid_scope`) rather than
just omitting the claim. No `scopes` override is needed at all — the
`argo-workflows` clientScope is a **default** scope, always in the token.

## Workflow pods need their own ServiceAccount — the chart's defaults don't give them one

**Symptom:** every step of every workflow fails, *even when its container exits
0*. **Cause:** the executor sidecar reports each node's outcome by creating and
patching a `workflowtaskresults.argoproj.io`. No permission ⇒ no result ⇒ the
step is recorded as failed regardless of what the container did.

The upstream chart's defaults are internally inconsistent:
`workflow.rbac.create` is **true** (renders Role + RoleBinding) while
`workflow.serviceAccount.create` is **false** — so out of the box the
RoleBinding's only subject is a ServiceAccount that never exists. Found live:

```bash
kubectl -n mlops get sa argo-workflow                      # NotFound
kubectl -n mlops get rolebinding argo-workflows-workflow -o yaml
#   subjects: [{kind: ServiceAccount, name: argo-workflow}]   ← no such SA
kubectl -n mlops auth can-i create workflowtaskresults.argoproj.io \
  --as=system:serviceaccount:mlops:default                 # no
```

(The RoleBinding subject carries no `namespace:` field, which is correct — for
a RoleBinding, a ServiceAccount subject with an empty namespace defaults to the
binding's own namespace. That is not the bug.)

⚠️ **Creating the SA is necessary but NOT sufficient.** Argo defaults a workflow
pod to the namespace's `default` SA. Both halves are required:

```yaml
workflow:
  serviceAccount:
    create: true
    name: argo-workflow
    createSecret: false          # pods get a projected token; no legacy Secret
  rbac:
    create: true
    agentPermissions: true       # http/plugin templates — else the agent HANGS
    artifactGC: true             # else artifact GC wedges the wf finalizer
controller:
  workflowDefaults:
    spec:
      serviceAccountName: argo-workflow   # ← the half people forget
```

`workflowDefaults` is *merged into* each Workflow, so an explicit
`spec.serviceAccountName` still wins.

On the two RBAC extras — both are two verbs on one Argo-internal CRD,
namespaced to `mlops`, and both fail as **silent hangs rather than clean 403s**:

- `agentPermissions` grants `workflowtasksets` list/watch + `.../status` patch
  to the **agent pod** (the single pod Argo runs for `http`/`plugin` templates
  instead of one pod per step). Without it the agent cannot watch its taskset
  and the workflow sits in `Running` until its deadline.
- `artifactGC` grants `workflowartifactgctasks` list/watch + `.../status`
  patch. This one also removes a *destructive* trap: Argo puts a
  `workflows.argoproj.io/artifact-gc` **finalizer** on any Workflow declaring
  `spec.artifactGC`, and a GC pod that cannot reach its tasks leaves it in
  place — the Workflow then sticks in `Terminating` until someone patches the
  finalizer off by hand. With `artifactRepository.archiveLogs: true` writing a
  log tarball per pod into the shared `ssegning-k8s-state` bucket (no lifecycle
  rule on the prefix), GC is the only thing that will ever delete any of it.

Neither flag turns on any behaviour — they only create RBAC.

## Programmatic access: `--auth-mode=client`

**Symptom:** a CI job or script passing a Kubernetes ServiceAccount token gets
`{"code":16,"message":"token not valid..."}` (HTTP 401) from every endpoint.

**Cause, from `server/auth/mode.go` (v4.0.7):** SSO mode matches **only** the
prefix `Bearer v2:` — an *encrypted* JWE that argo-server mints in its own
`/oauth2/callback` and that nothing else can produce. A plain
`Bearer <k8s-token>` falls through to the **Client** mode branch, which was
disabled. With `authModes: [sso]` there is simply no programmatic path.

**Fix:** `server.authModes: [sso, client]`. Each entry renders one
`--auth-mode=<x>` arg on the server Deployment.

### Why `client` and not `server`

In **client** mode argo-server builds a Kubernetes `rest.Config` **from the
caller's own token** and acts *as that identity* — ordinary namespaced RBAC
decides every call, and every call is attributable. It is the
**least-privileged** of the three modes.

`server` mode is the dangerous one: every caller shares argo-server's own
ServiceAccount and therefore its full permissions. **Never enable it here.**

### Using it

```bash
# 1. Mint a SHORT-LIVED bound token. Never a *.service-account-token Secret —
#    those never expire and cannot be revoked without deleting the SA, which
#    is why none is created for this SA.
TOKEN=$(kubectl -n mlops create token argo-workflows-ci --duration=30m)

# 2. Call the API as that identity.
curl -H "Authorization: Bearer $TOKEN" \
  https://argo-workflows.mlops.ai.camer.digital/api/v1/workflows/mlops

# …or drive the CLI with it.
export ARGO_SERVER=argo-workflows.mlops.ai.camer.digital:443
export ARGO_SECURE=true ARGO_HTTP1=true ARGO_NAMESPACE=mlops
export ARGO_TOKEN="Bearer $TOKEN"
argo submit --wait pipeline.yaml
```

⚠️ **An API client's SA needs its OWN namespaced RBAC** on `argoproj.io` in
`mlops`. The SSO delegates' permissions do **not** transfer — client mode
bypasses SSO RBAC delegation. `argo-workflows-ci`'s Role
(`deps/argo-workflows/rbac.yaml`) covers `workflows` /
`workflowtemplates` / `cronworkflows` CRUD plus read-only `pods`, `pods/log`
(needed for `argo logs` — the server reads them *as the caller*) and `events`.

Deliberately **not** in that Role:

- `workflowtaskresults` — that belongs to identity #2, the workflow pod, not to
  the submitter. It only becomes relevant if a Workflow explicitly sets
  `spec.serviceAccountName: argo-workflows-ci`; don't.
- `clusterworkflowtemplates` — cluster-scoped, so it would need a
  ClusterRoleBinding and would widen a CI credential past its namespace.
  Reference namespaced `WorkflowTemplate`s instead.

A second automation consumer with different needs gets its **own** SA + Role.
Grant more identities, not more verbs.

## Reaching LakeFS from a workflow step

LakeFS OSS runs with `rbac: none`, which supports exactly **one** credential —
its credential-management API answers `501 Not Implemented`, so there is no
per-workflow key to mint. That single pair already exists in this namespace as
Secret **`lakefs-proxy-admin`** (keys `access-key-id` / `secret-access-key`,
materialised by `charts/lakefs-secrets` from ssegning-aws
`ai/camer/digital/prod/env`). It is deliberately **not** duplicated for Argo: a
copy would be a second thing to rotate and would hide the blast radius.

> ⚠️ **This key is effectively LakeFS root, and it is shared with the SSO shim.**
> It is the LakeFS `admin` user — there is no lesser role to drop to — and it is
> the same pair `lakefs-proxy` ([ADR-0090](../adr/0090-lakefs-sso-via-lakefs-proxy-shim.md))
> logs in with to mint browser sessions. A workflow that leaks it compromises
> LakeFS entirely, and rotating it means updating both ASM properties **and**
> deleting the shim pod (its env binds once at pod start). Mount it only into
> steps that genuinely talk to LakeFS — never into a step running untrusted or
> user-supplied code.

Scripts authenticate to the LakeFS API with **HTTP Basic** using the pair
(verified in-cluster). Workflow pods reach
`http://lakefs.mlops.svc.cluster.local:80` directly: the only Cilium policy in
`mlops` selects `app.kubernetes.io/instance: argo-workflows`, a label workflow
pods do not carry, so they are not in enforcement mode. **If a namespace-wide
default-deny is ever added to `mlops`, workflow pods will need their own
additive allow.**

```yaml
- name: lakefs-list-repos
  container:
    image: alpine/curl:latest
    env:
      - name: LAKEFS_ACCESS_KEY_ID
        valueFrom:
          secretKeyRef:
            name: lakefs-proxy-admin
            key: access-key-id
            optional: false          # ⚠️ never true — see below
      - name: LAKEFS_SECRET_ACCESS_KEY
        valueFrom:
          secretKeyRef:
            name: lakefs-proxy-admin
            key: secret-access-key
            optional: false
    command: [sh, -c]
    args:
      - |
        curl -fsS -u "$LAKEFS_ACCESS_KEY_ID:$LAKEFS_SECRET_ACCESS_KEY" \
          http://lakefs.mlops.svc.cluster.local/api/v1/repositories
```

⚠️ **Do not use `envFrom: [secretRef: …]` as a shortcut.** `envFrom` derives env
*names* from the Secret *keys*, and these are hyphenated (`access-key-id`) —
not valid environment-variable identifiers. Kubernetes **silently skips** them
and only records an `InvalidEnvironmentVariableNames` event on the pod, so the step runs
with no credential and fails with a 401 that looks like a bad key.

⚠️ **`optional: false` is not decoration.** Env from a `secretKeyRef` binds once
at pod start and never refreshes; an optional ref lets a pod that beats ESO
capture an **empty** credential and 401 forever against a perfectly valid key
(the context7 `MCP_TOKEN` incident — see `CLAUDE.md`; same reasoning as
`lakefs-proxy`'s own env refs).

For the S3 gateway (`lakectl`, boto, pandas `s3://`) use the same pair as
`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` against the same endpoint.
External access is not an option: the only public route to LakeFS is through
oauth2-proxy + the shim, which is a browser-session path.

## Argo Workflows — symptom → fix

| Symptom | Cause | Fix |
|---|---|---|
| `{"code":7,"message":"not allowed"}` on **everything**, but the log says `selected SSO RBAC service account for user` | The impersonation token Secret is misnamed | Name it `<sa>.service-account-token` (dot!), type `kubernetes.io/service-account-token`, annotation `kubernetes.io/service-account.name` |
| `code:7` only on `clusterworkflowtemplates` | Cluster-scoped resource authorized by a namespaced RoleBinding | Minimal 1-resource ClusterRole + ClusterRoleBinding |
| `code:7 … list workflows in namespace ""` | Server is cluster-scoped; UI queries all namespaces; delegates are namespaced | `singleNamespace: true` |
| `code:5 the server could not find the requested resource (get sensors.argoproj.io)` | Argo **Events** CRDs absent; the Workflows UI probes them anyway | Register the minimal EventBus/EventSource/Sensor CRD stubs — RBAC will not fix this |
| Login bounces at Keycloak with `invalid_scope` | `sso.scopes` names a scope not on the client | Drop the override; the clientScope is a default scope |
| Whole Application fails to sync, hook Job timing out on `dial tcp 185.199.x.x:443` | The CRD-install hook Job fetching from GitHub under deny-egress | `crds.install: false`; manage CRDs out-of-band |
| Users log in but see nothing | The `argo_workflows_roles` claim is absent/misnamed, so only the `true` viewer catch-all matches | Check the claim in the token; `customGroupClaimName: argo_workflows_roles` |
| **Every step fails although the container exited 0** | Workflow pods run as `default`, which cannot create `workflowtaskresults` | `workflow.serviceAccount.create: true` **and** `controller.workflowDefaults.spec.serviceAccountName: argo-workflow` — both halves |
| Workflow hangs in `Running` on an `http`/`plugin` step, no pod to look at | The Argo **agent** cannot watch its `workflowtasksets` | `workflow.rbac.agentPermissions: true` |
| Workflow stuck in `Terminating` and will not delete | Artifact GC failed, so the `workflows.argoproj.io/artifact-gc` finalizer is still on it | `workflow.rbac.artifactGC: true`; unstick the existing one by patching the finalizer off |
| `{"code":16,"message":"token not valid..."}` (401) from a script with a valid SA token | `authModes: [sso]` matches only `Bearer v2:` (argo-server's own JWE) | Add `client` to `server.authModes` |
| Script authenticates but gets `code:7` on `argo submit` | Client mode acts AS the caller; the caller's SA has no `argoproj.io` RBAC in `mlops` (SSO delegate rules do **not** transfer) | Use `argo-workflows-ci`, or give the SA its own namespaced Role |
| `argo logs` 403s while `argo submit` works | Client-mode log fetch reads `pods/log` as the caller | Add `pods` / `pods/log` get/list/watch to that SA's Role |
| A LakeFS step 401s with a key that is known good | `envFrom` skipped the hyphenated keys, or an `optional: true` ref bound an empty value at pod start | Explicit `secretKeyRef` with `optional: false`; delete the pod so the env re-binds |

---

# MLflow

Config: `ai-helm-values` `environments/prod/values/mlflow-app.yaml` (reference
copy `charts/mlflow/ci/mlflow-app.yaml`). Auth is the `mlflow-oidc-auth` plugin
bundled in the `community-charts/mlflow` image — real per-user Keycloak identity
and group-based RBAC **inside** MLflow, no proxy.

## 🔴 `oidcAuth.audience` is the ONLY thing gating the Bearer path

Without it, **any** valid token from the `camer-digital` realm was accepted by
the MLflow API. Verified live (2026-07): a client-credentials token minted for
the unrelated `testing-client` — `aud: ['coder','account']`, no `mlflow_roles`
claim — got **HTTP 200** from `POST /api/2.0/mlflow/experiments/search` on the
public ingress.

Why: `mlflow-oidc-auth` v7.3.1 validates the JWT signature against the Keycloak
JWKS, but that JWKS is **realm-wide** — it proves "Keycloak signed this", not
"this was issued for MLflow". The audience check is *conditional*:
`config.py::_get_claims_options()` adds
`{"aud": {"essential": True, "value": <OIDC_AUDIENCE>}}` to the validation
options **only when `OIDC_AUDIENCE` is set**.

And the group gate does **not** save you: `groupName` / `adminGroupName` are
evaluated on the browser OIDC-callback path only, never on
`Authorization: Bearer`.

```yaml
oidcAuth:
  audience: "mlflow"      # renders env OIDC_AUDIENCE
```

Consequences to keep in mind:

- This gates the **Bearer** path only. The browser session path is unaffected.
- Any token intended for the MLflow API must now carry `mlflow` in `aud` — a
  Keycloak audience mapper on the `mlflow` client, configured out-of-band like
  the rest of the realm. See
  [`keycloak-audience-operations.md`](./keycloak-audience-operations.md).
- A missing audience presents as a flat 401, not as "you need an audience". If
  a previously working integration starts 401-ing right after this change,
  check `aud` in its token first.

Decision: [ADR-0091](../adr/0091-mlops-programmatic-access-and-bearer-audience.md).

## ⚠️ The plugin needs its OWN database

The plugin keeps its **own** users/groups/permissions store, separate from the
MLflow tracking store, and auto-migrates it (Alembic → head) **on first login**.

Both stores use the default `alembic_version` table. Point the plugin at the
tracking `mlflow` database and it reads **MLflow's** migration revision, cannot
resolve it against its own chain, **aborts before issuing any DDL**, and never
creates its tables — so every login fails `Failed to update user/groups`.

Fix: a **dedicated `mlflow_oidc` database**. Same CNPG cluster
(`lightbridge-main-db`), same role, same host/port — so no new egress and no new
Secret; only the database name differs. The plugin then finds an empty
`alembic_version` and migrates from base.

Leaving it unset is worse and looks unrelated: it defaults to
`sqlite:///auth.db` on a **read-only pod filesystem** →
`sqlite3.OperationalError: unable to open database file`.

## ⚠️ Two error strings, two layers

| Message | Layer | Meaning |
|---|---|---|
| `User is not allowed to login` | Group/claim check — runs **before** any DB write | The `mlflow_roles` claim did not match `groupName`/`adminGroupName` |
| `Failed to update user/groups` | Persistence layer | Auth passed; the plugin's own DB is missing/unmigrated/unwritable |

Read the message before touching config: they point at opposite ends of the
login path.

## ⚠️ `mlflow_roles` must be a multivalued claim mapper

The Keycloak client-role mapper must have **`multivalued: true`** so the claim is
a **JSON array**. With `multivalued: false` Keycloak emits a bare string that the
plugin cannot match against `groupName` / `adminGroupName`, and login is rejected
outright (`User is not allowed to login`).

Mapping in use: client roles `viewer` → `groupName`, `admin` → `adminGroupName`,
`defaultPermission: READ`.

## Schema traps in this specific chart

- `oidcAuth` is a **top-level** key, a sibling of `auth` — not nested under it.
  Misplacing it fails schema validation with
  `additional properties 'oidcAuth' not allowed` at `/auth`.
- `auth.enabled: false` — the chart's built-in basic auth stays off; `oidcAuth`
  is the mechanism.
- `extraEnvVars` is a **map**, not a list (LakeFS's same-sounding key is a list).
- OIDC `scope` is **space-separated** per spec — Keycloak rejects the
  comma-separated form outright.
- Memory: 2Gi still OOMKilled, because gunicorn's default 4 workers each
  duplicate the FastAPI+SQLAlchemy+OIDC process. Runs with
  `extraArgs.workers: "2"` and a 4Gi limit.

## MLflow — symptom → fix

| Symptom | Cause | Fix |
|---|---|---|
| `User is not allowed to login` | Claim/group check failed — claim absent, misnamed, or a bare string | `groupsAttribute: mlflow_roles`; make the Keycloak mapper **multivalued** so the claim is an array |
| `Failed to update user/groups` | Plugin DB unmigrated — it is sharing the tracking DB and hit the `alembic_version` collision | Give it a dedicated `mlflow_oidc` database |
| `sqlite3.OperationalError: unable to open database file` | `oidcAuth.database` unset → default `sqlite:///auth.db` on a read-only rootfs | Configure the Postgres `oidcAuth.database` block |
| Helm render fails `additional properties 'oidcAuth' not allowed` at `/auth` | `oidcAuth` nested under `auth` | Move it to the top level |
| Keycloak rejects the authorization request | Comma-separated `scope` | `scope: "openid email profile"` (spaces) |
| Pod OOMKilled at 2Gi | 4 gunicorn workers | `extraArgs.workers: "2"`, memory limit 4Gi |
| A token from *another* client is accepted by the API | `oidcAuth.audience` unset ⇒ the plugin never checks `aud`, and the realm JWKS is shared | `oidcAuth.audience: "mlflow"` |
| An integration starts 401-ing on Bearer right after the audience change | Its token has no `mlflow` in `aud` | Add a Keycloak audience mapper on the `mlflow` client and re-mint |

## Related

- [ADR-0085](../adr/0085-mlops-platform-lakefs-argo-workflows-mlflow.md) — the platform decision (shared CNPG + S3, per-app auth).
- [ADR-0091](../adr/0091-mlops-programmatic-access-and-bearer-audience.md) — MLflow bearer-audience enforcement, workflow-pod identity, Argo client-mode API access.
- [ADR-0090](../adr/0090-lakefs-sso-via-lakefs-proxy-shim.md) / [`lakefs-sso.md`](./lakefs-sso.md) — LakeFS, the app with no OIDC.
- [`../integrations/homepage.md`](../integrations/homepage.md) — the hub these apps are annotated for.
- [`keycloak-audience-operations.md`](./keycloak-audience-operations.md) — realm-side claim/audience operations.
