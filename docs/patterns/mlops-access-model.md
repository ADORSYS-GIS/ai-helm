# MLOps access model — who can reach LakeFS, Argo Workflows and MLflow, and as what

Reference for the `mlops` namespace (ADR-0085 / ADR-0090 / ADR-0091). Answers one
question: **"I am X; I need to reach Y; how do I authenticate and what am I allowed
to do?"** — for humans, in-cluster workloads, and external scripts alike.

For *debugging* a broken login, go to the playbooks instead:
[mlops-app-auth.md](../playbooks/mlops-app-auth.md) (Argo + MLflow) and
[lakefs-sso.md](../playbooks/lakefs-sso.md). This document is the map, not the runbook.

Everything here was verified live against the running cluster on 2026-07-25.

---

## 1. The three principal types

| Principal | What it is | Can it do a browser redirect? |
|---|---|---|
| **Human** | A person in the `camer-digital` Keycloak realm | ✅ yes — OIDC authorization-code flow |
| **Workload** | A pod in the cluster (e.g. an Argo workflow step running a training script) | ❌ no — needs a credential mounted or a k8s SA token |
| **External script / CI** | Something outside the cluster (laptop, GitHub Actions) | ❌ no — needs a token it can mint non-interactively |

The distinction matters because **SSO is a redirect protocol**. Anything that can't
open a browser needs a *different* credential, and every app in `mlops` solves that
differently.

---

## 2. The matrix

| | **LakeFS** | **Argo Workflows** | **MLflow** |
|---|---|---|---|
| **Human** | Keycloak SSO → the shared `admin` identity | Keycloak SSO → delegate SA (`admin` or `viewer` by claim) | Keycloak SSO → **real per-user identity** |
| **Workload (in-cluster)** | Basic auth with the single platform key, direct to the Service | runs as SA `argo-workflow` (executor rights only) | Bearer token from `mlflow-automation` |
| **External script / CI** | ❌ **not reachable** | short-lived k8s SA token (`--auth-mode=client`) | Bearer token from `mlflow-automation` |
| **Per-user identity inside the app?** | ❌ shared | ✅ two roles, but only two | ✅ genuine per-user |
| **Can issue >1 credential?** | ❌ exactly one, ever | ✅ per-SA | ✅ per-client / per-user |

The single most important row is the last: **LakeFS has exactly one credential for the
entire platform** and it cannot mint another. Everything below follows from that.

---

## 3. LakeFS

### Humans
`browser → oauth2-proxy (Keycloak) → lakefs-proxy → lakeFS`. See
[ADR-0090](../adr/0090-lakefs-sso-via-lakefs-proxy-shim.md). Authentication is genuinely
per-Keycloak-user — a wrong password or an unknown user is rejected by Keycloak — but
**every authenticated user then operates as the one lakeFS `admin`**. In-lakeFS
authorization and audit are therefore shared: all commits show the same author.

### Workloads
LakeFS OSS with `auth.ui_config.rbac: none` runs `BasicAuthService`, which does **not
implement credential management**:

```
GET  /api/v1/auth/users/{user}/credentials  → 501 Not Implemented
POST /api/v1/auth/users/{user}/credentials  → 400 Bad Request
```

So there is **one** access-key/secret pair for the whole platform. It lives in the
`mlops` Secret **`lakefs-proxy-admin`** (keys `access-key-id`, `secret-access-key`) and
is *also* what the lakefs-proxy shim logs in with.

A workflow step authenticates with **HTTP Basic** against the in-cluster Service
(which bypasses oauth2-proxy entirely):

```yaml
- name: train
  container:
    image: your/trainer:tag
    env:
      - name: LAKEFS_ENDPOINT
        value: http://lakefs.mlops.svc.cluster.local:80
      - name: LAKEFS_ACCESS_KEY_ID
        valueFrom: { secretKeyRef: { name: lakefs-proxy-admin, key: access-key-id } }
      - name: LAKEFS_SECRET_ACCESS_KEY
        valueFrom: { secretKeyRef: { name: lakefs-proxy-admin, key: secret-access-key } }
```

> ⚠️ **This key is effectively lakeFS root, and it is shared with the SSO shim.** A
> workflow that leaks it compromises lakeFS completely, and rotating it means updating
> the shim in the same change. Treat mounting it as a deliberate decision per workflow,
> not a default.

### External scripts — currently blocked
oauth2-proxy fronts **every path** on `lakefs.mlops.ai.camer.digital`, so an API call
from outside gets an HTML redirect, not a challenge it can answer:

```
POST https://lakefs.mlops.ai.camer.digital/api/v1/auth/login  → 302 → Keycloak
```

`lakectl`, boto3 against the S3 gateway, and CI therefore cannot reach lakeFS from
outside the cluster. This is a deliberate consequence of the single-root-credential
constraint: exposing `/api/` would put an unrotatable root key on laptops. Run
data-plane work **inside** the cluster (i.e. as an Argo workflow step) instead.

---

## 4. Argo Workflows

There are **three unrelated identities** here; they share nothing.

### 1. Humans — SSO
Keycloak `argo_workflows` client → the `argo_workflows_roles` claim → argo-server
selects a *delegate ServiceAccount* by `workflows.argoproj.io/rbac-rule` and
**impersonates it** for every Kubernetes call:

| Claim contains | Delegate SA | Rights in `mlops` |
|---|---|---|
| `admin` | `argo-workflows-admin` | full CRUD on workflows/templates/cron + pods/logs |
| anything else | `argo-workflows-viewer` | read-only |

### 2. Scripts / CI — `--auth-mode=client`
`server.authModes: [sso, client]` ([ADR-0091](../adr/0091-mlops-programmatic-access-and-bearer-audience.md)).
SSO mode only accepts a `Bearer v2:` **encrypted** cookie that argo-server itself mints
after a browser flow — a script can't construct one. `client` mode accepts an ordinary
Kubernetes token and acts **as that caller**, so normal k8s RBAC applies.

```bash
# Mint a SHORT-LIVED bound token — never use a *.service-account-token Secret,
# which never expires and can't be revoked without deleting the SA.
TOKEN=$(kubectl -n mlops create token argo-workflows-ci --duration=10m)
curl -H "Authorization: Bearer $TOKEN" \
  https://argo-workflows.mlops.ai.camer.digital/api/v1/workflows/mlops
```

`argo-workflows-ci` is a dedicated SA with namespaced rights on `workflows`,
`workflowtemplates` and `cronworkflows`. **SSO delegate permissions do not transfer** —
client mode bypasses SSO RBAC delegation entirely, so an API client's SA needs its own
RBAC.

### 3. Workflow pods — SA `argo-workflow`
Set as the namespace default via `controller.workflowDefaults.spec.serviceAccountName`.
It grants only what the *executor* needs (`workflowtaskresults` create/patch) — **not**
access to LakeFS or MLflow, which come from mounted credentials as shown above.

> Creating the SA alone is not enough: without `workflowDefaults`, pods still run as
> `mlops/default` and every step fails on `workflowtaskresults` even when the container
> exits 0. Both halves are required.

---

## 5. MLflow

MLflow is the only one of the three with a real per-user model.

### What it accepts, in order
The `mlflow-oidc-auth` middleware tries three things, in this order:

1. **`Authorization: Basic`** — username + a token from `PATCH /api/2.0/mlflow/users/access-token`, checked against a local password hash (**not** the IdP).
2. **`Authorization: Bearer <JWT>`** — verified against the Keycloak JWKS.
3. **Session cookie** — the browser path.

### Humans
Keycloak OIDC. The `mlflow_roles` claim (multivalued) gates login and admin:
`viewer` = may log in, `admin` = MLflow administrator. A user with neither is refused
with *"User is not allowed to login"*.

### Workloads and scripts — the `mlflow-automation` client
A dedicated Keycloak **service-account** client (no browser flow) whose tokens carry
`aud: [mlflow, account]` via an audience mapper:

```bash
TOKEN=$(curl -s https://auth.verif.fyi/realms/camer-digital/protocol/openid-connect/token \
  -d grant_type=client_credentials -d client_id=mlflow-automation \
  -d client_secret=$MLFLOW_AUTOMATION_CLIENT_SECRET | jq -r .access_token)
curl -H "Authorization: Bearer $TOKEN" \
  https://mlflow.mlops.ai.camer.digital/api/2.0/mlflow/experiments/search
```

> 🔒 **`OIDC_AUDIENCE=mlflow` is a security control, not a formality.** The JWKS is
> *realm-wide*, so without it MLflow accepted **any** signature-valid `camer-digital`
> token — verified live: an unrelated client with no `mlflow_roles` claim read
> experiment data. The `viewer` login gate does **not** apply to the Bearer path. Only
> tokens minted *for* MLflow are accepted now. Never remove it; never add an audience
> mapper for `mlflow` to an unrelated client.

### Permissions
Five levels: `READ` < `USE` < `EDIT` < `MANAGE`, plus `NO_PERMISSIONS`.
`DEFAULT_MLFLOW_PERMISSION=READ` here (upstream default is `MANAGE` — do not raise it).
An identity with no explicit grant therefore gets **read-only**, so *logging runs
requires an explicit `EDIT`* on the target experiment. Admins bypass all checks.

---

## 6. End-to-end: a training job

A workflow step that reads data from LakeFS and logs runs to MLflow needs **three**
things, from three different systems:

1. **Run as the right SA** — automatic (`workflowDefaults` → `argo-workflow`), which
   covers only reporting step status.
2. **LakeFS**: mount `lakefs-proxy-admin` (§3) and talk to
   `http://lakefs.mlops.svc.cluster.local:80` with Basic auth.
3. **MLflow**: mount the `mlflow-automation` client secret, exchange it for a bearer
   token, and set `MLFLOW_TRACKING_URI`. The identity is
   `service-account-mlflow-automation`, which **must be granted `EDIT`** on the target
   experiment by an MLflow admin, or run logging returns `403`.

Network access is not a constraint today: `mlops` has **no namespace-wide
default-deny**, so pods egress freely to the other services, S3, Keycloak and the
internet. ⚠️ If the standard `allow-dns` + `default-deny-ingress` baseline is ever added
to `mlops` (every other workload namespace has it), workflow pods will break unless a
permissive `CiliumNetworkPolicy` for them ships **in the same change** — the existing
policies select the named app pods only, which workflow pods don't match.

---

## 7. Credential inventory

| Credential | Where it lives | Consumed by | Rotation |
|---|---|---|---|
| lakeFS root access key | Secret `mlops/lakefs-proxy-admin` ← ASM `lakefs_admin_*` | lakefs-proxy shim **and** any workflow reading lakeFS | Manual, and breaks the shim — see the lakeFS playbook runbook |
| `lakefs_proxy` OIDC client | Secret `mlops/lakefs-proxy-secret` | oauth2-proxy | Keycloak (manual — realm isn't reconciled) |
| `mlflow-automation` client secret | ASM `mlflow_automation_client_secret` | training jobs / CI → MLflow | Keycloak credentials tab |
| Argo CI token | none stored — minted on demand | CI → Argo API | N/A, expires by design |
| ghcr pull credential | Secret `mlops/lakefs-ghcr` ← ASM `github_*` | pulling the private lakefs-proxy image | With the PAT |

---

## 8. Known limitations

| # | Limitation | Consequence |
|---|---|---|
| 1 | lakeFS has **one** credential, un-rotatable per-consumer, effectively root | No per-script keys; no per-user audit; sharing it with a workflow is a real risk |
| 2 | lakeFS is **unreachable from outside** the cluster | No `lakectl`/boto3 from laptops or CI; data-plane work must run in-cluster |
| 3 | Argo SSO offers only **two** roles (admin / viewer) | No finer-grained human authorization without more delegate SAs |
| 4 | `charts/keycloak-baseline` is **not reconciled by anything** | Every realm change here is manual and can drift silently |
| 5 | `mlops` has **no NetworkPolicy baseline** | Pods egress anywhere; adding the baseline later is a breaking change |

Items 1–2 are inherent to lakeFS OSS and would need lakeFS Enterprise or the external
ACL server to fix ([ADR-0090](../adr/0090-lakefs-sso-via-lakefs-proxy-shim.md) covers
why). Items 4–5 are platform gaps worth their own decisions.
