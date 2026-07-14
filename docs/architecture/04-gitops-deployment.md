# 04 · GitOps & deployment topology

How charts in this repo become running workloads — the ArgoCD machinery, the
two-cluster split, the render patterns, the sync-wave ordering, and the
release flow. Source ADRs: **0017** (destinations), **0018** (umbrellas +
environments), **0031** (tag-based deploys), **0055** (continuous delivery —
OCI charts + image-updater write-back; supersedes 0031, see the Release-flow
section).

## Two clusters, two roles

ArgoCD does **not** run on the cluster it deploys to.

```mermaid
flowchart LR
    subgraph cp["🧠 admin@homeos (Talos) — the CONTROL plane"]
        ARGOCD["ArgoCD<br/>ns: argocd"]
        ROOT["Application: ai-apps-v2<br/><i>applied manually; tracks main (ADR-0055)</i>"]
        APPS["charts/apps renders<br/>23 Application/ApplicationSet CRs<br/><i>(control objects live here)</i>"]
        ARGOCD --> ROOT --> APPS
    end

    subgraph wl["⚙️ home-remote (Hetzner k3s) — the WORKLOAD plane"]
        NS1["ns: converse* / observability /<br/>envoy-*-system / monitoring / ..."]
        PODS["actual pods<br/>gateway · librechat · models · LGTM"]
        NS1 --> PODS
    end

    HOMEOS["home-os repo<br/>charts/cd/values.yaml<br/><i>pins ai-apps-v2 targetRevision = main</i>"]
    HOMEOS -.->|"GitOps-manages the root"| ROOT
    APPS ==>|"deploys workloads to"| wl

```

- **Control objects** (`Application`, `ApplicationSet`) must live where ArgoCD's
  controllers watch → **in-cluster**, the `argocd` namespace on `admin@homeos`.
- **Workloads** target the registered destination **`home-remote`** (the Hetzner
  cluster). A render-time guard hard-fails any workload that resolves to the
  in-cluster handle unless it opts in (`controlPlane` or `homeCluster`).

## Two-tier destinations (ADR-0017)

```mermaid
flowchart TB
    subgraph apps["charts/apps — per-app destination logic"]
        WL["normal workload<br/><i>(default)</i>"]
        CP["controlPlane: true<br/><i>(orchestrators: models, librechat,<br/>mcps, observability, lightbridge-backend)</i>"]
        HC["homeCluster: true<br/><i>(model-serving-qwen3-* only — ADR-0022)</i>"]
    end

    DESTW["→ home-remote<br/>(workload namespace)"]
    DESTC["→ https://kubernetes.default.svc<br/>argocd ns (the AppSet it emits<br/>lands where ArgoCD watches)"]
    DESTH["→ in-cluster server<br/>but keeps its own workload ns;<br/>guard called with allowInCluster"]

    WL --> DESTW
    CP --> DESTC
    HC --> DESTH

    GUARD{{"render guard:<br/>workload → in-cluster?<br/>FAIL unless allowInCluster"}}
    WL -.checked by.-> GUARD

```

> **Project invariant:** every Application/ApplicationSet from this repo is in the
> `ai` AppProject. `charts/apps` hardcodes `project: ai`; orchestrator children
> set `argocd.project` (= `ai`). There is intentionally **no per-app override**.

## Three render patterns

```mermaid
flowchart TB
    subgraph p1["1 · Direct — most charts"]
        D["Application"] --> DW["chart templates → workloads"]
    end
    subgraph p2["2 · Orchestrator + leaves (ADR-0012/0014)"]
        O["Application"] --> OS["ApplicationSet<br/>(List generator)"]
        OS --> OL1["leaf: charts/ai-model (route+budget)"]
        OS --> OL2["leaf: charts/librechat-app ..."]
    end
    subgraph p3["3 · App-of-Apps (ADR-0019/0020)"]
        AA["Application"] --> AAT["templates/applications.yaml<br/>iterates .Values.children"]
        AAT --> AC1["child: local Helm chart"]
        AAT --> AC2["child: upstream chart as source"]
    end

```

| Pattern | Used by | Why |
|---|---|---|
| **Direct** | `core-gateway`, `kuadrant-policies`, most | One chart, one lifecycle |
| **Orchestrator + leaves** | `ai-models` → `ai-model`, `librechart` → `librechat-*` | Per-component sync waves / rollback; adding a component is a list edit |
| **App-of-Apps** | `observability`, (formerly `coder`) | Fixed, heterogeneous children (local + upstream charts with big inline values) |

## Umbrella apps + `environments/` overlays (ADR-0018)

A flat app and its app-scoped prerequisites sync as **one** multi-source
Application:

```mermaid
flowchart LR
    subgraph umbrella["Umbrella Application (e.g. lightbridge-repo-auth)"]
        SA["Source A — workload<br/>charts/&lt;x&gt; or upstream chart"]
        SB["Source B — deps overlay (kustomize)<br/>environments/prod/deps/&lt;app&gt;<br/><i>ingress Certificate, ExternalSecrets,<br/>CiliumNetworkPolicy</i>"]
        SC["Source C — $values (optional)<br/><i>per-env workload knob</i>"]
    end
    CLUSTER["environments/prod/cluster.yaml<br/><i>clusterIssuer, secretStore,<br/>ingressClass, storageClass, domainBase</i>"]
    CLUSTER -.->|patched into| SB

```

- Attach deps with one field on the app entry: `depsOverlay: environments/prod/deps/<app>`.
- Kustomize is confined to plain CRs (certs, secrets, network policies) —
  **never** kustomize-over-Helm.
- Today only `environments/prod/` exists; a second env is a drop-in sibling.

## Sync waves (the ordering contract)

Lower waves sync first. The rule is **infrastructure → storage → collection →
visualisation** — violating it once cost a day (`MONITORING_FIX.md`).

```mermaid
flowchart LR
    W3["wave -3<br/>namespace bootstrap<br/>observability-secrets<br/>(allow-same-namespace)"]
    W2["wave -2<br/>storage backends<br/>Mimir · Loki · Tempo<br/>kube-state-metrics · node-exporter"]
    W1["wave -1<br/>operators + collectors<br/>grafana-operator · Alloy<br/>librechat-search"]
    W0["wave 0<br/>workloads<br/>gateway · LibreChat · models"]
    WP1["wave 1<br/>content<br/>dashboards · opencode-wellknown"]
    WP2["wave 2+<br/>post-sync"]
    W3 --> W2 --> W1 --> W0 --> WP1 --> WP2

```

> cert-manager and ESO are **not** synced here (external). The `allow-same-namespace`
> CiliumNetworkPolicy ships at wave -3 (before the Mimir stores) so the ring's
> memberlist gossip isn't blocked at startup — see [06 Networking](06-networking-tls.md).

## Release flow — tag-based, two repos (ADR-0031) — RETIRED

> ⚠️ **Retired (2026-06-22), superseded by ADR-0055 (continuous delivery).** The
> tag-based flow below (`release.sh` + `release-*` tags + manual root repoint) no
> longer runs — `tools/release.sh` and `docs/releasing.md` were deleted. Kept here
> as historical context; the live model is the next section + [`../continuous-delivery.md`](../continuous-delivery.md).

Deploys pin an **immutable release tag** (`release-YYYY.MM.DD-vNN`), never `main`.

```mermaid
sequenceDiagram
    autonumber
    participant M as Maintainer
    participant R as tools/release.sh
    participant GH as ai-helm (git)
    participant HO as home-os charts/cd
    participant AC as ArgoCD (cd app)

    M->>R: tools/release.sh (tag) --dry-run, then for real
    R->>GH: bump every self-referencing targetRevision (1 commit)
    R->>R: helm template-check
    R->>GH: tag that commit, push tag → then branch + main
    Note over GH: tag is self-consistent —<br/>children resolve to a tag containing their own ref
    M->>HO: bump ai-apps-v2 targetRevision to (new tag) (governance PR)
    HO->>AC: ArgoCD cd app (selfHeal) reconciles the root pin
    AC->>AC: root ai-apps-v2 rolls forward to (new tag)
```

> ⚠️ Skip the **home-os** step and the root self-heals back to the OLD tag — an
> effective rollback. The durable source of the root's pin is `home-os`
> `charts/cd`, not a live `kubectl patch`. Rollback = bump the root to any prior
> tag (immutable → exact prior state). _(Historical — `releasing.md` removed.)_

## Release flow — continuous delivery (ADR-0055, the target model)

Per-app opt-in via `chart:` on the `charts/apps` entry. Two independent flows; no
`release.sh`, no manual root repoint per change. Immutability is traded away —
charts float on a semver range, image tags float via write-back.

```mermaid
sequenceDiagram
    autonumber
    participant Dev as Merge to ai-helm main
    participant CI as publish-charts-oci
    participant OCI as ghcr.io/adorsys-gis/charts
    participant IMG as image registry
    participant IU as argocd-image-updater
    participant VAL as ai-helm-values (private)
    participant AC as ArgoCD

    Dev->>CI: chart files changed
    CI->>OCI: helm push (auto-semver, libs vendored)
    Note over OCI,AC: child Apps float on chartVersionRange → pull newest next reconcile
    IMG-->>IU: new signed image (sha-*/semver)
    IU->>VAL: commit tag into environments/<env>/values/<app>.yaml (cosign-gated)
    VAL-->>AC: $values Source B updated
    AC->>AC: sync (OCI chart + values + deps)
```

> Rollback: `git revert` in `ai-helm-values` (image tag) and/or pin an app's
> `chartVersionRange` to a known-good version (chart). No immutable fleet snapshot.
> Runbook + the TWO-credential prerequisite: [`../continuous-delivery.md`](../continuous-delivery.md).

→ Related: [06 Networking & TLS](06-networking-tls.md) · [07 Data & secrets](07-data-secrets.md)
