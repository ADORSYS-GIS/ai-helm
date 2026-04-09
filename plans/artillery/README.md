# Artillery Load Testing Configurations

This directory contains Artillery configurations for investigating gateway performance issues tracked in [Issue #98](https://github.com/ADORSYS-GIS/ai-helm/issues/98).

## Prerequisites

```bash
# Install Artillery
npm install -g artillery

# Verify installation
artillery --version

# Set required environment variables
export GEMINI_API_KEY="your-gemini-api-key"
export LIGHTBRIDGE_API_KEY="your-lightbridge-api-key"
```

## Configuration Files

| File | Purpose | Risk Level | Duration |
|------|---------|------------|----------|
| `artillery-latency-comparison.yml` | Compare direct LiteLLM vs gateway latency | Low | 1 min |
| `artillery-lua-overhead.yml` | Measure Lua policy overhead | Medium | 2 min |
| `artillery-load-test.yml` | Find LiteLLM throughput limits | Medium | 8 min |
| `artillery-gateway-load.yml` | Full gateway stack load test | Medium | 6 min |

## Quick Start

### Test 1: Latency Comparison

```bash
# Port-forward to LiteLLM
kubectl port-forward svc/litellm 4000:4000 -n converse-proxy &

# Test direct LiteLLM
artillery run artillery-latency-comparison.yml -o report-direct.json

# Test through gateway (override target)
artillery run artillery-latency-comparison.yml \
  --target https://api.ai.camer.digital \
  -o report-gateway.json \
  --overrides '{"config":{"defaults":{"headers":{"Authorization":"Bearer $LIGHTBRIDGE_API_KEY","x-ai-eg-model":"gemini-2.5-flash"}}}}'

# Generate reports
artillery report report-direct.json --output report-direct.html
artillery report report-gateway.json --output report-gateway.html
```

### Test 2: Lua Overhead

```bash
# Baseline with Lua enabled
artillery run artillery-lua-overhead.yml -o report-with-lua.json

# Disable Lua policy
kubectl patch envoyextensionpolicy -n converse-gateway core-gateway-telemetry-lua \
  --type=json -p='[{"op":"replace","path":"/spec/lua","value":[]}]'
sleep 30

# Test without Lua
artillery run artillery-lua-overhead.yml -o report-without-lua.json

# Re-enable Lua policy
kubectl rollout restart deployment/envoy -n converse-gateway
kubectl rollout status deployment/envoy -n converse-gateway

# Generate reports
artillery report report-with-lua.json --output report-with-lua.html
artillery report report-without-lua.json --output report-without-lua.html
```

### Test 3: LiteLLM Load Test

```bash
# Port-forward to LiteLLM
kubectl port-forward svc/litellm 4000:4000 -n converse-proxy &

# Run phased load test
artillery run artillery-load-test.yml -o report-load-test.json

# Generate report
artillery report report-load-test.json --output report-load-test.html
```

### Test 4: Gateway Load Test

```bash
# Run full gateway load test
artillery run artillery-gateway-load.yml -o report-gateway-load.json

# Generate report
artillery report report-gateway-load.json --output report-gateway-load.html
```

## Output Files

Each test generates:
- `report-*.json` - Raw metrics data (can be queried with `jq`)
- `report-*.html` - Visual report with charts

## Quick Metrics Extraction

```bash
# Extract latency percentiles from JSON report
jq '.aggregate.latency' report-load-test.json

# Extract per-phase metrics
jq '.aggregate.phases' report-load-test.json

# Extract error rate
jq '.aggregate.errors' report-load-test.json

# Extract requests per second
jq '.aggregate.rps' report-load-test.json
```

## Interpreting Results

### Latency Comparison
- **Direct LiteLLM latency** = LiteLLM processing + provider API
- **Gateway latency** = Envoy + Authorino + Lua + LiteLLM + provider API
- **Gateway overhead** = Gateway latency - Direct LiteLLM latency

### Lua Overhead
- **Lua overhead** = With Lua latency - Without Lua latency
- If overhead > 10ms, optimization is worth pursuing

### Load Test
- Look for latency degradation at higher RPS
- Note the RPS where p95 latency doubles
- Check for error rate spikes

### Gateway Load Test
- Compare Fireworks direct vs. LiteLLM proxied latency
- Check if streaming requests have different latency profile
- Identify if Authorino becomes a bottleneck under load
