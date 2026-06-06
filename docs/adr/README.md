# Architecture Decision Records

This directory captures the **why** behind every meaningful architectural
choice in this repo. Implementation details (the **how**) live in the
broader `docs/` tree; ADRs link to them.

## What is an ADR

A short, dated record of a single decision: the context it was made in, the
options considered, what was chosen, and the consequences (good and bad). The
format is [Michael Nygard's original](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).

ADRs are **immutable once accepted**. To change a decision, write a new ADR
that supersedes the old one — never edit history. Reading the chain shows
how thinking evolved.

## Index

| # | Title | Status | Date | Supersedes |
|---|---|---|---|---|
| [0001](./0001-record-architecture-decisions.md) | Record architecture decisions in this repo | Accepted | 2026-05-24 | — |
| [0002](./0002-replace-phoenix-with-tempo.md) | Replace Arize Phoenix with Grafana Tempo for LLM tracing | Accepted | 2026-05-24 | — |
| [0003](./0003-skip-opa-for-service-accounts.md) | Skip OPA / external metadata for service-account tokens via `azp` allowlist | Superseded by [0021](./0021-burst-budget-billing-and-dual-plane-authconfigs.md) | 2026-05-24 | — |
| [0004](./0004-grafana-operator-external-mode.md) | Adopt grafana-operator in external mode for dashboards-as-code | Accepted | 2026-05-24 | — |
| [0005](./0005-per-user-attribution-via-authorino-headers.md) | Propagate per-user identity via Authorino response headers → Loki labels | Accepted | 2026-05-24 | — |
| [0006](./0006-multi-source-applicationset.md) | Migrate charts/apps to a multi-source ApplicationSet (List generator, no-dup) | Superseded by [0018](./0018-umbrella-apps-and-env-overlays.md) | 2026-05-24 | — |
| [0007](./0007-kc-token-go-cli.md) | Build `kc-token` as a single static Go binary + GH composite action | Superseded by [0009](./0009-ai-in-ci-via-keycloak-token-exchange.md) | 2026-05-24 | — |
| [0008](./0008-python-dashboard-generation.md) | Generate Grafana dashboards from Python | Accepted | 2026-05-24 | — |
| [0009](./0009-ai-in-ci-via-keycloak-token-exchange.md) | AI in CI via Keycloak OIDC token exchange (Python step, shared SA, fork-deny) | Accepted | 2026-05-24 | [0007](./0007-kc-token-go-cli.md) |
| [0010](./0010-argocd-image-updater-writeback-to-ai-gitops.md) | argocd-image-updater with git write-back to `ai-gitops` (PR + auto-merge, GitHub App auth, once per Application) | Superseded by [0013](./0013-defer-image-updater-writeback.md) | 2026-05-24 | — |
| [0011](./0011-oidc-downstream-headers.md) | Canonical `x-oidc-*` downstream header contract (supplements ADR-0005) | Accepted | 2026-05-24 | — |
| [0012](./0012-split-ai-models-applicationset.md) | Split `charts/ai-models` into 3 sub-charts + ApplicationSet (1 backends App + N per-model Apps) | Accepted | 2026-05-24 | — |
| [0013](./0013-defer-image-updater-writeback.md) | Defer argocd-image-updater write-back; manual chart-version bumps stay (supersedes ADR-0010) | Accepted | 2026-05-24 | [0010](./0010-argocd-image-updater-writeback-to-ai-gitops.md) |
| [0014](./0014-split-librechart-and-opencode-wellknown.md) | Split `charts/librechart` into 3 leaf charts + add opencode `.well-known` endpoint | Accepted | 2026-05-24 | — |
| [0015](./0015-models-info-catalog-endpoint.md) | OpenRouter-shape `/v1/models/info` catalog endpoint for opencode (charts/ai-models-info) | Accepted | 2026-05-24 | — |
| [0016](./0016-fork-bjw-s-app-template-locally.md) | Fork bjw-s app-template + common locally as `bjw-template` / `bjw-common` (rewire 12 consumers) | Accepted | 2026-05-31 | — |
| [0017](./0017-home-remote-destination-invariant.md) | Workloads target the home-remote cluster, never in-cluster (render-time guard + `allowInCluster` escape hatch) | Accepted | 2026-05-31 | — |
| [0018](./0018-umbrella-apps-and-env-overlays.md) | Umbrella Applications (workload + app-scoped deps via kustomize) + per-env `environments/` overlays | Proposed | 2026-05-31 | [0006](./0006-multi-source-applicationset.md) |
| [0019](./0019-coder-app-of-apps-orchestrator.md) | Factor Coder into an App-of-Apps orchestrator (db + app as separate Applications) | Accepted | 2026-06-01 | — |
| [0020](./0020-observability-app-of-apps-orchestrator.md) | Factor the observability stack into an App-of-Apps orchestrator (+ a secrets app) | Accepted | 2026-06-01 | — |
| [0021](./0021-burst-budget-billing-and-dual-plane-authconfigs.md) | Burst control, budgeting & billing via dual-plane (internal/external) AuthConfigs | Proposed | 2026-06-04 | supersedes [0003](./0003-skip-opa-for-service-accounts.md) |
| [0022](./0022-self-hosted-gpu-model-federated-into-gateway.md) | Self-hosted GPU model (Qwen3-4B, KServe/Knative + vLLM + LMCache) federated into the gateway as a public-FQDN backend | Proposed | 2026-06-05 | exception to [0017](./0017-home-remote-destination-invariant.md) |
| [0023](./0023-grafana-stateless-no-pvc.md) | Grafana runs stateless (no PVC) — dashboards-as-code + provisioned datasources; persistence (if ever) goes to an external DB | Accepted | 2026-06-06 | builds on [0020](./0020-observability-app-of-apps-orchestrator.md) |
| [0024](./0024-right-size-observability-tiny.md) | Right-size observability to a tiny footprint (cluster + Envoy AI usage, no alerting) — fix Mimir PDB sync bug, drop dead components + Alertmanager | Accepted | 2026-06-06 | builds on [0020](./0020-observability-app-of-apps-orchestrator.md), [0005](./0005-per-user-attribution-via-authorino-headers.md) |
| [0025](./0025-linode-to-hetzner-cutover-domain-ai.md) | Cut over Linode → Hetzner; rename public domain `ai-v2.camer.digital` → `ai.camer.digital` (DNS-gated; Mongo data via script, Keycloak PG out of scope) | Proposed | 2026-06-06 | builds on [0017](./0017-home-remote-destination-invariant.md), [0018](./0018-umbrella-apps-and-env-overlays.md) |
| [0026](./0026-lightbridge-orchestrator-split.md) | Split lightbridge into an App-of-Apps orchestrator (secrets/db/app children); drop `opa` + `usage`, keep `api`+`mcp`; backups → Hetzner | Accepted | 2026-06-06 | builds on [0019](./0019-coder-app-of-apps-orchestrator.md); relates to [0021](./0021-burst-budget-billing-and-dual-plane-authconfigs.md), [0025](./0025-linode-to-hetzner-cutover-domain-ai.md) |

## Status legend

- **Proposed** — written, not yet implemented; can still change.
- **Accepted** — implemented or being implemented; treated as the current truth.
- **Deprecated** — no longer the recommended path, but still in effect (e.g. partly migrated away).
- **Superseded** — replaced by a later ADR; carry a `Supersedes` link and a `Superseded by` link in both records.

## Writing a new ADR

1. Copy [`template.md`](./template.md) to `NNNN-short-imperative-title.md` (next free number, zero-padded to 4).
2. Fill in Context, Decision, Consequences. Keep it short — 1–2 pages.
3. List Alternatives considered with WHY they were rejected (this is often the most valuable section).
4. Open the PR with `Status: Proposed`. Move to `Accepted` when the implementation lands (same PR or a follow-up).
5. Update the index above.

## Scope: what deserves an ADR

Write one when you make a choice that:
- Has consequences a future reader would want to understand without git-archeology.
- Locks in a contract (CRD version, naming convention, label key).
- Trades off something non-obvious (cost vs. ergonomics, lock-in vs. simplicity, type-safety vs. cardinality).

Don't write one for:
- "Use Helm" — read the repo, that's obvious.
- "Bump grafana to 11.2" — that's a release note.
- "Add a NetworkPolicy to mcpo" — that's a bug fix or a chart README change.
