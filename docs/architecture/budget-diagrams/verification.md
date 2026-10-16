# Budget Flow Verification

Last refreshed: 2026-09-29, against the current Kubernetes context from `/home/koufan/dev/ai-helm`.

## Live process and image check

Read-only command:

```bash
kubectl get pods,deployments -A -o wide | rg "lightbridge|authorino|envoy|gateway|usage|budget|authz"
```

Observed budget-relevant deployments:

| Namespace | Deployment | Replicas | Container image |
|---|---:|---:|---|
| `converse` | `lightbridge-api-main` | 2/2 | `ghcr.io/adorsys-gis/lightbridge-authz:sha-5cfad5ca39c5bae3b5e2d65dfbc107652a82356b` |
| `converse` | `lightbridge-budget-main` | 1/1 | `ghcr.io/adorsys-gis/lightbridge-authz:sha-5cfad5ca39c5bae3b5e2d65dfbc107652a82356b` |
| `converse` | `lightbridge-idp-main` | 2/2 | `ghcr.io/adorsys-gis/lightbridge-authz:sha-5cfad5ca39c5bae3b5e2d65dfbc107652a82356b` |
| `converse` | `lightbridge-opa-main` | 2/2 | `ghcr.io/adorsys-gis/lightbridge-authz:sha-5cfad5ca39c5bae3b5e2d65dfbc107652a82356b` |
| `converse` | `lightbridge-usage-main` | 2/2 | `ghcr.io/adorsys-gis/lightbridge-authz-usage:sha-5cfad5ca39c5bae3b5e2d65dfbc107652a82356b` |
| `converse-gateway` | `kuadrant-policies-main` | 2/2 | `quay.io/kuadrant/authorino:v0.24.0` |
| `converse-gateway` | `core-gateway-usage-collector` | 1/1 | `ghcr.io/open-telemetry/opentelemetry-collector-releases/opentelemetry-collector-k8s:0.159.0` |
| `envoy-gateway-system` | `envoy-converse-gateway-core-gateway-c480b207` | 3/3 | `docker.io/envoyproxy/envoy:distroless-v1.38.3`, `docker.io/envoyproxy/gateway:v1.8.2` |
| `envoy-gateway-system` | `envoy-ratelimit` | 2/2 | `docker.io/envoyproxy/ratelimit:f2fb1577` |

## Source revision note

The live authz image tag `sha-5cfad5ca39c5bae3b5e2d65dfbc107652a82356b` was not present in the local `lightbridge-authz` checkout at verification time. The architecture document therefore cites local source paths for implementation structure and records the live deployment image separately here.

Local checkout observed:

```bash
git -C /home/koufan/dev/lightbridge-authz rev-parse HEAD
```

Result:

```text
3f13667bf5f2efe26a0501fd8a5cf18311c5a706
```

## Usage collector spot check

Read-only command:

```bash
kubectl logs -n converse-gateway deployment/core-gateway-usage-collector --tail=80 --since=15m
```

Observed on 2026-09-29: the sample showed repeated exporter attempts to `https://lightbridge-usage.converse.svc.cluster.local:3000/v1/otel/logs` and did not show the prior `HTTP Status Code 400` / dropped-batch pattern in that 15-minute window.

This does not prove historical usage completeness. The 2026-09-15 investigation did observe repeat 400/drop logs, so the diagrams keep that as a known failure mode rather than a current outage claim.
