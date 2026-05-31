# 2026 currency audit

**Date:** 2026-05-24
**Scope:** Helm chart pins, Kubernetes API versions, dashboard schema, project tooling
**Method:** Web research (release pages, official docs) + repo inspection. See "Sources" at the bottom.

## Snapshot

This repo lands at roughly **5/10** on the 2026-currency scale. Kubernetes-API
choices are mostly defensible (Gateway API v1, OTel CR `v1beta1`, AuthConfig
`v1beta3` are all current), but a large fraction of Helm chart pins are 6–12
months behind, and a few are on tracks that have moved or are being phased out.

**Top 3 things to fix in order:**
1. `cert-manager: '*'` floating pin + the Loki/Tempo charts have **migrated
   away from `grafana/helm-charts`** to `grafana-community/helm-charts`.
   Reproducibility hole + impending silent breakage.
2. bjw-s `app-template` — eight first-party charts use four different 4.x
   pins; **v5.0.1 shipped 2026-05-14**. Standardize on v5 in one pass.
3. **Helm 3 EOL ~July 2026** (security fixes only to 2026-11-11). Helm 4.2 is
   current; confirm ArgoCD's renderer supports it.

## Helm charts

| Component | Pinned | Latest stable (2026-05-24) | Drift | Action |
|---|---|---|---|---|
| grafana-operator | v5.18.0 | **5.23.0** (2026-05-21) | 5 minors | Bump to 5.23.0 |
| grafana chart | 9.4.5 | 12.x line | Several majors | Plan upgrade — schema + provisioning changed in Grafana 12 |
| mimir-distributed | 5.3.0 | **6.0.6** stable (6.1.0 weekly) | 1 major | Bump; follow 5.x→6.0 migration guide |
| loki | 7.0.0 (`grafana/helm-charts`) | Chart **moved to `grafana-community/helm-charts`** on 2026-03-16 (forked at 6.55.0) | Repo moved | Re-point `repoURL`, re-pin |
| tempo | 1.9.0 (`grafana/helm-charts`) | **1.24.4** (also migrating to grafana-community after 2026-01-30) | 15 minors + repo migration | Migrate repo, bump |
| alloy | 1.0.1 | **1.8.1** | 8 minors | Bump |
| kube-state-metrics | 5.25.1 | **7.4.0** (2026-05-21) | 2 majors | Bump; review value-schema diffs |
| prometheus-node-exporter | 4.39.0 | **4.55.0** | 16 minors | Bump |
| prometheus-operator-crds | 28.0.1 | 29.0.0 | 1 major | Bump; verify CRD compat |
| envoy-gateway (eg) | v1.7.0 | **v1.8.0** (2026-05-13) | 1 minor | Bump |
| envoy-ai-gateway (aieg + aieg-crd) | v0.5.0 | **v0.6.0** (2026-05-05) — *first production-ready API surface, CRDs promoted to `v1beta1`* | 1 minor, big | **Bump now**; required to use `v1beta1` CRDs; v1.0 GA targeted June 2026 |
| authorino-operator | 0.23.1 | 0.24.0 (2025-04-01) | 1 minor | Bump |
| ~~cnpg (cloudnative-pg)~~ | ~~0.27.1~~ | ~~0.28.2~~ | — | **Superseded:** CNPG operator installed externally; removed from this repo. |
| ~~plugin-barman-cloud~~ | ~~0.5.0~~ | ~~0.6.0~~ | — | **Superseded:** Barman Cloud plugin installed externally; removed from this repo. |
| ~~**cert-manager** (`charts/cert`)~~ | ~~`'*'`~~ | ~~**v1.20.2** (2025-04-11)~~ | — | **Superseded:** cert-manager + its ClusterIssuers are now deployed externally by the `home-os` repo. `charts/cert` removed from this repo (ADR-noted in CLAUDE.md). This pin no longer applies here. |
| bjw-s/app-template | 4.1.2 / 4.3.0 / 4.5.0 / 4.6.2 across charts | **5.0.1** (2026-05-14) | 1 major + drift | Standardize on 5.0.1 |
| ~~traefik~~ | ~~39.0.2~~ | ~~40.2.0~~ | — | **Superseded:** Traefik installed externally; removed from this repo. |
| ~~external-secrets~~ | ~~2.4.0~~ | ~~2.5.0~~ | — | **Superseded:** ESO is installed externally now; removed from this repo. Pin no longer applies here. |
| ~~opentelemetry-operator~~ | ~~0.106.0~~ | — | — | **Superseded:** OTel Operator installed externally; removed from this repo. |
| coder | 2.31.9 | Verify upstream | unverified | Check |

## Kubernetes APIs

| API | Pinned | Latest (2026-05) | Drift | Action |
|---|---|---|---|---|
| `authorino.kuadrant.io` (AuthConfig) | v1beta3 | v1beta3 still current; v1 GA not shipped | None | Keep |
| `operator.authorino.kuadrant.io` (Authorino CR) | v1beta1 | v1beta1 | None | Keep |
| `gateway.networking.k8s.io` (Gateway/HTTPRoute/…) | v1 | v1 GA — latest v1.5.1 (2025-03-14) | None | Keep; consider v1.5's ListenerSet / CORS |
| `gateway.envoyproxy.io` | v1alpha1 | v1alpha1 still ships in EG 1.8 | Acceptable | Track promotion |
| **`aigateway.envoyproxy.io`** | v1alpha1 | **v1beta1 preferred since v0.6.0** (2026-05-05); v1alpha1 is legacy | 1 version | **Migrate manifests to v1beta1** when bumping the chart (`charts/core-gateway/templates/gateway-config.yaml` etc.) |
| `opentelemetry.io` (OpenTelemetryCollector) | v1beta1 | v1beta1 current; no v1 GA yet | None | Keep |
| `cert-manager.io` | v1 | v1 (cert-manager 1.20.2) | None | Keep |
| `monitoring.coreos.com` (PodMonitor/ServiceMonitor) | v1 | v1 | None | Keep |
| `postgresql.cnpg.io` (Cluster image) | `postgresql:18.1` | PG **18.4** (2026-05-14) | Patch lag | Bump image to `18.4-system-trixie` |
| Loki schema config | v13 | v13 still current | None | Keep |
| **Grafana dashboard `schemaVersion`** | 38 (in `per-user.json`) | Grafana 12.x ships a migration pipeline up to **42**; new CUE-based v2 dashboard schema in rollout | 4 versions | Set `schemaVersion: 42` or re-export from current Grafana |

## Patterns + tooling

| Pattern | Current | 2026 state of the art | Action |
|---|---|---|---|
| ArgoCD multi-source `sources[]` | Used in `coder` (1 source — could just be `source:`) | Multi-source stable, ≤2–3 sources; ApplicationSet `Git`/`Cluster`/`Matrix` generators are the answer for fleets | Already queued (ADR-0006, task #2) |
| OAuth | OAuth 2.0; Keycloak generic_oauth | OAuth 2.1 is IETF draft-15 (March 2026), requirements stable; PKCE mandatory for all auth-code flows; MCP mandates OAuth 2.1 + PKCE | Audit Keycloak clients for PKCE-required; remove any implicit/password grants |
| Python tooling (planned) | N/A | **uv + ruff** are the 2026 stack (replacing pip/poetry/black/isort/flake8); `ty` type-checker in beta; PEP 621 `pyproject.toml` | When writing the CLI (#3) and dashboard generator (#11), skip the legacy stack entirely |
| Dashboards-as-code | Hand JSON | **`grafana-foundation-sdk-python`** (official, multi-language, typed, builder pattern) has overtaken grafanalib in 2026 | Use `grafana-foundation-sdk-python` for the generator (#11) |
| Go toolchain | n/a | Go 1.26.3 (2026-05-07); `goreleaser/v2` (2026-04-21) | Use Go 1.26.x + goreleaser v2 for `kc-token` |
| Helm | v3 implicit | **Helm v4.2.0** (due 2026-05-13); **Helm 3 EOL ~July 2026**, security fixes until 2026-11-11 | Confirm ArgoCD renders charts with Helm 4; render-test bjw-s, grafana, cnpg under v4 |
| `values.schema.json` | None of the first-party charts ship one | Baseline practice for shared charts in 2026 | Add to `core-gateway`, `kuadrant-policies`, `observability-dashboards`, `cert`, `librechart`, `coder-db` |
| Policy-as-code | None in CI | Kyverno has clearly won K8s-admission in 2026; `kubeconform` for schema validation; `conftest` (Rego) alive | Add `kubeconform` to CI (low cost); pick Kyverno if runtime guardrails wanted |
| Secrets | ExternalSecrets via ESO + `ai-ops-secrets` repo | ESO 2.x current | Keep |

## Punch list — ordered by impact

| # | Change | Effort | Risk | Notes |
|---|---|---|---|---|
| 1 | Pin `cert-manager` (`'*'` → `v1.20.2`) | S | Low | Reproducibility / silent-break fix |
| 2 | Bump Envoy AI Gateway 0.5.0 → 0.6.0 + migrate CRs to `v1beta1` | M | Med | v1.0 GA targets June 2026; touches `charts/core-gateway/templates/*` |
| 3 | Re-point Loki/Tempo `repoURL` to `grafana-community/helm-charts` + bump | S–M | Low | Charts moved 2026-01-30 / 2026-03-16; future bumps will silently break otherwise |
| 4 | Bump envoy-gateway 1.7.0 → 1.8.0 | S | Low | Clean minor |
| 5 | Bump grafana-operator 5.18.0 → 5.23.0 | S | Low | Just-pinned; bump to current |
| 6 | Refresh observability chart pins (kube-state-metrics 5→7, node-exporter 4.39→4.55, prom-op-crds 28→29, alloy 1.0→1.8) | S | Low | Read release notes for kube-state-metrics v6/v7 breaking changes |
| 7 | Consolidate bjw-s app-template pins → v5.0.1 | M | Med | 8 charts; common-library v4→v5 breaking changes |
| 8 | Plan grafana 9.4.5 → 12.x upgrade | L | Med | 3 majors; CUE-based dashboard schema is the future |
| 9 | Bump mimir-distributed 5.3.0 → 6.0.6 | M | Med | Follow official 5→6 migration |
| 10 | Bump traefik 39.0.2 → 40.2.0 | S | Low | v40 drops bundled Gateway API CRDs — fine, we set `kubernetesGateway.enabled: false` |
| 11 | CNPG + barman bumps + PG 18.1 → 18.4 | S | Low | All minor / patch |
| 12 | external-secrets 2.4.0 → 2.5.0; authorino-operator 0.23.1 → 0.24.0 | S | Low | Straight minors |
| 13 | Helm 4 / Helm 3 EOL readiness | M | Med | Render-test umbrella against Helm 4; check ArgoCD's renderer version |
| 14 | Refresh `per-user.json` `schemaVersion` 38 → 42 | S | Low | Open in current Grafana, save, re-export |
| 15 | Add `values.schema.json` to first-party charts | M | Low | Catches typos at `helm template` time |
| 16 | CI: add `kubeconform` (and optionally Kyverno) | S | Low | One-time CI addition |
| 17 | ApplicationSet refactor | L | Med | Already ADR-0006 / task #2 |

## Decisions taken from this audit (in subsequent commits)

- **ADR-0008 finalized:** dashboard generator uses `grafana-foundation-sdk-python` (not grafanalib).
- **Pin cert-manager** in this same series of commits.
- **Bump grafana-operator** to 5.23.0 to keep our own work current.
- **Refresh `per-user.json`** to schemaVersion 42 alongside the generator work.
- The rest of the punch list is tracked as follow-up tasks; risky items
  (bjw-s v5, grafana 12, mimir 6, Helm 4 readiness) are deferred to dedicated
  sessions.

## Sources

- grafana/grafana-operator releases (GitHub)
- grafana/helm-charts and grafana-community/helm-charts releases
- envoyproxy/gateway and envoyproxy/ai-gateway releases + roadmap issue #2083
- Kuadrant/authorino-operator releases
- cloudnative-pg/charts releases
- cert-manager/cert-manager releases
- bjw-s-labs/helm-charts releases
- traefik/traefik-helm-chart releases
- external-secrets/external-secrets releases
- kubernetes-sigs/gateway-api releases
- helm.sh blog (Helm 4 release)
- grafana.com docs (Grafana 12 dashboard schema, Foundation SDK)
- oauth.net/2.1
- postgresql.org news (18.4 release)
