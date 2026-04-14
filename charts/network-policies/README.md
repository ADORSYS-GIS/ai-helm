# NetworkPolicy Helm Chart

A generic, reusable NetworkPolicy template for managing policies across multiple namespaces centrally.

## Features

- **Multi-Namespace Support**: Define policies for any namespace from a single `values.yaml`.
- **Flexible Rules**: Full support for Kubernetes Ingress and Egress rules via `toYaml`.
- **Default Deny Strategy**: Easily implement "deny-all" policies by defining a policy with an empty `podSelector` and no rules.

---

## Usage

Define your policies in the `policies` map in `values.yaml`:

```yaml
policies:
  # Example: Default Deny All for a namespace
  my-namespace-default-deny-all:
    namespace: my-namespace

  # Example: Allow traffic from a specific namespace
  my-app-ingress:
    namespace: my-namespace
    podSelector:
      matchLabels:
        app: my-app
    ingress:
      - from:
          - namespaceSelector:
              matchLabels:
                kubernetes.io/metadata.name: traefik-system
        ports:
          - protocol: TCP
            port: 8080
```

### Policy Structure

Each policy in the `policies` map supports the following fields:

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
