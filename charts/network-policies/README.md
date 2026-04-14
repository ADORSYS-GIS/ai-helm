# NetworkPolicy Helm Chart

A generic, reusable NetworkPolicy template for managing policies across multiple namespaces centrally.

## Design Choices

1.  **Self-Contained & Robust**: The template does not depend on external library charts (like `common`), ensuring it can be deployed centrally to manage many namespaces without dependency conflicts.
2.  **Abstractions over Raw YAML**: Instead of forcing users to write complex `podSelector` and `namespaceSelector` blocks for every rule, we provide simple keys like `ingress.namespaces` and `egress.internalServices`.
3.  **Default Security**: DNS egress is enabled by default as it is a fundamental requirement for service discovery in Kubernetes. Egress is otherwise restricted to defined targets.
4.  **Escape Hatches**: The `custom` blocks allow for any advanced NetworkPolicy features not covered by our abstractions, ensuring the template never blocks specialized needs.

---

## Migration Approach (Centralized to Per-Chart)

Our long-term goal is to move from this centralized repository to a **per-chart approach**, where each application chart owns its own `networkpolicy.yaml`.

1.  **Extract**: Identify the rules for component `X` in these `values.yaml`.
2.  **Add**: Copy the reference template to `charts/X/templates/`.
3.  **Config**: Map the old rules to the new `networkPolicy` schema in `charts/X/values.yaml`.
4.  **Test**: Dry-run with `helm template`.
5.  **Remove**: Delete the old rules from this centralized chart.

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
