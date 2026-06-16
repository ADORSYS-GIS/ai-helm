# VSCode + OpenCode Integration

## Setup

### 1. Install OpenCode CLI

```bash
npm install -g opencode-ai
```

### 2. Authenticate

```bash
opencode auth login https://ai.camer.digital/opencode
```

Browser opens for authentication. Login, return to terminal, select model.

### 3. Install VS Code Extension

**Automatic:**
- Open VS Code integrated terminal (Ctrl+`)
- Run: `opencode`
- Extension installs automatically

**Manual:**
- Open Extensions (Ctrl+Shift+X)
- Search: OpenCode
- Click Install

## Configuration

### Editor Setup

Add to shell profile (`~/.bashrc` or `~/.zshrc`):

```bash
export EDITOR="code --wait"
```

## Usage

### Keyboard Shortcuts

| Action | Windows/Linux | macOS |
|--------|---------------|-------|
| Open OpenCode | Ctrl+Esc | Cmd+Esc |
| New session | Ctrl+Shift+Esc | Cmd+Shift+Esc |
| File reference | Alt+Ctrl+K | Cmd+Option+K |

### Examples

**Initialize project:**
```
/init
```

**Ask questions:**
```
Explain authentication in @src/auth/login.ts
```

**Use Plan Mode:**
- Press Tab to switch to Plan
- Describe feature
- Press Tab to switch to Build
- Type "Go ahead"

## Troubleshooting

**Extension not installing:**
- Run: `opencode` in integrated terminal
- VS Code path command: Install 'code' command in PATH

**Command not found:**
```bash
export PATH="$HOME/.local/bin:$PATH"
```