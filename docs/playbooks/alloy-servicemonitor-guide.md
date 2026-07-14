# Grafana Alloy & ServiceMonitor — Concept Explanation & How-To Guide

## Table of Contents

1. [What is Grafana Alloy?](#what-is-grafana-alloy)
2. [What is a ServiceMonitor?](#what-is-a-servicemonitor)
3. [How They Work Together](#how-they-work-together)
4. [Overhauled Deployment Architecture](#overhauled-deployment-architecture)
5. [How to Add Monitoring for Your Own Service](#how-to-add-monitoring-for-your-own-service)
6. [Debugging & Verification](#debugging--verification)
7. [Phase 2 Preview: External Observability Cluster](#phase-2-preview-external-observability-cluster)

---

## What is Grafana Alloy?

**Grafana Alloy** is a programmable telemetry collector from Grafana Labs. It is the successor to both Grafana Agent and Prometheus Agent. In our cluster, it acts as a lightweight **metrics collection agent** that:
- Discovers what to scrape via Kubernetes ServiceMonitors.
- Buffers metrics locally in a Write-Ahead Log (WAL).
- Forwards metrics to a remote backend.

---

## What is a ServiceMonitor?

A **ServiceMonitor** is a Kubernetes Custom Resource (CRD) that provides a **declarative** way to tell Alloy "scrape this service." Instead of editing a central config file, you simply deploy a ServiceMonitor alongside your app.

---

## Overhauled Deployment Architecture

Our 2026-standard deployment in [values.yaml](file:///home/koufan/ai-helm/charts/apps/values.yaml) includes several "premium" features for production readiness:

### 1. StatefulSet & Clustering
We use a **StatefulSet** (instead of a Deployment) to give Alloy pods stable network identities. This enables **Clustering**, allowing multiple Alloy pods to coordinate and distribute the scrape load automatically.

### 2. Multi-Stage Pipeline
The metrics flow through a structured pipeline inside Alloy:
1. **Discovery**: `prometheus.operator.servicemonitors` watches for all CRDs cluster-wide.
2. **Sanitization**: `prometheus.relabel` acts as a global middle-stage to scrub noisy labels and inject cluster metadata (`cluster_origin="ai-helm"`).
3. **Forwarding**: `prometheus.remote_write` sends data to the destination.

### 3. ArgoCD Sync Resilience
We use `SkipDryRunOnMissingResource=true` in ArgoCD to ensure Alloy can be deployed even while the Prometheus Operator CRDs are still being registered in the API server.

---

## How to Add Monitoring for Your Own Service

### Step 1: Ensure Your Service Exposes Metrics
Your application should expose a Prometheus-format `/metrics` endpoint on a named port (e.g., `metrics` or `http`).

### Step 2: Create a ServiceMonitor
Deploy a ServiceMonitor that selects your Service. Example for `my-api` in namespace `converse`:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: my-api-monitor
  namespace: converse
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: my-api   # Must match your Service labels
  endpoints:
    - port: http                       # Port name in your Service
      path: /metrics
      interval: 60s
  namespaceSelector:
    matchNames:
      - converse
```

Alloy will automatically pick this up within ~60 seconds.

---

## Debugging & Verification

```bash
# List all ServiceMonitors
kubectl get servicemonitor -A

# Check Alloy logs
kubectl logs -n monitoring -l app.kubernetes.io/name=alloy --tail=100

# Open the Alloy UI (The "Source of Truth")
kubectl port-forward -n monitoring svc/alloy 12345:12345
# Navigate to http://localhost:12345 to see the pipeline components and discovered targets.
```

---

## Phase 2 Preview: External Observability Cluster

When the external observability cluster is ready, we will update the `prometheus.remote_write` block in `values.yaml` with the real URL and credentials. Alloy's multi-stage pipeline is already designed to handle this transition seamlessly.
