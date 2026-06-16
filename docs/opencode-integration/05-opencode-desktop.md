# OpenCode Desktop Integration

## Setup

### 1. Download

Download the appropriate package for your system from:

**https://opencode.ai/download**

Available formats:
- Linux (.deb)
- Linux (.rpm)

### 2. Install

- Double-click the downloaded `.deb` or `.rpm` file
- Your software manager (GNOME Software, KDE Discover, etc.) will open  
- Click "Install"

### 3. Launch

Launch from your application menu.

### 4. Connect to Converse Gateway

**In OpenCode Desktop:**

1. Open Settings (Ctrl+, or Cmd+,)
2. Navigate to Provider/Connection settings
3. Set endpoint URL: `https://ai.camer.digital/opencode`
4. Click "Connect" or "Login"
5. Browser opens for authentication
6. Login and authorize
7. Return to OpenCode Desktop

### 5. Select Model

After authentication, select your preferred model from the dropdown.

## Usage

### Keyboard Shortcuts

| Action | Windows/Linux | macOS |
|--------|---------------|-------|
| Open Settings | Ctrl+, | Cmd+, |
| New Chat | Ctrl+N | Cmd+N |
| Toggle Sidebar | Ctrl+B | Cmd+B |

### Examples

**Initialize project:**
```
/init
```

**File references:**
```
Explain @src/auth.ts
```

**Shell commands:**
```
!npm test
```

## Troubleshooting

**Cannot connect to gateway:**
- Verify endpoint URL: `https://ai.camer.digital/opencode`
- Check network connectivity
- Try authentication again

**Desktop app not launching:**
- Verify installation in your software manager
- Try reinstalling via the `.deb` or `.rpm` file
- Check system logs for errors