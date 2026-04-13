# Artillery Load Testing Configurations

This directory contains Artillery configurations for testing different layers of the AI gateway stack.

## Directory Structure

```
artillery/
├── direct-provider/     # Direct calls to AI providers (baseline)
│   ├── artillery-direct-gemini.yml
│   └── artillery-direct-fireworks.yml
├── models-proxy/        # Tests targeting LiteLLM (models-proxy) directly
│   ├── artillery-models-proxy-latency.yml
│   └── artillery-models-proxy-load.yml
└── gateway/             # Tests through the full gateway stack
    ├── artillery-gateway-latency.yml
    ├── artillery-gateway-load.yml
    ├── artillery-lua-overhead.yml
    └── artillery-authorino-load.yml
```

## Prerequisites

```bash
# Install Artillery
npm install -g artillery

# Install just (command runner)
# macOS: brew install just
# Linux: cargo install just
# See: https://github.com/casey/just

# Set required environment variables
export LIGHTBRIDGE_API_KEY="your-lightbridge-key"    # For gateway tests
export GEMINI_API_KEY="your-gemini-key"              # For Gemini/LiteLLM tests
export FIREWORKS_API_KEY="your-fireworks-key"        # For direct Fireworks tests

# Note: Artillery uses {{ $processEnvironment.VAR_NAME }} syntax for env vars
```

## Quick Start with just

The `justfile` automates test execution:

```bash
# Show all available commands
just

# Run complete test suite
just all

# Run specific test layer
just direct-gemini
just models-proxy-latency
just gateway-load

# View summary comparison
just summary

# Check Kubernetes resources
just resources
```

## Test Execution Order

### 1. Direct Provider Tests (Baseline)

These establish the raw AI provider latency without any infrastructure overhead.

```bash
# Direct to Google AI Studio
artillery run direct-provider/artillery-direct-gemini.yml -o report-direct-gemini.json
artillery report report-direct-gemini.json --output report-direct-gemini.html

# Direct to Fireworks AI
artillery run direct-provider/artillery-direct-fireworks.yml -o report-direct-fireworks.json
artillery report report-direct-fireworks.json --output report-direct-fireworks.html
```

### 2. Models-Proxy Tests (LiteLLM Layer)

Tests the LiteLLM proxy directly, bypassing the gateway.

```bash
# Port-forward to models-proxy
kubectl port-forward svc/models-proxy 4000:4000 -n converse-proxy &

# Latency test
artillery run models-proxy/artillery-models-proxy-latency.yml -o report-models-proxy.json
artillery report report-models-proxy.json --output report-models-proxy.html

# Load test
artillery run models-proxy/artillery-models-proxy-load.yml -o report-models-proxy-load.json
artillery report report-models-proxy-load.json --output report-models-proxy-load.html
```

### 3. Gateway Tests (Full Stack)

Tests through the complete gateway stack (Envoy + Authorino + Lua).

```bash
# Latency test
artillery run gateway/artillery-gateway-latency.yml -o report-gateway.json
artillery report report-gateway.json --output report-gateway.html

# Load test
artillery run gateway/artillery-gateway-load.yml -o report-gateway-load.json
artillery report report-gateway-load.json --output report-gateway-load.html

# Authorino-focused load test
artillery run gateway/artillery-authorino-load.yml -o report-authorino.json
artillery report report-authorino.json --output report-authorino.html
```

### 4. Lua Overhead Test

Measures the overhead of the Lua cost calculation policy.

```bash
# Step 1: Baseline WITH Lua
artillery run gateway/artillery-lua-overhead.yml -o report-with-lua.json

# Step 2: Disable Lua policy
kubectl patch envoyextensionpolicy -n converse-gateway core-gateway-telemetry-lua \
  --type=json -p='[{"op":"replace","path":"/spec/lua","value":[]}]'
sleep 30  # Wait for Envoy to reload

# Step 3: Measurement WITHOUT Lua
artillery run gateway/artillery-lua-overhead.yml -o report-without-lua.json

# Step 4: Re-enable Lua policy (IMPORTANT!)
kubectl rollout restart deployment/envoy -n converse-gateway
kubectl rollout status deployment/envoy -n converse-gateway

# Step 5: Generate reports
artillery report report-with-lua.json --output report-with-lua.html
artillery report report-without-lua.json --output report-without-lua.html
```

## Report Generation

The `artillery report` command is deprecated. We use a custom HTML report generator instead.

### Generate HTML Reports

```bash
# Generate HTML for a specific JSON report
just report report-direct-gemini

# Generate HTML for all existing JSON reports
just reports-all

# View console summary without generating HTML
just view report-direct-gemini

# Or use the script directly
node generate-report.js reports/report-direct-gemini.json
```

### HTML Report Features

The generated HTML reports include:
- **Summary metrics**: Total requests, success rate, errors, timeouts
- **Latency distribution**: Min, mean, median, p75, p90, p95, p99, max
- **Per-phase breakdown**: Charts and tables showing metrics per test phase
- **Raw counters**: All Artillery counter metrics in tabular format
- **Color-coded status**: Green/yellow/red indicators for quick assessment

### Thresholds Used

| Metric | Good (green) | Warning (yellow) | Critical (red) |
|--------|--------------|------------------|----------------|
| Success rate | ≥99.9% | 99-99.9% | <99% |
| p95 latency | ≤500ms | 500-1000ms | >1000ms |
| p99 latency | ≤1000ms | 1000-2000ms | >2000ms |
| Max latency | ≤2000ms | 2000-5000ms | >5000ms |

## Latency Comparison Analysis

After running all tests, compare the latencies to identify bottlenecks:

| Layer | Config File | Expected Overhead |
|-------|-------------|-------------------|
| Direct Provider | `direct-provider/artillery-direct-gemini.yml` | Baseline (0ms) |
| Models-Proxy | `models-proxy/artillery-models-proxy-latency.yml` | +5-20ms |
| Gateway | `gateway/artillery-gateway-latency.yml` | +10-50ms |

### Calculating Overhead

```bash
# Extract p50 latency from each report
jq '.aggregate.latency.median' report-direct-gemini.json
jq '.aggregate.latency.median' report-models-proxy.json
jq '.aggregate.latency.median' report-gateway.json

# Overhead calculations:
# LiteLLM overhead = models-proxy - direct-provider
# Gateway overhead = gateway - models-proxy
# Total overhead   = gateway - direct-provider
```

## Output Files

All tests generate JSON reports that can be converted to HTML:

| File | Description |
|------|-------------|
| `report-direct-*.json` | Direct provider baseline results |
| `report-models-proxy*.json` | LiteLLM layer results |
| `report-gateway*.json` | Full gateway stack results |
| `report-with-lua.json` | Gateway with Lua policy enabled |
| `report-without-lua.json` | Gateway with Lua policy disabled |

## Model Reference

The tests use these models from the ai-models chart:

| Model | Backend | Route |
|-------|---------|-------|
| `gemini-2.5-flash` | models-proxy | Gemini via LiteLLM |
| `qwen3-8b` | Fireworks direct | Fireworks AI |
