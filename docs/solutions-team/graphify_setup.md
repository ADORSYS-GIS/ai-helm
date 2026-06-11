# Graphify + OpenCode — Setup & Adoption Guide



## What is Graphify?

**Graphify** is a tool that turns any codebase (and associated documentation, diagrams, images) into a **queryable knowledge graph** – a map of files, functions, classes, calls, imports, and semantic relationships. This graph lets AI assistants like OpenCode answer questions about dependencies, impact analysis, and architecture in milliseconds, using **70x fewer tokens** than traditional file‑grepping approaches.

---

## 1. How it works (quick mental model)

Graphify builds the graph in two independent modes:

| Mode | What it does | Requires API key? |
|------|--------------|-------------------|
| **Code‑only (AST)** | Parses code using `tree‑sitter` – extracts functions, classes, calls, imports. Fully local, deterministic. | ❌ No |
| **Full (with LLM)** | Also sends docs, images, PDFs to an LLM (e.g. Google Gemini) to infer semantic relationships (e.g. “this diagram implements that function”). | ✅ Yes – for non‑code files only |

The output is `graph.json`. Once the Graphify skill is installed, OpenCode can query the graph directly – no more slow, expensive file scanning.

---

## 2. Prerequisites

- Python 3.10+ and `pip`
- OpenCode installed in your project (CLI or IDE)
- (Optional) A **Google Gemini API key** if you want semantic enrichment of docs/images.  
  Code‑only analysis needs **no key**.
- Your project uses Git (Graphify respects `.gitignore`)

---

## 3. Generate the graph

### 3.1 Install Graphify

```bash
pip install graphifyy
```

Verify: `graphify --version`

### 3.2 Code‑only graph (no API key, recommended first step)

Use `graphify update .` – this command is designed for incremental code re‑extraction. It **only processes code files** (`.py`, `.js`, `.go`, etc.) and completely ignores documentation and images. No API key is ever required.

```bash
cd /path/to/your/project
graphify update .
```

> **Why `update` instead of `graphify .`?**  
> - `graphify .` attempts to analyse **all files**, including docs and images. If an LLM key is not set, it will fail with an error like `no LLM API key found (11 doc/paper/image file(s) need semantic extraction)`.  
> - `graphify update .` is explicitly for code‑only extraction – it skips non‑code files entirely, so it never needs an API key and never fails that way. It is also faster because it uses caching for unchanged files.

Output is written to `graphify-out/`:
- `graph.json` – machine‑readable graph
- `graph.html` – interactive visualisation (open in your browser)
- `GRAPH_REPORT.md` – plain‑English summary (god nodes, communities, cohesion scores)

### 3.3 (Optional) Add LLM enrichment for docs/images

Set your Gemini key and run the standard `graphify .` command (this will also reprocess code, which is fine):

```bash
export GEMINI_API_KEY="your-key-here"
graphify .
```

Now the graph will contain `INFERRED` edges linking diagrams, PDFs, and markdown to code.  
**Note:** Your source code is never sent to any LLM – only the non‑code files you explicitly include.

---

## 4. Integrate with OpenCode

### 4.1 Install the Graphify skill for OpenCode

```bash
graphify install --platform opencode
```

This registers the MCP tools (like `graphify_find_nodes`, `graphify_affected`) so OpenCode can call them.

### 4.2 Verify the integration inside OpenCode

Open your OpenCode assistant (terminal or IDE) and type:

```
/graphify
```

If the graph is present and the skill loaded, you'll see a confirmation. You can also type `/graphify status` to see status of the graphs.

### 4.3 Open the interactive graph in your browser

From your project root:

```bash
open graphify-out/graph.html   # or double‑click the file
```

You'll see a colour‑coded, clickable visualisation of your entire codebase – communities, central files, and dependencies.

### 4.4 Ask OpenCode questions that use the graph

Now OpenCode can answer instantly, without grepping:

- *“What functions call `load_trades`?”*
- *“Which files depend on `database.py`?”*
- *“Show the shortest path from `main` to `analytics`.”*

OpenCode will use the graph and respond in milliseconds, reading only the relevant lines.

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

For CI (e.g., GitLab), add a job that runs `graphify update .` and archives `graphify-out/graph.json` as an artifact.

---

## 6. Quick start checklist

- [ ] `pip install graphifyy`
- [ ] `cd your-project && graphify update .`
- [ ] Open `graphify-out/graph.html` in browser – explore
- [ ] `graphify install --platform opencode`
- [ ] Inside OpenCode: `/graphify status`
- [ ] Ask: *“What are the most central files?”* – watch instant answer
- [ ] (Optional) Set `GEMINI_API_KEY` and run `graphify .` for doc‑code links
- [ ] Add `graphify update .` to your CI pipeline

Now OpenCode has a real map of your codebase – faster answers, lower token costs, and better architectural insights.

---

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `error: no LLM API key found` | Running `graphify .` without a key and with docs/images present | Use `graphify update .` instead, or set `GEMINI_API_KEY` |
| `graphify: command not found` | Not installed or PATH issue | `pip install graphifyy`; restart terminal |
| OpenCode doesn’t show `/graphify` commands | Skill not installed | Re-run `graphify install --platform opencode` and restart OpenCode |
| `/graphify status` reports stale graph | Code changed without rebuild | Run `graphify update .` again |
| Graph is very slow or huge | Repository very large | Use `.graphifyignore` to exclude `node_modules`, `dist`, etc. |

---

## 8. Reference links

- Graphify CLI – `graphify --help`
- Graphify GitHub – [https://github.com/graphify/graphify](https://github.com/graphify/graphify)
- OpenCode MCP integration – [https://opencode.ai/docs/mcp/](https://opencode.ai/docs/mcp/)
- Google Gemini API – [https://ai.google.dev/gemini-api](https://ai.google.dev/gemini-api)
- python install [https://pypi.org/project/graphifyy/](https://pypi.org/project/graphifyy/)