# OpenCode — GitHub Actions Integration

This setup enables OpenCode to automatically review pull requests and handle issue tasks in CI, authenticating to the AI gateway via GitHub OIDC (keyless — no shared secrets).

## Architecture

The integration uses a **reusable workflow** hosted in the ai-governance repository:

- The reusable workflow contains all job logic, authentication, and agent configuration
- Your repository only needs a thin caller workflow that invokes it

This means you only need to:

1. Install the CAMER DIGITAL GitHub App
2. Set the `OPENCODE_GATEWAY_AUDIENCE` variable
3. Add a minimal caller workflow

## Prerequisites

### 1. Install the CAMER DIGITAL GitHub App

Install the **[camer-digital-ai](https://github.com/apps/camer-digital-ai)** GitHub App on your repository or organization.

This enables the OIDC binding that allows the workflow to authenticate with the AI gateway using your repo's own GitHub Actions OIDC token — no shared secrets required.

### 2. Configure the Gateway Audience

Create an organization or repository variable:

| Variable | Value |
|----------|-------|
| `OPENCODE_GATEWAY_AUDIENCE` | Your Source URL, e.g., `https://api.ai.camer.digital/sources/src-XXXXXXXXXXXX` |

Contact the AI team to obtain your Source audience value after they configure your account.

> **Note:** The workflow is a no-op if this variable is not set, keeping unprepared forks and CI green.

## Setup

### Add the Caller Workflow

Create `.github/workflows/opencode.yml` in your repository:

```yaml
name: opencode

on:
  pull_request:
    types: [opened, synchronize]
  issue_comment:
    types: [created]
  pull_request_review_comment:
    types: [created]

concurrency:
  group: opencode-review-${{ github.event.pull_request.number || github.event.issue.number }}
  cancel-in-progress: true

jobs:
  review:
    if: ${{ vars.OPENCODE_GATEWAY_AUDIENCE != '' }}
    uses: ADORSYS-GIS/ai-governance/.github/workflows/opencode-review.yml@main
    permissions:
      id-token: write
      contents: write
      pull-requests: write
      issues: write
    with:
      audience: ${{ vars.OPENCODE_GATEWAY_AUDIENCE }}
```

> **Supply-chain control:** Pin `@main` to an immutable SHA for production use. Bump the SHA deliberately when adopting new versions.

## How It Works

| Trigger | Behavior |
|---------|----------|
| Pull request opened/synced | Runs automatic PR review |
| `/oc` or `/opencode` on a PR comment | Runs manual PR review |
| `/oc` or `/opencode` on an issue comment | Runs issue task agent |

The workflow:

1. Mints a GitHub Actions OIDC token with your Source audience
2. Authenticates to the AI gateway via the lightbridge-repo-auth binding
3. Runs OpenCode with the appropriate agent (`auto-review`, `manual-review`, or `build`)
4. Posts results as `github-actions[bot]` comments

## Configuration

The reusable workflow supports optional overrides:

| Input | Default | Description |
|-------|---------|-------------|
| `audience` | *(required)* | Your Source URL for OIDC authentication |
| `gateway_base_url` | `https://api.ai.camer.digital/v1` | AI gateway base URL |
| `provider` | `camer-digital` | OpenCode provider ID |
| `auto_model` | `camer-digital/adorsys-reviewer` | Model for automatic PR reviews |
| `manual_model` | `camer-digital/adorsys-reviewer-pro` | Model for `/oc` PR reviews |
| `issue_model` | `camer-digital/adorsys-reviewer-pro` | Model for `/oc` issue tasks |
| `runs_on` | `ubuntu-latest` | Runner label (use `self-hosted` for private runners) |

Example with overrides:

```yaml
with:
  audience: ${{ vars.OPENCODE_GATEWAY_AUDIENCE }}
  auto_model: camer-digital/adorsys-reviewer
  runs_on: self-hosted
```

## Security Model

| Aspect | Implementation |
|--------|----------------|
| Authentication | Keyless — uses your repo's GitHub Actions OIDC token |
| Config delivery | In-memory via `OPENCODE_CONFIG_CONTENT` env var, never written to disk |
| Loop prevention | Actor guard prevents bot-triggered re-runs |
| Supply chain | Actions and workflows pinned to immutable SHAs |

## Resources

| Resource | Link |
|----------|------|
| Reusable workflow source | [github.com/ADORSYS-GIS/ai-governance/.../opencode-review.yml](https://github.com/ADORSYS-GIS/ai-governance/blob/main/.github/workflows/opencode-review.yml) |
| Caller workflow template | [github.com/ADORSYS-GIS/ai-governance/.../opencode.yml](https://github.com/ADORSYS-GIS/ai-governance/blob/main/templates/.github/workflows/opencode.yml) |

## Related

- [VSCode Integration](01-vscode.md) — Local development setup
- [CLI Integration](03-cli.md) — Terminal and TUI usage
- [OpenCode Overview](00-overview.md) — General integration guide