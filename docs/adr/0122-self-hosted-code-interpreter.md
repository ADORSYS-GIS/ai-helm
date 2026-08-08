# ADR-0122: Self-Hosted LibreChat Code Interpreter

**Status:** Accepted
**Date:** 2026-08-07
**Deciders:** @stephane-segning

> **Corrected 2026-08-08 (same PR, before merge — not a supersession):** the
> first pass of this work got two things wrong, caught in review before
> merge. (1) It referenced `ghcr.io/clickhouse/code-interpreter/*` images
> that were never verified and do not exist — upstream publishes no images
> at all (its own CI only runs `docker buildx build --check`, never a push).
> Fixed by forking upstream to
> [`ADORSYS-GIS/code-interpreter`](https://github.com/ADORSYS-GIS/code-interpreter)
> with a build+push workflow publishing to `ghcr.io/adorsys-gis/
> code-interpreter-*`, pinned to a commit SHA tag. (2) It hand-wrote raw
> Kubernetes manifests instead of using `bjw-template` (`charts/bjw-template`,
> this repo's standard app-scaffolding chart — see `charts/librechat-app` for
> the established multi-controller pattern this now mirrors), against repo
> convention. Rewritten so the whole chart is `bjw-template`-driven
> (`controllers`/`service`/`persistence`/`networkpolicies`); only the
> ExternalSecret (not a bjw-common resource type) stays a custom template.
> The architecture decisions below (NsJail mode, dedicated namespace, JWT
> auth, shared redis-ha/S3) are unchanged — only *how* the chart is
> authored and *where* the images come from changed.

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

Build `charts/librechat-code-interpreter` on `bjw-template` (this repo's
standard app-scaffolding chart, `charts/bjw-template` — repo convention, see
`charts/librechat-app` for the established pattern) rather than hand-rolled
manifests, re-implementing upstream's `helm/codeapi` chart's 7 components
(api, service-worker, sandbox-runner, file-server, tool-call-server,
egress-gateway, package-init) as `bjw-template` `controllers`/`service`/
`persistence`/`networkpolicies` entries. Only the ExternalSecret (not a
bjw-common resource type) is a custom template
(`templates/externalsecret.yaml`). Images come from the
`ADORSYS-GIS/code-interpreter` fork (upstream publishes none — see the
correction note above), pinned to a commit SHA tag, not `latest`.

Adaptations from upstream's own chart design (re-implemented, not literally
copied — see also the correction note above):

- **No bundled Redis/MinIO.** Always point at the shared `redis-ha`
  (`redis-ha-redis-haproxy.redis-system.svc.cluster.local`, TLS, same as every
  other consumer) and the shared Hetzner Object Storage bucket
  (`ssegning-k8s-state`) that `librechat-app` itself already uses for file
  storage. The chart has no S3 key-prefix knob, so codeapi's objects land in
  the bucket root alongside LibreChat's own — both use opaque
  session/execution-scoped keys, so collision risk is negligible; a dedicated
  bucket is a one-line follow-up (`fileServer.s3.bucket`) if that changes.
- **Secrets are an ExternalSecret** (`templates/externalsecret.yaml`,
  producing a single `codeapi-secrets` Secret) sourced from `ssegning-aws`
  (`ai/camer/digital/prod/env`, one property per key — repo convention),
  never plaintext values. Every container reads it via `secretKeyRef` —
  same pattern `charts/librechat-app` already uses. A missing property
  surfaces as `SecretSyncedError` / pod CrashLoop, same as every other
  ESO-backed secret in this repo.
- **NsJail/chroot sandbox mode** (`sandbox-runner`'s container
  `securityContext.capabilities.add: [SYS_ADMIN, …]`), deployed to a new
  dedicated `librechat-sandbox` namespace elevated to the `privileged`
  Pod Security Standard (via `global.namespacePodSecurity` in
  `charts/apps/values.yaml`, the existing mechanism). Every other
  container in the chart keeps this repo's usual hardened
  `securityContext` (`drop: [ALL]`, no priv-esc, `readOnlyRootFilesystem`)
  — sandbox-runner and the `package-init` Job (compiles Python from
  source into system paths) are the two documented exceptions
  (`.trivyignore` / `.trivyignore.yaml`).
- **A shared packages PVC** (10Gi, ReadWriteOnce, cluster default storage
  class), with **`sandbox-runner` and `service-worker`/`api` at 1 replica**
  for the first deploy (RWO can't be shared across
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
- **Deployed as a flat `charts/apps` entry**, NOT a `librechart` orchestrator
  child (ADR-0014) despite being part of the LibreChat application group —
  the `librechart` ApplicationSet's children all share ONE
  `destination.namespace` (`charts/librechart/templates/applicationset.yaml`
  has no per-child namespace override), which is incompatible with this
  needing its own dedicated `librechat-sandbox` namespace. A `depsOverlay`
  (`environments/prod/deps/librechat-code-interpreter` in `ai-helm-values`)
  ships the one Cilium egress gap the chart's own `bjw-template`
  `networkpolicies` don't cover: `file-server` → Hetzner Object Storage
  (FQDN egress, which plain `NetworkPolicy` can't express). Everything else
  cross-component is scoped by those `networkpolicies` entries directly
  (podSelector on `app.kubernetes.io/controller`, the label `bjw-template`
  stamps on every controller's pods).

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
- A six-controller stateful-ish service (Redis queue, S3, a PVC-backed
  package-init Job, an ExternalSecret with 8 properties) is real new
  operational surface on a home cluster, and the images come from a fork
  (`ADORSYS-GIS/code-interpreter`) we now own the release cadence of —
  bumping the image version means merging an upstream-sync PR there, then
  re-pinning every `tag:` here and confirming nothing else changed shape
  (env vars, ports, probe paths) before merging.
- The upstream chart's own `fail`-guard validation of the execution-manifest
  keypair is gone (it's ESO-sourced now); a missing/misnamed
  `ssegning-aws` property now surfaces as `SecretSyncedError` at sync time
  instead of a `helm template` failure — consistent with every other
  ESO-backed secret here, but worth knowing when debugging a first install.

**Neutral / follow-ups**
- Confirm whether any `home-remote` node pool actually exposes `/dev/kvm`;
  if so, migrate to KVM mode (materially better security posture).
- Investigate an RWX-capable storage path (or accept node-pinning) before
  scaling `sandbox-runner` beyond 1 replica.
- **Redis TLS is encrypted but not CA-verified** — `REDIS_TLS=true` maps to
  `tls.rejectUnauthorized: false` in this service's own Redis client (all
  five consumers: api, service-worker, file-server, tool-call-server,
  egress-gateway); there's no CA-verification knob like `librechat-app`'s
  `rediss://`+`REDIS_CA`. Redis here carries the BullMQ job queue, the
  internal service token, execution manifests, and the egress-grant
  ledger — an in-cluster MITM could decrypt/forge that traffic. Likelihood
  is low (needs cluster-networking compromise; sandbox-runner's own egress
  is locked to egress-gateway only, so untrusted code can't reach Redis
  directly) and accepted for now, but proper `rejectUnauthorized: true` +
  CA pinning would need an upstream patch (flagged in review, P2 — tracked
  here rather than fixed in this PR).
- Programmatic Tool Calling (routing MCP tool calls through the sandbox) is
  available upstream but not wired here yet.
- **Every controller runs as root** — caught live on first deploy (2026-08-08):
  none of the `ADORSYS-GIS/code-interpreter` fork's Dockerfiles declare a
  non-root `USER` (checked all 7 — every production stage is `FROM
  oven/bun:1.3.14`/`buildpack-deps:bookworm` with no `USER` directive), so
  `defaultPodOptions.securityContext.runAsNonRoot: true` made kubelet refuse
  to start every controller (`CreateContainerConfigError`). Removed; every
  container still gets `allowPrivilegeEscalation: false` /
  `capabilities.drop: [ALL]` / `readOnlyRootFilesystem` (where tolerated) /
  seccomp `RuntimeDefault`, but running as root is a real regression on
  defense-in-depth versus this repo's usual posture. Proper fix is patching
  the fork's Dockerfiles to add non-root `USER`s — needs care (matching
  ownership on `/pkgs` and other writable mounts) — tracked here rather than
  attempted under live-incident pressure.

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
- Charts/files touched: `charts/librechat-code-interpreter/` (new, built on
  `charts/bjw-template`), `charts/apps/values.yaml` (new app entry +
  `global.namespacePodSecurity`), `charts/librechat-app/values.yaml`
  (JWT signing env/secret), `environments/{base,prod}/deps/
  librechat-code-interpreter/` (new, in `ai-helm-values`)
- Upstream: [`clickhouse/code-interpreter`](https://github.com/clickhouse/code-interpreter)
  (the design/architecture this chart re-implements; NOT consumed as a chart
  or image dependency — see the correction note),
  [`ADORSYS-GIS/code-interpreter`](https://github.com/ADORSYS-GIS/code-interpreter)
  (the fork that actually publishes the images this chart pulls),
  [`danny-avila/LibreChat`](https://github.com/danny-avila/LibreChat)
  (`packages/api/src/auth/codeapi.ts`)
- Supersedes: none — extends the managed-API wiring from issue #734 (now
  dormant, kept as a fallback path)
