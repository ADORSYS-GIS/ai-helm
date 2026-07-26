# MLOps platform — consumer brief

**For:** an agent/developer working in another repo (e.g. `webank-mobile`, `webank-models`)
who needs to **use** the shared MLOps platform — version data in LakeFS, track
experiments in MLflow, run training in Argo Workflows.

**Not** a deployment guide. You do not need to deploy or modify the platform; it already
runs. This tells you how to *connect to it*.

**Self-contained by design** — it is meant to be handed to someone working in another
repo who may not have access to this one, so it inlines what they need rather than
linking inward. Contains **no secret values**: only the names and locations of the
credentials to request.

Status: verified live 2026-07-25. Platform lives in Kubernetes namespace `mlops` on the
`home-remote` cluster. Identity provider is Keycloak, realm `camer-digital`
(`https://auth.verif.fyi`).

---

## 1. The three services

| Service | URL | What it's for |
|---|---|---|
| **LakeFS** | `https://lakefs.mlops.ai.camer.digital` | Git-like versioning for data & model artifacts (S3-backed) |
| **MLflow** | `https://mlflow.mlops.ai.camer.digital` | Experiment tracking, metrics, model registry |
| **Argo Workflows** | `https://argo-workflows.mlops.ai.camer.digital` | Running training/batch pipelines as Kubernetes workflows |

In-cluster addresses (use these from a pod — faster and avoids the public ingress):

```
http://lakefs.mlops.svc.cluster.local:80
http://mlflow.mlops.svc.cluster.local:80
http://argo-workflows-server.mlops.svc.cluster.local:2746
```

---

## 2. The one rule that explains everything

**SSO is a redirect protocol.** A browser can follow a redirect to Keycloak and log in;
a script cannot. So every service here has *two* front doors:

- a **browser** door (Keycloak SSO), and
- a **machine** door (a token or key you send in a header).

If you ever get an unexpected `302` to `auth.verif.fyi` instead of `401`, you're
knocking on the browser door with a script. Use the machine door below.

---

## 3. LakeFS

### Connecting (scripts, `lakectl`, SDKs)
`/api` is reachable from anywhere and uses **HTTP Basic** with a LakeFS access-key pair:

```bash
curl -u "$LAKEFS_ACCESS_KEY_ID:$LAKEFS_SECRET_ACCESS_KEY" \
  https://lakefs.mlops.ai.camer.digital/api/v1/repositories
```

`lakectl` config (`~/.lakectl.yaml`):

```yaml
credentials:
  access_key_id: <ask the platform maintainer>
  secret_access_key: <ask the platform maintainer>
server:
  endpoint_url: https://lakefs.mlops.ai.camer.digital
```

Python (`lakefs-sdk` / `lakefs` package) uses the same endpoint + key pair.

From inside the cluster, the credential is already available as the Kubernetes Secret
**`lakefs-proxy-admin`** in namespace `mlops` (keys `access-key-id`, `secret-access-key`):

```yaml
env:
  - name: LAKEFS_ACCESS_KEY_ID
    valueFrom: { secretKeyRef: { name: lakefs-proxy-admin, key: access-key-id } }
  - name: LAKEFS_SECRET_ACCESS_KEY
    valueFrom: { secretKeyRef: { name: lakefs-proxy-admin, key: secret-access-key } }
```

### ⚠️ Things you must know about LakeFS here
1. **There is exactly ONE credential for the whole platform, and it is effectively
   root.** LakeFS is running in its open-source single-user mode, which cannot create
   additional users or keys (the credentials API returns `501 Not Implemented`). You will
   be given *the* key, not *a* key.
2. **Therefore: never log it, never bake it into an image, never commit it.** A leak
   compromises all platform data, and rotating it requires coordinated changes on the
   platform side.
3. **All actions are attributed to a single shared identity** (`platform-admin`). LakeFS
   commits will not show who really made them — keep real authorship in your commit
   messages/metadata if it matters to you.
4. **The S3 gateway is not exposed externally.** boto3-style bulk data access works only
   from inside the cluster. From a laptop, use the API/`lakectl`.

### Browser access
Just open the URL — you'll be redirected to Keycloak and logged in automatically. (You
land as the shared admin identity; that's expected.)

---

## 4. MLflow

### Connecting (scripts, training jobs)
MLflow accepts a **Keycloak bearer token** from the dedicated machine client
**`mlflow-automation`**:

```bash
TOKEN=$(curl -s https://auth.verif.fyi/realms/camer-digital/protocol/openid-connect/token \
  -d grant_type=client_credentials \
  -d client_id=mlflow-automation \
  -d client_secret="$MLFLOW_AUTOMATION_CLIENT_SECRET" | jq -r .access_token)

curl -H "Authorization: Bearer $TOKEN" \
  https://mlflow.mlops.ai.camer.digital/api/2.0/mlflow/experiments/search
```

In Python:

```python
import os, mlflow
os.environ["MLFLOW_TRACKING_URI"]   = "https://mlflow.mlops.ai.camer.digital"
os.environ["MLFLOW_TRACKING_TOKEN"] = token   # the bearer token from above
mlflow.set_experiment("webank/<your-experiment>")
with mlflow.start_run():
    mlflow.log_param("lr", 3e-4)
    mlflow.log_metric("auc", 0.91)
```

### ⚠️ Things you must know about MLflow here
1. **Your token MUST be issued for MLflow.** MLflow enforces the audience claim
   (`aud` must contain `mlflow`). A token from any *other* Keycloak client is rejected
   with `401`, even though it's a perfectly valid realm token. Use `mlflow-automation`
   (or ask for a client configured with an MLflow audience mapper) — do not reuse an
   existing client's token.
2. **Default permission is READ.** Reading works out of the box; **logging runs requires
   an explicit `EDIT` grant** on the target experiment for your identity, done by an
   MLflow admin. Your machine identity is `service-account-mlflow-automation`.
   Symptom if missing: `403 Permission denied` on write calls.
3. Permission levels are `READ` < `USE` < `EDIT` < `MANAGE`.

### Browser access
Open the URL → "Sign in with Keycloak". Humans get a **real per-user identity** here
(unlike LakeFS). You need the `viewer` or `admin` role on the `mlflow` Keycloak client,
or login is refused with *"User is not allowed to login"*.

---

## 5. Argo Workflows

### Connecting (CI / scripts)
Argo accepts a **short-lived Kubernetes ServiceAccount token**. A dedicated SA
`argo-workflows-ci` exists in namespace `mlops`:

```bash
# Short-lived and bound — do NOT use a long-lived ServiceAccount token Secret.
TOKEN=$(kubectl -n mlops create token argo-workflows-ci --duration=30m)

curl -H "Authorization: Bearer $TOKEN" \
  https://argo-workflows.mlops.ai.camer.digital/api/v1/workflows/mlops

# or with the CLI
export ARGO_SERVER=argo-workflows.mlops.ai.camer.digital:443
export ARGO_SECURE=true ARGO_HTTP1=true
export ARGO_TOKEN="Bearer $TOKEN"
argo list -n mlops
```

You need `kubectl` access to the cluster to mint that token. If your CI can't reach the
cluster, ask the platform maintainer for a scoped SA + token strategy.

### ⚠️ Things you must know about Argo here
1. **Everything runs in namespace `mlops`.** Argo is namespace-scoped; workflows in other
   namespaces are not visible or runnable.
2. **Workflow pods run as ServiceAccount `argo-workflow`** automatically. That SA can
   report step status but has **no access to LakeFS or MLflow** — you must inject those
   credentials yourself (see §6).
3. Humans in the UI get `admin` or `viewer` based on their `argo_workflows_roles`
   Keycloak claim.

---

## 6. End-to-end: a training workflow

A training step needs credentials from **two** different systems. Minimal shape:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Workflow
metadata:
  generateName: webank-train-
  namespace: mlops
spec:
  entrypoint: train
  templates:
    - name: train
      container:
        image: <your training image>
        command: [python, /app/train.py]
        env:
          # ── LakeFS (data/model versioning) ──
          - name: LAKEFS_ENDPOINT
            value: http://lakefs.mlops.svc.cluster.local:80
          - name: LAKEFS_ACCESS_KEY_ID
            valueFrom: { secretKeyRef: { name: lakefs-proxy-admin, key: access-key-id } }
          - name: LAKEFS_SECRET_ACCESS_KEY
            valueFrom: { secretKeyRef: { name: lakefs-proxy-admin, key: secret-access-key } }
          # ── MLflow (experiment tracking) ──
          - name: MLFLOW_TRACKING_URI
            value: http://mlflow.mlops.svc.cluster.local:80
          - name: MLFLOW_AUTOMATION_CLIENT_SECRET
            valueFrom: { secretKeyRef: { name: <see §7>, key: <see §7> } }
```

Your `train.py` then exchanges `MLFLOW_AUTOMATION_CLIENT_SECRET` for a bearer token
(§4) and sets `MLFLOW_TRACKING_TOKEN` before calling `mlflow.start_run()`.

Network access is unrestricted inside `mlops` today — pods can reach the three services,
object storage, Keycloak and the public internet (e.g. pip installs).

---

## 7. What to request from the platform maintainer

Before you can run anything, ask for:

| # | What | Why |
|---|---|---|
| 1 | LakeFS **access-key + secret** (or confirmation you'll read `lakefs-proxy-admin` in-cluster) | All LakeFS access |
| 2 | **`mlflow-automation` client secret**, and where it's stored as a Kubernetes Secret in `mlops` | MLflow machine auth |
| 3 | **`EDIT` permission** on your MLflow experiments for `service-account-mlflow-automation` | Otherwise run logging returns `403` |
| 4 | Your Keycloak user granted `viewer`/`admin` on the `mlflow` client, and `argo_workflows_roles` | Browser access to the UIs |
| 5 | A LakeFS **repository** for your project (or permission to create one) | Somewhere to put data |

> ⚠️ At the time of writing, items **2 and 3 are not yet provisioned** — the
> `mlflow-automation` client exists and its tokens are accepted, but its secret has not
> been stored as a Kubernetes Secret and it has **not** been granted `EDIT`. Confirm both
> with the maintainer before assuming run-logging works.

---

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `302` to `auth.verif.fyi` from a script | Hit the browser door | LakeFS: use `/api`. Others: send a token |
| MLflow `401` with a valid-looking token | Token's `aud` doesn't include `mlflow` | Use the `mlflow-automation` client |
| MLflow `403 Permission denied` on writes | Identity only has READ | Request `EDIT` (§7 item 3) |
| MLflow *"User is not allowed to login"* (browser) | Missing `viewer`/`admin` role | Request the Keycloak client role |
| Argo `{"code":16,"token not valid"}` | Not a Kubernetes token, or expired | Re-mint with `kubectl create token` |
| Argo `403` on workflows | Your SA lacks namespaced RBAC in `mlops` | Ask for RBAC on the SA you're using |
| LakeFS `401` on `/api` | Wrong/missing Basic credentials | Check the key pair |
| Workflow step fails but container exited 0 | Pod couldn't report status | Ensure `serviceAccountName` isn't overridden away from `argo-workflow` |

---

## 9. Ground rules

- **Never commit or log the LakeFS key** — it is a single shared root credential for all
  platform data.
- **Prefer in-cluster endpoints** from workloads (`*.mlops.svc.cluster.local`).
- **Use short-lived tokens** for Argo; never long-lived ServiceAccount token Secrets.
- **Don't reuse another Keycloak client's token** for MLflow — it will be rejected, and
  adding an MLflow audience mapper to an unrelated client would re-open a security hole
  that was deliberately closed.
- Deeper reference in this repo: the full
  [access model](../patterns/mlops-access-model.md) (principal × app matrix, credential
  inventory), the [MLOps auth playbook](../playbooks/mlops-app-auth.md) and
  [LakeFS SSO playbook](../playbooks/lakefs-sso.md) for troubleshooting, and
  [ADR-0085](../adr/0085-mlops-platform-lakefs-argo-workflows-mlflow.md) /
  [ADR-0090](../adr/0090-lakefs-sso-via-lakefs-proxy-shim.md) /
  [ADR-0091](../adr/0091-mlops-programmatic-access-and-bearer-audience.md) for why.
