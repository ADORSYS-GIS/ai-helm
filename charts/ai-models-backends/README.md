# `ai-models-backends` — leaf

Shared backend infrastructure for the AI gateway. One `Backend` +
`AIServiceBackend` + `BackendSecurityPolicy` + `BackendTLSPolicy` per
upstream provider account.

**ADR:** [`0012`](../../docs/adr/0012-split-ai-models-applicationset.md)
**Consumed by:** every [`ai-model`](../ai-model/) leaf via the
`backendsInventory` value.

## What it renders

For each entry in `.Values.backends` (unless `enabled: false`):

| Resource | Purpose |
|---|---|
| `Backend` (gateway.envoyproxy.io/v1alpha1) | DNS-based upstream endpoint (fqdn + port) |
| `AIServiceBackend` (aigateway.envoyproxy.io/v1alpha1) | Schema declaration (OpenAI / GCP / Bedrock) + prefix path |
| `BackendSecurityPolicy` (aigateway.envoyproxy.io/v1alpha1) | API-key auth via Secret (or GCPCredentials variant) |
| `BackendTLSPolicy` (gateway.networking.k8s.io/v1) | TLS validation against system CA, hostname pin |

## Values

```yaml
backends:
  <backendName>:
    schema: OpenAI                    # | GCPVertexAI | Bedrock
    prefix: "/v1/openai"              # path prefix forwarded upstream
    fqdn:
      hostname: api.example.com
      port: 443
    securityType: APIKey              # | GCPCredentials
    secretRef:
      name: example-api-key           # for APIKey: the Secret holding `apiKey`
    tlsHostname: api.example.com      # if set, BackendTLSPolicy is rendered
    resourceName: example-backend-01-svc  # the K8s name AIServiceBackend etc. take
```

The orchestrator (`ai-models`) populates this from its own `backends:`
map via the `ApplicationSet` element values; this leaf doesn't carry
defaults of its own.

## Audit fix carried in

The pre-split `ai-models` chart didn't gate `BackendSecurityPolicy` on
`enabled: false`, so disabling a backend left a dangling policy
referencing a non-existent `AIServiceBackend`. Fixed in this leaf.

## Verifying

```bash
helm template backends . --set-json 'backends={
  "fw-01": {
    "schema":"OpenAI","prefix":"/inference/v1",
    "fqdn":{"hostname":"api.fireworks.ai","port":443},
    "securityType":"APIKey","tlsHostname":"api.fireworks.ai",
    "secretRef":{"name":"fireworks-api-key-01"},
    "resourceName":"fw-backend-01-svc"
  }
}'
```
