# 2026 Hetzner cutover — change log + live status

Record of the work done on branch `claude/magical-bohr-390242` to move the AI
platform onto the Hetzner k3s cluster, plus a live verification of each fix as
of 2026-06-01. The *why* of the structural pieces lives in the ADRs (linked);
this doc is the operational narrative + the "did it actually work" check.

> Deploy model: ArgoCD on the **home-os** cluster reconciles this branch.
> Root app `ai-apps-v2` → `charts/apps` → emits the `aii-*` Application set.
> Deploys run from the branch now → a release **tag** next, never `main`
> (see `argocd.selfTargetRevision` in `charts/apps/values.yaml`).

## What changed (by theme)

### Architecture / GitOps structure
- **Umbrella apps + `environments/` overlays (ADR-0018).** Flat leaf apps can
  attach app-scoped dep CRs (ingress `Certificate`, app-scoped `ExternalSecret`)
  via a one-line `depsOverlay: environments/<env>/deps/<app>`; the apps template
  folds it in as a second (kustomize) source. Per-env knobs live in
  `environments/prod/cluster.yaml`. Converted: `grafana`, `lightbridge-backend`.
- **Coder → App-of-Apps orchestrator (ADR-0019).** `charts/coder` renders two
  child Applications: `coder-db` (CNPG leaf) + `coder-app` (OCI workload + cert
  overlay). Rendered as plain Application CRs (not an ApplicationSet) because
  the children are fixed + heterogeneous.
- **Observability → App-of-Apps orchestrator (+ secrets app) (ADR-0020).**
  `charts/observability` groups the 10 components as children + a (disabled,
  placeholder) `observability-secrets` child. Carries `podSecurityEnforce`.
- **syncPolicy wrapper bug fixed.** The `charts/apps` template dropped the
  `syncPolicy:` key for apps with a custom policy → ~13 apps silently ran with
  no automation; now they get their declared `automated: {prune, selfHeal}`.
- Removed `adminer` and `librechat-admin-panel` (out of scope).

### Cluster portability knobs (the "configurable per cluster kind" theme)
- **Pod Security per namespace** — `global.namespacePodSecurity` (charts/apps)
  + the observability orchestrator's `podSecurityEnforce: privileged`, applied
  via ArgoCD `managedNamespaceMetadata`. k3s enforces `baseline` cluster-wide,
  which forbids the hostPath/host-net the observability collectors need.
- **Platform domain** — `environments/prod/cluster.yaml: domainBase` is the
  source of truth; switched `ai.camer.digital` → **`ai-v2.camer.digital`**
  everywhere (hostnames live inside upstream-chart valuesObjects with
  Go-template syntax, so it's a documented-knob + guided-sweep, not `tpl`).
- **Hetzner LB annotations** — `envoyProxy.service.annotations` on the
  core-gateway EnvoyProxy (private-IP LB + health checks); configurable.

### Live-deploy fixes (found while reconciling)
| Fix | Commit | Root cause |
|---|---|---|
| authorino-operator `0.24.0`→`0.23.1` | `3fe2074` | pinned chart version didn't exist (ComparisonError) |
| grafana-operator `v5.23.0`→`v5.20.0` | `3fe2074` | same — OCI tag didn't exist |
| `redis-ha-redis-auth` ES for envoy ratelimit | `f9b4cfe` | secret only existed in `redis-system` |
| envoy-ratelimit → Redis **TLS + CA** | `d6cea41` | redis-ha is TLS-only (`self-signed-ca`); plaintext client reset |
| core-gateway OTel collector `mode` | `5c26202` | `mode` empty → otel v1beta1 webhook rejected |
| core-gateway LB `externalTrafficPolicy` | `5c26202` | (attempted — see status) |
| Authorino `authz-tls` CA | `454ce52` | secret only existed in `converse`, Authorino runs in `converse-gateway` |
| Mimir invalid `limits` field | _this commit_ | `max_outstanding_requests_per_tenant` removed from Mimir `limits` → crash-loop |

The cross-namespace TLS fixes (ratelimit-redis-ca, authz-tls) use a common
pattern: issue a throwaway leaf `Certificate` from the **internal**
`self-signed-ca` ClusterIssuer in the consumer namespace and mount only its
`ca.crt` (= "Home SSegning Root CA"). Documented in CLAUDE.md (redis section).

## Live status (verified 2026-06-01, root `ai-apps-v2` synced to `454ce52`)

### ✅ Confirmed working
- **authorino-operator** — `Synced/Healthy @ 0.23.1`; the Authorino instance
  pods (`kuadrant-policies-main-*`) are **1/1 Running** (were ContainerCreating).
- **`authz-tls` CA** — secret present in `converse-gateway`; Authorino mounted
  it and started.
- **envoy-ratelimit** — **1/1 Running** (was CrashLoopBackOff); redis TLS + CA
  trust works.
- **core-gateway OTel collector** — `mode=deployment`, **1/1 Ready**.
- **Observability PSS** — `observability` ns labelled `enforce=privileged`;
  **alloy** (2/2) and **node-exporter** Running.
- **Orchestrators** — `aii-observability`, `aii-coder` Synced/Healthy; children
  `coder-db`, `alloy`, `node-exporter`, `prometheus-operator-crds` Healthy.
- **Domain** — certs/SANs render `ai-v2.camer.digital`.

### ❌ / ⚠️ Not resolved — needs follow-up
- **core-gateway Hetzner LB — STILL FAILING.** The
  `externalTrafficPolicy: Cluster` change did **not** fix it; the error
  persists regardless of policy:
  `ReconcileHCLBTargets: target ssegning-hetzner-k3s-cp-1: failed to resolve
  cloud private targets`. The working `traefik` LB (same annotations, same
  `nbg1`, also `Cluster`) provisions fine, so the difference is **node `cp-1`**
  (oldest server, `hcloud://127562844`) — its private target can't be resolved
  for the **new** LB. Almost certainly a Hetzner-network attachment issue for
  that node / the new LB, needing Hetzner-console insight (is the new LB
  attached to `HCLOUD_NETWORK`? is `cp-1` in it?). **Open — not a chart fix.**
  Options: add `load-balancer.hetzner.cloud/network: <name>`, fix `cp-1`'s
  network membership, or keep the LB off `cp-1`.
- **grafana-operator — ✅ ROOT-CAUSED & FIXED this session (was a silent
  CrashLoop).** The exit-2 "silent crash" was a **NetworkPolicy egress block**,
  not anything the prior sessions suspected (version / OOM / RBAC / cache-scope
  / discovery were all red herrings — they were untestable because the pod died
  *before* the real error logged). How it was found: ran the operator image as
  a standalone debug pod with `--zap-log-level=debug`, **no probes, no
  leader-elect**, so nothing killed it at 30s. It then logged the true error at
  ~32s:
  `setup: unable to detect the platform … Get "https://10.43.0.1:443/api?timeout=32s": dial tcp 10.43.0.1:443: i/o timeout`
  → the operator calls the **Kubernetes API server** at startup ("detect
  platform"), the call timed out after 32s, exit 2 at `main.go:180`. The real
  Deployment's liveness probe (no `initialDelaySeconds`, 3×10s) killed the pod
  at exactly 30s — ~2s **before** the error could log — which is why every prior
  session saw only the two setup lines and called it "silent."
  **Why the API was unreachable:** the cluster runs a **default-deny-egress
  baseline** — an `allow-dns` NetworkPolicy (`podSelector: {}`,
  `policyTypes: [Egress]`, present in `apps`/`data`/`observability`/`platform`,
  42d old, NOT ArgoCD-managed) whose only egress rule is DNS→kube-system.
  Selecting a pod for any egress policy flips it to deny-by-default, so every
  pod in `observability` can reach DNS and nothing else. Data-plane pods
  (loki/mimir/node-exporter) survive because they never initiate API calls; the
  operator can't. A plain busybox pod in the namespace reproduced the timeout.
  **Fix (in-repo, additive):** the grafana-operator child now ships an egress
  `NetworkPolicy` (`grafana-operator-allow-egress`) via its deps overlay
  (`environments/prod/deps/grafana-operator`) granting the operator pod egress
  to the API server (node CIDR `10.0.0.0/24`:6443 post-DNAT + Service CIDR
  `10.43.0.0/16`:443 pre-DNAT), intra-namespace (Grafana admin API), and DNS.
  NetworkPolicies union, so it complements `allow-dns` without touching it. The
  CIDRs are documented knobs in `environments/prod/cluster.yaml`
  (`nodeCIDR`/`serviceCIDR`). Diagnosis is conclusive (debug pod reproduced the
  exact error); the live apply needs a sync of the observability orchestrator.

### ⏳ Pre-existing / unrelated (not caused by this branch)
- **lightbridge-backend** — `CreateContainerConfigError` (missing referenced
  secrets); predates this work.
- **metrics-server — ✅ RESOLVED this session.** Was an `ai-metrics-server` ↔
  `aii-metrics-server` collision (immutable selector: old `k8s-app=*` pod vs new
  `app.kubernetes.io/*` Service → `Endpoints <none>` → `metrics.k8s.io`
  unavailable). Fixed by: deleting the old `ai-metrics-server` Application +
  the stuck `metrics-server` Deployment, then force-syncing `aii-metrics-server`
  (`apply.force`) to recreate it. Now: pod 2/2, endpoints populated,
  `metrics.k8s.io` **Available**, `kubectl top` works. (Note: this did NOT fix
  grafana-operator — see above — so it was a real but separate bug.)
- **secrets / mcps** — `OutOfSync` (missing namespaces `monitoring`/
  `converse-monitoring`, old-gen residue) — clears with the old-gen decommission.
- **apprise-api** — `ContainerCreating`, blocked mounting the `apprise-channels`
  secret (notification-channel URLs) which doesn't exist. Now wired as an
  **ExternalSecret** via the apprise-api umbrella overlay
  (`environments/prod/deps/apprise-api`, target key `alerts.cfg`, store
  `ssegning-aws`) — same pattern as `redis-ha-redis-auth`. **Fill the
  placeholder ssegning-aws remoteRef** (store the Apprise URL[s] there); ESO
  then creates the secret and the pod starts. bjw-s persistence can't mark the
  volume `optional`, so the secret must exist.

## Outstanding manual / external steps
1. **Old `ai-*` generation — decommission.** `ai-metrics-server` already done
   (see above). Retire the rest of the old `ai-apps` root + remaining `ai-*`
   children once their `aii-*` counterparts are green, to clear the duplicate
   management (each old↔new pair can collide the same way metrics-server did).
2. **`observability-secrets`** — fill the real `ssegning-aws` remoteRefs and
   flip `enabled: true` (currently disabled to avoid clobbering the live
   externally-provisioned secrets).
3. **Hetzner LB** — resolve the `cp-1` private-target issue (above).
4. **grafana-operator** — ✅ root-caused + fixed in-repo (egress NetworkPolicy
   via its deps overlay). Remaining: sync the observability orchestrator so the
   policy lands, then confirm the operator goes 1/1 Ready.
5. **DNS + Keycloak** — `*.ai-v2.camer.digital` records must resolve to the
   cluster; confirm Keycloak OIDC clients accept the new redirect URIs.
6. **`lightbridge-opa-auth`** — confirm the basic-auth secret exists in
   `converse-gateway` (Authorino's OPA metadata call needs it).
7. **`apprise-channels`** — fill the placeholder ssegning-aws remoteRef in
   `environments/base/deps/apprise-api/external-secret.yaml` (store the Apprise
   channel URL[s] there); ESO then materialises it and apprise-api starts.
7. On settle: move every self-referencing `targetRevision` to a release tag.
