# poc-ubuntu

A minimal Coder template for verifying the declarative delivery mechanism
decided in [ADR-0123](../../../docs/adr/0123-declarative-coder-template-management.md).

It provisions a single Kubernetes pod based on
`codercom/enterprise-base:ubuntu` (in the `coder` namespace) and runs a
`coder_agent` with a small startup script (installs `git`, `curl`). It is
intentionally **not** a production template — it exists to prove that a template
can be delivered from git via the `coder/coderd` Terraform provider instead of
`coder templates push`.

The template lifecycle is managed from [`terraform/coder](../../../terraform/coder/README.md)`.
