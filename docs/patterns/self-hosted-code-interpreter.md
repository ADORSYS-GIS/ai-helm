# Self-Hosted LibreChat Code Interpreter

The *why* is [ADR-0122](../adr/0122-self-hosted-code-interpreter.md). This is
the *how*: what to generate before the first deploy, what to verify once it's
live, and how to change/rotate things afterward.

## What this is

`charts/librechat-code-interpreter` is a vendored, adapted copy of
[`clickhouse/code-interpreter`](https://github.com/clickhouse/code-interpreter)'s
`helm/codeapi` chart — the open-source sandboxed code-execution service behind
LibreChat's Code Interpreter agent capability. It replaces the managed
librechat.ai API (issue #734) as the backend for `execute_code`. Five
components (API, service-worker + sandbox-runner, file-server, tool-call-
server, egress-gateway) in the dedicated `librechat-sandbox` namespace on
`home-remote`, deployed as a flat `charts/apps` app (not a `librechart` child
— see the ADR for why).

## One-time setup: generate and store the secrets

Every property below must exist in `ssegning-aws` **before** the app first
syncs, or the `codeapi-secrets` / `librechat-codeapi-jwt` ExternalSecrets sit
in `SecretSyncedError` and every codeapi pod (and JWT-signing on the LibreChat
side) fails. All go under the consolidated app secret
`ai/camer/digital/prod/env` unless noted otherwise.

```bash
# 1. Internal service-to-service token (any component ↔ any component auth).
openssl rand -hex 32
# → librechat_codeapi_internal_service_token

# 2. Egress-gateway encrypted-grant secret (≥32 bytes).
openssl rand -hex 32
# → librechat_codeapi_egress_grant_secret

# 3. Execution-manifest Ed25519 keypair (service-worker signs, sandbox-runner
#    verifies). Chart wants base64-encoded DER for both halves.
openssl genpkey -algorithm ed25519 -out /tmp/exec-manifest.pem
openssl pkey -in /tmp/exec-manifest.pem -pubout -out /tmp/exec-manifest.pub.pem
openssl pkey -in /tmp/exec-manifest.pem -outform DER | base64 -w0
# → librechat_codeapi_execution_manifest_private_key
openssl pkey -in /tmp/exec-manifest.pem -pubout -outform DER | base64 -w0
# → librechat_codeapi_execution_manifest_public_key

# 4. Code-API JWT auth keypair (LibreChat signs, codeapi verifies) — a
#    DIFFERENT keypair from #3. PEM (not DER) for the private half — LibreChat
#    reads CODEAPI_JWT_PRIVATE_KEY_BASE64 as base64(PEM).
openssl genpkey -algorithm ed25519 -out /tmp/codeapi-jwt.pem
openssl pkey -in /tmp/codeapi-jwt.pem -pubout -out /tmp/codeapi-jwt.pub.pem
base64 -w0 /tmp/codeapi-jwt.pem
# → librechat_codeapi_jwt_private_key_base64  (librechat-app's secret)
cat /tmp/codeapi-jwt.pub.pem
# → librechat_codeapi_jwt_public_key  (codeapi's secret; PEM, not base64 —
#   CODEAPI_JWT_PUBLIC_KEY accepts PEM directly)

rm -f /tmp/exec-manifest*.pem /tmp/codeapi-jwt*.pem
```

Redis and S3 reuse **existing** properties (no new generation needed) — see
`codeApiSecrets.remoteRefs` in `charts/librechat-code-interpreter/values.yaml`
for the exact property names (`redis_password`, `s3_backup_cnpg_client_id`,
`s3_backup_cnpg_secret` — all in `prod/meta/test-app`, the platform secret
every redis-ha/S3 consumer already reads from).

**`CODEAPI_JWT_KID` must match on both sides** — the chart default
(`lc-codeapi-2026-05`, matching LibreChat's own compiled-in default) is used
on both `charts/librechat-code-interpreter` (`api.extraEnv`) and
`charts/librechat-app` (`CODEAPI_JWT_KID` env). If you ever rotate the JWT
keypair, bump the kid on **both** sides in the same change, or the old kid's
verifier key stays cached (`CODEAPI_JWT_KEY_CACHE_TTL_SECONDS`, default 30s)
and new tokens fail `unknown_kid` until it expires.

## Verifying a fresh install

```bash
# ExternalSecrets synced?
kubectl -n librechat-sandbox get externalsecret codeapi-secrets -o jsonpath='{.status.conditions}'
kubectl -n converse get externalsecret librechat-codeapi-jwt -o jsonpath='{.status.conditions}'

# Package-init Job completed (populates the NsJail runtime PVC)?
kubectl -n librechat-sandbox get job codeapi-package-init
kubectl -n librechat-sandbox logs job/codeapi-package-init

# All pods Running?
kubectl -n librechat-sandbox get pods

# API healthy from in-cluster?
kubectl -n librechat-sandbox run -it --rm curl --image=curlimages/curl --restart=Never -- \
  curl -s http://codeapi-api.librechat-sandbox.svc.cluster.local:3112/v1/health
```

Then in LibreChat: start a chat on an agent with Code Interpreter enabled
("Converse" — the default persona — has `executeCode: true`) and ask it to
run a trivial snippet (`print("hello")`). A 401 on the LibreChat side usually
means the JWT keypair/kid mismatch above; a `SecretSyncedError` means a
missing `ssegning-aws` property; a pod stuck `Pending` on the packages PVC
means no storage class bound (see the ADR's RWO-storage note).

## Known limitations of the current deploy (see the ADR for the trade-offs)

- **NsJail/chroot sandbox mode**, not the safer KVM microVM mode — no
  confirmed `/dev/kvm` on `home-remote` worker nodes. If you confirm KVM
  support on a node pool, flip `workerSandbox.kvmEnabled: true`,
  `workerSandbox.packages.source: image` (drop the PVC/package-init Job
  entirely), and re-derive `workerSandbox.resources` — the microVM launcher
  has different memory/CPU shape than the chroot path.
- **`api.replicaCount`/`workerSandbox.replicaCount` pinned to 1** — the
  packages PVC is ReadWriteOnce and `home-remote`'s general nodes have no RWX
  storage class (Longhorn is GPU-node-scoped, ADR-0092). Scaling
  `sandboxRunner` past 1 needs either an RWX-capable storage class or
  `nodeSelector`/`affinity` pinning every replica to one node.
- **File-server shares LibreChat's own S3 bucket root** (`ssegning-k8s-state`)
  — no key-prefix knob in the upstream chart. Low collision risk (both use
  opaque random keys) but not a hard guarantee; switch
  `fileServer.s3.bucket` to a dedicated bucket if that ever matters.
- `api`/`file-server`/`tool-call-server`/`egress-gateway` containers don't yet
  carry this repo's usual KSV-0118 hardening (`runAsNonRoot`/`drop:
  ALL`/`readOnlyRootFilesystem`) — deferred until each image's non-root
  behaviour is confirmed live.

## Bumping the vendored chart version

There's no `helm dep update` safety net here — the chart is copied from
upstream source, not consumed as a dependency. To pick up a new
`clickhouse/code-interpreter` release: diff `helm/codeapi/` between the pinned
and target upstream tags, re-apply the same adaptations (no Bitnami
redis/minio, `templates/secrets.yaml` → `templates/externalsecret.yaml`, the
`executionManifest.publicKey` → secretKeyRef edit in
`worker-sandbox-deployment.yaml`), and re-render (`helm template`) to confirm
nothing else changed shape before bumping `appVersion`/chart `version`.
