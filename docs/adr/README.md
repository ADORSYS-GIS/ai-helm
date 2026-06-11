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
| [0019](./0019-coder-app-of-apps-orchestrator.md) | Factor Coder into an App-of-Apps orchestrator (db + app as separate Applications) | Superseded by [0027](./0027-mcps-orchestrator-split-and-coder-removal.md) | 2026-06-01 | — |
| [0020](./0020-observability-app-of-apps-orchestrator.md) | Factor the observability stack into an App-of-Apps orchestrator (+ a secrets app) | Accepted | 2026-06-01 | — |
| [0021](./0021-burst-budget-billing-and-dual-plane-authconfigs.md) | Burst control, budgeting & billing via dual-plane (internal/external) AuthConfigs | Proposed | 2026-06-04 | supersedes [0003](./0003-skip-opa-for-service-accounts.md) |
| [0022](./0022-self-hosted-gpu-model-federated-into-gateway.md) | Self-hosted GPU model (Qwen3-4B, KServe/Knative + vLLM + LMCache) federated into the gateway as a public-FQDN backend | Accepted | 2026-06-05 | exception to [0017](./0017-home-remote-destination-invariant.md) |
| [0023](./0023-grafana-stateless-no-pvc.md) | Grafana runs stateless (no PVC) — dashboards-as-code + provisioned datasources; persistence (if ever) goes to an external DB | Accepted | 2026-06-06 | builds on [0020](./0020-observability-app-of-apps-orchestrator.md) |
| [0024](./0024-right-size-observability-tiny.md) | Right-size observability to a tiny footprint (cluster + Envoy AI usage, no alerting) — fix Mimir PDB sync bug, drop dead components + Alertmanager | Accepted | 2026-06-06 | builds on [0020](./0020-observability-app-of-apps-orchestrator.md), [0005](./0005-per-user-attribution-via-authorino-headers.md) |
| [0025](./0025-linode-to-hetzner-cutover-domain-ai.md) | Cut over Linode → Hetzner; rename public domain `ai-v2.camer.digital` → `ai.camer.digital` (DNS-gated; Mongo data via script, Keycloak PG out of scope) | Accepted | 2026-06-06 | builds on [0017](./0017-home-remote-destination-invariant.md), [0018](./0018-umbrella-apps-and-env-overlays.md) |
| [0026](./0026-lightbridge-orchestrator-split.md) | Split lightbridge into an App-of-Apps orchestrator (secrets/db/app children); drop `opa` + `usage`, keep `api`+`mcp`; backups → Hetzner | Accepted | 2026-06-06 | builds on [0019](./0019-coder-app-of-apps-orchestrator.md); relates to [0021](./0021-burst-budget-billing-and-dual-plane-authconfigs.md), [0025](./0025-linode-to-hetzner-cutover-domain-ai.md) |
| [0027](./0027-mcps-orchestrator-split-and-coder-removal.md) | Split MCPs into per-MCP Applications (generic `charts/mcp` leaf + ApplicationSet, in-chart ExternalSecrets, + Refero); remove Coder | Accepted | 2026-06-06 | supersedes [0019](./0019-coder-app-of-apps-orchestrator.md); builds on [0012](./0012-split-ai-models-applicationset.md), [0017](./0017-home-remote-destination-invariant.md), [0018](./0018-umbrella-apps-and-env-overlays.md) |
| [0028](./0028-owned-hardware-model-pricing.md) | Price owned-hardware (self-hosted) models at cost-recovery, derived from a documented €/hour TCO (weighted strategy; replaces ADR-0022's flat $0) | Accepted | 2026-06-07 | amends [0022](./0022-self-hosted-gpu-model-federated-into-gateway.md) (pricing); builds on [0021](./0021-burst-budget-billing-and-dual-plane-authconfigs.md), [0012](./0012-split-ai-models-applicationset.md) |
| [0029](./0029-self-hosted-model-plain-deployment.md) | Serve the self-hosted model as a plain Deployment (drop KServe/Knative) — always-on + Recreate on the dedicated GPU (kills cold starts + rollout deadlock) | Accepted | 2026-06-07 | supersedes [0022](./0022-self-hosted-gpu-model-federated-into-gateway.md) (serving mode only); builds on [0017](./0017-home-remote-destination-invariant.md) |
| [0030](./0030-merge-model-and-proxy-into-one-statefulset-bjw.md) | Co-locate the model + Caddy auth-proxy in ONE StatefulSet (proxy → model over localhost), rendered via bjw-template | Accepted | 2026-06-07 | refines [0029](./0029-self-hosted-model-plain-deployment.md); builds on [0016](./0016-fork-bjw-s-app-template-locally.md) |
| [0031](./0031-tag-based-deploys.md) | Tag-based deploys (`release-YYYY.MM.DD`), never `main`: self-ref `targetRevision`s + root pin an immutable tag (self-consistent commit); external first-party sources pinned to SHAs; `tools/release.sh` automates it | Accepted | 2026-06-08 | retires the branch-deploy/flip-to-main plan; relates to [0010](./0010-argocd-image-updater-writeback-to-ai-gitops.md)/[0013](./0013-defer-image-updater-writeback.md) (ai-gitops absent); builds on [0017](./0017-home-remote-destination-invariant.md), [0018](./0018-umbrella-apps-and-env-overlays.md) |
| [0032](./0032-llama-cpp-engine-for-self-hosted-models.md) | llama.cpp (`llama-server`) as a 2nd self-hosted engine alongside vLLM: GGUF/Q4_K_M, native `--api-key` (no Caddy), `/v1`, `/health` probe — chosen for Qwen3.5-4B Q4 because vLLM's Qwen3.5 support is turbulent (`charts/model-serving-qwen3-5`, staged) | Accepted | 2026-06-08 | adds an engine to [0030](./0030-merge-model-and-proxy-into-one-statefulset-bjw.md)/[0029](./0029-self-hosted-model-plain-deployment.md); builds on [0022](./0022-self-hosted-gpu-model-federated-into-gateway.md), pricing [0028](./0028-owned-hardware-model-pricing.md) |
| [0033](./0033-relax-free-tier-burst-limits.md) | Relax free-tier burst rate limits (200 req/min, 200k tokens/min) and pro requests (400 req/min) — burst caps become backend guards, monthly budgets remain the spend backstop | Accepted | 2026-06-08 | amends [0021](./0021-burst-budget-billing-and-dual-plane-authconfigs.md) |
| [0034](./0034-restore-streaming-timeouts-and-extproc-headroom.md) | Restore streaming-stability fixes lost when the magical-bohr rewrite diverged: explicit 600s AIGatewayRoute + per-model upstream timeouts (cloud models were cut at the 60s/15s defaults), ExtProc CPU headroom, OTel `debug` removal — re-implemented values-driven | Accepted | 2026-06-09 | re-implements pre-cutover `20d8f4f` + the "faster envoy responses" series; builds on [0012](./0012-split-ai-models-applicationset.md), [0021](./0021-burst-budget-billing-and-dual-plane-authconfigs.md), [0022](./0022-self-hosted-gpu-model-federated-into-gateway.md) |
| [0035](./0035-per-person-monthly-budget-and-free-50.md) | Key the monthly spend budget on `x-account-id` (per-person) instead of `x-org-id` (shared org bucket) so colleagues don't contend for one pool; raise the free tier $30 → $50 | Accepted | 2026-06-09 | amends [0021](./0021-burst-budget-billing-and-dual-plane-authconfigs.md); relates to [0033](./0033-relax-free-tier-burst-limits.md) |
| [0036](./0036-remove-apprise-notification-path.md) | Remove the redundant Grafana apprise path (`grafana-apprise-adapter` + external-alertmanager override → Grafana native); keep a LEAN stateless `apprise-api` (drop the `apprise-channels` mount that hung it 0/1) solely as opencode-k8s-agent's `/notify` gateway — the agent has no built-in notifier | Accepted | 2026-06-09 | relates to [0020](./0020-observability-app-of-apps-orchestrator.md), [0024](./0024-right-size-observability-tiny.md) |
| [0037](./0037-opencode-agent-internal-sa-token.md) | opencode-k8s-agent auth → the INTERNAL plane via its own projected SA token (ADR-0021 one-time-job path): drops Keycloak/OAuth2 + the apiKey secret; internal `core-gateway-internal` endpoint + internal-CA trust like LibreChat; opencode.json static-bearer change via agent-repo PR | Accepted | 2026-06-09 | builds on [0021](./0021-burst-budget-billing-and-dual-plane-authconfigs.md), [0018](./0018-umbrella-apps-and-env-overlays.md); relates to [0036](./0036-remove-apprise-notification-path.md) |
| [0038](./0038-mcp-oauth-protected-resource-metadata.md) | MCP OAuth discovery (RFC 9728) via native AIEG `MCPRoute.securityPolicy.oauth`: gateway-served PRM + AS metadata + 401 `resource_metadata` challenge per `/mcp/*`; Envoy-native JWT replaces Authorino on MCP routes (x-oidc-* restored via claimToHeaders); plus a non-spec path-appended PRM alias via DirectResponse | Accepted | 2026-06-10 | builds on [0021](./0021-burst-budget-billing-and-dual-plane-authconfigs.md), [0027](./0027-mcps-orchestrator-split-and-coder-removal.md); relates to [0011](./0011-oidc-downstream-headers.md) |
| [0039](./0039-mcp-external-backend-tls-envoypatchpolicy.md) | Repair external MCP backend upstream TLS via `EnvoyPatchPolicy` (charts/core-gateway): AIEG stamps a `dummy.transport_socket` (empty SNI) on MCP backend clusters that `BackendTLSPolicy`/`Backend.spec.tls` never reach → external HTTPS handshake fails; patch injects a real TLS socket w/ SNI + system-CA. RSA upstreams only (firecrawl, refero); context7's ECDSA cert is BoringSSL-rejected → self-hosted instead | Superseded by [0040](./0040-external-mcps-via-caddy-normalizing-proxy.md) | 2026-06-10 | builds on [0038](./0038-mcp-oauth-protected-resource-metadata.md), [0027](./0027-mcps-orchestrator-split-and-coder-removal.md) |
| [0040](./0040-external-mcps-via-caddy-normalizing-proxy.md) | External hosted MCPs via per-MCP in-cluster **Caddy normalizing proxies** (`charts/mcp` `mode: proxiedExternal`): Caddy does the upstream TLS (Go TLS handles context7's ECDSA cert), injects the credential, and rewrites refero's mislabeled `text/event-stream`→`application/json` (AIEG #2218 workaround). Turns external MCPs into reliable in-cluster plain-HTTP backends; **removes** the ADR-0039 EnvoyPatchPolicy. Brings context7 back; off-the-shelf caddy image (no custom build) | Accepted | 2026-06-11 | supersedes [0039](./0039-mcp-external-backend-tls-envoypatchpolicy.md); builds on [0027](./0027-mcps-orchestrator-split-and-coder-removal.md), [0030](./0030-merge-model-and-proxy-into-one-statefulset-bjw.md) |

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
