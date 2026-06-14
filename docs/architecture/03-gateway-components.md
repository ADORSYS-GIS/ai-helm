# 03 · Gateway components & the request path (C4 Level 3)

Zoom into the **load-bearing block**: how one inference request crosses the
Envoy AI Gateway, gets authenticated, rate-limited, routed to a provider, and
metered. This is the layer where latency and correctness live.

## Components inside the gateway

```mermaid
flowchart TB
    CLIENT["client (HTTP/2)"]:::ext

    subgraph dp["Envoy data plane (eg) — HPA 3–5, LeastRequest LB"]
        LISTEN["Listeners<br/><b>external</b>: api.ai.camer.digital (ACME TLS)<br/><b>internal</b>: core-gateway-internal.svc (self-signed CA)"]:::own
        FILTER["HTTP filter chain<br/>ext_authz → ratelimit → router"]:::own
    end

    subgraph authz["Authorino (authorino-system, 2 replicas)"]
        AC["AuthConfig per Host (ADR-0021)<br/>verify JWT (JWKS, ttl 3600)<br/>stamp x-oidc-* + descriptors"]:::own
    end

    subgraph route["AI Gateway CRs (per model)"]
        AIR["AIGatewayRoute<br/><i>model name → backend</i>"]:::own
        BTP["BackendTrafficPolicy<br/><i>burst + monthly budget + circuit breaker</i>"]:::own
        ASB["AIServiceBackend<br/><i>provider mapping + key</i>"]:::own
    end

    PROV["Provider<br/>DeepInfra / Fireworks / Google AI"]:::ext
    GPU["Self-hosted model<br/>(llama.cpp, home GPU)"]:::gpu
    REDIS["redis-ha<br/><i>ratelimit counters</i>"]:::ext
    OBS["Alloy → Loki / Mimir<br/><i>access log + counters</i>"]:::own

    CLIENT --> LISTEN --> FILTER
    FILTER -->|"gRPC ext_authz"| AC
    AC -->|allow + headers| FILTER
    FILTER -->|descriptors| REDIS
    FILTER --> AIR --> BTP --> ASB
    ASB --> PROV
    ASB --> GPU
    FILTER -->|"JSON access log"| OBS

    classDef own fill:#eaf3ea,stroke:#4a8a4a,color:#1a401a;
    classDef ext fill:#eee,stroke:#888,color:#333,stroke-dasharray:4 3;
    classDef gpu fill:#f7e8f0,stroke:#a54a81,color:#401a2e;
```

| Component | CR / chart | Responsibility |
|---|---|---|
| **Listeners** | `Gateway` (`core-gateway`) | Terminate TLS; split external (public, ACME) vs internal (ClusterIP, self-signed CA) planes |
| **ext_authz** | `SecurityPolicy` → Authorino | Call Authorino over gRPC before routing |
| **AuthConfig** | `kuadrant-policies` | Per-`Host` JWT verification; stamp `x-oidc-*` + `x-account-id`/`x-org-id`/`x-billing-plan` |
| **ratelimit** | `BackendTrafficPolicy` + Redis | Burst (req/min, tokens/min, per user) + monthly USD budget (per user, ADR-0035) |
| **AIGatewayRoute** | `ai-model` leaf | Map an OpenAI model id → an `AIServiceBackend` |
| **AIServiceBackend** | `ai-models-backends` | Provider endpoint + credential + token-cost metadata (`llmRequestCosts`) |
| **access log** | `core-gateway` | Emit per-request JSON (carrying `x-oidc-*`) to Alloy |

## Runtime view — the four canonical request paths

### A · Developer via opencode (external plane, full attribution)

```mermaid
sequenceDiagram
    autonumber
    participant C as opencode CLI
    participant E as Envoy (external)
    participant A as Authorino
    participant R as Redis
    participant P as Provider
    participant O as Alloy→Loki/Mimir

    C->>E: POST /v1/chat/completions (Bearer JWT)
    E->>A: ext_authz (the JWT)
    A->>A: verify (JWKS) — read sub, azp, billing_plan
    A-->>E: 200 + x-oidc-*, x-account-id=sub, x-billing-plan
    E->>R: check burst + monthly budget buckets
    alt budget/burst exhausted
        R-->>E: over limit
        E-->>C: 429 Too Many Requests
    else within limits
        E->>P: proxy request (provider key injected)
        P-->>E: completion (+ token usage)
        E-->>C: 200 stream
        E->>O: JSON access log {user_id, azp, model, cost}
    end
```

### B · Human via LibreChat (internal plane, service-level attribution)

```mermaid
sequenceDiagram
    autonumber
    participant U as Browser
    participant L as LibreChat
    participant E as Envoy (internal)
    participant A as Authorino

    U->>L: chat (Keycloak session)
    L->>E: /v1 call to core-gateway-internal.svc
    Note over L,E: apiKey OR k8s SA token<br/>+ X-LibreChat-User: (end-user sub)
    E->>A: ext_authz (internal AuthConfig)
    A->>A: prefer X-LibreChat-User → x-account-id<br/>plan = internal (uncapped, burst-only)
    A-->>E: 200 + descriptors
    E->>E: route → provider as path A
```

### C · CI runner via GitHub OIDC (the repo-auth binding)

```mermaid
sequenceDiagram
    autonumber
    participant W as GitHub Actions
    participant E as Envoy (external)
    participant A as Authorino
    participant RA as lightbridge-repo-auth

    W->>W: mint GHA OIDC token (audience = org Source URL)
    W->>E: /v1 call (Bearer GHA-OIDC)
    E->>A: ext_authz
    A->>A: verify (github issuer), then github-actions →
    A->>RA: POST /v1/resolve (JSON body: repository_owner_id)
    alt owner bound & not blocked
        RA-->>A: {account_id, billing_plan}
        A-->>E: 200 + x-account-id, x-billing-plan
        E->>E: route → provider
    else unbound / blocked
        RA-->>A: 403
        A-->>E: deny
        E-->>W: 403
    end
```

### D · MCP tool call (`/mcp/*` — Authorino carve-out)

`/mcp/*` routes **displace** the gateway-attached Authorino policy with
Envoy-native JWT verification (same Keycloak issuer). Full detail in
[10 MCP](10-mcp.md).

```mermaid
sequenceDiagram
    autonumber
    participant C as MCP client
    participant E as Envoy (native jwt_authn)
    participant M as MCP server / proxy

    C->>E: GET /.well-known/oauth-protected-resource/mcp/(name)
    E-->>C: 200 RFC 9728 metadata (unauthenticated)
    C->>E: POST /mcp/(name) (Bearer Keycloak JWT)
    E->>E: native jwt_authn (Keycloak issuer)<br/>claimToHeaders → x-oidc-*
    E->>M: forward to in-cluster MCP backend
    M-->>C: tool result
```

## Why the gateway can scale

| Concern | Mechanism | Where |
|---|---|---|
| Throughput | HTTP/2 multiplexing + data-plane HPA `3→5` (right-sized to the 32-CPU worker pool), LeastRequest LB | `ClientTrafficPolicy` / `EnvoyProxy` |
| Fairness | Per-user burst + per-user monthly budget | `BackendTrafficPolicy` + Redis |
| Resilience | Circuit breaker + outlier detection (eject erroring backend ≤30 s) | `BackendTrafficPolicy` |
| Zero-cut rollout | 60 s drain (`minDrainDuration` 15 s); PDB `maxUnavailable: 1` | `EnvoyProxy` |
| Cost metering | Native `llmRequestCosts` token extraction (no Lua/Python hop) | `AIGatewayRoute` |

→ Subsystems: [05 Auth](05-auth-identity.md) · [09 Model serving](09-model-serving.md) · [08 Observability](08-observability.md)
