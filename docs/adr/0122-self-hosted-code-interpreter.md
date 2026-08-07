# ADR-0122: Self-Hosted LibreChat Code Interpreter

**Status:** Accepted
**Date:** 2026-08-07
**Deciders:** @stephane-segning

## Context

LibreChat's Code Interpreter agent capability (`execute_code`) was already wired
to the managed librechat.ai sandbox API (`LIBRECHAT_CODE_API_KEY`, ADR history:
issue #734) — code runs on LibreChat's infra, not ours. We want our own
instance instead: our data never leaves the cluster, no per-request cost to a
third party, and it's a prerequisite for future Programmatic Tool Calling
(routing MCP tool calls through the sandbox).

LibreChat's Code Interpreter is powered by the open-source (Apache-2.0)
[`clickhouse/code-interpreter`](https://github.com/clickhouse/code-interpreter)
service (`helm/codeapi` chart, appVersion 2.0.0 at the time of writing) — five
components (API, Worker/Sandbox-Runner split, File Server, Tool Call Server,
Egress Gateway) behind a Redis job queue and S3-compatible file storage. It is
not published to any Helm repository or OCI registry, so it can't be consumed
the way we consume grafana/loki/cnpg (`chart:` + registry); it only ships as
source in the upstream GitHub repo.

Several details only became clear by reading the actual source (not just its
docs), and materially shaped this decision:

1. **Sandbox isolation has two modes with very different privilege profiles.**
   The default is a libkrun **microVM** (`workerSandbox.kvmEnabled: true`) —
   the sandbox container runs `privileged: false` with zero added Linux
   capabilities, needing only `/dev/kvm` (nested virtualization) on the node.
   The fallback is **NsJail/chroot** (`kvmEnabled: false`) — no `/dev/kvm`
   needed, but the container requires `SYS_ADMIN`, `NET_ADMIN`, `SYS_PTRACE`,
   `seccompProfile: Unconfined`, and 8 more capabilities. We have no confirmed
   `/dev/kvm` support on `home-remote`'s general worker pool (unlike the two
   dedicated Hetzner Robot GPU nodes, Cloud VMs typically don't expose nested
   virt), so we default to the NsJail fallback and accept the heavier
   capability grant.
2. **That capability grant needs the `privileged` Pod Security Standard** —
   `baseline` (our cluster default) forbids adding `SYS_ADMIN`. Rather than
   elevate the existing `converse` namespace (librechat-app, mongo,
   meilisearch), this ships in a **new, dedicated namespace**
   (`librechat-sandbox`) so the elevation is scoped to nothing but this
   service — same pattern as `observability`'s hostPath collectors (ADR-0020),
   but here the elevated pod is running arbitrary user-submitted code, which
   argues even more strongly for isolation.
3. **Production auth is JWT-only, not a static API key.** The service
   explicitly rejects the legacy `X-API-Key` header outside `LOCAL_MODE`
   (`service/src/middleware/auth.ts`) — the only non-local paths are
   `librechat-jwt` (short-lived, ≤300s, Ed25519/RS256-signed JWTs verified
   against a configured public key) or an explicitly-insecure `none` escape
   hatch. This isn't managed-cloud-only: `danny-avila/LibreChat`
   (`packages/api/src/auth/codeapi.ts`) natively mints these per-request JWTs
   once `CODEAPI_AUTH_PROVIDER=librechat-jwt` (or `CODEAPI_JWT_ENABLED=true`)
   and a private signing key are configured on LibreChat's own side — no
   plugin needed. `LIBRECHAT_CODE_API_KEY` (the env var already wired for the
   managed API) is not referenced anywhere in the OSS LibreChat source; it's
   specific to the managed-cloud client path and irrelevant here.
4. **No RWX-capable storage class on the general worker pool.** Longhorn is
   scoped to the two GPU nodes only (ADR-0092); `home-remote`'s general nodes
   use `hcloud-volumes` (Hetzner Cloud CSI), which is ReadWriteOnce-only. With
   `kvmEnabled: false`, the chart forces `workerSandbox.packages.source: pvc`
   (the KVM-only baked-image path is unavailable) — a shared RWO packages PVC
   only works cleanly with a single sandbox-runner replica.
5. **Repo convention forbids a second Redis or a second object-storage
   bucket** ("Don't re-add a redis chart here" — CLAUDE.md). The upstream
   chart bundles Bitnami Redis/MinIO as optional subchart dependencies.

## Decision

Vendor and adapt `helm/codeapi` as `charts/librechat-code-interpreter`
(copied from source, not a Helm chart dependency — nothing to point one at).
Adaptations from upstream:

- **Drop the Bitnami `redis`/`minio` chart dependencies entirely** rather than
  declaring-and-disabling them. Always point at the shared `redis-ha`
  (`redis-ha-redis-haproxy.redis-system.svc.cluster.local`, TLS, same as every
  other consumer) and the shared Hetzner Object Storage bucket
  (`ssegning-k8s-state`) that `librechat-app` itself already uses for file
  storage. The chart has no S3 key-prefix knob, so codeapi's objects land in
  the bucket root alongside LibreChat's own — both use opaque
  session/execution-scoped keys, so collision risk is negligible; a dedicated
  bucket is a one-line follow-up (`fileServer.s3.bucket`) if that changes.
- **Replace `templates/secrets.yaml`** (a plaintext-from-values Opaque
  Secret — would fight ArgoCD selfHeal against an ExternalSecret targeting
  the same object) **with an ExternalSecret** (`templates/externalsecret.yaml`)
  producing the identical Secret name/keys every other template already reads
  via `secretKeyRef`, sourced from `ssegning-aws`
  (`ai/camer/digital/prod/env`, one property per key — repo convention). This
  also removes the upstream chart's template-time `fail` guards that checked
  `executionManifest.privateKey`/`publicKey` presence in `.Values` — those
  values no longer exist as plaintext by design; a missing secret now surfaces
  as `SecretSyncedError` / pod CrashLoop, same as every other ESO-backed
  secret in this repo.
- **`workerSandbox.kvmEnabled: false`** — NsJail/chroot fallback, deployed to
  a new dedicated `librechat-sandbox` namespace elevated to the `privileged`
  Pod Security Standard (via `global.namespacePodSecurity` in
  `charts/apps/values.yaml`, the existing mechanism).
- **`workerSandbox.packages.source: pvc`** on a 10Gi ReadWriteOnce PVC (cluster
  default storage class), with **`sandboxRunner.replicaCount` and
  `api.replicaCount` at 1** for the first deploy (RWO can't be shared across
  nodes; conservative footprint on a resource-constrained home cluster).
  Revisit once validated live — scale `sandboxRunner` up only once an RWX
  storage class is available, or accept node-pinning via
  `sandboxRunner.nodeSelector`/`affinity`.
- **JWT auth** (`CODEAPI_AUTH_PROVIDER: librechat-jwt` on the API component).
  `librechat-app` gets matching `CODEAPI_JWT_ENABLED`/`CODEAPI_JWT_PRIVATE_KEY_BASE64`/
  `CODEAPI_JWT_ALGORITHM` env plus an ExternalSecret carrying the Ed25519
  private key; the codeapi API component gets the public half
  (`CODEAPI_JWT_PUBLIC_KEY`) — same keypair, both halves in `ssegning-aws`
  (the public half isn't sensitive but travels with the private half for
  rotation consistency). `LIBRECHAT_CODE_API_KEY`/`LIBRECHAT_CODE_BASEURL` stay
  wired (`LIBRECHAT_CODE_BASEURL` now points at the in-cluster Service instead
  of the managed API); the API key is simply unused by this auth path and left
  in place in case a managed-API fallback is ever wanted again.
- **Deployed as a `librechart` orchestrator child** (`charts/librechart`,
  ADR-0014 pattern) rather than a flat `charts/apps` umbrella entry, since it's
  part of the LibreChat application group. A `depsOverlay`
  (`environments/{base,prod}/deps/librechat-code-interpreter`) ships the
  CiliumNetworkPolicy opening the new namespace boundary (DNS, `redis-system`,
  Hetzner Object Storage FQDN egress; ingress on the `api` Service from
  `converse`) and the matching egress allow in `converse` for librechat-app to
  reach it — the chart's own plain-`NetworkPolicy` templates (vendored as-is)
  keep the five components from talking to each other outside the designed
  call graph, underneath that boundary.

## Consequences

**Positive**
- Code execution stays in-cluster; no per-request dependency on a third-party
  managed API or its billing.
- JWT auth (short-lived, per-request, asymmetrically signed) is strictly
  safer than the static shared secret we'd otherwise have used — no long-lived
  bearer token to leak, and it's the mechanism upstream actually designed for
  self-hosting, not a workaround.
- Privilege elevation (`SYS_ADMIN` et al.) is scoped to one dedicated
  namespace running nothing else, not loosened onto `converse`.
- Sets up Programmatic Tool Calling (MCP tools called from sandboxed code) as
  a future follow-up, once the Tool Call Server component is exercised.

**Negative**
- NsJail/chroot mode's capability grant (`SYS_ADMIN`, `NET_ADMIN`,
  `SYS_PTRACE`, `seccompProfile: Unconfined`, …) is a meaningfully bigger
  attack surface than the KVM microVM path would be. This is a direct
  trade-off for not having confirmed `/dev/kvm` on the worker pool — worth
  re-litigating if that ever changes (flip `kvmEnabled: true`, drop the
  `privileged` PSS need down to just the `/dev/kvm` device passthrough, which
  itself may need re-evaluating whether it needs `privileged` or can go
  through a device-plugin instead of hostPath).
- Single sandbox-runner replica (RWO storage constraint) means no HA and
  limited concurrent-execution throughput until an RWX storage path exists.
- A five-component stateful-ish service (Redis queue, S3, a PVC-backed
  package-init Job, an ExternalSecret with 8 properties) is real new
  operational surface on a home cluster, vendored from an upstream repo we
  don't control the release cadence of — bumping `appVersion` means re-diffing
  the vendored templates by hand (no `helm dep update` safety net).
- The upstream chart's own `fail`-guard validation of the execution-manifest
  keypair is gone (it's ESO-sourced now); a missing/misnamed
  `ssegning-aws` property now surfaces as `SecretSyncedError` at sync time
  instead of a `helm template` failure — consistent with every other
  ESO-backed secret here, but worth knowing when debugging a first install.

**Neutral / follow-ups**
- Confirm whether any `home-remote` node pool actually exposes `/dev/kvm`;
  if so, migrate to KVM mode (materially better security posture).
- Investigate an RWX-capable storage path (or accept node-pinning) before
  scaling `sandboxRunner` beyond 1 replica.
- Harden `api`/`file-server`/`tool-call-server`/`egress-gateway` container
  `securityContext` to this repo's usual KSV-0118 profile
  (`runAsNonRoot`/`drop: ALL`/`readOnlyRootFilesystem`) once each image's
  non-root behaviour is confirmed live — left at upstream defaults for this
  first pass to avoid an unverifiable breaking change.
- Programmatic Tool Calling (routing MCP tool calls through the sandbox) is
  available upstream but not wired here yet.

## Alternatives considered

- **Stay on the managed librechat.ai API** — rejected per the request driving
  this ADR (data locality, no per-request third-party cost).
- **KVM microVM mode as the default, gated on a `nodeSelector` for
  KVM-capable nodes** — rejected for now because we have no confirmed
  `/dev/kvm`-capable node in the general worker pool; revisit per the
  follow-ups above.
- **Bundle the chart's own Bitnami Redis/MinIO subcharts** — rejected; direct
  conflict with repo convention (CLAUDE.md: don't re-add a Redis chart, reuse
  the shared object-storage bucket).
- **Elevate the existing `converse` namespace to `privileged` instead of a new
  namespace** — rejected; would loosen PSS for librechat-app/mongo/meilisearch
  pods that don't need it, for the sake of one workload that does.
- **A static shared bearer key instead of JWT** — considered first (matches
  the already-wired `LIBRECHAT_CODE_API_KEY` plumbing and is simpler to
  reason about), but the service's own auth middleware rejects it in
  production, and LibreChat OSS already supports proper JWT signing
  natively — no reason to fight the grain for a worse security posture.

## Related

- Docs: `docs/patterns/self-hosted-code-interpreter.md` (the *how*)
- Charts/files touched: `charts/librechat-code-interpreter/` (new),
  `charts/librechart/values.yaml`, `charts/librechat-app/values.yaml`,
  `environments/{base,prod}/deps/librechat-code-interpreter/` (new),
  `charts/apps/values.yaml` (`global.namespacePodSecurity`)
- Upstream: [`clickhouse/code-interpreter`](https://github.com/clickhouse/code-interpreter)
  (`helm/codeapi`), [`danny-avila/LibreChat`](https://github.com/danny-avila/LibreChat)
  (`packages/api/src/auth/codeapi.ts`)
- Supersedes: none — extends the managed-API wiring from issue #734 (now
  dormant, kept as a fallback path)
