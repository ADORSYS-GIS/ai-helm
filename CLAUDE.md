# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repo type

Helm charts + ArgoCD GitOps for the Camer Digital AI platform. **Not an application** — no build, no compile, no traditional test loop. The "verification cycle" is `helm template` (does it render?) + the relevant `helm lint` + CI's chart-render and security scans. Things deploy via ArgoCD reconciling these charts in the cluster.

> **Maintainer:** @stephane-segning. Use this handle in ADR `Deciders:` lines and any maintainer-attribution context. Don't substitute branch names.

> **Companion repo:** `ai-gitops` (separate) holds per-environment overrides and the ArgoCD root Application. This repo is the **chart source**, `ai-gitops` is the **deployment state**. Don't put image-tag overrides or env-specific values here.

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
```

There is no `npm`, no `pytest`, no `cargo`, no `go build` in this repo. The dashboards Python project at `tools/dashboards/` is the only code that runs; everything else is YAML rendered by Helm.

## The orchestrator-plus-leaves pattern (used for `ai-models` and `librechart`)

When a chart's components have different lifecycles (sync waves, rollback granularity, per-component ArgoCD UI surface), split it:

```
charts/<thing>/                  # orchestrator: emits ApplicationSet only
charts/<thing>-<componentA>/     # leaf: one Application worth of stuff
charts/<thing>-<componentB>/     # leaf
```

The orchestrator's `Chart.yaml` depends only on `common`. Its `templates/applicationset.yaml` emits ONE `ApplicationSet` whose List generator has one element per child. Children point at the sibling leaf charts via `path: charts/<thing>-<componentN>`.

See ADR-0012 (`ai-models`) and ADR-0014 (`librechart`) for the canonical examples + the rationale. **Don't reinvent this pattern** — copy from one of these when you need it again.

## Umbrella Applications + `environments/` overlays (ADR-0018)

Flat leaf apps in `charts/apps/values.yaml` use a multi-source **umbrella** so a workload and its app-scoped prerequisites sync as one Application:

- **Source A — workload**: the Helm chart (`path: charts/<x>` or an upstream `chart:`).
- **Source B — app-scoped deps**: a **kustomize** overlay at `path: environments/<env>/deps/<app>` emitting the ingress `Certificate` and any per-app image-pull / session `ExternalSecret`. Kustomize is confined to these plain CRs — **never kustomize-over-Helm** (that needs the controller-wide `--enable-helm` flag).
- **Source C — `ref: values`** (optional): a `$values` ref so Source A can pull a per-env values file when a *workload* knob actually diverges between environments.

Per-env knobs (`clusterIssuer`, `secretStore`, `ingressClass`, `storageClass`, `domainBase`) live in `environments/<env>/cluster.yaml` (source of truth) and are patched into the dep CRs by the `environments/<env>/deps/<app>/` kustomize overlay (base under `environments/base/deps/<app>/`). Today only `environments/prod/` exists (Hetzner); a second env is a drop-in sibling directory.

Ownership split: umbrellas own **app-scoped** secrets/certs (referencing `ssegning-aws` by name). **Platform/shared** secrets (S3, Keycloak, redis-auth) stay external in `ai-ops-secrets.git`. The store is never defined here.

**How to attach deps:** add one field to the app entry — `depsOverlay: environments/<env>/deps/<app>`. `applications.yaml` folds it in as Source B (pointing at this repo via `argocd.selfRepoURL` @ `argocd.selfTargetRevision`), keeping the workload's `source:` + `valuesObject` verbatim (no re-indenting big value blocks). Also drop the `cert-manager.io/cluster-issuer` annotation from that chart's ingress — the overlay `Certificate` now owns the TLS secret. Converted so far: `grafana`, `coder`, `lightbridge-backend`, `librechat-admin-panel`. Dep-less infra/backends stay single-source.

The umbrella needs **no ApplicationSet** — `applications.yaml` already passes `.sources` through. (The List/Matrix-generator conversion, old ADR-0006, is decoupled future work.) Orchestrators (`models`, `librechat`) are **not** wrapped — they're already ApplicationSets.

> ⚠️ The `applications.yaml` template's custom-`syncPolicy` branch previously omitted the `syncPolicy:` wrapper key (contents leaked into `destination:`), so ~13 apps that declared their own `syncPolicy` rendered with **no** `spec.syncPolicy` (manual sync, declared automation silently dropped). Fixed in the ADR-0018 work — those apps now get their declared `automated: {prune, selfHeal}`. Sanity-check sync behaviour on the live cluster after merge.

## ai-helm ↔ ai-gitops separation

| | `ai-helm` (this repo) | `ai-gitops` (other repo) |
|---|---|---|
| Holds | Helm charts (logic, templates, sane defaults in `values.yaml`) | ArgoCD `Application` manifests + per-env overrides |
| Image tags | Default in `charts/<x>/values.yaml` | (Today: not overridden — see ADR-0013) |
| You can touch from this repo | All chart logic | Nothing |
| Cross-references via | `repoURL: https://github.com/ADORSYS-GIS/ai-helm` + `targetRevision` | n/a |

**ADR-0010** proposed automated image-updater write-back between them; **ADR-0013** deferred it. See those for the reasoning.

## `targetRevision`: deploy branch now → release tag next, **never `main`**

The current deployment runs from the branch **`claude/magical-bohr-390242`**, not `main`. The earlier "flip back to `main` on PR merge" plan is **retired** — `main` is never a deploy target. After this deployment settles, every self-referencing `targetRevision` (in `charts/apps/values.yaml` — `argocd.selfTargetRevision` + the per-app self-Source revisions — and the orchestrator children in `charts/ai-models/values.yaml` + `charts/librechart/values.yaml`) moves to a **release tag** (tag-based deploys only). The canonical note lives at `argocd.selfTargetRevision` in `charts/apps/values.yaml`. (`HEAD` revisions that point at *other* repos are unaffected.)

## ArgoCD destinations: two-tier — control objects in-cluster, workloads home-remote (ADR-0017)

**Two distinct "where"s.** ArgoCD `Application` / `ApplicationSet` CRs (control objects) must live on the cluster ArgoCD runs in — **in-cluster**, `argocd` namespace — or the controllers never watch them. The **workloads** those Applications deploy go to the registered cluster **`home-remote`**.

- **Workloads → `home-remote`.** Driven by `argocd.destination` (`name` / `server` / `allowInCluster`) in `charts/{apps,ai-models,librechart}/values.yaml`. Never use ArgoCD's built-in in-cluster handle (`name: in-cluster` / `server: https://kubernetes.default.svc`) for a workload — even if it resolves to the same physical cluster, it's a different ArgoCD destination. The helper `<chart>.argocd.destinationClusterRef` (each chart's `templates/_helpers.tpl`) **hard-fails the render** if a workload destination resolves to the in-cluster handle unless `allowInCluster: true`.
- **Control objects → local cluster / argocd.** In `charts/apps`, an app whose deployed content is itself a control object (an orchestrator emitting an ApplicationSet — `models`→`charts/ai-models`, `librechat`→`charts/librechart`) sets **`controlPlane: true`** on its entry. The template then targets `argocd.inClusterServer` (**`server: https://kubernetes.default.svc`** — the canonical local-cluster ref, used instead of the `name: in-cluster` handle which depends on that registration existing) / `argocd.controlPlaneNamespace` (`argocd`) and bypasses the guard. The orchestrators' ApplicationSet `template.spec.destination` (the **child** Applications) stays `home-remote`.
- **The root `ai-apps-v2` Application** (in `ai-gitops`) deploys `charts/apps` and **must itself target in-cluster/argocd** so the generated Application CRs land where the controller watches. (External change — not in this repo.)

Don't re-hardcode a cluster name in the templates (the old `lke560142-ctx` magic string is gone). The render-time guard is complemented (out-of-band, in `ai-gitops`) by the `ai` AppProject's `destinations:` allowlist. See ADR-0017.

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

Don't reintroduce the placeholder `x-cd-*` prefix or invent new headers without an ADR.

## Service-account auth path (ADR-0003)

SA tokens (CI runners) skip the lightbridge-opa metadata + the dependent `enforce-valid-key` authorization step. The allowlist of SA `azp` values lives in `charts/apps/values.yaml` under `security-policies.authConfigs.main.serviceAccountClients`. The marker on individual steps is `_skipForServiceAccounts: true` — see `charts/kuadrant-policies/templates/_helpers.tpl`.

The `enforce-valid-key` step itself is currently **commented out** in `charts/apps/values.yaml` (per a maintainer commit on main). The SA-skip marker is preserved inside the comment so re-enabling is mechanical.

## Python tooling (`tools/dashboards/`)

Per ADR-0008:

- **`uv`** is the only resolver/runner. Not `pip`, not `poetry`.
- **`ruff`** for lint + format. Not `black`, not `isort`, not `flake8`.
- **Python 3.12+**, PEP 621 `pyproject.toml`, commit `uv.lock`.
- SDK: `grafana-foundation-sdk` (Grafana Labs' official multi-language SDK, NOT `grafanalib`).

## Commit style

Conventional commits with a substantive body that explains **why** (the diff already shows what). Link the ADR when implementing one: `(ADR-NNNN)`. AI-assisted commits get the trailer:

```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

See recent `git log` for the established length and style — bodies of 20–60 lines are common for non-trivial changes.

## Local shell convention

Default shell on the maintainer's laptop is **zsh** (not bash). For shell commands that depend on shell features, prefer POSIX-portable; otherwise note zsh assumptions explicitly. CI workflows use GitHub Actions' implicit `bash` — that's intentional, don't change it (the user's "use zsh locally" preference is local-only).

## Tool quirks to remember

- **Edit tool** requires Read first when the target file already exists (Write also requires Read first for overwrites). Failure mode: `File has not been read yet`. Mitigation: Read with a small `limit:` if the file is large.
- **`gh` CLI** sometimes needs `zsh -i -c '...'` to pick up `GITHUB_TOKEN` from interactive profile. The harness's Bash tool runs zsh but non-interactively.
- **`helm template` warnings** about `~/.kube/config` group/world readability are noise — ignore.
- **`helm lint`** WARNING-level output ≠ failure. Look for `1 chart(s) failed`.
- **The `.opencode/README.md`** is stale (refers to an unrelated "Azamra monorepo"). Ignore it. The canonical agent/CI rules live in `.github/workflows/opencode.yml`.

## `.well-known/opencode` is NOT OIDC discovery

If you're touching `charts/librechat-opencode-wellknown/`, read ADR-0014 first. The endpoint is opencode-proprietary; the JSON has an `auth.command` + `config` shape. The `config.plugin` array triggers opencode's auto-install (bun-install at startup, cached under `~/.cache/opencode/node_modules/`). End users only run `opencode auth login <url>` — no manual install. Sources: `packages/opencode/src/cli/cmd/providers.ts` + `config/config.ts` in the opencode repo.

## Where the cluster's actual state lives that this repo doesn't track

- **Secrets + ESO** — the External Secrets Operator (controller + CRDs) is **installed externally**, not by this repo (it runs in the `external-secrets` namespace, Helm-managed). The `ClusterSecretStore` is `ssegning-aws` (cluster-scoped, external). ExternalSecret CRs are sourced from `ai-ops-secrets.git` (the `secrets` Application) + other external sources; all reference `ssegning-aws`. This repo references Secret names only. Don't re-add an ESO operator or a ClusterSecretStore chart here (the old Vault `bootstrap-secrets` store config was removed — it was never the store actually used).
- **Keycloak realm clients/scopes/groups** — `charts/keycloak-baseline/values.yaml` defines them; keycloak-config-cli applies. Client secrets come from ESO at sync time.
- **Backups** — `charts/*-backup/` define the CronJobs; the S3 buckets + retention policies are out-of-band.
- **ArgoCD root Application** — in `ai-gitops`. The chart `charts/apps/` in this repo is what that root Application points at.
- **Redis** — deployed by the `home-os` repo (`charts/home-apps/redis-ha`) as `redis-ha-redis` in the `redis-system` namespace. This repo only *consumes* it (LibreChat, LiteLLM proxy, Envoy rate-limit point at `redis-ha-redis.redis-system.svc.cluster.local:6379`). Don't re-add a redis chart here. **Auth:** redis-ha requires a password (remote ref `prod/meta/test-app` / `redis_password` in the `ssegning-aws` ClusterSecretStore). Consumers read it from a local Secret `redis-ha-redis-auth` (key `redis-password`) — LibreChat via `REDIS_PASSWORD`, LiteLLM via `REDIS_PASSWORD` (split `REDIS_HOST`/`REDIS_PORT`), Envoy ratelimit via the `REDIS_AUTH` env injected through the `rateLimitDeployment.patch`. That Secret must exist in **each consumer namespace** (`converse`, `envoy-gateway-system`) via its own ExternalSecret — the repo references it by name only (secrets are provisioned externally; same as every other secret here).
- **Traefik** — the ingress controller + the `traefik` IngressClass are deployed externally (runs in the `traefik` namespace). This repo only sets `ingressClassName: traefik` / `className: traefik` on its Ingresses. Don't re-add a traefik chart here.
- **CloudNativePG** — the `cnpg` Postgres operator **and** the Barman Cloud backup plugin (`cnpg-barman-cloud`) are deployed externally (`cnpg-system`; CRDs `postgresql.cnpg.io` + `barmancloud.cnpg.io`). This repo only defines CNPG `Cluster` CRs (e.g. `charts/coder-db`) that the external operator reconciles. Don't re-add a cnpg or plugin-barman-cloud chart here.
- **OpenTelemetry Operator** — installed externally (`opentelemetry-system`; CRDs `opentelemetry.io`). This repo only defines `OpenTelemetryCollector` CRs (`charts/core-gateway`: the `-traces` collector → Alloy → Tempo) that the external operator reconciles. Don't re-add an otel-operator chart here. (The `-usage` collector was removed — usage/billing is handled via the Envoy AI Gateway + OAuth2 path; Envoy access logs go straight to Alloy → Loki for ADR-0005 per-user observability.)
- **cert-manager** — controller, CRDs, **and** the shared cluster-scoped ClusterIssuers (`cert-home-cert-http`, `self-signed-ca`, `cert-cloudflare`) are deployed by `home-os` (`charts/cert`, `cert-remote` Application). This repo only references the issuers via `cert-manager.io/cluster-issuer:` annotations. ⚠️ `cert-home-cert-envoy` (the Gateway-API ACME issuer `core-gateway` uses for `api.ai.camer.digital`) is referenced here but **not yet defined in home-os** — it must be added there. Don't re-add a cert chart here.

## When you finish substantive work

- Update `docs/README.md` index if you added a doc.
- Update `docs/adr/README.md` index if you added/superseded an ADR.
- If you renamed/restructured charts, check `charts/apps/values.yaml` doesn't reference a deleted path.
- `helm template <touched chart>` is the fastest pre-commit smoke test.
- For PR work: tasks are tracked in the harness; mark them as you go.
