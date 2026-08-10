# Declarative Coder Template Management

> **Decision:** Adopt the `coder/coderd` Terraform provider to manage Coder
> workspace templates declaratively from Git, and retire `coder templates push`.
> This is the "how" — the "why" is [ADR-0124](./../adr/0124-declarative-coder-template-management.md).

## The Answer

**Yes — Coder templates can be managed fully declaratively from Git** using the
`coder/coderd` Terraform provider. The imperative `coder templates push` CLI is
the legacy/manual path and can be eliminated in production.

There is a clean split:

- **Template source files** (the Terraform that defines a workspace) must live
  in Git. The provider *builds* versions from a directory; it does not author them.
- **Template lifecycle** (create, version, activate/deactivate, ACLs, TTL,
  deprecation) is **fully declarative** via the provider.

## Verified facts

> Each row shows the date it was verified, so a stale row is plainly visible.

| Item | Value | Verified |
|------|-------|----------|
| Provider `coder/coderd` latest release | `v0.0.22` | 2026-08-03 |
| Provider requirement | Coder `>= 2.10.1` | 2026-08-03 |
| Coder latest stable / mainline | `v2.34.7` (stable) / `v2.35.3` (mainline) — we run `v2.34.6` via `coder.image.tag` in `ai-helm-values` prod `coder-app.yaml` | 2026-08-07 |
| `versions[].directory` declarative attribute | ✅ supported | 2026-08-03 |
| `coder templates push` CLI | still exists (imperative path) | 2026-08-03 |

References:
- Provider registry: https://registry.terraform.io/providers/coder/coderd/latest
- Provider source: https://github.com/coder/terraform-provider-coderd
- `coderd_template` resource docs: https://registry.terraform.io/providers/coder/coderd/latest/docs/resources/template
- `coder templates push` CLI: https://coder.com/docs/reference/cli/templates_push
- Templates as Terraform modules: https://coder.com/docs/admin/templates/extending-templates/modules
- Provider GitOps announcement: https://coder.com/blog/release-recap-2-15-0

## Parity: provider vs. `coder templates push`

| Capability | `push` (CLI) | `coderd` provider |
|-----------|-------------|-------------------|
| Create template | ✅ | ✅ |
| Create version from a directory | ✅ | ✅ (`versions[].directory`) |
| Set active version | ✅ (`--activate`) | ✅ (`active = true`) |
| Template params (`tf_vars`) | ✅ | ✅ (`tf_vars`) |
| Route a build to a specific provisioner | ❌ | ✅ (`provisioner_tags`) |
| Deactivate/archive a version | ⚠️ manual | ✅ (`active = false`) |
| ACLs (Enterprise) | ⚠️ separate | ✅ (`acl`) |
| TTL / dormancy / deprecation (Enterprise) | ⚠️ separate | ✅ |
| Drift detection | ❌ none | ✅ `terraform plan` |
| Rollback | ❌ manual | ✅ revert Git / state |
| Idempotent re-run | ❌ | ✅ |

No parity gap blocks adopting the provider.

## Repository layout

```
ai-helm/
├── .coder/templates/<name>/   ← template SOURCE (main.tf, variables.tf, …)
├── terraform/coder/           ← template LIFECYCLE (coderd provider)
│   ├── main.tf                ← provider + state
│   ├── templates.tf           ← coderd_template resources
│   └── variables.tf
└── .github/workflows/         ← validate / deploy / reconcile
```

## Implementation pattern

`terraform/coder/main.tf`:

```hcl
terraform {
  required_version = ">= 1.5"
  required_providers {
    coderd = {
      source  = "coder/coderd"
      version = "~> 0.0"
    }
  }
  # Remote state on Hetzner Object Storage (S3-compatible, Ceph-RGW) —
  # reuses the platform's existing `ssegning-k8s-state` bucket + creds.
  # See "State backend" below for the S3 backend flags required.
  backend "s3" {
    bucket                      = "ssegning-k8s-state"
    key                         = "coder/templates/terraform.tfstate"
    region                      = "us-east-1"              # Ceph-RGW accepts this

    # S3-compatible (Ceph-RGW) backend flags — modern (Terraform >= 1.6) names:
    # `endpoint` → `endpoints.s3`, `force_path_style` → `use_path_style`.
    endpoints                   = { s3 = "https://nbg1.your-objectstorage.com" }
    use_path_style              = true
    use_lockfile                = true   # S3-native locking; verify Ceph-RGW honours conditional writes (If-None-Match)
    skip_s3_checksum            = true   # verify; AWS SDK v2 checksums can break uploads against S3-compatible stores
    skip_credentials_validation = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
  }
}

provider "coderd" {
  url   = var.coder_url
  token = var.coder_token
}
```

`terraform/coder/templates.tf`:

```hcl
resource "coderd_template" "ubuntu" {
  name            = "ubuntu"
  display_name    = "Ubuntu Development"
  description     = "Full-featured Ubuntu development environment"
  organization_id = var.organization_id

  versions = [{
    name      = "v-${var.git_commit_sha}"
    message   = "Managed version"   # NOT `description` — `description` is invalid inside `versions`
    directory = "${path.root}/../../.coder/templates/ubuntu"
    active    = true
    # provisioner_tags = ["gpu"]  # optional: route this version's build to a specific provisioner
  }]

  default_ttl_ms       = 86400000  # 24h
  max_port_share_level = "owner"
}
```

> **How new versions are detected.** The provider **content-hashes the
> directory** (a `sha256` over the concatenated file contents) at plan time. If
> the hash differs from the last one recorded in Terraform's private state, the
> version gets a new ID and the next `apply` creates a brand-new version in
> Coder. Encoding the Git SHA in the version name
> (`name = "v-${var.git_commit_sha}"`) is **not** what triggers the new version —
> the hash does that. The SHA-in-name guarantees a **distinct, traceable name**:
> Coder identifies versions by name, and a version's name must change whenever
> its directory contents (or `tf_vars`) change, so the new content-hash gets a
> new, meaningful label instead of colliding with the old one.

## GitOps flow

```
git commit → PR (validate workflow: fmt + validate + plan) → merge to main
  → deploy workflow: terraform apply
  → optional daily reconcile workflow (drift)
```

A new Coder deployment needs only: Git + a provider token + **empty**
Terraform state — **no manual `coder templates push`**. (State carried over from
a previous deployment holds stale template/version UUIDs — discard it
(`terraform state rm`) or use a fresh state key for a genuinely new cluster.)

### State backend

Terraform state lives on **Hetzner Object Storage** (S3-compatible/Ceph-RGW),
reusing the platform's existing `ssegning-k8s-state` bucket (key
`coder/templates/terraform.tfstate`) — the same store the platform already uses
for CNPG backups, Mimir/Loki/Tempo blocks and LibreChat. Credentials come from
the `ssegning-aws` store (`prod/meta/test-app`, the `s3_backup_*` properties)
via `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`.

Alternatives considered and rejected:
- **GCS** — this repo/platform has no Google Cloud footprint; GCS was a
  placeholder in the original spike docs.
- **HCP Terraform (Terraform Cloud)** — managed state + runs, but a new SaaS
  dependency + token secret for no benefit over the existing store.
- **Git-backed (Atlantis / state committed to `ai-helm-values`)** — Terraform
  has no official git backend; requires custom automation and has no locking.

Importing an already-pushed template into Terraform state (one-time):

```bash
# The import ID is <organization-name>/<template-name> — `coder` below is the
# ORG name, not a fixed namespace or provider prefix. A template UUID is also
# accepted and is the unambiguous option.
terraform import coderd_template.ubuntu <org-name>/ubuntu
# then declare its versions in templates.tf to reach "no drift"
```

## Known limitations & workarounds

- **Version naming** — version **names** must change when directory contents
  (or `tf_vars`) change (Coder identifies versions by name); encode the Git SHA
  in the name so each new content-hash gets a unique, traceable label.
- **Import is one-time manual** — versions must be declared after `import`.
- **Startup metadata race** — some enterprise attributes
  (e.g. `max_port_share_level`) may need a second apply after first creation.
- **Global/workspace server settings** — not in the provider; manage via UI/API
  or Helm (server-level admin is tracked separately).
- **Multi-org** — provider manages one org per config; use separate workspaces/configs.

## Follow-up

Building the actual custom workspace templates (out of scope here) is tracked as
a separate ticket; deliver them with `.coder/templates/<name>/` source +
`terraform/coder/templates.tf` entries per this pattern.
