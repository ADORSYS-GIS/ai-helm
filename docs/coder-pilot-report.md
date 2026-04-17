# Coder Pilot Report

## Executive Summary

This document captures the outcomes and recommendations from the Coder autonomous coding workflow pilot, executed in the `coder` namespace with Keycloak authentication and PostgreSQL (CloudNativePG) backend.

## Pilot Configuration

| Component | Version | Namespace | Details |
|-----------|--------|-----------|---------|
| Coder | 2.32.0 | coder | Helm chart from OCI registry |
| Database | 18.3.0 | coder | CloudNativePG, 2 instances |
| Auth | OIDC | coder | Keycloak (camer-digital realm) |

### Network Exposure
- Coder service exposed via LoadBalancer (NodePort 31934)
- Access URL: `https://coder.ai.camer.digital`
- Workspace wildcard: `*.serverless.coder.ai.camer.digital`

### Resource Allocation
```yaml
Coder Pod:
  CPU: 2 cores (request/limit)
  Memory: 4Gi (request/limit)

PostgreSQL:
  CPU: 500m limit, 250m request
  Memory: 1Gi limit, 512Mi request
  Storage: 10Gi (linode-block-storage)
```

## Observed Performance Metrics

### Resource Consumption (Idle State)
| Pod | CPU | Memory |
|-----|-----|--------|
| coder | 2m | 308Mi |
| postgresql | 7m | 72Mi |
| **Total** | **9m** | **380Mi** |

### Note on Resource Requests
The Coder pod requests 2 CPU cores, which is a high baseline. Actual usage at idle is negligible (~2m).

## Production Assessment Guide

### Key Metrics to Monitor

1. **Workspace Activity**
   - Active workspaces count
   - Workspace build frequency
   - Template usage stats

2. **Resource Utilization**
   - CPU spike during workspace provisioning
   - Memory growth with concurrent users
   - Network I/O for git operations

3. **Authentication Health**
   - OIDC token refresh success rate
   - Keycloak session duration
   - Login failure count

4. **Database Performance**
   - Connection pool usage
   - Query latency
   - Replication lag (replica instance)

### Recommended Monitoring Queries

```bash
# Get Coder pod resource usage
kubectl top pods -n coder

# Check Coder logs for errors
kubectl logs -n coder -l app.kubernetes.io/name=coder --tail=100 | grep -i error

# View active connections to database
kubectl exec -n coder postgresql-0 -- psql -U coder -c 'SELECT count(*) FROM coder_user}'
```

### Health Check Endpoints

| Endpoint | Path | Purpose |
|----------|------|---------|
| Health | `/healthz` | Basic availability |
| Ready | `/readyz` | Service readiness |
| Metrics | `:2112/metrics` | Prometheus (internal) |

## Infrastructure Impact Analysis

### Potential Issues

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Resource exhaustion** | High CPU request (2 cores) may cause scheduling issues | Adjust requests to match actual usage; use HPA |
| **Workspace ephemeral storage** | Container churn increases disk I/O | Separate storage class for workspaces |
| **Git operations** | Network bandwidth spike | Implement rate limiting |
| **Concurrency** | Database connection starvation | Configure connection pooler |
| **Workspace sprawl** | Uncontrolled pod creation | Hard quota on workspace count per user |

### Scaling Considerations
- Current setup: single replica for Coder server
- For high availability: scale to 3+ replicas with load balancer
- Workspaces spawn as ephemeral pods (destroyed on inactivity)

## Rollout Recommendations

### Immediate Actions
1. **Adjust resource requests** - Reduce Coder pod CPU request from 2 cores to 500m-1 core (actual usage is minimal)
2. **Add Ingress** - Configure proper Ingress with TLS termination instead of NodePort
3. **Set quota** - Apply Kubernetes ResourceQuota for workspace namespace

### Pre-Full-Rollout Requirements
1. Define workspace templates (development, review, CI runner)
2. Implement usage tracking and cost allocation tags
3. Establish timeout policies for idle workspaces
4. Document user onboarding flow

### Future Enhancements
- Enable workspace templates for specific workflows
- Integrate with GitHub/GitLab for automated PR environments
- Add audit logging for compliance
- Implement MCP server for internal tooling

## Conclusion

The pilot validates that Coder is operational with Keycloak authentication and PostgreSQL backend. The system is stable at idle with minimal resource consumption. Key next steps before broader rollout:

1. Right-size resource allocations
2. Add proper Ingress configuration
3. Define workspace quotas and limits

---
*Generated: April 2026*
*Namespace: coder*