# NetworkPolicy Helm Chart

A generic, reusable NetworkPolicy template for managing policies across multiple namespaces centrally.

## Architecture Model

We use a **hybrid approach** for network policies:

1.  **Co-located Policies (Internal Workloads)**: Internal charts (e.g., `core-gateway`, `librechart`, `mcps`, `ai-models`) define their own network policies using the `network-policy-lib` library chart. This is preferred because it improves maintainability, ensures policies are versioned alongside the application code, and clarifies ownership.
2.  **Centralized Policies (Third-Party Infrastructure)**: This centralized `network-policies` chart is strictly reserved for third-party infrastructure components (e.g., `traefik-system`, `redis-system`, `cnpg-system`, `cert-system`, `opentelemetry-system`, `authorino-system`).

## Ownership Rules

*   **Internal charts MUST define their own policies.** They should depend on the `network-policy-lib` chart and use the `network-policy.full` template.
*   **The centralized chart is ONLY for third-party components.** All policies in this chart must include ownership labels (`network-policy/owned-by` and `network-policy/type: "third-party"`).

## Migration Guide

To move a chart to a co-located policy, follow these steps:

1.  **Add Dependency**: Add the `network-policy-lib` to the chart's `Chart.yaml`:
    ```yaml
    dependencies:
      - name: network-policy-lib
        version: 0.1.0
        repository: "file://../lib/network-policy"
    ```
2.  **Create Template**: Create `templates/networkpolicy.yaml` in the chart:
    ```yaml
    {{ include "network-policy.full" . }}
    ```
3.  **Move Configuration**: Move the relevant policy configuration from the centralized `network-policies/values.yaml` to the chart's `values.yaml`. Ensure selectors match the workload labels in the same chart.
4.  **Remove Centralized Policy**: Delete the old policy from the centralized `network-policies/values.yaml`.

### Example: `core-gateway`

1.  **`charts/core-gateway/Chart.yaml`**:
    ```yaml
    dependencies:
      - name: network-policy-lib
        version: 0.1.0
        repository: "file://../lib/network-policy"
    ```
2.  **`charts/core-gateway/templates/networkpolicy.yaml`**:
    ```yaml
    {{ include "network-policy.full" . }}
    ```
3.  **`charts/core-gateway/values.yaml`**:
    ```yaml
    networkPolicy:
      enabled: true
      name: converse-gateway-otel-security
      podSelector:
        matchLabels:
          app.kubernetes.io/managed-by: opentelemetry-operator
      # ... rest of the policy configuration
    ```

---

## Design Choices

1.  **Self-Contained & Robust**: The template does not depend on external library charts (like `common`), ensuring it can be deployed centrally to manage many namespaces without dependency conflicts.
2.  **Abstractions over Raw YAML**: Instead of forcing users to write complex `podSelector` and `namespaceSelector` blocks for every rule, we provide simple keys like `ingress.namespaces` and `egress.internalServices`.
3.  **Default Security**: DNS egress is enabled by default as it is a fundamental requirement for service discovery in Kubernetes. Egress is otherwise restricted to defined targets.
4.  **Escape Hatches**: The `custom` blocks allow for any advanced NetworkPolicy features not covered by our abstractions, ensuring the template never blocks specialized needs.

---

## Usage

### 1. Centralized Mode (Collective)

Define multiple policies in the `policies` map. This is useful for third-party or legacy namespaces.

```yaml
policies:
  my-app-security:
    namespace: my-namespace
    podSelector:
      matchLabels:
        app: my-app
    ingressNamespaces:
      - name: traefik-system
        ports:
          - port: 8080
    egressDns: true
    egressInternalServices:
      - namespace: redis-system
        ports:
          - port: 6379
```

### 2. Solo Mode (Singleton)

Enable the primary `networkPolicy` block for the current namespace. This uses the new abstraction-based schema.

```yaml
networkPolicy:
  enabled: true
  ingress:
    namespaces:
      - name: traefik-system
        ports:
          - port: 8080
  egress:
    dns: true
    intraNamespace: true
```

### Policy Structure (Centralized)

| Field | Type | Description |
|-------|------|-------------|
| `namespace` | string | **Required**. The target namespace for the policy. |
| `podSelector` | object | Standard Kubernetes pod selector. |
| `policyTypes` | list | Defaults to `[Ingress, Egress]`. |
| `ingress` | list | List of NetworkPolicyIngressRule. |
| `egress` | list | List of NetworkPolicyEgressRule. |

---

## Validation Strategy

When adding new policies, it is critical to verify:
1. **Label Selectors**: Ensure `podSelector.matchLabels` matches real pods (`kubectl get pods -n <ns> --show-labels`).
2. **Namespace Labels**: Ensure `namespaceSelector.matchLabels` matches the `kubernetes.io/metadata.name` label of the target namespace.
3. **Ports**: Ensure ports match the container port or service target port.

For detailed validation steps and examples, see the [demo.md](https://github.com/ADORSYS-GIS/ai-helm/blob/main/Stuffs/demo.md) file.

```bash
helm template charts/network-policies
```
