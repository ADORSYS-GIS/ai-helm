# Declarative Coder templates — test wiring

This directory is the **declarative lifecycle** for Coder templates (ADR-0123).
The template **source** lives in `.coder/templates/`; this Terraform manages the
template/version in Coder via the `coder/coderd` provider.

> ⚠️ This is a **test/scratch** setup for proving the delivery mechanism with a
> simple template (`poc-ubuntu`). Not production.

## Layout

- `main.tf` — `coder/coderd` provider + S3 (Hetzner Object Storage) state
- `variables.tf` — `coder_url`, `coder_token`, `organization_id`, `git_commit_sha`
- `templates.tf` — the `coderd_template` resource(s) pointing at `.coder/templates/*`

## Prereqs

- Terraform >= 1.10 (S3-native state locking via `use_lockfile`; ADR-0123)
- A Coder API token with template-admin scope
- Hetzner Object Storage (S3-compatible) credentials for the state backend

## Run locally

```bash
cd terraform/coder

# env (or use terraform.tfvars / TF_VAR_*)
export CODER_URL=https://<coder-host>
export CODER_TOKEN=<token>
export AWS_ACCESS_KEY_ID=<from ssegning-aws>
export AWS_SECRET_ACCESS_KEY=<from ssegning-aws>

export TF_VAR_git_commit_sha=$(git rev-parse HEAD)

terraform init
terraform fmt -recursive .
terraform validate
terraform plan -out=tfplan
terraform apply tfplan
```

Verify in Coder:

```bash
coder templates list
coder templates versions list poc-ubuntu
coder create test-ws --template poc-ubuntu
coder ssh test-ws
coder delete test-ws
```

## Importing an already-pushed template (one-time)

```bash
# The import ID is <organization-name>/<template-name>. `default` is the org
# name for the built-in org, NOT a fixed namespace. A template UUID also works
# and is unambiguous.
terraform import coderd_template.poc_ubuntu default/poc-ubuntu
# then declare the template in templates.tf to reach "no drift"
```

## Fresh deployments

For a genuinely new Coder deployment, do **not** reuse state from a previous
one — it holds stale template/version UUIDs. Use **empty** state (fresh state
key, or `terraform state rm`) as documented in ADR-0123.

## Notes

- Version names encode the Git SHA so each source change yields a new version.
- A second `terraform plan` should show **no changes** (idempotent).
- State locking is provided by `use_lockfile = true` (S3-native); verify the
  Hetzner Object Storage / Ceph-RGW backend honours conditional writes.
