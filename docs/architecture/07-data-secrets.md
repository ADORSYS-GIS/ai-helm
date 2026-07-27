# 07 · Data & secrets

Where state lives and how secrets get into pods. Almost all the *storage*
infrastructure is owned externally — this repo defines the **consumers** (CRs,
ExternalSecrets, backup jobs) and references the platform by name.

## Stateful data map

```mermaid
flowchart TB
    subgraph owned["Defined by this repo (consumers)"]
        LC["LibreChat"]
        MONGO["MongoDB<br/>(librechat-app)"]
        MEILI["Meilisearch<br/>(librechat-search)"]
        REPOAUTH["lightbridge-repo-auth"]
        LGTM["Mimir / Loki / Tempo"]
        MBK["mongodb-backup CronJob"]
        LBDB["lightbridge-db cluster (CNPG Cluster CR)<br/>charts/lightbridge-db + repoauth Database CR"]
    end

    subgraph external["Owned externally (the actual engines)"]
        CNPGOP["CNPG operator + Barman plugin<br/>cnpg-system"]
        REDIS["redis-ha · redis-system<br/>(TLS-only)"]
        S3["Hetzner Object Storage<br/>bucket: ssegning-k8s-state"]
    end

    LC --> MONGO
    LC --> MEILI
    LC -->|sessions| REDIS
    LC -->|files| S3
    REPOAUTH -->|"Database CR + managed role"| LBDB
    LBDB -->|reconciled by| CNPGOP
    LGTM -->|blocks| S3
    MONGO --> MBK --> S3
    LBDB -->|Barman backup| S3

```

| Store | Engine | Who owns it | This repo defines |
|---|---|---|---|
| Chat data | MongoDB | in-chart (`librechat-app`) | the StatefulSet + `mongodb-backup` |
| Chat search | Meilisearch | in-chart (`librechat-search`) | the deployment |
| Sessions / ratelimit counters | redis-ha | `home-os` | consumer config + auth Secret only |
| `lightbridge-repo-auth` DB | CNPG Postgres | **repo-owned** Cluster (`charts/lightbridge-db`); reconciled by the external CNPG operator | the `lightbridge-db` `Cluster` CR + a `repoauth` `Database` CR + managed role (not a new pod) |
| Metrics / logs / traces | Mimir / Loki / Tempo | in-chart (`observability`) | the charts (data → S3) |
| Object storage | Hetzner S3 (Ceph-RGW) | Hetzner | bucket prefixes + creds reference |
| Model-cache PVCs on the Hetzner GPU nodes | Longhorn (`aii-longhorn`) | in-chart (`charts/apps`, ADR-0092) | the Application entry, pinned to `hetzner-k8s-gpu-1/2` only |

⚠️ **Two separate Longhorn instances exist, same product name, different clusters
— do not conflate them:**
- **This repo's `aii-longhorn`** (ADR-0092) — `home-remote`, pinned via
  `nodeSelector`/tolerations to the two hand-joined Hetzner Robot GPU nodes only
  (which have no hcloud-csi at all). Backs model-cache PVCs for workloads on
  those nodes.
- **The `admin@homeos`-cluster Longhorn** — backed the `model-serving-qwen3-4b`/
  `model-serving-zimage-turbo` RWX PVCs (`docs/patterns/self-hosted-model-serving.md`,
  `docs/models/qwen3-4b.md`). Provisioned outside `ai-helm` entirely, on the home
  GPU node. Untouched by anything in this repo. ⚠️ Since ADR-0100 every app that
  used it is `enabled: false` (`zimage-turbo` was the last, and moved to the
  fleet), so those volumes are orphaned data awaiting that cluster's
  decommissioning — not live storage.

### Object storage layout (one bucket, prefixes per tenant)

```mermaid
flowchart LR
    BUCKET["🪣 ssegning-k8s-state<br/>endpoint: nbg1.your-objectstorage.com<br/>region: us-east-1"]
    BUCKET --> P1["mimirblocks/<br/><i>(alphanumeric-only prefix)</i>"]
    BUCKET --> P2["loki/"]
    BUCKET --> P3["tempo/"]
    BUCKET --> P4["cnpg backups/"]
    BUCKET --> P5["librechat files/"]
    BUCKET --> P6["mongodb backups/"]
```

> `mimir.storage_prefix` must be **alphanumeric-only** (no `/`) → `mimirblocks`.

## Secret flow (ESO + `ssegning-aws`)

The External Secrets Operator (installed externally) syncs from one
cluster-scoped `ClusterSecretStore` — `ssegning-aws`. This repo **owns the
`ExternalSecret` CRs in-chart**; the old wholesale `secrets` Application was
removed (2026-06-04).

```mermaid
flowchart TB
    AWS["AWS Secrets Manager<br/>(behind ssegning-aws store)"]
    subgraph keys["Two key namespaces"]
        K1["ai/camer/digital/prod/env<br/><i>APP secrets (one prop each)</i>"]
        K2["prod/meta/test-app<br/><i>PLATFORM secrets (S3, redis pw)</i>"]
    end
    ESO["External Secrets Operator<br/>external-secrets ns"]

    subgraph charts["In-chart ExternalSecret CRs (this repo)"]
        ES1["ai-models-backends (provider keys)"]
        ES2["librechat-app"]
        ES3["observability-secrets"]
        ES4["lightbridge-repo-auth + db-role"]
        ES5["environments/prod/deps/* overlays"]
    end

    K8S["k8s Secrets in each namespace"]

    AWS --> K1 & K2
    K1 --> ESO
    K2 --> ESO
    charts -->|reference store by name| ESO
    ESO --> K8S

```

### Ownership split (who owns which secret)

| Scope | Key | Examples | Owner CR |
|---|---|---|---|
| **App** | `ai/camer/digital/prod/env` | provider API keys, repo-auth webhook secret, internal token, GitHub App PEM | in-chart `ExternalSecret` |
| **Platform** | `prod/meta/test-app` | S3 backup creds, redis password | in-chart `ExternalSecret` |

> ⚠️ **Re-home a secret in-chart *before* retiring its provisioner.** Pruning the
> old `secrets` app cascade-deleted `lightbridge-opa-auth` → gateway outage. And
> an ESO `{{ }}` template inside a `tpl`'d string must be escaped
> (`{{ "{{ .password }}" }}`) so Helm passes it through to ESO untouched.

## What this repo does NOT own (consumed by name)

```mermaid
flowchart LR
    subgraph repo["ai-helm references"]
        R1["Database CR"] -.-> E1["CNPG operator (cnpg-system)"]
        R2["ExternalSecret"] -.-> E2["ESO + ssegning-aws (external-secrets)"]
        R3["REDIS_* env"] -.-> E3["redis-ha (redis-system, home-os)"]
        R4["ingressClassName: traefik"] -.-> E4["Traefik (traefik ns)"]
        R5["cluster-issuer annotations"] -.-> E5["cert-manager + ClusterIssuers (home-os)"]
        R6["OpenTelemetryCollector CR"] -.-> E6["otel-operator (opentelemetry-system)"]
    end
```

Don't re-add operators/stores/issuers for any of these — they're provisioned by
the companion repos. This repo only declares the CRs they reconcile.

→ Related: [04 GitOps (secret-bearing umbrellas)](04-gitops-deployment.md) · [06 Networking & TLS](06-networking-tls.md)
