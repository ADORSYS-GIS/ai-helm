# MLOps app auth — Argo Workflows SSO/RBAC + MLflow OIDC

**Live** in namespace `mlops` on `home-remote`: `argo-workflows.mlops.ai.camer.digital`
and `mlflow.mlops.ai.camer.digital`. Both authenticate against Keycloak
(`camer-digital` @ `auth.verif.fyi`) with their **own native OIDC** — no
fronting proxy. Decision: [ADR-0085](../adr/0085-mlops-platform-lakefs-argo-workflows-mlflow.md).

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

---

# MLflow

Config: `ai-helm-values` `environments/prod/values/mlflow-app.yaml` (reference
copy `charts/mlflow/ci/mlflow-app.yaml`). Auth is the `mlflow-oidc-auth` plugin
bundled in the `community-charts/mlflow` image — real per-user Keycloak identity
and group-based RBAC **inside** MLflow, no proxy.

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

## Related

- [ADR-0085](../adr/0085-mlops-platform-lakefs-argo-workflows-mlflow.md) — the platform decision (shared CNPG + S3, per-app auth).
- [ADR-0090](../adr/0090-lakefs-sso-via-lakefs-proxy-shim.md) / [`lakefs-sso.md`](./lakefs-sso.md) — LakeFS, the app with no OIDC.
- [`../integrations/homepage.md`](../integrations/homepage.md) — the hub these apps are annotated for.
- [`keycloak-audience-operations.md`](./keycloak-audience-operations.md) — realm-side claim/audience operations.
