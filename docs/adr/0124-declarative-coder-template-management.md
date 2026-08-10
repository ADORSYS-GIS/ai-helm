# ADR-0124: Declarative Coder template management via the `coder/coderd` Terraform provider

**Status:** Accepted
**Date:** 2026-08-03
**Deciders:** @stephane-segning

## Context

Coder workspace templates are currently pushed to the live Coder deployment
imperatively with `coder templates push` (from ticket #834's parent epic #822,
which wants workspaces reproducible from git, no manual CLI push required for a
fresh cluster). `coder templates push` is stateless: no version control of the
deployment action, no rollback, and no drift detection — reasons enough to
retire it from the production workflow.

Coder ships a first-party Terraform provider, `coder/coderd` (registry
`coder/coderd`, current release `v0.0.22`, requires Coder `>= 2.10.1`; our
deployment runs **v2.34.6** via the `coder.image.tag` override in
`ai-helm-values` prod `coder-app.yaml`; the latest **stable** Coder release is
**v2.34.7** and **mainline** is **v2.35.3**, verified online 2026-08-07).
Its `coderd_template`
resource manages the full template lifecycle — create, version from a
directory, activate/deactivate, ACLs (Enterprise), TTL/dormancy, deprecation —
declaratively. Research (verified against the provider's current documentation,
Aug 2026) found no parity gap that blocks adopting it over `push`.

## Decision

**Adopt the `coder/coderd` Terraform provider to manage Coder workspace
templates declaratively from the `ai-helm` monorepo via GitOps, and retire
`coder templates push` in the production workflow.**

- Template **source** (the Terraform defining a workspace) lives in
  `.coder/templates/<name>/` in Git.
- Template **lifecycle** lives in `terraform/coder/` (`coderd_template`
  resources, `versions[].directory` pointing at the source, remote state on
  **Hetzner Object Storage** via the S3-compatible backend, Git-SHA-encoded
  version names). The provider content-hashes each template directory at plan
  time and creates a new Coder version when the hash changes; the SHA-in-name
  gives each new content-hash a distinct, traceable version name.
- Deployment flows through a GitOps pipeline (PR validates via
  `terraform plan`; merge to `main` runs `terraform apply`; optional scheduled
  reconciliation detects drift).
- New/fresh Coder deployments reproduce templates from Git + a token with
  **empty** Terraform state — no manual `coder templates push`. (State from a
  previous deployment holds stale template/version UUIDs and must be discarded
  (`terraform state rm`) or kept under a separate state key first.)

## Consequences

**Positive**
- Single source of truth via Terraform remote state; deterministic,
  reproducible template delivery from git.
- Drift detection (`terraform plan`) and rollback (revert git / restore state)
  where the CLI has none.
- Full audit trail through PR review; aligns with the platform's existing IaC/
  GitOps conventions.

**Negative**
- One-time overhead importing already-pushed templates: `terraform import`
  works but existing versions must be manually re-declared in `templates.tf`
  to reach "no drift".
- Version **names** must change when directory contents (or `tf_vars`) change
  (Coder identifies versions by name), so the Git SHA is encoded into each
  version name to guarantee a unique label per content change.
- Some Enterprise attributes (e.g. `max_port_share_level`) can need a second
  apply after first creation; global/workspace server settings are not in the
  provider and remain UI/Helm-managed (server-level admin tracked separately).

**Neutral / follow-ups**
- Building the actual custom workspace templates (`.coder/templates/`) is out
  of scope here — tracked as a follow-up ticket; deliver per the pattern doc.
- Provider is young (`v0.0.x`); pin the version in `required_providers` and
  test upgrades before adopting a new release.
- New secret surface & runner: the pipeline needs a Coder admin token and S3
  credentials as GitHub Actions secrets — the repo's ESO → cluster secret flow
  does not reach Actions, so a provisioning/rotation owner must be stated — and
  the follow-up workflow should run on `adorsys-gis-runner` (GitHub-hosted
  runners are billing-blocked org-wide).

## Alternatives considered

- **CLI-only (`coder templates push`)** — rejected: stateless, not
  GitOps-compliant, no drift detection or rollback. (This is also the repo's
  **first** Terraform surface and its first Actions-driven `terraform apply` —
  a second delivery mechanism alongside ArgoCD continuous delivery, ADR-0055.)
- **REST API + custom scripts** — rejected: still imperative, DIY automation
  with no state management, reinvents what the provider already does.
- **Helm values / Argo CD App as the delivery mechanism** — rejected: Coder
  does not expose templates as Helm values, and Argo CD is for cluster
  resources, not a stateful Coder template store; GitHub Actions +
  `terraform apply` is the declared source of truth (Argo CD only for drift
  visibility).

## Related

- Docs: [`docs/patterns/coder-declarative-templates.md`](../patterns/coder-declarative-templates.md)
  (the *how*: verified facts, parity table, repo layout, implementation pattern)
- ADRs: [0083](./0083-coder-re-introduction.md) (the parent decision that put
  Coder in the platform), [0121](./0121-coder-workspace-url-exposure-strategy.md)
  (Coder workspace URL exposure — cross-referenced in both directions)
- Tickets: [#834](https://github.com/ADORSYS-GIS/ai-helm/issues/834)
  (this spike), epic #822
- External references:
  [provider registry](https://registry.terraform.io/providers/coder/coderd/latest),
  [provider source](https://github.com/coder/terraform-provider-coderd),
  [`coderd_template` resource](https://registry.terraform.io/providers/coder/coderd/latest/docs/resources/template),
  [`coder templates push`](https://coder.com/docs/reference/cli/templates_push),
  [templates as modules](https://coder.com/docs/admin/templates/extending-templates/modules),
  [provider GitOps announcement](https://coder.com/blog/release-recap-2-15-0)
