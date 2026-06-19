
# IntelliJ + OpenCode Integration

## Overview

You can integrate OpenCode into IntelliJ IDEA in two ways:

1. **OpenCode UI Plugin (Recommended)**: Provides a native chat interface, visual diff viewer for code changes, and one-click context sharing.
2. **Terminal CLI**: Runs the raw command-line interface inside IntelliJ's built-in terminal.

## Setup

### 1. Install OpenCode CLI (Required for both methods)

The plugin acts as a bridge to the CLI, so the CLI must be installed first.

```bash
npm install -g opencode
# OR for macOS
brew install opencode
```

### 2. Authenticate

Authenticate the CLI once; the plugin will inherit this session.

```bash
opencode auth login https://ai.camer.digital/opencode
```

*Browser opens for authentication. Login, return to terminal, and select your model.*

---

## Method A: Using the OpenCode UI Plugin (Recommended)

This method offers superior integration, including **visual code reviews**, **automatic file synchronization**, and **desktop notifications**.

### 1. Install the Plugin

**From JetBrains Marketplace:**

1. Open IntelliJ IDEA.
2. Go to **Settings** → **Plugins** → **Marketplace**.
3. Search for **"OpenCode"** or **"OpenCode UI"**.
4. Click **Install** and **Restart IDE**.

> **Direct link:** [OpenCode UI on JetBrains Marketplace](https://plugins.jetbrains.com/plugin/29744-opencode-ui)

**Manual Installation (if not found in Marketplace):**

1. Download the plugin from [JetBrains Marketplace](https://plugins.jetbrains.com/plugin/29744-opencode-ui).
2. In IntelliJ, go to **Settings** → **Plugins** → **Gear icon** → **Install Plugin from Disk...**
3. Select the downloaded `.zip` file.
4. Click **OK** and **Restart IDE**.

### 2. Launch and Connect

1. **Shortcut**: Press `Ctrl` + `\` (Windows/Linux) or `Cmd` + `Esc` (macOS).
2. **Dialog**:
   - **Create New Session**: Select this to let the plugin spawn a managed session (default port `4096`).
   - **Connect to Server**: If you already have `opencode serve` running, enter `127.0.0.1:4096`.
3. The OpenCode chat window will appear in the tool window bar.

> **Keyboard shortcuts differ from VSCode.** For VSCode shortcuts, see [VSCode Integration](01-vscode-integration.md).

### 3. How It Works

The UI plugin connects to the OpenCode CLI in one of two ways:

1. **Managed mode (default)**: The plugin spawns a background HTTP server (`opencode serve`) on port `4096` and communicates via HTTP. This is transparent to you — just open the tool window and start chatting.
2. **External server mode**: You run `opencode serve` manually and connect to it. Useful for debugging or when running multiple IDEs simultaneously.

The CLI handles all AI interactions. The plugin provides the visual layer (chat, diffs, notifications).

### 4. Key Plugin Features

- **Context Sharing**: Highlight code in the editor and press `Ctrl` + `Alt` + `K` (Win/Linux) or `Cmd` + `Option` + `K` (Mac) to instantly send it to the chat.
- **Visual Diff Review**: When OpenCode edits files, a **native diff window** opens automatically. Click **Accept** to write changes and stage them in Git, or **Reject** to discard.
- **Notifications**: Enable OS notifications to be alerted when long tasks complete.

---

## Method B: Using the IntelliJ Terminal (CLI)

Use this method if you prefer the raw TUI (Text User Interface) or need to run specific shell commands alongside the agent.

### 1. Open Terminal

- **Shortcut**: `Alt` + `F12` (Windows/Linux) or `Option` + `F12` (macOS).
- **Navigate**: `cd /path/to/project`

### 2. Run OpenCode

```bash
opencode
```

*The interactive terminal UI will load directly in the pane.*

### 3. Terminal Split Workflow

For advanced multitasking:

1. Right-click the terminal tab.
2. Select **Split Right**.
3. Run `opencode` in one pane and your build/test commands in the other.

---

## Configuration

### Editor Environment Variables

To allow OpenCode to open files in IntelliJ from the terminal, set the `EDITOR` variable in your shell profile.

**macOS (zsh — default shell):**
```bash
echo 'export EDITOR="idea --wait"' >> ~/.zshrc
source ~/.zshrc
```

**macOS (bash):**
```bash
echo 'export EDITOR="idea --wait"' >> ~/.bash_profile
source ~/.bash_profile
```

**Linux:**
```bash
export EDITOR="/opt/idea/bin/idea.sh --wait"
# Or if installed via Snap:
# export EDITOR="idea --wait"
# Add to ~/.bashrc or ~/.zshrc for persistence
```

**Windows (PowerShell):**
```powershell
$env:EDITOR = "idea64 --wait"
# Add to $PROFILE for persistence
Add-Content -Path $PROFILE -Value '$env:EDITOR = "idea64 --wait"'
```

### Plugin Settings (Method A Only)

If the plugin cannot find the CLI or uses a non-standard port:

1. Go to **Settings** → **Tools** → **OpenCode**.
2. **OpenCode Command**: Set path if not in system PATH (e.g., `/usr/local/bin/opencode`).
3. **Server Port**: Default is `4096`. Change if running multiple instances.
4. **Auto Start Server**: Enable to launch the background service when IntelliJ starts.

---

## Usage Comparison

| Feature | OpenCode UI Plugin | Terminal CLI |
|:--------|:-------------------|:-------------|
| **Interface** | Native Chat Window | Text-based TUI |
| **Code Diffs** | **Visual Side-by-Side** (Accept/Reject buttons) | Text Unified Diff (Manual typing) |
| **Context** | **One-Click** (`Cmd`+`Option`+`K`) | Manual typing (`@file`) |
| **File Sync** | **Automatic** (Instant VFS refresh) | May require "Reload from Disk" |
| **Multitasking** | Runs in background/tool window | Tied to terminal tab |
| **Best for** | Most users, visual workflows | Power users, script integration |

---

## Troubleshooting

### Command not found (Plugin)

If the plugin says "OpenCode command not found":

1. Verify installation: `opencode --version` in your system terminal.
2. In Plugin Settings, set the **absolute path** to the binary:
   - macOS/Linux: `/usr/local/bin/opencode` or `/opt/homebrew/bin/opencode`
   - Windows: `C:\Users\<You>\AppData\Roaming\npm\opencode.cmd`
   - npm global: `$(npm config get prefix)/bin/opencode`

### Connection Refused

- Ensure no other process is using port `4096`.
- Try restarting the session via the plugin dialog (`Ctrl` + `\` / `Cmd` + `Esc`).
- Check firewall settings if using external server mode.

### Plugin Not Appearing in Tool Windows

- Verify plugin is installed: **Settings** → **Plugins** → **Installed** → search "OpenCode"
- Ensure plugin is enabled: checkbox next to plugin name
- Restart IntelliJ after installation
- Check **View** → **Tool Windows** → **OpenCode** to manually open it

### Authentication Issues

- Verify endpoint URL in plugin settings: `https://ai.camer.digital/opencode`
- Try re-authenticating via CLI: `opencode auth login https://ai.camer.digital/opencode`
- Check browser pop-up blocker settings
- Ensure session hasn't expired (re-login if needed)