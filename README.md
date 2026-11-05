# ai-helm

GitOps source-of-truth for the Camer Digital AI platform — Helm charts for
every workload that runs in the cluster, plus the ArgoCD `Application` /
`ApplicationSet` manifests that wire them together.

> **Companion repo (deployment state):** the private
> **`adorsys-gis/ai-helm-values`** holds what is *deployed* — workload values,
> image tags, the model catalog, the GPU-fleet (inference) catalog, provider
> prices, and the `environments/<env>/deps/` overlays. This repo holds *how to
> render*: chart logic, templates, and structural defaults. See
> [ADR-0055 / ADR-0056](docs/adr/) for the hard split. The old "ai-gitops" repo
> was never built under that name.
>
> **Rule of thumb:** a Helm `valuesObject`, a model, a price, an image tag, or a
> per-env CR belongs in `ai-helm-values`, not here.

## Layout

```
.
├── charts/                     62 Helm charts; each subdirectory is one chart.
│                               (full inventory + categories in the table below)
│
├── tools/
│   ├── dashboards/             Python dashboard generator (grafana-foundation-sdk,
│   │                            uv + ruff). ADR-0008.
│   ├── commit-lint.sh          Conventional-Commits message checker.
│   └── oci-chart-sbom.sh       OCI chart SBOM emitter.
│
├── tests/
│   ├── envoy-gateway-lua/      egctl x translate gate over every rendered Lua entry.
│   ├── budget-limiter/         Real-Envoy behaviour harness for budget-limiter.lua.
│   └── model-policy/           Real-Envoy behaviour harness for the model policy Lua.
│
├── e2e-tests/                  Playwright end-to-end suite (LibreChat OAuth2/MCP).
├── skills/                     LibreChat `SKILL.md` skills synced into the deployment.
│
├── docs/
│   ├── adr/                    Architecture Decision Records (ADR-0001 … ADR-0138;
│   │                           143 files incl. the index + template). Start here
│   │                           when asking "why?".
│   ├── README.md               Index of every doc.
│   └── …                       Subsystem docs, migration notes, runbooks.
│
├── .github/workflows/          CI: ten workflows (see "Verification" below).
└── .githooks/commit-msg        Conventional-Commits hook (git config core.hooksPath .githooks).
```

## Charts by category

The three render patterns: a **single chart** that renders directly; an
**ApplicationSet orchestrator + leaves** (one `ApplicationSet` fanning out to
sibling leaf charts, [ADR-0012](docs/adr/0012-split-ai-models-applicationset.md) /
[ADR-0014](docs/adr/0014-split-librechart-and-opencode-wellknown.md)); and an
**App-of-Apps orchestrator** that renders child `Application` CRs directly
([ADR-0019](docs/adr/0019-coder-app-of-apps-orchestrator.md) /
[ADR-0020](docs/adr/0020-observability-app-of-apps-orchestrator.md)) — used when
children are fixed and heterogeneous (local + upstream sources with large inline
values).

| Category | Charts | Pattern |
|---|---|---|
| **GitOps root & libraries** | `apps` — the umbrella; emits ArgoCD `Application` manifests for every workload, the entry point ArgoCD points at. `common` — Bitnami common library. `bjw-common` — local fork of bjw-s common ([ADR-0016](docs/adr/0016-fork-bjw-s-app-template-locally.md)). `bjw-template` — local fork of bjw-s app-template ([ADR-0016](docs/adr/0016-fork-bjw-s-app-template-locally.md)). | umbrella root; libraries |
| **AI gateway (data plane)** | `core-gateway` — Envoy AI Gateway (Gateway, EnvoyProxy, access-log, traces collector); the data plane. `kuadrant-policies` — Authorino AuthConfig + SecurityPolicy. `aisix` — Rust `/v1/responses`→`/v1/chat/completions` protocol adapter behind EAIG. `same-origin-proxy` — Caddy proxy serving external resources same-origin to dodge CORS. `z-image-proxy` — nginx/njs proxy injecting `response_format: b64_json` into image-generation POSTs. | single charts |
| **Model fleet / catalog** | `ai-models` — orchestrator (`ApplicationSet`) fanning out to backends + one Application per model ([ADR-0012](docs/adr/0012-split-ai-models-applicationset.md)). `ai-model` — leaf: one AIGatewayRoute + BackendTrafficPolicy per model. `ai-models-backends` — leaf: shared Backend + AIServiceBackend + security/TLS policies for upstream backends. `ai-models-info` — serves the OpenRouter-shape model catalog JSON for opencode. | orchestrator + leaves |
| **Self-hosted GPU inference** | `inference` — orchestrator (`ApplicationSet`, engine profiles) for every self-hosted model on the GPU fleet. `inference-server` — generic leaf for exactly one model on one GPU. `llm-d` — distributed inference middleware (prefix/KV/queue-aware router + vLLM). `lmcache` — KV-cache offload. `gpu-priority-classes` — cluster-scoped PriorityClasses arbitrating serving vs training ([ADR-0114](docs/adr/0114-gpu-priority-preemption-over-a-serving-clock.md)). *Legacy/disabled rollback surface ([ADR-0100](docs/adr/0100-image-generation-on-the-gpu-fleet.md)), superseded by `inference`+`inference-server` ([ADR-0094](docs/adr/0094-generic-model-serving-orchestrator.md)); all `enabled: false`:* `model-serving-qwen3-5`, `model-serving-qwen3-4b`, `model-serving-qwen3-8b`, `model-serving-qwen25-3b-awq`, `model-serving-ministral-3b`, `model-serving-qwen2-vl-2b`, `model-serving-deepseek-r1-1-5b`, `model-deployment`. | orchestrator + leaves; legacy singles |
| **LibreChat / chat plane** | `librechart` — orchestrator (`ApplicationSet`) for LibreChat and adjacent components ([ADR-0014](docs/adr/0014-split-librechart-and-opencode-wellknown.md)). `librechat-app` — leaf: LibreChat + MongoDB. `librechat-search` — leaf: Meilisearch. `librechat-opencode-wellknown` — leaf: nginx serving the opencode `.well-known` JSON; MCP catalog / skills / per-agent tool injection governed by [ADR-0042](docs/adr/0042-opencode-wellknown-mcp-catalog.md), [ADR-0043](docs/adr/0043-one-skills-system-in-the-opencode-wellknown.md), [ADR-0048](docs/adr/0048-global-browser-plugin-and-per-agent-tool-injection.md), [ADR-0049](docs/adr/0049-source-claim-operator-cli-not-self-serve.md). `librechat-code-interpreter` — leaf: sandboxed code-execution (NsJail). | orchestrator + leaves |
| **MCP** | `mcps` — orchestrator (`ApplicationSet`) generating one child per enabled MCP. `mcp` — generic MCP-server leaf (external FQDN or self-hosted) rendered as an MCPRoute. `mcpo` — MCP-to-OpenAPI proxy. | orchestrator + leaves |
| **Auth / identity** | `keycloak-baseline` — Keycloak realm config (clients, scopes, groups, roles) via keycloak-config-cli. `lightbridge` — App-of-Apps orchestrator for the authz stack. `lightbridge-db` — leaf: CNPG Cluster + barman backup. `lightbridge-secrets` — leaf: ExternalSecrets. `lightbridge-code-intelligence` — GitHub-App code-review / repo-Q&A control plane + Neo4j. | App-of-Apps; single |
| **MLOps platform** | `lakefs` — App-of-Apps orchestrator for LakeFS (data-lake version control). `lakefs-proxy` — SSO shim giving LakeFS OSS a Keycloak login. `lakefs-secrets` — leaf: ExternalSecrets. `mlflow` — App-of-Apps orchestrator for MLflow (experiment tracking). `mlflow-secrets` — leaf: ExternalSecrets. `argo-workflows` — App-of-Apps orchestrator for Argo Workflows (pipeline orchestration). `argo-workflows-secrets` — leaf: ExternalSecrets. `mlops-db` — dedicated CNPG Cluster for the mlops namespace tenants. `webank-training` — governed Webank dataset-build / training WorkflowTemplates. | App-of-Apps; singles |
| **Workspaces / hub / storage UI** | `coder` — App-of-Apps orchestrator for the Coder platform ([ADR-0019](docs/adr/0019-coder-app-of-apps-orchestrator.md)). `coder-secrets` — leaf: ExternalSecrets. `homepage` — App-of-Apps orchestrator for the central-hub dashboard. `homepage-app` — leaf: Homepage itself (no ingress; behind oauth2-proxy). `homepage-secrets` — leaf: ExternalSecrets. `longhorn-auth` — App-of-Apps orchestrator: oauth2-proxy front door for the Longhorn UI. `longhorn-secrets` — leaf: ExternalSecrets. | App-of-Apps |
| **Observability** | `observability` — App-of-Apps orchestrator for the LGTM stack ([ADR-0020](docs/adr/0020-observability-app-of-apps-orchestrator.md)). `observability-dashboards` — Grafana operator CRs (folders, dashboards, datasources, alerting); dashboards/alerting/scoreboard governed by [ADR-0008](docs/adr/0008-python-dashboard-generation.md), [ADR-0058](docs/adr/0058-precompute-gateway-usage-metrics-to-mimir.md), [ADR-0059](docs/adr/0059-grafana-unified-alerting-to-discord.md), [ADR-0060](docs/adr/0060-gamified-app-scoreboard.md) ([ADR-0004](docs/adr/0004-grafana-operator-external-mode.md) is only the original external-mode decision). `provider-billing-exporter` — polls provider billing APIs → Mimir. `grafana-pdf-reporter` — headless-chromium for the Grafana dashboard-reporter plugin. | App-of-Apps; singles |
| **Secrets & backups** | per-app `*-secrets` leaves listed with their consumers above; plus `mongodb-backup` — automated Mongo backup to S3. `keycloak-backup` — automated Keycloak DB backup to S3. | singles |
| **Delivery** | `imageupdater` — `ImageUpdater` CRs activating the CRD-based argocd-image-updater ([ADR-0055](docs/adr/0055-oci-charts-and-image-updater-writeback-to-values-repo.md)). | single |

## The delivery model (continuous delivery, ADR-0055/0056)

A **merge to `main` is a live deploy** — immutability is deliberately abandoned:

- Charts **auto-semver-publish to `oci://ghcr.io/adorsys-gis/charts`** on merge;
  every app (and orchestrator child) floats its chart on a **semver range**.
- Image tags + per-env values are **written back to the private
  `ai-helm-values` repo by `argocd-image-updater`** (direct commit; ArgoCD reads
  them via each app's `$values` and `depsOverlay` sources).
- The root **`ai-apps-v2` Application is pinned in `home-os`** and **tracks
  `main`**.
- **Rollback is a `git revert` in `ai-helm-values`** (image tags / values) or a
  chart-version pin. There is **no immutable fleet snapshot**.

Runbook: [`docs/continuous-delivery.md`](docs/continuous-delivery.md).

## Verification

This repo is Helm + ArgoCD YAML — there is no application build. The
verification cycle **is** `helm template` plus the gates below; CT and any
application tests never build a binary here.

- **Primary check:** `helm lint` + `helm template --dry-run` per chart (CI:
  `.github/workflows/helm-lint.yaml`). Render-only **leaf** charts use `ci/*-values.yaml`
  fixtures instead of default values, signalled by the
  `ai-helm.adorsys-gis.github.io/lint-mode: ci-values` Chart.yaml annotation.
- **`tests/envoy-gateway-lua/`** — runs Envoy Gateway's own `egctl x translate`
  over every rendered Lua entry. This gate exists because a controller rejection
  rewrites every route to `directResponse: 500`.
- **`tests/budget-limiter/`** and **`tests/model-policy/`** — real-Envoy
  behaviour harnesses for the shipped Lua.
- **`tools/dashboards/`** — `uv run dashboards build|check`,
  `uv run ruff format --check .`, `uv run ruff check .`.
- **`tools/commit-lint.sh`** — Conventional-Commits checker, wired through
  `.githooks/commit-msg` (`git config core.hooksPath .githooks`).
- **`tools/oci-chart-sbom.sh`** — OCI chart SBOM generator.
- **`e2e-tests/`** — Playwright end-to-end suite (LibreChat OAuth2/MCP).
- **`skills/`** — LibreChat `SKILL.md` skills synced into the deployment.

CI runs **ten workflows** in `.github/workflows/`: `helm-lint.yaml`,
`dashboards-drift.yml`, `envoy-gateway-lua.yml`, `commit-lint.yml`,
`security.yml`, `opencode.yml`, `governance.yml`, `release-helm-charts.yml`,
`publish-charts-oci.yml`, `release-please.yml`.

## Companion repos

- **`adorsys-gis/ai-helm-values`** (private) — deployment state: workload values,
  image tags, model + GPU-fleet catalogs, prices, `environments/<env>/deps/`.
- **`home-os`** — shared cluster infra this repo only *consumes* (cert-manager +
  ClusterIssuers, Traefik, CloudNativePG + Barman, ESO, redis-ha); also pins the
  root `ai-apps-v2` Application in `charts/cd`.
- **`hetzner-k8s`** — Terraform nodes/network/CNI/LB plus platform bootstrap.
- **`inference-ops`** — the team's inference knowledge base. VRAM budgeting,
  quantization, engine selection, benchmarks, and runbooks live THERE, not here.

## Parked: image-gen-mcp-rs

[`ADORSYS-GIS/image-gen-mcp-rs`](https://github.com/ADORSYS-GIS/image-gen-mcp-rs) (a
multi-provider image-generation MCP server) was evaluated for a sixth `charts/mcps`
route and deliberately **not** wired ([Story #991](https://github.com/ADORSYS-GIS/ai-helm/issues/991)):

- Image generation is already delivered by the self-hosted **Z-Image-Turbo** on the
  GPU fleet (LocalAI, ADR-0100/0102) via LibreChat's `IMAGE_GEN`.
- The server is a full major + 7 minors behind its core deps (`rust-mcp-sdk` 0.9→1.0.1,
  `async-openai` 0.34→0.41.3) — see [image-gen-mcp-rs#41](https://github.com/ADORSYS-GIS/image-gen-mcp-rs/issues/41).
- Its default providers are external SaaS (OpenAI / Gemini), not the platform's
  self-hosted path.

Revisit only if a consumer needs **agent-side** image generation **and** #41 lands.

## Where to start

| You want to… | Read this |
|---|---|
| Understand the system at a glance | [`docs/architecture.md`](docs/architecture.md) |
| See every architectural decision and why | [`docs/adr/README.md`](docs/adr/README.md) |
| Contribute a change | [`CONTRIBUTING.md`](CONTRIBUTING.md) |
| Audit chart pin currency vs upstream | [`docs/migrations/2026-currency-audit.md`](docs/migrations/2026-currency-audit.md) |
| Add a new dashboard | [`docs/playbooks/grafana-operator-and-dashboards.md`](docs/playbooks/grafana-operator-and-dashboards.md) + [`docs/playbooks/python-dashboard-generation.md`](docs/playbooks/python-dashboard-generation.md) |
| Understand the gateway auth flow | [`docs/patterns/per-user-observability.md`](docs/patterns/per-user-observability.md) + [`docs/adr/0011-oidc-downstream-headers.md`](docs/adr/0011-oidc-downstream-headers.md) |
| Use the AI gateway from a CLI | [`docs/integrations/opencode-well-known.md`](docs/integrations/opencode-well-known.md) |
| Operate the LGTM stack | [`docs/playbooks/observability-stack.md`](docs/playbooks/observability-stack.md) |
| Restore a backup | [`docs/cnpg-native-backup/`](docs/cnpg-native-backup/), [`docs/playbooks/mongodb-restoration-guide.md`](docs/playbooks/mongodb-restoration-guide.md) |

## The big picture in three sentences

1. **`charts/apps`** is the GitOps root; ArgoCD points at it. It emits one
   `Application` per workload — most pointing at other charts in this
   repo, some at upstream OCI/HTTPS chart repos.
2. **Three patterns** govern how charts are split: a single chart
   that renders directly (small charts), an **orchestrator chart that
   renders an `ApplicationSet` fanning out to leaf charts** (ai-models,
   librechart, mcps, inference — ADR-0012 / ADR-0014), or an **App-of-Apps
   orchestrator that renders child `Application` CRs** when children are fixed
   and heterogeneous (coder, observability, lightbridge, lakefs, mlflow,
   argo-workflows, homepage, longhorn-auth — ADR-0019 / ADR-0020).
3. **Observability is unified**: every signal (metrics, logs, traces)
   funnels through Alloy into Mimir/Loki/Tempo and surfaces in Grafana.
   The AI gateway emits structured access logs that carry per-user
   attribution (Authorino → headers → Loki labels — ADR-0005, ADR-0011)
   so dashboards segment by user / repo / CI run.

## Conventions

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the full set. Highlights:

- **uv + ruff** for any Python tooling we ship (ADR-0008).
- **ADR for any non-obvious architectural choice** (`docs/adr/`,
  Michael Nygard format). Immutable once accepted; supersede with a
  new ADR rather than editing.
- **Commit messages**: conventional-commits style (`chore`, `feat`,
  `fix`, `refactor`, `docs` scopes) — enforced by `tools/commit-lint.sh`.
- **Branch names**: feature work on `<topic>/<short-name>` or
  `<issue>-<topic>`; never push to `main` directly.
- **Helm chart pins**: explicit semver or commit SHA. No `:latest`,
  no `'*'` (audit findings; ADRs cover the few intentional exceptions).
- **Dashboard JSON** is generator-emitted (Python under
  `tools/dashboards/`). Hand-written JSON is allowed for one-offs but
  flagged in the per-dashboard README.
- **Values, tags, models, prices, per-env CRs** belong in `ai-helm-values`,
  not here — cut over **values-repo-first**.

## License

[MIT](LICENSE).

## Maintainer

@stephane-segning (Stephane Segning Lambou).
