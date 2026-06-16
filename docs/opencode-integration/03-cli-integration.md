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