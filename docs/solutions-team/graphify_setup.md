I’ve updated the guide by adding a new **Section 3.4** that explains the `graphify install --platform opencode` step, its purpose, and why it’s recommended before integrating with OpenCode’s MCP. I also adjusted the related note in Section 4.1 and the checklist to reflect this addition.

Here is the complete revised documentation:

---

# Graphify + OpenCode — Setup & Adoption Guide

## What is Graphify?

**Graphify** is a tool that turns any codebase (and associated documentation, diagrams, images) into a **queryable knowledge graph** – a map of files, functions, classes, calls, imports, and semantic relationships. This graph lets AI assistants like OpenCode answer questions about dependencies, impact analysis, and architecture in milliseconds, using **70x fewer tokens** than traditional file‑grepping approaches.

---

## 1. How it works (quick mental model)

Graphify builds the graph in two independent modes:

| Mode | What it does | Requires API key? |
|------|--------------|-------------------|
| **Code‑only (AST)** | Parses code using `tree‑sitter` – extracts functions, classes, calls, imports. Fully local, deterministic. | ❌ No |
| **Full (with LLM)** | Also sends docs, images, PDFs to an LLM (e.g. Google Gemini or custom OpenAI-compatible provider) to infer semantic relationships (e.g. “this diagram implements that function”). | ✅ Yes – for non‑code files only |

The output is `graphify-out/graph.json`. Once the Graphify MCP server is configured and running, OpenCode can query the graph directly via Model Context Protocol (MCP) – no more slow, expensive file scanning.

---

## 2. Prerequisites

- Python 3.10+ and `pip`
- OpenCode installed in your project (CLI or IDE)
- (Optional) A **Google Gemini API key** or a **custom OpenAI-compatible API key** if you want semantic enrichment of docs/images. Code‑only analysis needs **no key**.
- Your project uses Git (Graphify respects `.gitignore`)

---

## 3. Generate the graph

### 3.1 Install Graphify

Install Graphify with the extras you need:

```bash
# For code‑only (AST) + MCP server + PDF support:
pip install "graphifyy[mcp,pdf]"

# If you plan to use Google Gemini for LLM enrichment (docs/images):
pip install "graphifyy[mcp,gemini,pdf]"

# If you plan to use an OpenAI‑compatible provider (including custom internal endpoints):
pip install "graphifyy[mcp,openai,pdf]"
```

> **Note:** The PyPI package name is **`graphifyy`** (with a double 'y'), though the command-line utility and project name is `graphify`.

Verify installation: `graphify --version`

### 3.2 Code‑only graph (no API key, recommended first step)

Use `graphify update .` – this command is designed for incremental code re‑extraction. It **only processes code files** (`.py`, `.js`, `.go`, etc.) and completely ignores documentation and images. No API key is ever required.

```bash
cd /path/to/your/project
graphify update .
```

> **Why `update` instead of `graphify .`?**  
> - `graphify .` attempts to analyse **all files**, including docs and images. If an LLM key/backend is not configured, it will fail with an error like `no LLM API key found`.  
> - `graphify update .` is explicitly for code‑only extraction – it skips non‑code files entirely, so it never needs an API key and never fails that way. It is also faster because it uses caching for unchanged files.

Output is written to `graphify-out/`:
- `graph.json` – machine‑readable graph (used by the MCP server)
- `graph.html` – interactive visualisation (open in your browser)
- `GRAPH_REPORT.md` – plain‑English summary (god nodes, communities, cohesion scores)

### 3.3 (Optional) Add LLM enrichment for docs/images

To link diagrams, PDFs, and markdown to code, you must specify a backend and provide the necessary credentials.

#### Option A: Using Google Gemini or OpenAI (example)
Set your Gemini key and run the extraction:
```bash
 export GEMINI_API_KEY="your-gemini-key-here"
# or
export OPENAI_API_KEY="your-openai-key-here"
# then
graphify .
```


#### Option B: Using a Custom OpenAI-Compatible Provider (e.g. kivoyo Provider)
To point Graphify to a custom OpenAI-compatible endpoint, register a custom provider via the Graphify CLI:
```bash
# Register the custom provider
graphify provider add kivoyo \
  --base-url "https://your-custom-openai-endpoint/v1" \
  --default-model "your-model-name" \
  --env-key "OPENAI_API_KEY"

# Set the key and extract the graph
export OPENAI_API_KEY="your-custom-api-key"
graphify . --backend kivoyo
```
openai here must be installed else run 
- `pip install graphifyy[openai]`

### 3.4 Install the OpenCode skill (recommended)

Graphify provides a convenience command to install a skill file for OpenCode, which adds custom prompts and instructions that help OpenCode interact with the graph's MCP tools more effectively. This skill is **not required** for the MCP server to function, but it greatly improves the user experience by providing context‑aware guidance and example queries.

Run this command **after** generating the graph and **before** configuring the MCP server:

```bash
graphify install --platform opencode
```

This copies a `graphify.js` file into your project's `.opencode/plugins/` directory (creating it if necessary). The skill file is automatically loaded when OpenCode starts if you have the plugin configured in your `opencode.json` (as shown in Section 4.2).

**What this command does:**
- It installs a skill that teaches OpenCode how to use the MCP tools (`query_graph`, `get_node`, `shortest_path`).
- It provides example queries and explanations of the graph structure.
- It gives OpenCode a better understanding of how to phrase questions to get the most out of the graph.

**What it does NOT do:**
- It does **not** start or configure the MCP server itself – you still need to follow the steps in Section 4 to expose the graph as an MCP server.
- It does not modify your `opencode.json`; you must add the MCP server configuration manually (see 4.2).

> **Tip:** Run this command whenever you regenerate the graph or update OpenCode, to keep the skill file in sync.

---

## 4. Integrate with OpenCode via MCP

### 4.1 Why run it as an MCP server?
While the Graphify CLI builds the graph, exposing it as a Model Context Protocol (MCP) server allows AI assistants like OpenCode to query the codebase structure dynamically. Rather than passing entire files as context (which is slow and expensive), OpenCode calls tools to navigate connections, trace dependencies, and retrieve only the relevant parts of code in milliseconds.

> **Note:** The `graphify install --platform opencode` command (Section 3.4) installs a skill file that helps OpenCode use these tools effectively, but it does **not** set up the MCP server itself. The following steps are required to actually expose the graph as queryable tools.

### 4.2 Configure OpenCode to connect to the MCP server

OpenCode supports two configuration scopes for MCP servers: **project-specific** and **global**. Choose the approach that best fits your workflow.

#### Option A: Project-Specific Configuration (Recommended for teams)

Add the server configuration to your project's `.opencode/opencode.json` file. This ensures every team member working on the project has the MCP server configured identically.

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": [".opencode/plugins/graphify.js"],
  "mcp": {
    "graphify": {
      "type": "local",
      "command": ["graphify-mcp", "graphify-out/graph.json"],
      "enabled": true
    }
  }
}
```

**Advantages:**
- Configuration is version-controlled alongside your code
- Team members automatically inherit the correct setup when cloning the repository
- Allows project-specific customizations (e.g., different graph paths)

**When to use:** Team projects where consistency across contributors is important, or when you need project-specific settings.

#### Option B: Global Configuration (Use with caution)

Configure the MCP server once in your user-level OpenCode configuration at `~/.config/opencode/opencode.jsonc`. This makes Graphify available across all your projects without per-project setup.

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "graphify": {
      "type": "local",
      "command": ["graphify-mcp"],
      "enabled": true
    }
  }
}
```

> **⚠️ Important: How MCP Servers Work**
>
> The MCP server is a **running process** that OpenCode starts automatically when you launch it. OpenCode executes the `command` from your **current working directory** (where you run `opencode` from).
>
> For global config:
> - OpenCode will try to start `graphify-mcp` from **whatever directory you're in**
> - If `graphify-out/graph.json` doesn't exist in that directory, **the server fails to start**
> - You'll see "graphify failed and disabled" in the MCP status
>
> **This means:** Global config only works if you **always run OpenCode from a project directory that has `graphify-out/graph.json`**.

**Key difference:** Notice the `command` array omits the graph path argument. The `graphify-mcp` executable defaults to `graphify-out/graph.json` relative to the current working directory.

**Advantages:**
- Single configuration applies to all projects
- No per-project `.opencode/opencode.json` required for MCP setup

**Disadvantages:**
- **Fails silently** if you run OpenCode from a directory without `graphify-out/graph.json`
- Requires you to always remember to run OpenCode from the correct directory

**When to use:** Only if you consistently work from project directories that have `graphify-out/graph.json` and understand the directory requirement.

#### Critical: Understanding How MCP Servers Work

**The MCP server is a running process, not just a configuration.**

When you start OpenCode, it reads your MCP configuration and **automatically starts the server process** by executing the `command` from your current working directory. This is why the directory matters:

| Configuration | When MCP Server Starts | What Happens |
|--------------|------------------------|--------------|
| **Project-specific** | Only when running `opencode` from that project's directory | OpenCode starts `graphify-mcp` from the project root where `graphify-out/graph.json` exists ✅ |
| **Global** | Always, regardless of directory | OpenCode tries to start `graphify-mcp` from whatever directory you're in. If no `graphify-out/graph.json`, the server **fails to start** ❌ |

**Scenario 1: Project-specific config (Recommended)**

```bash
# Config exists in: /home/user/projects/myapp/.opencode/opencode.json

# ✅ CORRECT - running from the project
cd /home/user/projects/myapp
opencode
# → OpenCode loads .opencode/opencode.json
# → Starts graphify-mcp from /home/user/projects/myapp
# → graphify-out/graph.json exists → SERVER STARTS SUCCESSFULLY ✅

# ❌ WRONG - running from different directory
cd /home/user/projects/other-project
opencode
# → OpenCode does NOT load myapp's .opencode/opencode.json
# → No graphify MCP configured at all
```

**Scenario 2: Global config (Use with caution)**

```bash
# Config exists in: ~/.config/opencode/opencode.jsonc (global)

# ✅ CORRECT - running from project with graph
cd /home/user/projects/myapp  # has graphify-out/graph.json
opencode
# → OpenCode loads global config
# → Starts graphify-mcp from /home/user/projects/myapp
# → graphify-out/graph.json exists → SERVER STARTS SUCCESSFULLY ✅

# ❌ WRONG - running from directory without graph
cd /home/user/projects/other-project  # NO graphify-out/
opencode
# → OpenCode loads global config
# → Tries to start graphify-mcp from /home/user/projects/other-project
# → graphify-out/graph.json NOT FOUND → SERVER FAILS TO START ❌
# → You'll see: "graphify failed and disabled"
```

**Summary:**

| Scope | Config Location | Server Starts From | Prerequisite for Success |
|-------|----------------|-------------------|-------------------------|
| Project-specific | `.opencode/opencode.json` | Project root (where `.opencode/` exists) | `graphify-out/graph.json` must exist in project |
| Global | `~/.config/opencode/opencode.jsonc` | Current working directory | You must run `opencode` from a directory with `graphify-out/graph.json` |

**Recommendation:**
- **Team projects:** Use project-specific config — guarantees the server starts from the correct directory
- **Personal multi-project workflow:** Either use project-specific config for each project, OR always remember to run `opencode` from a project directory that has `graphify-out/graph.json`

#### Configuration Details

| Field | Description |
|-------|-------------|
| `type` | Must be `"local"` for command-based MCP servers |
| `command` | Array where the first item is the executable, followed by arguments. Use the full path if `graphify-mcp` is not on your global `PATH`, e.g., `["/home/user/.local/bin/graphify-mcp"]` |
| `enabled` | Set to `true` to activate the server. Set to `false` to temporarily disable without removing the configuration |
| `plugin` | (Project-specific only) Path to the Graphify skill file, relative to the project root. Installed via `graphify install --platform opencode` |

#### How OpenCode Merges Configurations

OpenCode merges global and project configurations:

1. **Global config** (`~/.config/opencode/opencode.jsonc`) is loaded first
2. **Project config** (`.opencode/opencode.json`) is loaded second and can override or extend global settings

This means you can:
- Define Graphify globally and use it in all projects
- Override specific settings per-project if needed (e.g., disable for a particular project by setting `"enabled": false`)

#### Verification

Once configured, OpenCode automatically gains access to the following tools:

- `query_graph`: Execute structured queries against the graph
- `get_node`: Retrieve a specific file/function/class node's details and connections
- `get_neighbors`: Get all direct neighbors of a node with edge details
- `get_community`: Get all nodes in a community by community ID
- `shortest_path`: Compute the dependency chain between two nodes
- `graph_stats`: Return summary statistics (node count, edge count, communities)
- `god_nodes`: Return the most connected nodes (core abstractions)
- `list_prs`: List open GitHub PRs with CI status and graph impact
- `triage_prs`: Return actionable open PRs with full graph impact data
- `get_pr_impact`: Get detailed graph impact for a specific PR

To verify the MCP server is running, ask OpenCode: *"What graph tools do you have available?"*
You could also run : /mcp  and then search for  `graphify`.

---

### 4.3 Expose the Graphify MCP Server

Expose your generated graph via the native MCP server. If installed globally or via `pipx`, you can run:
```bash
graphify-mcp graphify-out/graph.json
```
Or run the module directly:
```bash
python -m graphify.serve graphify-out/graph.json
```
*Note: Make sure you installed the `[mcp]` extra so the server dependencies are met.*

### 4.4 Verify the MCP Server is Running

After configuring and exposing the MCP server, you can verify that the process is running correctly:

```bash
ps aux | grep -i graphify | grep -v grep
```

This command will show you any running graphify processes. If the MCP server is properly configured and graphify is running, you should see the process listed.

If you see the `graphify-mcp` process, it means the MCP server is actively serving your graph.

---

### 4.5 Ask OpenCode questions using the graph

Once the MCP server is configured and the skill is installed, OpenCode can answer questions about your codebase using the graph. The graph contains detailed information about files, functions, classes, imports, and calls, so you can ask about **structure, dependencies, and impact analysis** – all in natural language.

**General question templates you can try (replace `function_name` and `file.rs` with your own names):**

- *“Show me the callers of `function_name`.”* – Finds every function or method that calls that specific one.
- *“What does `file.rs` depend on?”* – Lists all modules, files, or functions that `file.rs` directly uses.
- *“Which files are affected if I change `file.rs`?”* – Traces reverse dependencies to find files that import or call that file.
- *“Show the shortest path from `main` to `analytics`.”* – Computes the chain of calls/imports connecting two components.
- *“What are the most central files in this project?”* – Uses graph metrics to identify high‑cohesion or high‑impact nodes.
- *“List all functions that call `utils/helpers.rs` and are called by `api/controllers.rs`.”* – Combine filters to narrow down context.

Because the graph knows your project’s structure, OpenCode can answer these questions almost instantly – no need to grep through thousands of files or feed entire contexts into the model.

**Feel free to experiment**: ask OpenCode about your own modules, classes, or functions. The answers will help you understand architecture, plan refactoring, or onboard new team members quickly.

If you’re unsure what to ask, you can start with:
- *“What does the current graph tell you about my codebase?”* – OpenCode will summarise the graph’s contents and suggest relevant questions you might want to ask.






---

## 5. Keeping the graph up‑to‑date

After pulling changes or editing code:

```bash
graphify update .
```

For automatic rebuilding during development:

```bash
graphify watch .
```

To verify the status of your Graphify hooks or check if the graph needs rebuilding, run:
```bash
graphify check-update
# or
graphify hook status
```

For CI (e.g., GitLab/GitHub Actions), add a job that runs `graphify update .` and archives `graphify-out/graph.json` as an artifact.

---

## 6. Quick start checklist

### For Team Projects (Project-Specific Config)

- [ ] Install package with needed extras: `pip install "graphifyy[mcp,gemini,pdf]"` (or `[openai]` if using custom provider)
- [ ] Build initial graph: `cd your-project && graphify update .`
- [ ] Open `graphify-out/graph.html` in browser to explore the visual map
- [ ] **Install the OpenCode skill:** `graphify install --platform opencode` (recommended)
- [ ] Configure the MCP server in `.opencode/opencode.json` (see Section 4.2, Option A)
- [ ] Commit `.opencode/opencode.json` and `.opencode/plugins/graphify.js` to version control
- [ ] Verify the graph status from the command line: `graphify check-update`
- [ ] Ask OpenCode: *"What are the most central files in the codebase?"*
- [ ] (Optional) Configure custom OpenAI/Gemini credentials for doc-code enrichment
- [ ] Add `graphify update .` to your CI pipeline

### For Personal Workflows (Global Config)

> **⚠️ Remember:** With global config, you must run `opencode` from a directory that has `graphify-out/graph.json`, otherwise the MCP server will fail to start.

- [ ] Install package with needed extras: `pip install "graphifyy[mcp,gemini,pdf]"` (or `[openai]` if using custom provider)
- [ ] Configure Graphify MCP globally in `~/.config/opencode/opencode.jsonc` (see Section 4.2, Option B)
- [ ] For each project: `cd your-project && graphify update .`
- [ ] Verify the graph exists: `ls graphify-out/graph.json`
- [ ] **Always run `opencode` from the project directory** (where `graphify-out/` exists)
- [ ] Ask OpenCode: *"What graph tools do you have available?"*

---

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `error: no LLM API key found` | Running `graphify .` without a key and with docs/images present | Use `graphify update .` instead, or configure your Gemini/OpenAI credentials |
| `ImportError: No module named mcp` | Running `graphify.serve` without MCP dependencies | Re-install with extras: `pip install "graphifyy[mcp]"` |
| `graphify: command not found` | Not installed or PATH issue | `pip install graphifyy`; restart terminal |
| MCP server doesn't reload changes | Graph server reads `graph.json` at startup only | Restart the `graphify.serve` process after rebuilding |
| Graph is very slow or huge | Repository very large | Use `.graphifyignore` to exclude `node_modules`, `dist`, etc. |
| Graphify tools not available in OpenCode | MCP server not configured or not running | Verify configuration in `.opencode/opencode.json` (project) or `~/.config/opencode/opencode.jsonc` (global); ensure `graphify-out/graph.json` exists |
| MCP server not listed at all (project-specific) | Running opencode from wrong directory | Run `opencode` from the project root (where `.opencode/` exists), not from a subdirectory or different location |
| MCP server listed but "failed and disabled" (global config) | Running OpenCode from a directory without `graphify-out/graph.json` | Run `opencode` from a project directory that has `graphify-out/graph.json`, or use project-specific config instead |
| Global config not working | Graph file missing in project | Global config requires `graphify-out/graph.json` in the project root. Run `graphify update .` first |
| Both global and project config present | Configs merge; project can override global | Check for conflicting `enabled: false` in project config, or duplicate MCP server names |
| `graphify-mcp` not found in global PATH | Installed via pipx or in user-local bin | Use full path in command: `["/home/user/.local/bin/graphify-mcp"]` |

---

## 8. Reference links

- Graphify CLI – `graphify --help`
- Graphify GitHub – [https://github.com/safishamsi/graphify](https://github.com/safishamsi/graphify)
- OpenCode MCP integration – [https://opencode.ai/docs/mcp-servers/](https://opencode.ai/docs/mcp-servers/)
- Google Gemini API – [https://ai.google.dev/gemini-api](https://ai.google.dev/gemini-api)
    
---