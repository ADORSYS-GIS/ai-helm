# 08 · Observability

The LGTM stack, how telemetry is collected, and how every request is attributed
back to a user. Deployed by the `observability` App-of-Apps orchestrator
(ADR-0020), namespace `observability`, enforced `privileged` Pod Security.
Source ADRs: **0004** (operator + dashboards-as-code), **0005/0046** (per-user
attribution), **0008** (Python dashboards), **0045** (scrape-first sourcing),
**0058** (cost metrics precomputed to Mimir), **0059** (unified alerting →
Discord), **0060** (gamified App Scoreboard). Cost observability — the metrics
backbone, dashboards, scoreboard, alerting + runbook — is its own guide:
[`cost-observability.md`](../cost-observability.md).

## The pipeline

```mermaid
flowchart BT
    subgraph sources["Telemetry sources"]
        WL["workload /metrics<br/>(Service/PodMonitor)"]:::own
        KSM["kube-state-metrics<br/><i>honorLabels: true</i>"]:::own
        NE["node-exporter"]:::own
        LOGS["pod logs (/var/log)"]:::own
        GWLOG["Envoy access log (OTLP)"]:::own
        TRACE["core-gateway -traces<br/>OTel collector"]:::own
    end

    subgraph collect["Collection · wave -1"]
        ALLOY["Alloy (DaemonSet)<br/>ServiceMonitor/PodMonitor discovery<br/>log tail · OTLP :4317/:4318 receiver<br/>ai_gateway_user_attribution stage"]:::own
    end

    subgraph store["Storage · wave -2 → S3"]
        MIMIR["Mimir<br/>metrics"]:::own
        LOKI["Loki<br/>logs"]:::own
        TEMPO["Tempo<br/>traces :3200"]:::own
    end

    GRAF["Grafana (stateless, emptyDir)<br/>+ grafana-operator (external mode)<br/>wave 0 / dashboards wave 1"]:::own

    WL --> ALLOY
    KSM --> ALLOY
    NE --> ALLOY
    LOGS --> ALLOY
    GWLOG --> ALLOY
    TRACE --> ALLOY
    ALLOY --> MIMIR
    ALLOY --> LOKI
    ALLOY --> TEMPO
    MIMIR --> GRAF
    LOKI --> GRAF
    TEMPO --> GRAF

    classDef own fill:#eaf3ea,stroke:#4a8a4a;
```

| Layer | Components | Notes |
|---|---|---|
| **Collection** | Alloy (DaemonSet) | One agent: metrics scrape + log tail + OTLP receiver. Needs API-server egress *and* OTLP ingress allows ([06](06-networking-tls.md)) |
| **Storage** | Mimir, Loki, Tempo | All persist blocks to Hetzner S3; sync wave -2 |
| **Visualisation** | Grafana + grafana-operator | Grafana is **stateless** (ADR-0023); dashboards/folders pushed by the operator |

## Per-user attribution (ADR-0005 / ADR-0046)

The thread that ties an LLM request to a person: JWT → Authorino headers →
Envoy access log → Alloy → Loki labels.

```mermaid
flowchart LR
    JWT["Keycloak JWT"]:::ext
    AUTH["Authorino<br/>stamp x-oidc-user-id, x-oidc-azp"]:::own
    ENVOY["Envoy access log (OTLP)<br/>fields → OTLP attributes (ADR-0046)"]:::own
    ALLOY["Alloy ai_gateway_user_attribution stage<br/>flatten attributes envelope<br/>promote user_id/azp/model labels<br/>pin service_name=envoy-ai-gateway"]:::own
    LOKI["Loki streams<br/>{user_id, azp, model}"]:::own
    DASH["per-user usage dashboard"]:::own

    JWT --> AUTH --> ENVOY --> ALLOY --> LOKI --> DASH

    classDef own fill:#eaf3ea,stroke:#4a8a4a;
    classDef ext fill:#eee,stroke:#888,stroke-dasharray:4 3;
```

> ⚠️ Two attribution traps, both fixed and worth remembering:
> - Envoy's OTel access-log sink emits `format.json` fields as **OTLP attributes,
>   not the log body** — a top-level `| json` finds nothing. Alloy must flatten the
>   `attributes` envelope and anchor on `service_name=envoy-ai-gateway`.
> - Alloy pod-log labels must come from **K8s service discovery**, never from
>   regex-on-the-line — any line mentioning a `/var/log/pods/...` path would
>   otherwise overwrite the stream's `namespace`/`pod` labels.

## Dashboards as code (ADR-0004 / ADR-0008 / ADR-0045)

```mermaid
flowchart LR
    PY["tools/dashboards/*.py<br/>(grafana-foundation-sdk)"]:::own
    JSON["generated JSON<br/>(committed; CI drift-checked)"]:::own
    CR["GrafanaDashboard / GrafanaFolder CRs<br/>(observability-dashboards)"]:::own
    OP["grafana-operator (external mode)"]:::own
    G["Grafana"]:::own

    PY -->|"uv run dashboards build"| JSON --> CR --> OP --> G

    classDef own fill:#eaf3ea,stroke:#4a8a4a;
```

- **Scrape-first (ADR-0045):** no board without verified metrics; API-verified
  gnetIds only; bespoke boards (per-user usage, ratelimit, Authorino) as code.
- Stateless Grafana means **every folder needs a `resyncPeriod`** or a pod roll
  wipes it → `folderRef` dashboards 400 until the operator restarts.
- The dashboard Python is the **only runnable code** in the repo; after editing
  `.py` you must `dashboards build` + commit the JSON (CI fails otherwise).

## In-Grafana AI assistant (ADR-0062)

The `grafana-llm-app` plugin gives operators AI help *inside* Grafana, but its
LLM backend is **our own Envoy AI Gateway** (OpenAI-compatible) — not an external
provider — so the same governance + per-account cost attribution apply. Because
the plugin sends a *static* bearer key it must use the gateway's **internal
plane** (`core-gateway-internal…svc`, ADR-0021); a dedicated `internal-key-grafana`
apiKey gives Grafana its own `x-account-id` spend bucket. Config is fully
declarative (it survives the stateless pod roll): plugin install + provisioning
ConfigMap live in `ai-helm-values` `environments/prod/values/grafana.yaml`, the
gateway-key ExternalSecret + a `self-signed-ca` CA-trust mount + Cilium egress to
`envoy-gateway-system:443` in the `deps/grafana` overlay.

## Why the sync-wave order is load-bearing

```mermaid
flowchart LR
    S["-3 secrets +<br/>allow-same-namespace"] --> ST["-2 stores<br/>(Mimir/Loki/Tempo)"] --> C["-1 collectors<br/>(Alloy)"] --> V["0/1 Grafana +<br/>dashboards"]
    classDef w fill:#eaf3ea,stroke:#4a8a4a;
    class S,ST,C,V w;
```

Collectors before stores = dropped data; visualisation before either = empty
boards. The postmortem of violating this is `MONITORING_FIX.md`.

→ Related: [06 Networking (egress allows)](06-networking-tls.md) · [05 Auth (attribution headers)](05-auth-identity.md)
