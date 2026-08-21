# poc-ubuntu

A minimal Coder template for verifying the declarative delivery mechanism
decided in [ADR-0124](../../../docs/adr/0124-declarative-coder-template-management.md).

It provisions a single Kubernetes pod based on
`codercom/enterprise-base:ubuntu` (in the `coder` namespace) and runs a
`coder_agent`. It is intentionally **not** a production template — it exists to
prove that a template can be delivered from git via the `coder/coderd` Terraform
provider instead of `coder templates push`.

> ⚠️ **Ephemeral:** the pod has **no PVC**, so the workspace loses its files on
> pod deletion/restart. That's deliberate for a mechanism proof, but worth
> knowing before copying this template.

The template lifecycle is managed from [`terraform/coder`](../../../terraform/coder/README.md).
