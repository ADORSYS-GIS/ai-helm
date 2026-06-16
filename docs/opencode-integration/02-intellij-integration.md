# IntelliJ + OpenCode Integration

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

### 3. Use in IntelliJ Terminal

- Open IntelliJ
- Open terminal: Alt+F12
- Navigate to project: `cd /path/to/project`
- Run: `opencode`

## Configuration

### Editor Setup

Add to shell profile (`~/.bashrc` or `~/.zshrc`):

**macOS:**
```bash
export EDITOR="idea --wait"
```

**Linux:**
```bash
export EDITOR="/opt/idea/bin/idea.sh --wait"
```

**Windows (PowerShell):**
```powershell
$env:EDITOR = "idea64 --wait"
```

## Usage

### Basic Commands

**Initialize:**
```
/init
```

**File references:**
```
Explain @src/main/kotlin/UserService.kt
```

**Shell commands:**
```
!./gradlew test
```

### Terminal Split

1. Open terminal (Alt+F12)
2. Right-click tab
3. Select Split Right
4. Run OpenCode in one pane

## Troubleshooting

**Command not found:**
```bash
export PATH="$HOME/.local/bin:$PATH"
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
```