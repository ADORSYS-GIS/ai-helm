# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repo type

Helm charts + ArgoCD GitOps for the Camer Digital AI platform. **Not an application** — no build, no compile, no traditional test loop. The "verification cycle" is `helm template` (does it render?) + the relevant `helm lint` + CI's chart-render and security scans. Things deploy via ArgoCD reconciling these charts in the cluster.

> **Maintainer:** @stephane-segning. Use this handle in ADR `Deciders:` lines and any maintainer-attribution context. Don't substitute branch names.

> **Companion repos:** `home-os` (shared cluster infra ai-helm only *consumes* — cert-manager + ClusterIssuers, redis-ha, CNPG + Barman, Traefik, ESO; local `/Users/selast/dev/personal/home-os`) and `hetzner-k8s` (Terraform nodes/network/CNI/LB + the platform bootstrap; local `/Users/selast/dev/personal/hetzner-k8s`). ⚠️ **`ai-gitops` does NOT exist** — older notes/ADRs reference it as the planned "deployment state" repo, but it was never created. Per-env overrides live **in this repo** under `environments/` (ADR-0018); the root `ai-apps-v2` Application is applied **manually**. Still don't put image-tag overrides in chart logic (ADR-0013).

## Read these first when changing anything architectural

1. `docs/adr/README.md` — index of every Architecture Decision Record. ADRs are the source of truth for "why". Read the relevant ones before touching anything they cover.
2. `docs/architecture.md` — system map (ArgoCD topology, sync waves, auth flow, observability pipeline). Orients quickly.
3. `CONTRIBUTING.md` — conventions, commit style, ADR process.
4. `docs/2026-currency-audit.md` — every chart-pin / API-version freshness assessment, with a punch-list of follow-ups.

## ADRs are immutable once Accepted

Don't edit the decision body of an Accepted ADR. To change a decision, write a new ADR that supersedes the old one (status → `Superseded by ADR-NNNN`, add a one-paragraph header note explaining what changed; the original body stays). The index in `docs/adr/README.md` shows the supersession chain.

## Common commands

```bash
# Render a chart (the primary "does this still work?" check)
helm template <release-name> charts/<chart>/ [-n <ns>] [-f /tmp/values.yaml]

# Fetch chart dependencies (required after touching Chart.yaml)
helm dep build charts/<chart>/
# or to also update versions:
helm dep update charts/<chart>/

# Lint a chart (run before pushing changes to charts/)
helm lint charts/<chart>/

# Dashboard generator (Python — uv + ruff, NEVER pip/poetry)
cd tools/dashboards
uv sync                                 # one-time, reads uv.lock
uv run dashboards build                 # regenerate every JSON
uv run dashboards check                 # CI guard: fail if committed JSON drifts
uv run ruff format . && uv run ruff check .

# After editing the dashboard .py source, you MUST run `dashboards build`
# and commit the regenerated JSON — CI fails otherwise.

# Match CI before pushing chart changes — CI lints --strict AND renders every
# chart (.github/workflows/helm-lint.yaml). To check the whole repo at once:
for c in charts/*/; do helm lint "$c" --strict && helm template x "$c" --dry-run >/dev/null || echo "FAIL: $c"; done
```

There is no `npm`, no `pytest`, no `cargo`, no `go build` in this repo. The dashboards Python project at `tools/dashboards/` is the only code that runs; everything else is YAML rendered by Helm. **CI gates** (`.github/workflows/`): `helm-lint` (`helm lint --strict` + `helm template --dry-run` per chart), `dashboards-drift` (`uv run dashboards check`), `security` (scans), `release-helm-charts` (package on tag), `opencode` (the agent/CI rules — see `.github/workflows/opencode.yml`, the canonical agent rules; the stale `.opencode/README.md` is unrelated).

## The orchestrator-plus-leaves pattern (used for `ai-models` and `librechart`)

When a chart's components have different lifecycles (sync waves, rollback granularity, per-component ArgoCD UI surface), split it:

```
charts/<thing>/                  # orchestrator: emits ApplicationSet only
charts/<thing>-<componentA>/     # leaf: one Application worth of stuff
charts/<thing>-<componentB>/     # leaf
```

The orchestrator's `Chart.yaml` depends only on `common`. Its `templates/applicationset.yaml` emits ONE `ApplicationSet` whose List generator has one element per child. Children point at the sibling leaf charts via `path: charts/<thing>-<componentN>`.

See ADR-0012 (`ai-models`) and ADR-0014 (`librechart`) for the canonical examples + the rationale. **Don't reinvent this pattern** — copy from one of these when you need it again.

> **App-of-Apps variant (`coder` ADR-0019, `observability` ADR-0020).** When an orchestrator's children are *fixed and heterogeneous* — e.g. local Helm charts + upstream charts that deploy as sources, with large inline valuesObjects — an ApplicationSet List generator handles it poorly (OCI-as-dep needs a `Chart.lock`; inline sources need controller-time goTemplate). These orchestrators instead render their child `Application` CRs directly via plain Helm (`templates/applications.yaml`, iterating `.Values.children`). Same controlPlane/destination rules; children support `depsOverlay` (cert/secret overlays) and an orchestrator-level `podSecurityEnforce`. `charts/coder` → `coder-db` + `coder-app`; `charts/observability` → the 10 observability components + a (disabled) `observability-secrets` child.

## Umbrella Applications + `environments/` overlays (ADR-0018)

Flat leaf apps in `charts/apps/values.yaml` use a multi-source **umbrella** so a workload and its app-scoped prerequisites sync as one Application:

- **Source A — workload**: the Helm chart (`path: charts/<x>` or an upstream `chart:`).
- **Source B — app-scoped deps**: a **kustomize** overlay at `path: environments/<env>/deps/<app>` emitting the ingress `Certificate` and any per-app image-pull / session `ExternalSecret`. Kustomize is confined to these plain CRs — **never kustomize-over-Helm** (that needs the controller-wide `--enable-helm` flag).
- **Source C — `ref: values`** (optional): a `$values` ref so Source A can pull a per-env values file when a *workload* knob actually diverges between environments.

Per-env knobs (`clusterIssuer`, `secretStore`, `ingressClass`, `storageClass`, `domainBase`) live in `environments/<env>/cluster.yaml` (source of truth) and are patched into the dep CRs by the `environments/<env>/deps/<app>/` kustomize overlay (base under `environments/base/deps/<app>/`). Today only `environments/prod/` exists (Hetzner); a second env is a drop-in sibling directory.

Ownership split: umbrellas own **app-scoped** secrets/certs (referencing `ssegning-aws` by name). The store is never defined here. ⚠️ The wholesale-provisioner `secrets` Application (`ai-ops-secrets.git`) was **removed (2026-06-04)** — secrets are now **chart-owned** (in-chart ExternalSecrets + the `environments/<env>/deps/*` overlays). **App** secrets resolve against the consolidated `ssegning-aws` key **`ai/camer/digital/prod/env`** (one property each); **platform** secrets (S3, redis password) against `prod/meta/test-app`. LESSON: re-home a secret in-chart *before* retiring its provisioner — pruning `secrets` cascade-deleted the lightbridge secrets (incl. `lightbridge-opa-auth`) and caused a gateway outage.

**How to attach deps:** add one field to the app entry — `depsOverlay: environments/<env>/deps/<app>`. `applications.yaml` folds it in as Source B (pointing at this repo via `argocd.selfRepoURL` @ `argocd.selfTargetRevision`), keeping the workload's `source:` + `valuesObject` verbatim (no re-indenting big value blocks). Also drop the `cert-manager.io/cluster-issuer` annotation from that chart's ingress — the overlay `Certificate` now owns the TLS secret. Flat umbrella: `lightbridge-backend`. Dep-less infra/backends stay single-source. (`coder` and `grafana` also consume `environments/<env>/deps/<app>` cert overlays, but as **children of App-of-Apps orchestrators** — `coder` ADR-0019, `grafana` under `observability` ADR-0020 — not as flat umbrellas. The orchestrator templates support `depsOverlay` on children too.)

The umbrella needs **no ApplicationSet** — `applications.yaml` already passes `.sources` through. (The List/Matrix-generator conversion, old ADR-0006, is decoupled future work.) Orchestrators (`models`, `librechat`) are **not** wrapped — they're already ApplicationSets.

> ⚠️ The `applications.yaml` template's custom-`syncPolicy` branch previously omitted the `syncPolicy:` wrapper key (contents leaked into `destination:`), so ~13 apps that declared their own `syncPolicy` rendered with **no** `spec.syncPolicy` (manual sync, declared automation silently dropped). Fixed in the ADR-0018 work — those apps now get their declared `automated: {prune, selfHeal}`. Sanity-check sync behaviour on the live cluster after merge.

## ai-helm ↔ ai-gitops separation (PLANNED, not realised)

⚠️ The `ai-gitops` repo described below was the *intended* design but **was never created**. In reality this one repo holds both the chart logic AND (under `environments/`, ADR-0018) the per-env overrides; the root `ai-apps-v2` Application is applied manually. Treat the table as design intent, not current state.

| | `ai-helm` (this repo) | `ai-gitops` (planned, absent) |
|---|---|---|
| Holds | Helm charts + `environments/` overlays + `charts/apps` root chart | (would hold) ArgoCD root Application + per-env overrides |
| Image tags | Default in `charts/<x>/values.yaml` (not overridden — ADR-0013) | — |

**ADR-0010** proposed automated image-updater write-back to `ai-gitops`; **ADR-0013** deferred it (and `ai-gitops` was never stood up). See those for the reasoning.

## `targetRevision`: deploy branch now → release tag next, **never `main`**

The current deployment runs from the branch **`claude/magical-bohr-390242`**, not `main`. The earlier "flip back to `main` on PR merge" plan is **retired** — `main` is never a deploy target. After this deployment settles, every self-referencing `targetRevision` (in `charts/apps/values.yaml` — `argocd.selfTargetRevision` + the per-app self-Source revisions — and the orchestrator children in `charts/ai-models/values.yaml` + `charts/librechart/values.yaml`) moves to a **release tag** (tag-based deploys only). The canonical note lives at `argocd.selfTargetRevision` in `charts/apps/values.yaml`. (`HEAD` revisions that point at *other* repos are unaffected.)

## ArgoCD destinations: two-tier — control objects in-cluster, workloads home-remote (ADR-0017)

**Two distinct "where"s.** ArgoCD `Application` / `ApplicationSet` CRs (control objects) must live on the cluster ArgoCD runs in — **in-cluster**, `argocd` namespace — or the controllers never watch them. The **workloads** those Applications deploy go to the registered cluster **`home-remote`**.

- **Workloads → `home-remote`.** Driven by `argocd.destination` (`name` / `server` / `allowInCluster`) in `charts/{apps,ai-models,librechart}/values.yaml`. Never use ArgoCD's built-in in-cluster handle (`name: in-cluster` / `server: https://kubernetes.default.svc`) for a workload — even if it resolves to the same physical cluster, it's a different ArgoCD destination. The helper `<chart>.argocd.destinationClusterRef` (each chart's `templates/_helpers.tpl`) **hard-fails the render** if a workload destination resolves to the in-cluster handle unless `allowInCluster: true`.
- **Control objects → local cluster / argocd.** In `charts/apps`, an app whose deployed content is itself a control object (an orchestrator emitting an ApplicationSet — `models`→`charts/ai-models`, `librechat`→`charts/librechart`) sets **`controlPlane: true`** on its entry. The template then targets `argocd.inClusterServer` (**`server: https://kubernetes.default.svc`** — the canonical local-cluster ref, used instead of the `name: in-cluster` handle which depends on that registration existing) / `argocd.controlPlaneNamespace` (`argocd`) and bypasses the guard. The orchestrators' ApplicationSet `template.spec.destination` (the **child** Applications) stays `home-remote`.
- **The root `ai-apps-v2` Application** (applied manually on the ArgoCD cluster — there is no `ai-gitops`) deploys `charts/apps` and **must itself target in-cluster/argocd** so the generated Application CRs land where the controller watches.
- **`homeCluster: true` — the ONE sanctioned ADR-0017 exception (ADR-0022).** A *workload* (not a control object) that must run on the cluster ArgoCD itself runs on — today only `model-serving` (the self-hosted GPU model: KServe/vLLM/LMCache needs the home GPU). It targets `argocd.inClusterServer` but keeps its own workload namespace (unlike `controlPlane`, which forces `argocd`), and the destination guard is called with `allowInCluster: true`. Don't add more `homeCluster` apps without an ADR — the default for every workload is still `home-remote`.

Don't re-hardcode a cluster name in the templates (the old `lke560142-ctx` magic string is gone). The render-time guard is complemented out-of-band by the `ai` AppProject's `destinations:` allowlist. See ADR-0017.

**Project invariant: every Application/ApplicationSet from this repo lives in the `ai` AppProject.** `charts/apps` hardcodes `project: ai` (not a per-app value — so an app entry can't drift); the four orchestrators (`ai-models`, `librechart`, `coder`, `observability`) set their children to `argocd.project` (= `ai`). There is intentionally **no per-app `project` override**. Verified live: all repo-sourced apps (flat + orchestrator children, old `ai-*` + new `aii-*`) are in `ai`. If you add an app, it inherits `ai` automatically — don't introduce a project knob.

## Hetzner cluster realities & recurring gotchas (2026 cutover)

Operational narrative + live verification: **`docs/2026-hetzner-cutover.md`** (read it before debugging the live cluster). The high-impact facts:

- **Two clusters, two kubeconfigs.** ArgoCD itself runs on a **separate** cluster — context **`admin@homeos`** (Talos, in `~/.kube/config`); all `Application`/`ApplicationSet` CRs live there in ns `argocd` (`kubectl --context admin@homeos -n argocd get applications`; trigger syncs via `argocd.argoproj.io/refresh=hard` or patching `.operation`). **Workloads** run on Hetzner k3s = `home-remote` — inspect with `KUBECONFIG=/Users/selast/dev/personal/hetzner-k8s/kubeconfig kubectl …`. The Hetzner kubeconfig has NO argo CRDs.
- **⚠️ `ai-*` vs `aii-*` = two DIFFERENT workload clusters, not a same-cluster collision.** Both app generations live on the same ArgoCD (`admin@homeos`) but deploy to different destinations: root **`ai-apps` @ HEAD → the other (pre-Hetzner) cluster** (the `ai-*` apps); root **`ai-apps-v2` → Hetzner `home-remote`** (the `aii-*` apps). They don't interact. **Only ever act on `aii-*` (Hetzner). NEVER touch `ai-*`** — a delete/sync hits the OTHER cluster (and the self-healing `ai-apps` root re-creates it anyway). Decommissioning the old `ai-*` gen is the maintainer's own exercise on that cluster.
- **CNI is Cilium + a default-deny-egress baseline.** Each app namespace (`apps`/`data`/`observability`/`platform`) carries a manual `allow-dns` NetworkPolicy (DNS-to-kube-system only, **not** ArgoCD-managed; defined in `hetzner-k8s`), so every pod is egress-deny-by-default. Any pod reaching the **API server** (operators: grafana-operator, kube-state-metrics) or **external object storage** (mimir/loki/tempo) crashloops until it gets an additive allow. ⚠️ A plain k8s `NetworkPolicy` `ipBlock` does **NOT** match on Cilium (node IPs carry `remote-node`/`host` identity). Use a **`CiliumNetworkPolicy`** with `toEntities: [kube-apiserver]` (API) or `toFQDNs: "*.your-objectstorage.com"` (S3), shipped via the app's deps overlay — see `environments/prod/deps/{grafana-operator,kube-state-metrics,observability-secrets}/`. Classic symptom: pod hangs ~32s then a 0-`initialDelay` liveness probe kills it → looks like a silent exit-2 CrashLoop. (`converse` has no baseline → its pods egress freely.)
- **Object storage = Hetzner Object Storage**, NOT the old `s3.ssegning.me`. Endpoint `nbg1.your-objectstorage.com`, shared bucket **`ssegning-k8s-state`** (Keycloak CNPG backups + mimir/loki/tempo + LibreChat, each in its own folder/prefix). Creds in `ssegning-aws` at key `prod/meta/test-app`, props `s3_backup_cnpg_client_id` / `s3_backup_cnpg_secret`; region `us-east-1` works (Ceph-RGW). mimir `storage_prefix` is **alphanumeric-only** (no `/`) → folders like `mimirblocks`.
- **Hetzner LB targets WORKERS ONLY.** The 3 control-plane nodes are labelled `node.kubernetes.io/exclude-from-external-load-balancers` (durable now in `hetzner-k8s` `install-platform.sh`). LB Services need `load-balancer.hetzner.cloud/use-private-ip: "true"` (cp-1 has a stale providerID and is an unusable server-ref target). core-gateway's data-plane LB is at `46.225.38.138`.
- **nginx static-serve charts** (`librechat-opencode-wellknown`, `ai-models-info`): their custom `default.conf` MUST set `root /usr/share/nginx/html;` or `try_files` 404s. Content is a subPath-mounted ConfigMap → a config change needs the **pods deleted** to remount (a CM edit alone doesn't reload nginx, and `kubectl rollout restart` is reverted by ArgoCD selfHeal).
- **Restart-ordering trap:** the `ai-gateway-controller` mutating webhook is fail-closed and gates ALL `envoy-gateway-system` pod creation — after a cluster restart, anything stuck on `FailedCreate: no endpoints available for ... ai-gateway-controller` recovers by deleting the stuck ReplicaSet once the controller is up.

## Pod Security Standards per namespace (cluster-portability knob)

k3s on Hetzner enforces the `baseline` Pod Security Standard cluster-wide, which forbids `hostPath` / host networking. The observability collectors need them (Alloy tails `/var/log` via a hostPath; node-exporter mounts host `/proc`,`/sys`,`/`), so their namespace must be `privileged`. Mechanism: an app-renderer injects `syncPolicy.managedNamespaceMetadata.labels.pod-security.kubernetes.io/enforce` for the relevant namespace, consistently across every app in it (no metadata contention). Two carriers: `charts/apps` has a declarative map **`global.namespacePodSecurity`** (`{ ns: level }`, empty today); the **`observability` orchestrator** carries **`podSecurityEnforce: privileged`** applied to all its children (since the observability stack moved there — ADR-0020). Control-plane apps (argocd ns) are never elevated.

**This is the per-cluster-kind knob:** a cluster with no Pod Security admission can ignore it (label is harmless); a `restricted`-default cluster still lists the namespaces needing `privileged`; per-env differences override the whole map via a `$values` multi-source (ADR-0018 Source C). A namespace not listed gets no PSS label (cluster default applies).

## Sync waves

Lower waves sync first:

- `-2`: Storage backends (Mimir, Loki, Tempo, kube-state-metrics, node-exporter)
- `-1`: Operators + ESO + cert-manager + grafana-operator + Alloy (collector)
- `0`: Workloads (LibreChat, AI Gateway, per-model apps)
- `1`: Content (dashboards, opencode-wellknown)
- `2+`: Per-app post-sync work

The infrastructure → storage → collection → visualisation order is load-bearing. `MONITORING_FIX.md` is the postmortem of what happens when you violate it.

## Auth headers contract (`x-oidc-*`)

ADR-0011 defines the canonical header set Authorino injects after JWT verification. Use these names downstream:

| Header | Loki label? | Source |
|---|---|---|
| `x-oidc-user-id` | yes (`user_id`) | `auth.identity.sub` |
| `x-oidc-azp` | yes (`azp`) | `auth.identity.azp` |
| `x-oidc-user-name`, `x-oidc-iss`, `x-oidc-roles-realm`, `x-oidc-resource-access`, `x-oidc-scope`, `x-oidc-jti`, `x-oidc-email`, `x-oidc-name` | no — body only | JWT claims |

Don't reintroduce the placeholder `x-cd-*` prefix or invent new headers without an ADR. The `x-oidc-*` set survives the OPA removal; alongside it, Authorino now also stamps the **rate-limit descriptors** `x-account-id` / `x-org-id` / `x-billing-plan` (ADR-0021) — see below. The old OPA-derived headers (`x-project-id`, `x-account-id`-as-`LIBRECHAT`, `x-api-key-id`, `x-api-key-status`) were removed.

## Gateway authz + rate limiting (ADR-0021) — OPA REMOVED, Keycloak JWT is the boundary

⚠️ The old OPA path is **gone** (2026-06-04). The `lightbridge-validation` HTTP
metadata source + the `enforce-valid-key` authorization step were **deleted** from
the AuthConfig (`security-policies.authConfigs.main` in `charts/apps/values.yaml`).
A valid **Keycloak JWT = "you're in our system, you may use the gateway."** OPA is
reserved for *future burst control* only (not wired). So: ADR-0003 (skip-OPA-for-SA)
and the OPA-derived response headers (`x-project-id`, `x-api-key-id`, the `llm_*`
dynamicMetadata) are historical — don't reintroduce them without a new ADR. The
`serviceAccountClients` allowlist + `_skipForServiceAccounts` markers are now inert
but kept for if OPA burst-control returns. (The missing `lightbridge-opa-auth`
Secret — pruned with the `secrets` app — is what caused the 404 outage that
prompted the removal; see `docs/2026-hetzner-cutover.md`.)

**Read [ADR-0021](docs/adr/0021-burst-budget-billing-and-dual-plane-authconfigs.md) before touching auth or rate limiting.** The shape now:

- **Dual-plane, AuthConfig-per-host** (one SecurityPolicy + one Authorino, indexed by Host):
  - **External** — `api.ai-v2.camer.digital` (public LB, ACME TLS): humans (opencode) + remote SAs. Full Keycloak JWT. Descriptors via CEL with defaults so `billing_plan`/`organization` claims are **optional** (`→ free` / `→ sub`).
  - **Internal** — `core-gateway-internal.envoy-gateway-system.svc.cluster.local` (ClusterIP only, `api-internal` listener, `self-signed-ca` TLS): in-cluster services. Accepts **EITHER** a k8s SA token (`kubernetesTokenReview`, one-time jobs) **OR** a static `apiKey` (labeled Secret `kuadrant.io/apikey-for=internal-gateway`, long-running services like LibreChat).
- **Per-user attribution:** a long-running service (LibreChat) authenticates as itself but **forwards the end-user's Keycloak sub** (`X-LibreChat-User`); the internal AuthConfig's CEL prefers it → per-user `x-account-id`/budget. Trust = internal plane is first-party-only + Authorino overwrites the descriptors.
- **Rate limiting** = per-model `BackendTrafficPolicy` (`charts/ai-model`) keyed on `x-account-id` (burst) + `x-org-id` (monthly µ$ budget) + `x-billing-plan` (tier: free/pro/service/internal). Tiers in `charts/ai-models/values.yaml` `rateLimitBudgeting.plans`. Static via Helm (the AIEG CRD), no dynamic OPA.

## Python tooling (`tools/dashboards/`)

Per ADR-0008:

- **`uv`** is the only resolver/runner. Not `pip`, not `poetry`.
- **`ruff`** for lint + format. Not `black`, not `isort`, not `flake8`.
- **Python 3.12+**, PEP 621 `pyproject.toml`, commit `uv.lock`.
- SDK: `grafana-foundation-sdk` (Grafana Labs' official multi-language SDK, NOT `grafanalib`).

## Commit style

Conventional commits with a substantive body that explains **why** (the diff already shows what). Link the ADR when implementing one: `(ADR-NNNN)`. AI-assisted commits get the trailer:

```
Co-Authored-By: Claude Opus <version> (1M context) <noreply@anthropic.com>
```

(use the running model version, e.g. `Opus 4.8`)

See recent `git log` for the established length and style — bodies of 20–60 lines are common for non-trivial changes.

## Local shell convention

Default shell on the maintainer's laptop is **zsh** (not bash). For shell commands that depend on shell features, prefer POSIX-portable; otherwise note zsh assumptions explicitly. CI workflows use GitHub Actions' implicit `bash` — that's intentional, don't change it (the user's "use zsh locally" preference is local-only).

## Tool quirks to remember

- **Edit tool** requires Read first when the target file already exists (Write also requires Read first for overwrites). Failure mode: `File has not been read yet`. Mitigation: Read with a small `limit:` if the file is large.
- **`gh` CLI** sometimes needs `zsh -i -c '...'` to pick up `GITHUB_TOKEN` from interactive profile. The harness's Bash tool runs zsh but non-interactively.
- **`helm template` warnings** about `~/.kube/config` group/world readability are noise — ignore.
- **`helm lint`** WARNING-level output ≠ failure. Look for `1 chart(s) failed`.
- **bjw-template-only charts fail `helm lint --strict`** with `[WARNING] templates/: directory not found` → `1 chart(s) failed`. This is expected: charts like `mcpo`/`lmcache` carry no own `templates/` dir — every manifest comes from the `bjw-template` subchart. **It's fine for us** — non-strict `helm lint` passes (`0 chart(s) failed`) and the real gate, `helm template … --dry-run`, renders cleanly. Don't add an empty `templates/` dir to silence it; judge these charts by render + non-strict lint.
- **The `.opencode/README.md`** is stale (refers to an unrelated "Azamra monorepo"). Ignore it. The canonical agent/CI rules live in `.github/workflows/opencode.yml`.

## `.well-known/opencode` is NOT OIDC discovery

If you're touching `charts/librechat-opencode-wellknown/`, read ADR-0014 first. The endpoint is opencode-proprietary; the JSON has an `auth.command` + `config` shape. The `config.plugin` array triggers opencode's auto-install (bun-install at startup, cached under `~/.cache/opencode/node_modules/`). End users only run `opencode auth login <url>` — no manual install. Sources: `packages/opencode/src/cli/cmd/providers.ts` + `config/config.ts` in the opencode repo.

## Where the cluster's actual state lives that this repo doesn't track

- **Secrets + ESO** — the External Secrets Operator (controller + CRDs) is **installed externally**, not by this repo (it runs in the `external-secrets` namespace, Helm-managed). The `ClusterSecretStore` is `ssegning-aws` (cluster-scoped, external). This repo now **owns the ExternalSecret CRs in-chart** (ai-models-backends, librechat-app, observability-secrets, + `environments/<env>/deps/*` overlays), all referencing `ssegning-aws` — the old wholesale `secrets` Application from `ai-ops-secrets.git` was **removed (2026-06-04)**. App secrets pull from key `ai/camer/digital/prod/env`, platform secrets from `prod/meta/test-app`. Don't re-add an ESO operator or a ClusterSecretStore chart here (the old Vault `bootstrap-secrets` store config was removed — it was never the store actually used).
- **Keycloak realm clients/scopes/groups** — `charts/keycloak-baseline/values.yaml` defines them; keycloak-config-cli applies. Client secrets come from ESO at sync time.
- **Backups** — `charts/*-backup/` define the CronJobs; the S3 buckets + retention policies are out-of-band.
- **ArgoCD root Application** (`ai-apps-v2`) — applied **manually** on the ArgoCD cluster (no `ai-gitops` repo). The chart `charts/apps/` in this repo is what it points at.
- **Redis** — deployed by the `home-os` repo (`charts/home-apps/redis-ha`) as `redis-ha-redis` in the `redis-system` namespace. This repo only *consumes* it (LibreChat, LiteLLM proxy, Envoy rate-limit point at `redis-ha-redis.redis-system.svc.cluster.local:6379`). Don't re-add a redis chart here. **Auth:** redis-ha requires a password (remote ref `prod/meta/test-app` / `redis_password` in the `ssegning-aws` ClusterSecretStore). Consumers read it from a local Secret `redis-ha-redis-auth` (key `redis-password`) — LibreChat via `REDIS_PASSWORD`, LiteLLM via `REDIS_PASSWORD` (split `REDIS_HOST`/`REDIS_PORT`), Envoy ratelimit via the `REDIS_AUTH` env injected through the `rateLimitDeployment.patch`. That Secret must exist in **each consumer namespace** (`converse`, `envoy-gateway-system`) via its own ExternalSecret — the repo references it by name only (secrets are provisioned externally; same as every other secret here). **TLS:** redis-ha is **TLS-ONLY** (`redis.conf`: `port 0` / `tls-port 6379`), server cert from the internal `self-signed-ca` ClusterIssuer ("Home SSegning Root CA"), `tls-auth-clients no` (clients need no client cert, only to trust that CA). So every consumer must connect over TLS **and** trust the internal CA — a plaintext client gets `connection reset by peer`. The Envoy ratelimit does this via `REDIS_TLS=true` + `REDIS_TLS_CACERT` pointing at a cert-manager `Certificate` (issued from `self-signed-ca`, `ca.crt` only) mounted from the `eg` umbrella overlay. New consumers need the same.
- **Traefik** — the ingress controller + the `traefik` IngressClass are deployed externally (runs in the `traefik` namespace). This repo only sets `ingressClassName: traefik` / `className: traefik` on its Ingresses. Don't re-add a traefik chart here.
- **CloudNativePG** — the `cnpg` Postgres operator **and** the Barman Cloud backup plugin (`cnpg-barman-cloud`) are deployed externally (`cnpg-system`; CRDs `postgresql.cnpg.io` + `barmancloud.cnpg.io`). This repo only defines CNPG `Cluster` CRs (e.g. `charts/coder-db`) that the external operator reconciles. Don't re-add a cnpg or plugin-barman-cloud chart here.
- **OpenTelemetry Operator** — installed externally (`opentelemetry-system`; CRDs `opentelemetry.io`). This repo only defines `OpenTelemetryCollector` CRs (`charts/core-gateway`: the `-traces` collector → Alloy → Tempo) that the external operator reconciles. Don't re-add an otel-operator chart here. (The `-usage` collector was removed — usage/billing is handled via the Envoy AI Gateway + OAuth2 path; Envoy access logs go straight to Alloy → Loki for ADR-0005 per-user observability.)
- **cert-manager** — controller (in `kube-system`, `--cluster-resource-namespace=kube-system`), CRDs, **and** the shared cluster-scoped ClusterIssuers (`cert-home-cert-http`, `self-signed-ca`, `cert-cloudflare`) are deployed by `home-os` (`charts/cert`, apps `cert` + `cert-remote`). home-os has **`config.enableGatewayAPI: true`** so cert-manager solves ACME HTTP-01 via `gatewayHTTPRoute` + honours the `cert-manager.io/cluster-issuer` gateway-shim. This repo only references issuers via annotations. ⚠️ The `cert-home-cert-envoy` issuer is **RETIRED** — `api.ai-v2.camer.digital` TLS now comes from an **in-chart ns ACME `Issuer` + HTTP-01 `gatewayHTTPRoute`** solver (`charts/core-gateway`, `gateway.acmeHttp01.enabled`), no DNS token. `cert-cloudflare` DNS-01 needs a `cloudflare-secret` (Cloudflare API token) in kube-system that is currently **missing** — only matters if you want DNS-01/wildcards. Don't re-add a cert chart here.

## When you finish substantive work

- Update `docs/README.md` index if you added a doc.
- Update `docs/adr/README.md` index if you added/superseded an ADR.
- If you renamed/restructured charts, check `charts/apps/values.yaml` doesn't reference a deleted path.
- `helm template <touched chart>` is the fastest pre-commit smoke test.
- For PR work: tasks are tracked in the harness; mark them as you go.
