# OpenCode CLI Integration

## Setup

### Install

```bash
npm install -g opencode-ai
```

### Authenticate

```bash
opencode auth login https://ai.camer.digital/opencode
```

Browser opens for authentication. Login, return to terminal, select model.

## Configuration

### AGENTS.md

```bash
opencode
/init
```

### Optional web research with Parallel Search MCP

For current release notes, upstream API changes, or troubleshooting references,
add [Parallel Search MCP](https://docs.parallel.ai/integrations/mcp/search-mcp).
It provides web search and page fetching without a Parallel account or API key.
Anonymous search uses Fast mode and has lower rate limits than authenticated use.

Merge this configuration into your project's `opencode.json` (or
`opencode.jsonc`). Add the new keys to the existing `mcp`, `permission`, and
`agent.web-search.permission` objects; keep your other settings and agent prompt:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "parallel-search": {
      "type": "remote",
      "url": "https://search.parallel.ai/mcp",
      "oauth": false,
      "enabled": true,
      "headers": {
        "User-Agent": "ai-helm-opencode"
      }
    }
  },
  "permission": {
    "parallel-search_*": "deny"
  },
  "agent": {
    "web-search": {
      "mode": "subagent",
      "permission": {
        "edit": "deny",
        "bash": "deny",
        "parallel-search_*": "allow"
      }
    }
  }
}
```

This is a local opt-in connection directly to Parallel. Keep your Camer Digital
model-provider authentication from the setup above; no Helm chart or gateway
change is needed. The global deny and the `@web-search` allow follow the
[existing specialist-tool pattern](../adr/0074-opencode-opt-in-mcps-and-multi-primary-fleet.md):
Parallel tools are available to that read-only subagent, keeping primaries lean.
Queries and requested page URLs are sent to Parallel, so use
public information and keep credentials and private cluster details out of prompts.

From that project directory, check the connection:

```bash
opencode mcp list
```

Confirm `parallel-search` is connected. Start `opencode` and try:

```text
@web-search Use parallel-search to find the current Helm upgrade documentation, fetch the
relevant page, and summarize the rollback options with source links.
```

The server exposes `web_search` and `web_fetch`; the model must support tool use.
If you hit an anonymous usage limit, wait before retrying or consult the
[Parallel setup guide](https://docs.parallel.ai/integrations/mcp/search-mcp)
for authenticated options. To disable it, set `enabled` to `false` or remove only
`mcp.parallel-search`, then restart OpenCode. You may also remove the two
`parallel-search_*` permission entries; keep the rest of `web-search` and your
other MCP entries intact.
See [OpenCode's MCP configuration](https://opencode.ai/docs/mcp-servers/) for
remote-server options.

## Usage Patterns

### Start OpenCode

```bash
# Current directory
opencode

# Specific directory
opencode /path/to/project

# Continue last session
opencode --continue
```

### TUI Commands

| Command | Purpose |
|---------|---------|
| `/help` | Show help |
| `/init` | Create AGENTS.md |
| `/connect` | Configure provider |
| `/models` | List models |
| `/share` | Share session |
| `/undo` | Undo changes |
| `/new` | New session |

### File References

```
Explain @src/utils/parser.ts
Refactor @src/api.ts using async/await
```

### Shell Commands

```
!npm test
!git status
```

### Non-Interactive Mode

```bash
# Single command
opencode run "Explain async/await"

# With files
opencode run --file src/main.ts "Add error handling"
```

### Session Management

```bash
# List sessions
opencode session list

# Export session
opencode export SESSION_ID

# Import session
opencode import session.json
```

### Web Interface

```bash
# Start web server
opencode web --port 4096

# Access at http://localhost:4096
```

## Troubleshooting

**Command not found:**
```bash
export PATH="$HOME/.local/bin:$PATH"
```