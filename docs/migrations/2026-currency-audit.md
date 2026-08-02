# 2026 currency audit

**Original date:** 2026-05-24
**Refreshed:** 2026-08-02 (this pass)
**Scope:** Helm chart pins, Kubernetes API versions, dashboard schema, project tooling
**Method:** Live repo inspection (`grep`/registry API calls against actual pinned
versions) + parallel research agents cross-checking each pin against upstream
release pages, GitHub APIs, and Helm repo indexes. See "Sources" at the bottom.

> This is a **refresh**, not a rewrite from scratch — most items below trace
> back to the 2026-05-24 pass. Anything the May audit flagged that turned out
> to be already resolved, superseded, or no longer this repo's concern is
> marked as such rather than re-litigated. The headline change since May: the
> "impending" Grafana/Loki/Tempo repo migration the old audit warned about has
> **now materialized** — see the Snapshot below.

## Snapshot

**The single most consequential finding this pass:** `grafana`, `loki`, and
`tempo` are not just behind — the old `grafana.github.io/helm-charts` repo
**stopped publishing them entirely on 2026-01-30**. This repo's pins
(`grafana` 10.5.15, `tempo` 1.24.4) are the **exact last versions that repo
ever shipped** — checking "latest on the pinned repoURL" would report "already
current" and mask the real problem. The OSS continuation lives at
`grafana-community.github.io/helm-charts` under **renumbered** chart lines
(loki jumped 7.x → 18.x; tempo 1.x → 2.x). Nothing is broken *today* — ArgoCD
still resolves the frozen versions fine — but there will be **no more updates,
security or otherwise**, until the `repoURL` is re-pointed.

**Second finding, downstream of the first:** the Grafana OSS *application*
itself (distinct from the chart's own version number) has crossed a major
version — this repo runs **12.3.1**, latest is **13.1.1** — but the dashboard
generator's `grafana-foundation-sdk` PyPI package still has **no 12.x release
at all** (confirmed directly against PyPI's release index today), so a chart
bump alone wouldn't unblock anything on the dashboard-authoring side. A free,
same-major bump (SDK 11.5.0 → 11.6.0) is available now independent of that.

**Two floating pins have demonstrated real risk**, not just theoretical drift:
`dcgm-exporter: "4.*"` absorbed a metric-label rename (`Hostname`→`hostname`)
within its own range, and `nvidia-device-plugin: "0.*"` shipped *and reverted*
a breaking default-value change within its own range — 0.x carries no semver
stability guarantee at all. Both are candidates for exact pins, same class of
fix as the cert-manager `'*'` pin the May audit already closed.

**Helm 3 EOL / Helm 4 — checked precisely, not actionable yet.** Helm 3's
final feature release is Sept 9, 2026 (security-only support now extended to
Feb 10, 2027, later than the May audit's Nov 2026 estimate). Helm 4 is at
v4.2.3. But **the current stable ArgoCD (v3.4.6) still shells out to Helm
3.19.4 internally** — Helm 4 support merged to ArgoCD's `master`/`v3.5.0` line
(currently `rc3`, not GA). This repo's actual rendering behavior is still
governed by Helm 3 today regardless of what's current upstream; re-check once
ArgoCD v3.5.0 ships GA.

**Top 3 things to fix in order (superseding the May audit's top 3, all three
of which are now resolved or obsolete — see the Helm charts table):**
1. Re-point `grafana`/`loki`/`tempo` `repoURL`s to `grafana-community.github.io/helm-charts`
   and re-pin — the old repo is a dead end, not just stale.
2. Retry the `authorino-operator` bump (0.23.1 → 0.26.0, 3 minors behind).
   The earlier "0.24.0 not found" ArgoCD error that stopped a prior bump
   attempt does **not** reflect reality — 0.24.0 (and every version through
   0.26.0) is confirmed live in the chart index today; that was very likely a
   stale ArgoCD repo-cache at the time, not an absent version.
3. `kube-state-metrics` 7.4.0 → 8.0.0 is a full major behind and the one
   documented breaking change (dropped chart-native Cilium support) is
   directly relevant to this cluster's Cilium-heavy posture — verify the
   chart's own `networkPolicy.cilium` toggle isn't in use (this repo's ksm
   egress is handled by hand-authored `CiliumNetworkPolicy` CRs, not that
   chart feature, so it's very likely a non-issue, but confirm before bumping).

## Helm charts

| Component | Pinned | Latest stable (2026-08-02) | Drift | Action |
|---|---|---|---|---|
| grafana chart | 10.5.15 | **12.10.1** (2026-07-31, `grafana-community`) — old repo frozen at 10.5.15 since 2026-01-30 | Repo dead + several majors | Re-point `repoURL` to `grafana-community.github.io/helm-charts`, re-pin |
| Grafana OSS app (bundled, distinct from chart version) | 12.3.1 | **13.1.1** | 1 major | Plan upgrade once the SDK supports 12.x+; skip v13.0.0 specifically (dashboard-loss bug w/ Git Sync), go to v13.0.1+ if/when bumping |
| grafana-operator | 5.23.0 | **5.24.0** (2026-06-09) | 1 minor | Bump |
| loki | 7.0.0 | Old repo: **frozen**, last ever published was 7.2.0 (2026-07-29, enterprise-maintenance-only). OSS continuation: **grafana-community** `loki` **18.7.1** (renumbered line, app 3.7.4) | Repo moved + renumbered | Re-point repo, re-pin to the `grafana-community` line (chart version numbering is unrelated to the old 7.x line — treat as a fresh pin, not a "bump") |
| tempo | 1.24.4 | Old repo: **frozen at exactly 1.24.4** (this repo's pin is the last version ever published there, 2026-01-30). OSS continuation: **grafana-community** `tempo` **2.2.3** (renumbered, app 2.10.7) | Repo moved + renumbered | Re-point repo, re-pin |
| mimir-distributed | 5.8.0 | **6.1.0** stable (2026-06-29) | 1 major | Bump; follow the 5.x→6.0 migration guide (nginx→gateway block, rollout-operator CRDs). Source moved to `grafana/mimir` but still publishes to the SAME `grafana.github.io/helm-charts` index — no repoURL change needed here, unlike grafana/loki/tempo |
| alloy | 1.8.2 | **1.11.0** (2026-07-20) | 3 minors | Bump. Source lives in `grafana/alloy` but still publishes to `grafana.github.io/helm-charts` — not part of the repo migration |
| kube-state-metrics | 7.4.0 | **8.0.0** (2026-07-20) | 1 major | Bump; only documented breaking change is dropped chart-native CiliumNetworkPolicy support — verify unused (see Snapshot) before bumping |
| prometheus-node-exporter | 4.55.0 | **4.56.1** (2026-07-14) | 1 minor | Bump |
| prometheus-operator-crds | 29.0.0 | **31.0.0** (2026-07-28) | 2 minors | Bump; no CRD API-version change (`monitoring.coreos.com/v1` unchanged for ServiceMonitor/PodMonitor) |
| prometheus-redis-exporter | 6.26.0 | **6.28.0** (2026-07-23) | 2 minors | Bump |
| dcgm-exporter | `"4.*"` (floating) | **4.6.0** chart / DCGM 4.8.3 (2026-07-15) | Floating — MEDIUM risk (confirmed): 4.6.0→4.8.3 renamed the `Hostname` metric label to `hostname`, a silent breaking change any dashboard/alert on the old name would hit within this repo's own floating range | Pin to an exact chart version |
| nvidia-device-plugin | `"0.*"` (floating) | **v0.19.3** (2026-06-22) | Floating — HIGH risk (confirmed): v0.19.0 changed `gds`/`gdrcopy`/`mofed` flag defaults, then v0.19.3 reverted it — a breaking-then-reverted change shipped and un-shipped inside this repo's own `0.*` range. 0.x carries no semver stability guarantee at all | Pin to an exact chart version |
| longhorn | `"1.12.0"` | **v1.12.0** (v1.12.1 still `-rc1`, not GA) | None — already current | Keep |
| reloader (stakater) | 2.2.14 | **chart-v2.2.14** (app v1.4.19, 2026-07-01) | None — exact match | Keep |
| argo-workflows | 1.0.20 | **1.0.23** (2026-07-24) | 3 patches | Bump; only dependency bumps + one `envFrom` feature add in this range, no RBAC/token changes — the documented ADR-0091 RBAC gotchas (`workflow.serviceAccount.create`, `authModes` bearer-format) remain unaddressed upstream either way |
| envoy-gateway (eg) | v1.8.2 | **v1.8.3** (2026-07-22) | 1 patch | Bump |
| envoy-ai-gateway (aieg + aieg-crd) | v1.0.0 | **v1.0.0 — confirmed current**, GA'd 2026-06-23; no v1.1+ exists | None | Keep. (v1.0 GA finally shipped — the May audit's "targets June 2026" note was accurate) |
| authorino-operator | 0.23.1 | **0.26.0** | 3 minors | Bump (see Snapshot — earlier "0.24.0 not found" was very likely a stale ArgoCD cache, not a real absence; every version 0.24.0→0.26.0 is confirmed live in `kuadrant.io/helm-charts/index.yaml` today) |
| coder | 2.33.7 | **2.34.7** (stable line; 2.35.3 on mainline) | 1 minor | Bump |
| mongodb (Bitnami-alternative, `repo.helmforge.dev`) | 1.7.6 | **1.7.16** | 10 patches | Bump; confirmed `repo.helmforge.dev` is still actively publishing (not superseded again) |
| meilisearch (`meilisearch-kubernetes`) | 0.25.1 | **0.33.0** (2026-06-16) | Several minors | Bump; review release notes for schema changes |
| llm-d-router-standalone | v0.9.0 | **v0.9.0 — confirmed current**, project is pre-1.0 and hasn't tagged since | None | Keep |
| bjw-s-labs app-template (fork base) | 4.6.2 (forked 2026-05-31 → local `charts/bjw-template`/`charts/bjw-common`) | **5.0.1** (2026-05-14, upstream) | 1 major — informational only | Not actionable: this is now a deliberate local fork (ADR-noted), not an upstream pin. Note for awareness only; cherry-pick from 5.x only if a specific fix is needed |
| ~~cert-manager~~ | ~~`'*'`~~ | — | — | **Resolved** (May audit): pinned, then made moot — cert-manager is now deployed externally by `home-os`; not this repo's concern at all |
| ~~traefik~~ | ~~39.0.2~~ | — | — | **Superseded:** Traefik deployed externally; removed from this repo |
| ~~external-secrets~~ | ~~2.4.0~~ | — | — | **Superseded:** ESO deployed externally; removed from this repo |
| ~~cnpg (cloudnative-pg) + plugin-barman-cloud~~ | — | — | — | **Superseded:** CNPG operator + Barman Cloud plugin installed externally; this repo only owns `Cluster` CRs now |
| ~~opentelemetry-operator~~ | ~~0.106.0~~ | — | — | **Superseded:** installed externally |

## Kubernetes APIs

| API | Pinned | Latest (2026-08-02) | Drift | Action |
|---|---|---|---|---|
| `authorino.kuadrant.io` (AuthConfig) | v1beta3 | v1beta3 — still current, no v1 | None | Keep |
| `operator.authorino.kuadrant.io` (Authorino CR) | v1beta1 | v1beta1 — still current, no v1 | None | Keep |
| `gateway.networking.k8s.io` (Gateway/HTTPRoute/…) | v1 | v1 GA — spec at v1.6.1 (2026-07-16); newer features (ListenerSet GA, CORS filter, GAMMA work) shipped as new resources/fields within v1, not a new API version | None | Keep; evaluate adopting newer v1 features if useful, no version bump forced |
| `gateway.envoyproxy.io` | v1alpha1 | v1alpha1 — still current for Envoy Gateway 1.8.x, no v1 promotion exists | None | Keep |
| **`aigateway.envoyproxy.io`** | v1beta1 | **v1beta1 is the declared-stable API at v1.0.0** — covered by a 1.x stability guarantee despite the "beta" name; no plain `v1` exists or is planned | None (naming is unusual, version is correct) | Keep — the May audit's "optional migrate to v1beta1" item is now moot since it already IS v1beta1 and that's confirmed stable |
| `opentelemetry.io` (OpenTelemetryCollector) | v1beta1 | v1beta1 current, no v1 GA yet | None | Keep |
| `cert-manager.io` | v1 | v1 — stable since 1.7 removed pre-v1 alphas/betas, no v2 planned | None | Keep |
| `monitoring.coreos.com` (PodMonitor/ServiceMonitor) | v1 | v1 — unchanged across prometheus-operator-crds 29→31 (newer CRDs like ScrapeConfig use v1alpha1, but these two kinds have been stable v1 for years) | None | Keep |
| `postgresql.cnpg.io` (Cluster image) | `postgresql:18.4-system-trixie` | Confirmed live (direct GHCR registry check, not just search): `18.4-*-system-trixie` is an actively-published ROLLING tag (dated builds through 2026-07-17+ seen). PG19 exists only as `19beta2` — not GA | None | Keep — already on the current stable rolling tag |
| Loki schema config | v13 | v13 — still current | None | Keep |
| **Grafana dashboard `schemaVersion`** | 42 | **42 is still the current documented max** for Grafana 12.x/13.x (re-checked against current docs, not just carried over from May) | None | Keep — the May audit's bump to 42 remains correct and current |

## Patterns + tooling

| Pattern | Current | 2026-08-02 state of the art | Action |
|---|---|---|---|
| **Helm 3 vs Helm 4, via ArgoCD** | ArgoCD v3.4.6 (current stable) bundles Helm **3.19.4** internally (`hack/tool-versions.sh`) | Helm 4.2.3 is current upstream; ArgoCD's own Helm-4 support merged to `master`/pending `v3.5.0` (rc3, not GA); plan is v3.5 makes Helm 4 default, v3 support drops around ~v3.6 (≈Helm 3 EOL, now Feb 2027) | Not actionable yet — this repo's actual chart-render behavior is still Helm-3-shaped no matter what's "current" upstream. Re-verify against ArgoCD v3.5.0's GA release notes once it ships; don't chase Helm 4 compatibility before then |
| `grafana-foundation-sdk` (dashboard generator) | Pinned `11.5.0` (local-version epoch pin, `tools/dashboards/pyproject.toml`), emits schemaVersion 39 | Latest **11.x is 11.6.0** (checked directly against PyPI's release index today); **no 12.x release exists on PyPI at all yet** | Take the free `11.5.0` → `11.6.0` bump now (same major, no coupling to the grafana chart's own version). The full jump to a 12.x SDK stays blocked on upstream publishing one — re-check PyPI before attempting the grafana-chart 12.x migration above, the two are still coupled as the existing `pyproject.toml` comment says |
| `ruff` | `ruff>=0.4.0` floor in `pyproject.toml`, `uv.lock` resolved to **0.15.14** | **0.16.0** (2026-07-23–30) — enabled **413 default rules, up from 59**, a large jump | Before bumping: run `uv run ruff check .` against a locally-pinned 0.16.0 first to see how much new lint noise the expanded default rule set surfaces, rather than let it land silently on the next `uv sync` |
| OAuth | OAuth 2.0; Keycloak generic_oauth | OAuth 2.1 still `draft-ietf-oauth-v2-1-15` (2026-03-02), not an RFC — IESG submission targeted Dec 2026, no material change since May | No action forced yet; re-check after the IESG milestone |
| Python tooling | uv + ruff | Still the clear 2026 best practice, no displacement | Keep |
| Dashboards-as-code | `grafana-foundation-sdk-python` | Still the maintained, current approach | Keep |
| ApplicationSet refactor (old item, ADR-0006) | N/A | ADR-0006 **superseded by ADR-0018** (2026-05-31) — the umbrella-apps pattern already achieves the multi-source/deps split this was chasing, via kustomize + in-repo overlays instead of a full ApplicationSet List/Matrix conversion. That conversion "remains valid future work, not a prerequisite" per ADR-0018's own text | Not blocking anything; optional future work only, not a punch-list item anymore |
| `values.schema.json` | None of the first-party charts ship one | Still baseline practice for shared charts | Unchanged from May — still open, not reassessed this pass |
| Policy-as-code (`kubeconform`/Kyverno) | None in CI | Unchanged from May — still open, not reassessed this pass | — |

## Punch list — ordered by impact

| # | Change | Effort | Risk | Notes |
|---|---|---|---|---|
| 1 | Re-point `grafana`/`loki`/`tempo` `repoURL` to `grafana-community.github.io/helm-charts`, re-pin | M | Med | The old repo is **dead**, not just stale (frozen since 2026-01-30) — this is no longer optional hygiene, it's the only way to receive any future update at all, security or otherwise. Loki/Tempo chart version numbers reset on the new repo — treat as fresh pins |
| 2 | Retry authorino-operator bump 0.23.1 → 0.26.0 | S | Low | The prior blocker ("0.24.0 not found") does not reflect current registry state — confirmed live today |
| 3 | Bump kube-state-metrics 7.4.0 → 8.0.0 | S–M | Med | Verify the chart-native Cilium toggle isn't in use first (see Snapshot); this cluster is Cilium-heavy |
| 4 | Bump mimir-distributed 5.8.0 → 6.1.0 | M | Med | Follow the official 5.x→6.0 migration guide; repoURL unchanged, only the version |
| 5 | Pin `dcgm-exporter` and `nvidia-device-plugin` to exact versions (drop the `4.*`/`0.*` floats) | S | Low | Both have DEMONSTRATED silent-breaking-change shipments within their own ranges — this is the same fix class as the already-closed cert-manager `'*'` pin |
| 6 | Bump meilisearch 0.25.1 → 0.33.0 | S | Low–Med | Several minors behind; skim release notes for schema changes before bumping |
| 7 | Bump coder chart 2.33.7 → 2.34.7 | S | Low | Clean minor |
| 8 | Bump mongodb (helmforge) 1.7.6 → 1.7.16 | S | Low | Clean patch train |
| 9 | Refresh remaining observability minor/patch pins: alloy 1.8.2→1.11.0, grafana-operator 5.23.0→5.24.0, node-exporter 4.55.0→4.56.1, prometheus-operator-crds 29.0.0→31.0.0, prometheus-redis-exporter 6.26.0→6.28.0, envoy-gateway 1.8.2→1.8.3, argo-workflows 1.0.20→1.0.23 | S | Low | All clean minors/patches, no known breaking changes |
| 10 | Bump `grafana-foundation-sdk` 11.5.0 → 11.6.0 | S | Low | Free same-major bump; does NOT unblock the grafana-chart 12.x migration (no 12.x SDK exists yet) |
| 11 | Plan the grafana-chart 12.x + Grafana-app-13.x migration | L | Med | Blocked on `grafana-foundation-sdk` publishing a 12.x line first (re-check PyPI periodically); when it lands, skip Grafana v13.0.0 specifically (dashboard-loss bug w/ Git Sync), go to v13.0.1+ |
| 12 | Evaluate `ruff` 0.15.14 → 0.16.0 | S | Low–Med | 413 default rules vs the current 59 — dry-run first to gauge new lint noise before landing it in CI |
| 13 | `values.schema.json` on first-party charts | M | Low | Not reassessed this pass — carried over from May, still open |
| 14 | CI: `kubeconform` (and optionally Kyverno) | S | Low | Not reassessed this pass — carried over from May, still open |
| 15 | Re-verify Helm 4 / ArgoCD renderer status | — | — | Not actionable now — re-check once ArgoCD v3.5.0 GA ships (currently `rc3`) |

## Decisions taken from this audit (in subsequent commits)

**From the 2026-05-24 pass:**
- ADR-0008 finalized: dashboard generator uses `grafana-foundation-sdk-python` (not grafanalib).
- Pinned cert-manager (later made moot when cert-manager moved externally).
- Bumped grafana-operator to 5.23.0.
- Refreshed `per-user.json` to schemaVersion 42.
- bjw-s app-template was forked locally (`charts/bjw-template`/`charts/bjw-common`,
  2026-05-31) rather than consolidated on a pinned upstream version — a more
  decisive resolution to punch-list item #7 than originally proposed.
- Envoy AI Gateway bumped v0.6.0 → v0.7.0 (interim), since further bumped to
  the now-GA v1.0.0 (see table above).
- CNPG, Barman Cloud plugin, Traefik, and External Secrets Operator were all
  moved to external management (`home-os`), removing their pins from this
  repo's scope entirely.

**From this 2026-08-02 pass:** none yet — this is a research-only refresh.
The punch list above is the queued follow-up work.

## Sources

**Carried over from the May pass** (still-relevant background):
- grafana/grafana-operator releases (GitHub)
- envoyproxy/gateway and envoyproxy/ai-gateway releases + roadmap
- Kuadrant/authorino-operator releases
- kubernetes-sigs/gateway-api releases
- oauth.net/2.1
- postgresql.org news

**New/re-verified this pass:**
- `pypi.org/pypi/grafana-foundation-sdk/json` (direct API check for 12.x releases — none found)
- `ghcr.io/v2/cloudnative-pg/postgresql/tags/list` (direct registry check — confirmed `18.4-*-system-trixie` actively published, `19beta2` confirms PG19 not GA)
- `repo.helmforge.dev/index.yaml` (direct index check — mongodb chart versions)
- GitHub Releases API for: envoyproxy/gateway, envoyproxy/ai-gateway (incl. `published_at` verification), kuadrant/authorino-operator, prometheus-community/helm-charts (kube-state-metrics, node-exporter, prometheus-operator-crds), grafana/alloy, coder/coder, meilisearch/meilisearch-kubernetes, argoproj/argo-helm, bjw-s-labs/helm-charts
- `kuadrant.io/helm-charts/index.yaml` (direct index check — confirmed 0.24.0–0.26.0 all live, correcting a prior "not found" assumption)
- `community.grafana.com/t/helm-repository-migration-grafana-community-charts/160983` and `github.com/grafana/loki/issues/20705` (repo migration confirmation)
- `helm.sh/blog/helm-v3-end-of-life`, `github.com/argoproj/argo-cd` releases + PR #28076 + `hack/tool-versions.sh@v3.4.6` (Helm 3/4 + ArgoCD renderer status)
- `astral.sh/blog/ruff-v0.16.0`, `github.com/astral-sh/uv/releases`
- `datatracker.ietf.org/doc/draft-ietf-oauth-v2-1` (OAuth 2.1 status)
