# GitHub PR Reviews

This guide covers automated pull request reviews using the OpenCode reusable workflow. For foundational GitHub Actions setup (app installation, OIDC tokens, gateway authentication), see [GitHub Actions Integration](../github-actions/00-github-actions.md).

## Overview

The PR review integration uses a **reusable workflow** hosted in the ai-governance repository:

- The reusable workflow contains all review logic, authentication, and agent configuration
- Your repository only needs a thin caller workflow that invokes it
- Reviews are triggered automatically on PR open/sync or manually via `/oc` comments

## Prerequisites

Before setting up PR reviews, ensure you have completed the [GitHub Actions Integration](../github-actions/00-github-actions.md) setup:

1. **CAMER DIGITAL GitHub App** installed on your repository or organization
2. **Organization approved** by platform admin
3. **`OPENCODE_GATEWAY_AUDIENCE`** variable configured

> **Note:** The workflow is a no-op if `OPENCODE_GATEWAY_AUDIENCE` is not set, keeping unprepared forks' CI green.

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

## Troubleshooting

### Branch naming conflict: avoid naming your branch `opencode`

If a pull request review is triggered on a branch named `opencode`, the workflow will fail with an error like:

```
Error: fatal: unable to read tree (8718f3161699ae03c8a970e1b4e3f6a20ad552bb)
Error: Process completed with exit code 1.
```

**Cause:** The OpenCode agent uses the `opencode` branch name internally for its workflow. When the review target branch is also named `opencode`, it conflicts with this internal branch.

**Solution:** Rename the branch before creating a pull request for review:

```bash
# Rename the branch locally
git branch -m opencode opencode-backup

# Push the renamed branch
git push origin opencode-backup

# Delete the old branch on remote
git push origin --delete opencode

# Update local tracking
git fetch --prune
```

> **Note:** If you've already opened a pull request on a branch named `opencode`, rename the branch and update the PR before triggering a review.

### Workflow triggers but produces no output

Ensure `OPENCODE_GATEWAY_AUDIENCE` is set as a repository or organization variable. The workflow is a no-op if this variable is empty (by design, to keep unprepared forks' CI green).

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

- [GitHub Actions Integration](../github-actions/00-github-actions.md) — Foundational setup (app installation, OIDC tokens, gateway auth)
- [VSCode Integration](01-vscode-integration.md) — Local development setup
- [CLI Integration](03-cli-integration.md) — Terminal and TUI usage
