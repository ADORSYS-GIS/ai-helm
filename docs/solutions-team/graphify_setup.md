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

#### Option A: Using Google Gemini (Default)
Set your Gemini key and run the extraction:
```bash
export GEMINI_API_KEY="your-gemini-key-here"
graphify .
```

#### Option B: Using a Custom OpenAI-Compatible Provider (e.g. ADORSYS Provider)
To point Graphify to a custom OpenAI-compatible endpoint, register a custom provider via the Graphify CLI:
```bash
# Register the custom provider
graphify provider add adorsys \
  --base-url "https://your-custom-openai-endpoint/v1" \
  --default-model "your-model-name" \
  --env-key "OPENAI_API_KEY"

# Set the key and extract the graph
export OPENAI_API_KEY="your-custom-api-key"
graphify . --backend adorsys
```

---

## 4. Integrate with OpenCode via MCP

### 4.1 Why run it as an MCP server?
While the Graphify CLI builds the graph, exposing it as a Model Context Protocol (MCP) server allows AI assistants like OpenCode to query the codebase structure dynamically. Rather than passing entire files as context (which is slow and expensive), OpenCode calls tools to navigate connections, trace dependencies, and retrieve only the relevant parts of code in milliseconds.

> **Note on `graphify install`:** Graphify provides a convenience command (`graphify install --platform opencode`) that copies a skill file for OpenCode. However, that command **does not** configure the MCP server itself – it only installs a prompt / instruction file. To actually expose the graph as queryable tools, you must follow the manual MCP server setup below.

### 4.2 Expose the Graphify MCP Server
Expose your generated graph via the native MCP server. If installed globally or via `pipx`, you can run:
```bash
graphify-mcp graphify-out/graph.json
```
Or run the module directly:
```bash
python -m graphify.serve graphify-out/graph.json
```
*Note: Make sure you installed the `[mcp]` extra so the server dependencies are met.*

### 4.3 Configure OpenCode to connect to the MCP server
Add the server configuration to your project's `.opencode/opencode.json` configuration file. OpenCode uses the `"mcp"` object mapping to a `"local"` configuration, where the `"command"` is an array containing the executable command and its arguments.

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

> **Configuration Details:**
> - **`command`**: This must be an array where the first item is the command executable, followed by its arguments. If you do not have `graphify-mcp` on your global path, you can use `["python", "-m", "graphify.serve", "graphify-out/graph.json"]`.
> - **`plugin`**: Add `".opencode/plugins/graphify.js"` to register the Graphify skill/plugin in OpenCode (copied during the `graphify install` step).

Once connected, OpenCode automatically gains access to the following tools:
- `query_graph`: Execute structured queries against the graph
- `get_node`: Retrieve a specific file/function/class node's details and connections
- `shortest_path`: Compute the dependency chain between two nodes

### 4.4 Ask OpenCode questions using the graph
Once the server is configured, OpenCode will call the MCP tools directly to answer architectural questions:
- *“What functions call `load_trades`?”*
- *“Which files depend on `database.py`?”*
- *“Show the shortest path from `main` to `analytics`.”*

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

- [ ] Install package with needed extras: `pip install "graphifyy[mcp,gemini,pdf]"` (or `[openai]` if using custom provider)
- [ ] Build initial graph: `cd your-project && graphify update .`
- [ ] Open `graphify-out/graph.html` in browser to explore the visual map
- [ ] Start the MCP server: `graphify-mcp graphify-out/graph.json` (or `python -m graphify.serve graphify-out/graph.json`)
- [ ] Configure the server in `.opencode/opencode.json`
- [ ] Verify the graph status from the command line: `graphify check-update`
- [ ] Ask OpenCode: *“What are the most central files in the codebase?”*
- [ ] (Optional) Configure custom OpenAI/Gemini credentials for doc-code enrichment
- [ ] Add `graphify update .` to your CI pipeline

---

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `error: no LLM API key found` | Running `graphify .` without a key and with docs/images present | Use `graphify update .` instead, or configure your Gemini/OpenAI credentials |
| `ImportError: No module named mcp` | Running `graphify.serve` without MCP dependencies | Re-install with extras: `pip install "graphifyy[mcp]"` |
| `graphify: command not found` | Not installed or PATH issue | `pip install graphifyy`; restart terminal |
| MCP server doesn't reload changes | Graph server reads `graph.json` at startup only | Restart the `graphify.serve` process after rebuilding |
| Graph is very slow or huge | Repository very large | Use `.graphifyignore` to exclude `node_modules`, `dist`, etc. |

---

## 8. Reference links

- Graphify CLI – `graphify --help`
- Graphify GitHub – [https://github.com/safishamsi/graphify](https://github.com/safishamsi/graphify)
- OpenCode MCP integration – [https://opencode.ai/docs/mcp-servers/](https://opencode.ai/docs/mcp-servers/)
- Google Gemini API – [https://ai.google.dev/gemini-api](https://ai.google.dev/gemini-api)
- PyPI package page – [https://pypi.org/project/graphifyy/](https://pypi.org/project/graphifyy/)

---
