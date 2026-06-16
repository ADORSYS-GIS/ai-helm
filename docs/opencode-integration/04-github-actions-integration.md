# GitHub Actions + OpenCode Integration

## Setup

### 1. Create Composite Action

Create `.github/actions/opencode-config/action.yaml`:

```yaml
name: 'Setup OpenCode Config'
inputs:
  opencode-base-url:
    required: true
  oauth2-issuer:
    required: true
  oauth2-client-id:
    required: true
  oauth2-client-secret:
    required: true
  opencode-model:
    required: true
runs:
  using: 'composite'
  steps:
    - name: Create OpenCode config
      shell: bash
      env:
        OPENCODE_BASE_URL: ${{ inputs.opencode-base-url }}
        OAUTH2_ISSUER: ${{ inputs.oauth2-issuer }}
        OAUTH2_CLIENT_ID: ${{ inputs.oauth2-client-id }}
        OAUTH2_CLIENT_SECRET: ${{ inputs.oauth2-client-secret }}
        OPENCODE_MODEL: ${{ inputs.opencode-model }}
      run: |
        mkdir -p ~/.config/opencode
        cat > ~/.config/opencode/opencode.json << EOF
        {
          "plugin": ["@vymalo/opencode-oauth2"],
          "provider": {
            "lightbridge": {
              "npm": "@ai-sdk/openai-compatible",
              "options": {
                "baseURL": "${OPENCODE_BASE_URL}",
                "oauth2": {
                  "issuer": "${OAUTH2_ISSUER}",
                  "clientId": "${OAUTH2_CLIENT_ID}",
                  "clientSecret": "${OAUTH2_CLIENT_SECRET}",
                  "scopes": ["openid"],
                  "authFlow": "client_credentials"
                }
              }
            }
          }
        }
        EOF
```

### 2. Add GitHub Secrets

- `OPENCODE_BASE_URL`: `https://api.ai.camer.digital/v1`
- `OAUTH2_ISSUER`: `https://auth.verif.fyi/realms/camer-digital/`
- `OAUTH2_CLIENT_ID`: Your Keycloak client ID
- `OAUTH2_CLIENT_SECRET`: Your Keycloak client secret
- `OPENCODE_MODEL`: `glm-5`

### 3. Workflow

```yaml
name: opencode
on:
  pull_request:
  issue_comment:
    types: [created]

jobs:
  opencode:
    runs-on: ubuntu-latest
    # Filter to only run on /oc or /opencode commands
    if: |
      github.event_name == 'pull_request' ||
      contains(github.event.comment.body, '/oc') ||
      contains(github.event.comment.body, '/opencode')
    permissions:
      id-token: write
      contents: write
      pull-requests: write
      issues: write
    steps:
      - uses: actions/checkout@v6
      - uses: ./.github/actions/opencode-config
        with:
          opencode-base-url: ${{ secrets.OPENCODE_BASE_URL }}
          oauth2-issuer: ${{ secrets.OAUTH2_ISSUER }}
          oauth2-client-id: ${{ secrets.OAUTH2_CLIENT_ID }}
          oauth2-client-secret: ${{ secrets.OAUTH2_CLIENT_SECRET }}
          opencode-model: ${{ secrets.OPENCODE_MODEL }}
      - uses: anomalyco/opencode/github@v1.16.2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        with:
          model: lightbridge/${{ secrets.OPENCODE_MODEL }}
          use_github_token: true
```

**Note:** The `if` condition filters comment events to only run when `/oc` or `/opencode` is present, preventing wasted CI minutes on regular comments.