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
| `ExternalSecret` (external-secrets.io/v1) | Materialises the APIKey `secretRef.name` Secret (key `apiKey`) from `ssegning-aws` — one per **unique** secret name, only when the backend carries an `externalSecret` block. See below. |

## API-key ExternalSecrets

Each APIKey backend can OWN its key Secret instead of relying on an
out-of-band app (the old `aii-secret`). Set `externalSecrets.enabled: true`
(default) and give the backend an `externalSecret: {key, property}` block
pointing at the `ssegning-aws` remoteRef; the chart renders one
`ExternalSecret` per **unique** `secretRef.name` (deduped — backends sharing one
Secret name render once; distinct keys need distinct names) with the provider
key under `apiKey`.

> ⚠️ **Cutover:** while `aii-secret` still provisions these same Secret
> names, ESO would have two owners. Remove each Secret from `aii-secret` as
> its chart-owned `ExternalSecret` here goes live.

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
    externalSecret:                   # optional: chart owns the key Secret
      key: prod/meta/example          # ssegning-aws remoteRef key
      property: example_api_key       # property holding the API key

externalSecrets:
  enabled: true                       # render the ExternalSecrets above
  secretStore: ssegning-aws
  refreshInterval: 1h
  apiKeyDataKey: apiKey               # data key the BackendSecurityPolicy reads
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
