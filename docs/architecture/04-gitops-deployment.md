# 04 · GitOps & deployment topology

How charts in this repo become running workloads — the ArgoCD machinery, the
two-cluster split, the render patterns, the sync-wave ordering, and the
release flow. Source ADRs: **0017** (destinations), **0018** (umbrellas +
environments), **0031** (tag-based deploys).

## Two clusters, two roles

ArgoCD does **not** run on the cluster it deploys to.

```mermaid
flowchart LR
    subgraph cp["🧠 admin@homeos (Talos) — the CONTROL plane"]
        ARGOCD["ArgoCD<br/>ns: argocd"]
        ROOT["Application: ai-apps-v2<br/><i>applied manually; pins a release tag</i>"]
        APPS["charts/apps renders<br/>~21 Application/ApplicationSet CRs<br/><i>(control objects live here)</i>"]
        ARGOCD --> ROOT --> APPS
    end

    subgraph wl["⚙️ home-remote (Hetzner k3s) — the WORKLOAD plane"]
        NS1["ns: converse* / observability /<br/>envoy-*-system / monitoring / ..."]
        PODS["actual pods<br/>gateway · librechat · models · LGTM"]
        NS1 --> PODS
    end

    HOMEOS["home-os repo<br/>charts/cd/values.yaml<br/><i>pins ai-apps-v2 targetRevision</i>"]:::ext
    HOMEOS -.->|"GitOps-manages the root tag"| ROOT
    APPS ==>|"deploys workloads to"| wl

    classDef ext fill:#eee,stroke:#888,color:#333,stroke-dasharray:4 3;
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
        WL["normal workload<br/><i>(default)</i>"]:::own
        CP["controlPlane: true<br/><i>(orchestrators: models, librechat,<br/>mcps, observability, lightbridge-backend)</i>"]:::ctrl
        HC["homeCluster: true<br/><i>(model-serving-qwen3-* only — ADR-0022)</i>"]:::gpu
    end

    DESTW["→ home-remote<br/>(workload namespace)"]:::own
    DESTC["→ https://kubernetes.default.svc<br/>argocd ns (the AppSet it emits<br/>lands where ArgoCD watches)"]:::ctrl
    DESTH["→ in-cluster server<br/>but keeps its own workload ns;<br/>guard called with allowInCluster"]:::gpu

    WL --> DESTW
    CP --> DESTC
    HC --> DESTH

    GUARD{{"render guard:<br/>workload → in-cluster?<br/>FAIL unless allowInCluster"}}:::warn
    WL -.checked by.-> GUARD

    classDef own fill:#eaf3ea,stroke:#4a8a4a;
    classDef ctrl fill:#e8eef7,stroke:#4a6fa5;
    classDef gpu fill:#f7e8f0,stroke:#a54a81;
    classDef warn fill:#fbeaea,stroke:#a54a4a;
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

    classDef g fill:#eaf3ea,stroke:#4a8a4a;
    class D,DW,O,OS,OL1,OL2,AA,AAT,AC1,AC2 g;
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
        SA["Source A — workload<br/>charts/&lt;x&gt; or upstream chart"]:::own
        SB["Source B — deps overlay (kustomize)<br/>environments/prod/deps/&lt;app&gt;<br/><i>ingress Certificate, ExternalSecrets,<br/>CiliumNetworkPolicy</i>"]:::own
        SC["Source C — $values (optional)<br/><i>per-env workload knob</i>"]:::own
    end
    CLUSTER["environments/prod/cluster.yaml<br/><i>clusterIssuer, secretStore,<br/>ingressClass, storageClass, domainBase</i>"]:::ext
    CLUSTER -.->|patched into| SB

    classDef own fill:#eaf3ea,stroke:#4a8a4a;
    classDef ext fill:#eee,stroke:#888,stroke-dasharray:4 3;
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
    W3["wave -3<br/>namespace bootstrap<br/>observability-secrets<br/>(allow-same-namespace)"]:::w
    W2["wave -2<br/>storage backends<br/>Mimir · Loki · Tempo<br/>kube-state-metrics · node-exporter"]:::w
    W1["wave -1<br/>operators + collectors<br/>grafana-operator · Alloy<br/>librechat-search"]:::w
    W0["wave 0<br/>workloads<br/>gateway · LibreChat · models"]:::w
    WP1["wave 1<br/>content<br/>dashboards · opencode-wellknown"]:::w
    WP2["wave 2+<br/>post-sync"]:::w
    W3 --> W2 --> W1 --> W0 --> WP1 --> WP2

    classDef w fill:#eaf3ea,stroke:#4a8a4a,color:#1a401a;
```

> cert-manager and ESO are **not** synced here (external). The `allow-same-namespace`
> CiliumNetworkPolicy ships at wave -3 (before the Mimir stores) so the ring's
> memberlist gossip isn't blocked at startup — see [06 Networking](06-networking-tls.md).

## Release flow — tag-based, two repos (ADR-0031)

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
> tag (immutable → exact prior state). See [`../releasing.md`](../releasing.md).

→ Related: [06 Networking & TLS](06-networking-tls.md) · [07 Data & secrets](07-data-secrets.md)
