# ArgoCD Sync Wave Pattern for Monitoring Stacks

## The Pattern

When deploying observability stacks with ArgoCD, follow this sync wave order:

```
Wave -3: Namespace infrastructure (optional, if separate from apps)
Wave -2: Storage backends (Mimir, Loki, Tempo) + ResourceQuota/LimitRange
Wave -1: Data collectors (Alloy, Prometheus Agent, Fluent Bit)
Wave  0: Visualization & UI (Grafana)
Wave +1: Dashboards, alerts, and other config
```

## Why This Order?

### 1. Storage Before Collection
**Collectors need endpoints to send data to.**

- Alloy sends metrics to `mimir-nginx.monitoring.svc`
- Alloy sends logs to `loki-gateway.monitoring.svc`
- If these services don't exist, Alloy will error or buffer indefinitely

### 2. Namespace Infrastructure First
**ResourceQuotas and LimitRanges must exist before pods are created.**

- If a collector creates the namespace first, it may apply incorrect defaults
- The storage backend should own the namespace setup (it's the largest consumer)
- Quotas can't be easily updated once pods are running against them

### 3. Visualization Last
**Grafana needs datasources to be healthy.**

- Grafana datasources point to Mimir, Loki, and Tempo
- If these aren't ready, Grafana will show datasource errors
- Better to wait and have a clean startup

## Applied to This Repository

### Before (Anti-Pattern) ❌
```yaml
- name: alloy
  sync-wave: "-2"    # Collector first
- name: mimir
  sync-wave: "-1"    # Storage second
- name: loki
  sync-wave: "-1"
- name: tempo
  sync-wave: "-1"
- name: grafana
  sync-wave: "0"
```

**Problem:** Alloy created the namespace with a 512Mi quota, blocking Mimir's correct 8Gi quota.

### After (Correct Pattern) ✅
```yaml
- name: mimir
  sync-wave: "-2"    # Storage first (owns namespace + quota)
- name: loki
  sync-wave: "-2"
- name: tempo
  sync-wave: "-2"
- name: alloy
  sync-wave: "-1"    # Collector second (sends to storage)
- name: grafana
  sync-wave: "0"     # Visualization last
```

**Benefit:** Mimir creates namespace with correct quota, Alloy finds healthy endpoints, Grafana starts clean.

## General Kubernetes Deployment Patterns

This pattern extends beyond monitoring:

### Application Stack
```
Wave -2: Databases (PostgreSQL, Redis)
Wave -1: Backend APIs
Wave  0: Frontend apps
Wave +1: Ingress routes
```

### Data Pipeline
```
Wave -2: Storage (S3, databases)
Wave -1: Processors (Kafka, Spark)
Wave  0: Producers (apps, collectors)
Wave +1: Consumers (analytics, dashboards)
```

## Key Principle

**Dependencies deploy before dependents.**

If A needs B to function:
- B gets a lower (more negative) sync wave
- A gets a higher sync wave
- ArgoCD ensures B is healthy before starting A

## References

- [ArgoCD Sync Waves Documentation](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-waves/)
- [Kubernetes Resource Quotas Best Practices](https://kubernetes.io/docs/concepts/policy/resource-quotas/)
- Content was rephrased for compliance with licensing restrictions

## Related Files

- `MONITORING_FIX.md` - Detailed fix for the quota issue
- `charts/apps/values.yaml` - Application definitions with sync waves
