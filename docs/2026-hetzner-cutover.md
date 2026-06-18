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
  source of truth; switched `ai.camer.digital` → **`ai.camer.digital`**
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
- **Domain** — certs/SANs render `ai.camer.digital`.

### ❌ / ⚠️ Not resolved — needs follow-up
- **core-gateway Hetzner LB — ✅ ROOT-CAUSED & FIXED in-repo this session.**
  The blocker was `use-private-ip: "false"` on the EnvoyProxy's `envoyService`
  annotations (a linter regression — the comment said "private network (the
  ask)" but the value was flipped to false). With it false, the hcloud-ccm adds
  LB targets **by hcloud server reference**; node **cp-1** has a stale
  `providerID` (`hcloud://127562844` — far older than every other node's 133M-
  range ID; the server was recreated), so the CCM hit
  `ReconcileHCLBTargets: target cp-1: cloud target was not found (invalid_input)`
  and the **whole** LB sync failed → `AddressNotAssigned` → at one point Envoy
  Gateway tore down the infra (a transient "GatewayClass not found" window →
  `DeletedLoadBalancer`), so the Service disappeared entirely.
  **Fix (two parts):**
  1. (in-repo) `use-private-ip: "true"` — matches the working `traefik` LB
     (private-IP targeting + `Cluster` policy). Necessary but NOT sufficient: it
     only changed cp-1's failure from `cloud target was not found` to
     `resolve_cloud_private_targets_error` — cp-1 is unusable as an LB target in
     BOTH modes, and the hcloud-ccm fails the WHOLE LB sync if any target fails.
  2. (cluster-admin, applied live 2026-06-01) labelled all three control-plane
     nodes `node.kubernetes.io/exclude-from-external-load-balancers=""` so the
     CCM targets **workers only** (CPs run operators, not ingress traffic — the
     maintainer's call). The CCM re-reconciled within ~1 min →
     `EnsuredLoadBalancer`. **✅ Verified: EXTERNAL-IP `46.225.38.138`
     (+10.0.0.4, IPv6), Gateway `core-gateway` PROGRAMMED=True.**
  **⚠️ The node labels are LIVE-only — not in any repo.** They must be made
  durable in the cluster bootstrap (home-os / k3s node config) or they vanish on
  node re-provision and the LB breaks again. cp-1's stale providerID
  (`hcloud://127562844`) is still worth fixing/replacing independently.
- **core-gateway `api-https` listener — still invalid (home-os gap).** The
  HTTPS listener (`api.ai.camer.digital`) refs Secret
  `converse-gateway/core-gateway-api-tls`, issued by ClusterIssuer
  `cert-home-cert-envoy` (Gateway annotation) which **isn't defined in home-os
  yet** → no secret → listener `InvalidCertificateRef`, controller logs the
  error every reconcile. The HTTP listener (22 routes) is Programmed and the LB
  fix above is independent of this. **Fix is in home-os** (define the ACME
  Gateway-API issuer); do NOT stopgap with `self-signed-ca` — this is a public
  endpoint and clients must trust the cert.
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
  **Fix (in-repo, additive) — two layers, because the cluster runs Cilium:**
  the grafana-operator child ships egress policy via its deps overlay
  (`environments/prod/deps/grafana-operator`):
  - a portable k8s `NetworkPolicy` (intra-namespace + DNS + API-server-by-CIDR)
    in `base/` — CIDRs are documented knobs in `cluster.yaml`
    (`nodeCIDR`/`serviceCIDR`); and
  - **the one that actually unblocks it: a `CiliumNetworkPolicy`** with the
    reserved entity `toEntities: [kube-apiserver]`.
  Why two: Cilium (v1.19, `policy-cidr-match-mode` empty) gives node IPs a
  `remote-node`/`host` identity, so a plain `ipBlock` CIDR does **not** match
  the API server (its endpoints live on the control-plane nodes) — the CIDR
  policy is inert on Cilium (verified: even an operator-labelled busybox pod
  still timed out to `10.43.0.1:443` with only the k8s NetworkPolicy applied).
  The `kube-apiserver` entity is Cilium's supported way to allow it. Both union
  with the `allow-dns` baseline. Lands when the observability orchestrator +
  the grafana-operator child sync.

### ⏳ Pre-existing / unrelated (not caused by this branch)
- **lightbridge-backend** — `CreateContainerConfigError` (missing referenced
  secrets); predates this work.
- **metrics-server — ✅ RESOLVED (2026-06-05), then reversed → ADR-0054 (2026-06-19).**
  The collision was the `aii-metrics-server` chart vs **k3s's bundled metrics-server**
  (both on Hetzner): k3s ships its own (Addon CRs from on-disk manifests, pods labelled
  `k8s-app=*`) while the chart's Service selects `app.kubernetes.io/*` → `Endpoints
  <none>` → `metrics.k8s.io` unavailable. The 2026-06-05 fix (force-sync `aii-metrics-server`
  so the HA chart owns it + commit `--disable metrics-server` to hetzner-k8s) **did not
  hold** — the addon kept returning on restores, so the collision recurred on every sync.
  **Final resolution ([ADR-0054](adr/0054-adopt-k3s-bundled-metrics-server.md)): we
  dropped our GitOps metrics-server entirely and adopted the healthy k3s-bundled one**
  (removed the `charts/apps/values.yaml` entry; the k3s addon re-owns the Service +
  APIService). No node reprovision, no `--disable metrics-server` dependency.
  ⚠️ NOT a same-cluster `ai-*`↔`aii-*` fight — those generations target **different
  clusters** (see below). The earlier grafana-operator CrashLoop was Cilium
  deny-egress, a separate bug.
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
1. **Old `ai-*` generation — decommission (on the OTHER cluster).** ⚠️ The
   `ai-*` apps (root `ai-apps` @ HEAD) and the `aii-*` apps (root `ai-apps-v2`)
   live on the **same ArgoCD (`admin@homeos`) but target two DIFFERENT clusters**
   — `ai-*` → the other (pre-Hetzner) cluster; `aii-*` → Hetzner `home-remote`.
   They do **NOT** collide (different clusters). **Only ever act on `aii-*`;
   leave `ai-*` alone** (deleting an `ai-*` app hits the other cluster — and the
   self-healing `ai-apps` root re-creates it anyway). Decommissioning the old gen
   is the maintainer's separate exercise on that cluster.
2. **`observability-secrets`** — fill the real `ssegning-aws` remoteRefs and
   flip `enabled: true` (currently disabled to avoid clobbering the live
   externally-provisioned secrets).
3. **Hetzner LB** — ✅ provisioned (chart fix `use-private-ip: true` + CP nodes
   labelled exclude-from-LB; EXTERNAL-IP `46.225.38.138`, Gateway PROGRAMMED).
   **Make the node labels durable** (home-os / k3s bootstrap) — they're live-only
   today. Independently, fix/replace cp-1 (stale providerID). Still define
   `cert-home-cert-envoy` in home-os so the `api-https` listener resolves.
4. **grafana-operator** — ✅ root-caused + fixed in-repo (egress NetworkPolicy
   via its deps overlay). Remaining: sync the observability orchestrator so the
   policy lands, then confirm the operator goes 1/1 Ready.
5. **DNS + Keycloak** — `*.ai.camer.digital` records must resolve to the
   cluster; confirm Keycloak OIDC clients accept the new redirect URIs.
6. **`lightbridge-opa-auth`** — confirm the basic-auth secret exists in
   `converse-gateway` (Authorino's OPA metadata call needs it).
7. **`apprise-channels`** — fill the placeholder ssegning-aws remoteRef in
   `environments/base/deps/apprise-api/external-secret.yaml` (store the Apprise
   channel URL[s] there); ESO then materialises it and apprise-api starts.
7. On settle: move every self-referencing `targetRevision` to a release tag.

## 2026-06-02 — version upgrades + further egress findings

### Chart/operator upgrades to latest
Bumped (all render-verified against our valuesObjects; live-rolled):
- grafana-operator `v5.20.0`→`5.23.0` (⚠️ tag `v` prefix dropped from 5.21+;
  the old `v5.23.0` pin failed because the real tag is `5.23.0`).
- alloy `1.0.1`→`1.8.2`; kube-state-metrics `5.25.1`→`7.4.0`;
  prometheus-operator-crds `28.0.1`→`29.0.0`.
- grafana `9.4.5`→`10.5.15` (chart major 9→10; bundled app only 12.1.1→12.3.1).
- tempo `1.9.0`→`1.24.4`.
- mimir-distributed `5.3.0`→**`5.8.0`** (latest within 5.x; **6.0 deferred** —
  breaking: top-level `nginx`→unified `gateway` migration + rollout-operator
  CRDs/disable required. Do as a dedicated change).
- Envoy AI Gateway `0.5.0`→`0.6.0` (CRDs + controller in lockstep; EG v1.8.0
  satisfies the v1.7+ requirement; our v1alpha1 CRs convert cleanly and stay
  Accepted; we don't use the removed `filterConfig`/`version`-as-prefix).
Already latest (unchanged): loki 7.0.0, node-exporter, metrics-server,
authorino-operator, lightbridge, envoy gateway-helm v1.8.0.

### kube-state-metrics egress (same Cilium deny-egress disease as grafana-operator)
ksm had been CrashLoopBackOff'd ~11h (pre-existing) — it watches the API server
and couldn't reach it under the `allow-dns` baseline + Cilium node-identity.
Fixed with the same overlay pattern (CiliumNetworkPolicy `kube-apiserver`
entity); ksm 7.4.0 now 1/1.

### ⚠️ OPEN BLOCKER — observability stores can't reach S3
mimir (ingester / store-gateway / querier) and tempo crashloop on
`dial https://s3.ssegning.me:443: i/o timeout` — the SAME default-deny-egress
baseline, now blocking egress to **external object storage** (Cilium `world`).
So the metrics/traces stores have never worked on this cluster. loki uses the
same S3 and is likely affected too. **Fix (same family, not yet applied):** a
CiliumNetworkPolicy granting the store components egress to S3 — `toFQDNs`
`s3.ssegning.me` :443 (+ DNS), per component (mimir/loki/tempo). Grafana itself
also has no workload pod yet (its child app needs attention). Tracked for a
dedicated egress pass.

## 2026-06-02 (later) — S3 → Hetzner Object Storage + api-https TLS

### Observability stores moved to Hetzner Object Storage ✅
The S3-egress blocker above is resolved by moving off the personal S3 onto
Hetzner Object Storage (same pattern as Keycloak's CNPG backups):
- endpoint `s3.ssegning.me` → `nbg1.your-objectstorage.com`; bucket `monitoring`
  → `ssegning-k8s-state` (shared with Keycloak; folders: `mimir*` prefixes,
  `tempo/`, loki at root, keycloak `keycloak-cnpg-backups/`).
- Creds: mimir-s3 / loki-s3 / tempo-s3 ExternalSecrets reuse Keycloak's exact
  ssegning-aws material (`prod/meta/test-app` → `s3_backup_cnpg_client_id` /
  `s3_backup_cnpg_secret`); observability-secrets child ENABLED.
- Egress: CiliumNetworkPolicy `observability-stores-allow-s3-egress` (toFQDNs
  `*.your-objectstorage.com` + DNS L7) — the stores are `world`-egress under the
  deny-egress baseline, same family as the API-server fixes.
- ⚠️ Gotcha fixed: mimir `storage_prefix` allows ONLY `[0-9A-Za-z]` (no `/`), so
  folders are `mimirblocks` / `mimiralertmanager` / `mimirruler`, not `mimir/…`.
- ⚠️ Rollout note: mimir's ArgoCD sync deadlocked (health-gated, StatefulSets
  crashlooping on old config) — broke it by terminating the op + a
  ServerSideApply sync, then force-deleting the pods.
- **Verified live:** tempo 1/1 (`blocklist poll complete`), loki-0 2/2, mimir
  converging (7/11→), all reaching Hetzner — no more `i/o timeout`.

### api-https TLS (api.ai.camer.digital) — ✅ ISSUED (HTTP-01 through the Gateway)
Final approach (no DNS token needed): a **namespace-scoped ACME `Issuer`** in
`converse-gateway` (`core-gateway-acme`, charts/core-gateway/templates/acme-issuer.yaml)
with an **HTTP-01 `gatewayHTTPRoute` solver** whose parentRef is the core-gateway.
cert-manager attaches a temporary solver HTTPRoute to the Gateway; Let's Encrypt
validates over the LB's `:80` listener (up even while api-https was certless).
The Certificate references this ns Issuer when `gateway.acmeHttp01.enabled` (set
in charts/apps), else falls back to an external issuer (`gateway.issuer` /
`issuerKind`). DNS A record `api.ai.camer.digital` → the LB (46.225.38.138).

Two-repo change:
- **ai-helm:** acme-issuer.yaml + certificate.yaml issuerRef switch + values
  (`gateway.acmeHttp01.enabled/email`). The earlier DNS-01/cert-cloudflare wiring
  is retained as the fallback path.
- **home-os (`charts/cert`):** enabled cert-manager's Gateway-API integration
  (`config.enableGatewayAPI: true`) — required for the gatewayHTTPRoute solver
  (and it turns on the gateway-shim platform-wide). cert-manager redeployed with
  `--config`.

**Verified live:** ns Issuer READY, Certificate READY (real Let's Encrypt cert,
`CN=api.ai.camer.digital`, valid 2026-06-01→08-30), Gateway listeners
`http` + `api-https` both Programmed, LB now serves `80` + `443`. The orphaned
DNS-01 challenge from the cert-cloudflare attempt was cleaned up. (Providing
`cloudflare-secret` in kube-system is no longer required for this endpoint;
cert-cloudflare/DNS-01 remains an option for wildcards.)

### HTTP→HTTPS redirect (ACME-safe) ✅
A core-gateway HTTPRoute (`core-gateway-https-redirect`, pinned to the `http`
listener) redirects `/`→`https` (308, preserves POST). Stays compatible with the
HTTP-01 solver: cert-manager's challenge route matches the EXACT
`/.well-known/acme-challenge/<token>` path, which out-ranks the `/` PathPrefix
(Gateway-API precedence) — so renewals keep serving on :80 while everything else
redirects. To make the redirect COMPLETE, model + MCP routes are pinned to the
`api-https` listener via `gatewayRef.sectionName: api-https` (AIGatewayRoute in
charts/ai-model, MCPRoute in charts/mcps) — otherwise their header/path matches
out-rank the `/` redirect on :80 and serve plaintext. **Verified live:** `http`
listener attachedRoutes 22→1 (redirect only), `api-https` 23; `curl http://…`
→ 308 → https; `https://…` → HTTP/2 401 (Authorino auth-gate, TLS good).

## 2026-06-02 (later still) — LibreChat / opencode / models-info

### nginx static-server `root` bug (two charts) ✅
Both `librechat-opencode-wellknown` and `ai-models-info` ship a custom nginx
`default.conf` that REPLACES the stock one but forgot to re-declare
`root /usr/share/nginx/html`. Without it, `try_files <path> =404` resolves
against nginx's compiled-in default root (`/etc/nginx/html`) and never finds the
mounted file → 404. Added `root /usr/share/nginx/html;` to both server blocks.
- `https://ai.camer.digital/opencode/.well-known/opencode` → now 200 JSON
  (verified live).
- `https://api.ai.camer.digital/v1/models/info` → was 404 even with a valid
  JWT (404 came from nginx itself, *after* Authorino); fixed the same way.
  **Verified:** in-cluster curl now returns 200 + the OpenRouter-shape catalog
  JSON. ⚠️ Rollout note: a ConfigMap-only change doesn't reload nginx, and
  `kubectl rollout restart` is reverted by ArgoCD selfHeal (the annotation is
  git-drift) — so after the CM syncs, the pods must be **deleted** (RS recreates
  them with the new subPath-mounted config).

### LibreChat S3 + secrets
- `librechat-app` uses `fileStrategy: s3` and referenced a missing
  `librechat-s3-config` secret + a stale `AWS_ENDPOINT_URL: https://s3.camer.digital`.
  Now: an in-chart ExternalSecret (templates/externalsecret-s3.yaml) materialises
  `librechat-s3-config` from the SAME Hetzner Object Storage material as
  Keycloak/observability (ssegning-aws `prod/meta/test-app`), via ESO
  `target.template` (region + bucket `ssegning-k8s-state` are plain config, only
  the access/secret keys are fetched); endpoint → `https://nbg1.your-objectstorage.com`.
- LibreChat also needs 8 user-owned secrets that didn't exist (real API keys,
  OAuth creds, encryption keys, Meili key). Scaffolded as ExternalSecrets
  (templates/externalsecret-app.yaml + `librechatSecrets` values) with
  PLACEHOLDER ssegning-aws remoteRefs — **fill them to bring librechat-app +
  librechat-search up**: librechat-main-config, librechat-config,
  librechat-openid-config, librechat-meili-config, librechat-mcp-{cd,coder,github}-
  credentials, librechat-websearch-config. (converse has no deny-egress baseline,
  so no egress policy is needed for S3.)

### ai-models-info placement — DECISION: stays under `ai-models` (not librechart)
`ai-models-info` (the `models-info` app serving `/v1/models/info`) is **not
missing** — it's a child of the **`ai-models`** orchestrator, Synced/Healthy with
its HTTPRoute on the core-gateway. It is deliberately NOT a `librechart` child:
it's rendered with the model catalog (`.Values.models` + `excludeKinds`) that is
the source of truth in `charts/ai-models/values.yaml`, and Helm can't share that
across the two separate orchestrator charts. Moving it to librechart would
require relocating the ~35-model catalog to a shared source (risky core-models
diff) AND a disruptive live cutover (the ai-models ApplicationSet has no
`preserveResourcesOnDeletion`, so it would prune the working app → `/v1/models/info`
briefly 404s). For a healthy, serving component that lives next to the catalog it
derives from, that cost isn't worth it. **Left under `ai-models` by decision.**

## 2026-06-04/05 — secrets re-homing, OPA removal, dual-plane gateway (ADR-0021)

### Secrets moved in-chart; the `secrets` app retired ✅ (with one self-inflicted outage)
The wholesale **`secrets` Application** (synced ExternalSecret/Secret CRs from
`ai-ops-secrets.git`) was **removed from `charts/apps`**. Secrets are now
**chart-owned**: in-chart ExternalSecrets (ai-models-backends, librechat-app,
observability-secrets) + the `environments/<env>/deps/*` overlays. App secrets
resolve against the consolidated `ssegning-aws` key **`ai/camer/digital/prod/env`**
(one property each); platform secrets stay on `prod/meta/test-app`. Filled:
librechat's ~18 refs, the 6 backend keys (deepinfra split into `-01`/`-02`),
grafana-admin/keycloak, `redis-ha-redis-auth` (converse). Still placeholder:
`apprise-channels`, `opencode-k8s-agent-secret`.
- ⚠️ **LESSON / outage:** pruning `secrets` cascade-deleted everything it owned —
  including `lightbridge-opa-auth` and the lightbridge backend's `opa-secret` /
  `lightbridge-api-client` / CNPG `*-db-app`. The gateway then returned **404
  `x-ext-auth-reason: Service not found`** on every request: Authorino's AuthConfig
  was stuck `Ready: False` ("secret lightbridge-opa-auth not found") so no host was
  linked. **Re-home a secret in-chart BEFORE retiring its provisioner.** The
  lightbridge backend is still down on those secrets but is now off the gateway
  critical path (OPA removed, below).

### OPA removed — Keycloak JWT is the authz boundary ✅
The fix for the 404 was to **drop OPA from the AuthConfig entirely** (maintainer:
"responsibility is moving to Keycloak; OPA only for future burst control"). Deleted
the `lightbridge-validation` HTTP metadata source + the `enforce-valid-key` step +
the OPA-derived response items (`x-project-id`, `x-api-key-id`, `llm_*`
dynamicMetadata). A valid Keycloak JWT now = access. The AuthConfig reconciles
without the OPA Secret/backend. The `x-oidc-*` (ADR-0011) contract is unchanged.

### Dual-plane gateway + burst/budget/billing (ADR-0021) ✅ (charts; activation pending)
Built per ADR-0021 (read it):
- **External plane** (`api.ai.camer.digital`, public LB): full Keycloak JWT;
  descriptors via CEL with defaults so `billing_plan`/`organization` claims are
  optional (`→ free` / `→ sub`).
- **Internal plane** (`core-gateway-internal.envoy-gateway-system.svc.cluster.local`):
  new `api-internal` HTTPS listener (`self-signed-ca` TLS) + a ClusterIP Service in
  `envoy-gateway-system` (selects the proxy pods, 443→10443). A 2nd AuthConfig binds
  this host and accepts **either** a k8s SA token (`kubernetesTokenReview`, audience
  `core-gateway-internal` — one-time jobs) **or** a static `apiKey` (labeled Secret
  `kuadrant.io/apikey-for=internal-gateway` — long-running services).
- **Rate limiting**: per-model `BackendTrafficPolicy` with 3 rule families — burst
  req/min (per-user `x-account-id`), burst tokens/min (from `llm_total_token`
  metadata), monthly µ$ budget (per-org `x-org-id`, only for plans with
  `monthlyBudgetUsd` → service/internal uncapped). Tiers in
  `charts/ai-models/values.yaml` `rateLimitBudgeting.plans` (free/pro/service/internal).
- **LibreChat** repointed to the internal host; redis over `rediss://` + internal-CA
  trust (`NODE_EXTRA_CA_CERTS`/`REDIS_CA` → `/etc/internal-ca`); authenticates with
  its existing `CONVERSE_OPENAI_API_KEY` (now also materialised as the gateway-side
  `internal-key-librechat` apiKey Secret — one value, both ends). **Per-user
  attribution**: LibreChat forwards `X-LibreChat-User` = the user's Keycloak sub; the
  internal AuthConfig's CEL maps it to per-user `x-account-id`/budget (so a person's
  LibreChat + opencode usage share one account). Trust = internal-plane-only +
  Authorino overwrites descriptors.

**Activation pending (maintainer's test pass):** Keycloak `billing_plan`/
`organization` mappers (external plane; optional thanks to CEL defaults), the
internal listener/cert/Service coming up, role→tier mapping value, Phase-4 metering
(Alloy→Mimir), and a Cilium NetworkPolicy confining `core-gateway-internal`.

### Catalog enrichment + frontend bump (smaller items)
- `/v1/models/info` per-model `context_length` (web-verified per backend; capped at
  400k) + `top_provider` + `supported_parameters[]` (`charts/ai-models/values.yaml`
  `info:` blocks). GLM-5.1 corrected to text-only; qwen3-embedding-8b → `kind:
  embedding` (excluded from the chat catalog).
- converse-frontend image bumped `sha-df5d442 → sha-7b3a945` (ported from `main`'s
  King-Koufan commit, tag only — `main` is ~2.8k lines behind, pre-`ai-v2` migration;
  teammates' image bumps on `main` don't reach the cluster).
