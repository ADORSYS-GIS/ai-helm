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

## ai-helm ↔ ai-gitops separation

| | `ai-helm` (this repo) | `ai-gitops` (other repo) |
|---|---|---|
| Holds | Helm charts (logic, templates, sane defaults in `values.yaml`) | ArgoCD `Application` manifests + per-env overrides |
| Image tags | Default in `charts/<x>/values.yaml` | (Today: not overridden — see ADR-0013) |
| You can touch from this repo | All chart logic | Nothing |
| Cross-references via | `repoURL: https://github.com/ADORSYS-GIS/ai-helm` + `targetRevision` | n/a |

**ADR-0010** proposed automated image-updater write-back between them; **ADR-0013** deferred it. See those for the reasoning.

## `targetRevision: HEAD/main` while testing

During an active PR, all `targetRevision` fields in `charts/apps/values.yaml` that point at this repo (and the orchestrator children in `charts/ai-models/values.yaml` + `charts/librechart/values.yaml`) get flipped to the testing branch (e.g. `claude/<branch>`). **They must flip back to `main` (or `HEAD`) on PR merge.** TODO'd in comments in those values files. Don't forget this on merge.

## ArgoCD destinations: home-remote, never in-cluster (ADR-0017)

All generated Applications reference the target cluster by its **registered name `home-remote`** — the same name the GitOps entrypoint uses (the root `ai-apps-v2` Application in `ai-gitops` deploys `charts/apps` to `destination.name: home-remote`, namespace `argocd`). Never use ArgoCD's built-in in-cluster handle (`name: in-cluster` / `server: https://kubernetes.default.svc`) — even if it resolves to the same physical cluster, it's a different ArgoCD destination. The cluster identity is a single knob, `argocd.destination` (`name` / `server` / `allowInCluster`), in each of `charts/{apps,ai-models,librechart}/values.yaml`. A shared helper `<chart>.argocd.destinationClusterRef` (in each chart's `templates/_helpers.tpl`) **hard-fails the render** if a destination resolves to the in-cluster handle, unless `argocd.destination.allowInCluster: true` is set. So a bad destination breaks `helm template` / CI / ArgoCD's own render before anything syncs. Don't re-hardcode a cluster name in the templates (the old `lke560142-ctx` magic string is gone); change the value. The render-time guard is complemented (out-of-band, in `ai-gitops`) by the `ai` AppProject's `destinations:` allowlist. See ADR-0017.

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
- **cert-manager** — controller, CRDs, **and** the shared cluster-scoped ClusterIssuers (`cert-home-cert-http`, `self-signed-ca`, `cert-cloudflare`) are deployed by `home-os` (`charts/cert`, `cert-remote` Application). This repo only references the issuers via `cert-manager.io/cluster-issuer:` annotations. ⚠️ `cert-home-cert-envoy` (the Gateway-API ACME issuer `core-gateway` uses for `api.ai.camer.digital`) is referenced here but **not yet defined in home-os** — it must be added there. Don't re-add a cert chart here.

## When you finish substantive work

- Update `docs/README.md` index if you added a doc.
- Update `docs/adr/README.md` index if you added/superseded an ADR.
- If you renamed/restructured charts, check `charts/apps/values.yaml` doesn't reference a deleted path.
- `helm template <touched chart>` is the fastest pre-commit smoke test.
- For PR work: tasks are tracked in the harness; mark them as you go.
