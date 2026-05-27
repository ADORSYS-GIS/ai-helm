# ai-helm

GitOps source-of-truth for the Camer Digital AI platform — Helm charts for
every workload that runs in the cluster, plus the ArgoCD `Application` /
`ApplicationSet` manifests that wire them together.

> **Companion repo:** `ai-gitops` holds the cluster-/environment-specific
> overrides (image tag pins, per-env values overlays, ArgoCD secret-store
> wiring). This repo is the chart source; `ai-gitops` is the deployment
> state. See [ADR-0010 / ADR-0013](docs/adr/) for the rationale and the
> deferral of write-back automation between them.

## Layout

```
.
├── charts/                     Helm charts. Each subdirectory is one chart.
│   ├── apps/                   The "umbrella" — emits ArgoCD Application
│   │                           manifests for every other workload. The
│   │                           entry point ArgoCD points at.
│   ├── ai-models/              Orchestrator (ApplicationSet) for the AI
│   │                           gateway model fleet. ADR-0012.
│   ├── ai-model/               Leaf: one AIGatewayRoute + BackendTraffic-
│   │                           Policy per model.
│   ├── ai-models-backends/     Leaf: shared Backend + AIServiceBackend +
│   │                           security/TLS policies for the upstream
│   │                           backends (Fireworks, DeepInfra, Google AI Studio).
│   ├── librechart/             Orchestrator (ApplicationSet) for LibreChat
│   │                           and adjacent components. ADR-0014.
│   ├── librechat-app/          Leaf: LibreChat + MongoDB.
│   ├── librechat-search/       Leaf: Meilisearch.
│   ├── librechat-opencode-wellknown/
│   │                           Leaf: nginx serving the opencode .well-known
│   │                           JSON. ADR-0014.
│   ├── core-gateway/           Envoy AI Gateway (Gateway, EnvoyProxy,
│   │                           access-log, traces collector). The data
│   │                           plane.
│   ├── kuadrant-policies/      Authorino AuthConfig + SecurityPolicy
│   │                           (ADR-0003, ADR-0005, ADR-0011).
│   ├── observability-dashboards/
│   │                           Grafana operator CRs (Grafana external-mode,
│   │                           Folders, Dashboards) — ADR-0004.
│   ├── cert/                   cert-manager ClusterIssuers + the self-signed
│   │                           internal CA chain.
│   ├── external-secrets/       ESO ClusterSecretStore + RBAC.
│   ├── keycloak-baseline/      Keycloak realm config (clients, scopes,
│   │                           groups, roles) via keycloak-config-cli.
│   ├── coder-db/               CNPG cluster for Coder.
│   ├── common/                 Bitnami common library — helpers used by
│   │                           every first-party chart.
│   └── …                       (mcps, mcpo, lmcache, model-deployment,
│                                models-proxy, *-backup, …)
│
├── tools/
│   └── dashboards/             Python dashboard generator (grafana-foundation-sdk,
│                                uv + ruff). ADR-0008.
│
├── docs/
│   ├── adr/                    Architecture Decision Records (ADR-0001..0014).
│   │                           Start here when asking "why?".
│   ├── README.md               Index of every doc.
│   └── …                       Subsystem docs, migration notes, runbooks.
│
├── .github/workflows/          CI: helm-lint, dashboards-drift, opencode
│                                review, release-helm-charts, security scan.
└── .gitlab-ci.yml              Mirror of the opencode review for GitLab.
```

## Where to start

| You want to… | Read this |
|---|---|
| Understand the system at a glance | [`docs/architecture.md`](docs/architecture.md) |
| See every architectural decision and why | [`docs/adr/README.md`](docs/adr/README.md) |
| Contribute a change | [`CONTRIBUTING.md`](CONTRIBUTING.md) |
| Audit chart pin currency vs upstream | [`docs/2026-currency-audit.md`](docs/2026-currency-audit.md) |
| Add a new dashboard | [`docs/grafana-operator-and-dashboards.md`](docs/grafana-operator-and-dashboards.md) + [`docs/python-dashboard-generation.md`](docs/python-dashboard-generation.md) |
| Understand the gateway auth flow | [`docs/per-user-observability.md`](docs/per-user-observability.md) + [`docs/adr/0011-oidc-downstream-headers.md`](docs/adr/0011-oidc-downstream-headers.md) |
| Use the AI gateway from a CLI | [`docs/opencode-well-known.md`](docs/opencode-well-known.md) |
| Operate the LGTM stack | [`docs/observability-stack.md`](docs/observability-stack.md) |
| Restore a backup | [`docs/cnpg-native-backup/`](docs/cnpg-native-backup/), [`docs/mongodb-restoration-guide.md`](docs/mongodb-restoration-guide.md) |

## The big picture in three sentences

1. **`charts/apps`** is the GitOps root; ArgoCD points at it. It emits one
   `Application` per workload — most pointing at other charts in this
   repo, some at upstream OCI/HTTPS chart repos.
2. **Two patterns** govern how complex charts are split: a single chart
   that renders directly (small charts), or an **orchestrator chart that
   renders an `ApplicationSet` fanning out to leaf charts** (ai-models,
   librechart — ADR-0012 and ADR-0014).
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
  `fix`, `refactor`, `docs` scopes).
- **Branch names**: feature work on `<topic>/<short-name>` or
  `<issue>-<topic>`; never push to `main` directly.
- **Helm chart pins**: explicit semver or commit SHA. No `:latest`,
  no `'*'` (audit findings; ADRs cover the few intentional exceptions).
- **Dashboard JSON** is generator-emitted (Python under
  `tools/dashboards/`). Hand-written JSON is allowed for one-offs but
  flagged in the per-dashboard README.

## License

[MIT](LICENSE).

## Maintainer

@stephane-segning (Stephane Segning Lambou).
