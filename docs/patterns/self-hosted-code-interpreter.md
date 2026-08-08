# Self-Hosted LibreChat Code Interpreter

The *why* is [ADR-0122](../adr/0122-self-hosted-code-interpreter.md). This is
the *how*: what to generate before the first deploy, what to verify once it's
live, and how to change/rotate things afterward.

## What this is

`charts/librechat-code-interpreter` re-implements
[`clickhouse/code-interpreter`](https://github.com/clickhouse/code-interpreter)'s
design — the open-source sandboxed code-execution service behind LibreChat's
Code Interpreter agent capability — on `bjw-template` (this repo's standard
app-scaffolding chart, repo convention), not upstream's own `helm/codeapi`
chart. It replaces the managed librechat.ai API (issue #734) as the backend
for `execute_code`. Six controllers (api, service-worker, sandbox-runner,
file-server, tool-call-server, egress-gateway) plus a `package-init` hook Job
in the dedicated `librechat-sandbox` namespace on `home-remote`, deployed as
a flat `charts/apps` app (not a `librechart` child — see the ADR for why).

**Images are not upstream's** — `clickhouse/code-interpreter` publishes none
(its own CI only validates the Dockerfiles build, never pushes). This chart
pulls from [`ADORSYS-GIS/code-interpreter`](https://github.com/ADORSYS-GIS/code-interpreter),
a fork with its own `publish-images.yml` workflow building the 7 images
(`code-interpreter-{api,worker,tool-call-server,egress-gateway,file-server,
sandbox-runner,package-init}`) to `ghcr.io/adorsys-gis/code-interpreter-*` on
every push to its `main`. Chart image tags are pinned to a commit SHA
(`sha-<short-sha>`), not `latest` — bump them deliberately when the fork
publishes a new build.

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
on both `charts/librechat-code-interpreter` (the `api` controller's `env`)
and `charts/librechat-app` (`CODEAPI_JWT_KID` env). If you ever rotate the JWT
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
  confirmed `/dev/kvm` on `home-remote` worker nodes. sandbox-runner's
  container `securityContext` (the `SYS_ADMIN` capability list) is what would
  need to change to move to KVM mode; there's no simple flag for it in this
  chart today (it wasn't built with a KVM path at all — the previous revision
  vendored upstream's own KVM/NsJail toggle, this one doesn't). Revisit if
  `/dev/kvm` is ever confirmed on a node pool — likely worth a fresh design
  pass rather than a values tweak.
- **`api`/`service-worker`/`sandbox-runner` pinned to 1 replica each** — the
  packages PVC is ReadWriteOnce and `home-remote`'s general nodes have no RWX
  storage class (Longhorn is GPU-node-scoped, ADR-0092). Scaling
  `sandbox-runner` past 1 needs either an RWX-capable storage class or
  `nodeSelector`/`affinity` pinning every replica to one node.
- **File-server shares LibreChat's own S3 bucket root** (`ssegning-k8s-state`)
  — the service has no key-prefix knob. Low collision risk (both use opaque
  random keys) but not a hard guarantee; point the `file-server` controller's
  `MINIO_BUCKET` env at a dedicated bucket if that ever matters.
- **Redis TLS is encrypted but not CA-verified** — `REDIS_TLS=true` maps to
  `tls.rejectUnauthorized: false` in this service's own Redis client; there's
  no CA-verification knob like `librechat-app`'s `rediss://`+`REDIS_CA`.
  Accepted for now (redis-ha is in-cluster only, no public exposure); would
  need an upstream patch to fix properly.

## Bumping the image version

Push to `main` on [`ADORSYS-GIS/code-interpreter`](https://github.com/ADORSYS-GIS/code-interpreter)
(e.g. merging an upstream sync PR) to publish new `sha-<short-sha>`-tagged
images, then bump every `tag:` in `charts/librechat-code-interpreter/values.yaml`
to the new SHA and `helm template` to confirm nothing else changed shape
(env var names, ports, probe paths) before merging.
