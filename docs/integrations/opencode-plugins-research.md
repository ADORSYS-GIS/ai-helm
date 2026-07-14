# OpenCode Plugins and Extensions Research

## Executive Summary

This document provides a comprehensive assessment of OpenCode plugins and their applicability to our development workflows. OpenCode is a terminal-based AI coding agent that supports an extensive plugin ecosystem for extending functionality, integrating external tools, and customizing agent behavior.

### Key Findings

1. **Plugin Ecosystem Maturity**: The OpenCode plugin ecosystem is rapidly growing with 50+ community plugins available, covering authentication, memory, notifications, workflow orchestration, and more.

2. **Target Plugin Assessment**: All five target plugins are actively maintained and production-ready. Each serves a distinct purpose and can be adopted independently based on team needs.

3. **Recommended Priority**:
   - **High Priority**: `opencode-subagent-statusline`, `opencode-slim-system` (immediate productivity gains)
   - **Medium Priority**: `opencode-skills-collection`, `ai-sdk-provider-opencode-sdk` (workflow enhancement)
   - **Evaluation Required**: `opencode-swarm` (complex orchestration - pilot recommended)

---

## Table of Contents

1. [OpenCode Plugin Architecture Overview](#opencode-plugin-architecture-overview)
2. [Target Plugin Assessments](#target-plugin-assessments)
   - [opencode-skills-collection](#1-opencode-skills-collection)
   - [opencode-subagent-statusline](#2-opencode-subagent-statusline)
   - [ai-sdk-provider-opencode-sdk](#3-ai-sdk-provider-opencode-sdk)
   - [opencode-swarm](#4-opencode-swarm)
   - [opencode-slim-system](#5-opencode-slim-system)
3. [Additional Notable Plugins](#additional-notable-plugins)
4. [Compatibility Matrix](#compatibility-matrix)
5. [Recommendations](#recommendations)
6. [Implementation Plan](#implementation-plan)

---

## OpenCode Plugin Architecture Overview

### What Are OpenCode Plugins?

OpenCode plugins are JavaScript/TypeScript modules that hook into various events and customize agent behavior. They can:

- **Add new features** through custom tools
- **Integrate external services** (GitHub, Jira, Slack, etc.)
- **Modify default behavior** (context pruning, notifications, authentication)
- **Extend the TUI** with sidebar panels and status indicators

### Plugin Installation Methods

| Method | Location | Use Case |
|--------|----------|----------|
| **npm packages** | `opencode.json` → `"plugin": ["package-name"]` | Published plugins, version-controlled |
| **Local files** | `.opencode/plugins/` (project) or `~/.config/opencode/plugins/` (global) | Custom plugins, development |
| **TUI plugins** | `tui.json` → `"plugin": ["package-name"]` | Sidebar extensions, visual components |

### Plugin Load Order

1. Global config (`~/.config/opencode/opencode.json`)
2. Project config (`opencode.json`)
3. Global plugin directory (`~/.config/opencode/plugins/`)
4. Project plugin directory (`.opencode/plugins/`)

### Available Plugin Events

Plugins can subscribe to numerous events:

- **Command Events**: `command.executed`
- **File Events**: `file.edited`, `file.watcher.updated`
- **Session Events**: `session.created`, `session.compacted`, `session.idle`
- **Tool Events**: `tool.execute.before`, `tool.execute.after`
- **Permission Events**: `permission.asked`, `permission.replied`
- **TUI Events**: `tui.command.execute`, `tui.toast.show`

---

## Target Plugin Assessments

### 1. opencode-skills-collection

**Repository:** [FrancoStino/opencode-skills-collection](https://github.com/FrancoStino/opencode-skills-collection)  
**npm:** `opencode-skills-collection`  
**Version:** 3.0.47 (actively maintained, 436+ versions published)  
**License:** MIT

#### Purpose

A comprehensive collection of 1000+ pre-bundled AI skills delivered with zero network latency at startup. Uses a **SkillPointer** architecture to avoid context bloat.

#### Functionality

- **Skill Discovery**: Automatically finds skills from project, user, and plugin directories
- **On-Demand Loading**: Skills are organized into categories inside a hidden vault and only loaded when needed
- **Context Efficiency**: Reduces startup tokens from ~80,000 to ~255 by using pointer files
- **Risk Filtering**: Configurable filtering of skills by risk level (`safe`, `critical`, `offensive`, `unknown`)

#### Key Features

| Feature | Description |
|---------|-------------|
| SkillPointer Architecture | ~35 lightweight pointer files instead of loading all skills |
| Vault System | Raw skills stored separately, loaded on demand |
| Risk-Based Filtering | Block skills by risk level or specific skill ID |
| Beta Releases | Available via `@beta` tag for testing |

#### Installation

```json
{
  "plugin": ["opencode-skills-collection@latest"]
}
```

#### Usage

```bash
# Explicit invocation
opencode run /brainstorming help me plan a new feature

# Slash commands in chat
/brainstorming
/refactor
/document

# Natural language (auto-detected)
"Help me brainstorm ideas for a REST API design"
```

#### Quality Assessment

| Criteria | Rating | Notes |
|----------|--------|-------|
| **Maintenance** | ⭐⭐⭐⭐⭐ | 436 versions, updated recently |
| **Community** | ⭐⭐⭐⭐ | Active development, clear documentation |
| **Documentation** | ⭐⭐⭐⭐⭐ | Comprehensive README with examples |
| **Stability** | ⭐⭐⭐⭐ | Mature architecture, versioned releases |

#### Benefits for Our Workflow

- **Immediate Value**: Ready-to-use skills for common tasks (code review, testing, debugging)
- **No Context Bloat**: Efficient loading prevents token exhaustion
- **Extensible**: Can add custom skills to the collection
- **Risk Management**: Built-in filtering for security-conscious environments

#### Potential Concerns

- Large number of skills may require curation for team-specific needs
- Risk filtering requires configuration for enterprise use

---

### 2. opencode-subagent-statusline

**Repository:** [Joaquinvesapa/sub-agent-statusline](https://github.com/Joaquinvesapa/sub-agent-statusline)  
**npm:** `opencode-subagent-statusline`  
**Version:** 0.9.2 (actively maintained)  
**License:** MIT

#### Purpose

A TUI sidebar plugin that provides real-time visibility into subagent activity. Shows running, completed, and failed subagents with elapsed time and token/context usage.

#### Functionality

- **Real-Time Monitoring**: Track subagent status without losing context
- **Session History**: Retained completed history (up to 3 days, 1,500-row cap)
- **Keyboard Navigation**: Full keyboard support for sidebar interaction
- **Token Tracking**: Displays token/context usage when available

#### Key Features

| Feature | Description |
|---------|-------------|
| Running Subagents | Live status of active subagents |
| Completed History | Toggle retained history with `c` key |
| Failed Subagents | Clear visibility of failures |
| Elapsed Time | Duration tracking per subagent |
| Token/Context Usage | Per-session metrics when exposed |

#### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Alt+B` | Toggle focus between sidebar and prompt |
| `j`/`↓` | Move to next subagent |
| `k`/`↑` | Move to previous subagent |
| `Enter` | Open selected subagent session |
| `c` | Toggle completed history |
| `h`/`←` | Collapse section |
| `l`/`→` | Expand section |
| `Esc` | Return to prompt |

#### Installation

```json
// ~/.config/opencode/tui.json
{
  "$schema": "https://opencode.ai/tui.json",
  "plugin": ["opencode-subagent-statusline"]
}
```

#### Quality Assessment

| Criteria | Rating | Notes |
|----------|--------|-------|
| **Maintenance** | ⭐⭐⭐⭐ | Updated few days ago, 30 versions |
| **Community** | ⭐⭐⭐⭐ | 6,858 weekly downloads |
| **Documentation** | ⭐⭐⭐⭐⭐ | Detailed docs in English and Spanish |
| **Stability** | ⭐⭐⭐⭐ | Solid TUI integration |

#### Benefits for Our Workflow

- **Critical for Multi-Agent Work**: Essential when using subagent delegation
- **Visibility**: Never lose track of background tasks
- **Debugging Aid**: Quickly identify failed subagents
- **Resource Awareness**: Token usage helps manage context budget

#### Potential Concerns

- Requires TUI configuration (separate from main `opencode.json`)
- Token/context usage depends on OpenCode version and event payloads

---

### 3. ai-sdk-provider-opencode-sdk

**Repository:** [ben-vargas/ai-sdk-provider-opencode-sdk](https://github.com/ben-vargas/ai-sdk-provider-opencode-sdk)  
**npm:** `ai-sdk-provider-opencode-sdk`  
**Version:** 3.0.6 (stable, AI SDK v6 support)  
**License:** MIT

#### Purpose

A community provider for the Vercel AI SDK that enables using AI models through OpenCode and the `@opencode-ai/sdk/v2` APIs. Allows developers to use OpenCode's AI capabilities through the familiar Vercel AI SDK interface.

#### Functionality

- **AI SDK Integration**: Use OpenCode models with `generateText()`, `streamText()`, `streamObject()`
- **Multi-Provider Support**: Anthropic, OpenAI, Google, Z.ai, MiniMax, Kimi
- **Session Management**: Maintain conversation context across calls
- **Tool Observation**: Monitor tool execution (read-only, server-side)

#### Key Features

| Feature | Support | Notes |
|---------|---------|-------|
| Text generation | ✅ Full | `generateText()`, `streamText()` |
| Streaming | ✅ Full | Real-time SSE streaming |
| Multi-turn conversations | ✅ Full | Session-based context |
| Tool observation | ✅ Full | See tool execution |
| Reasoning/thinking | ✅ Full | ReasoningPart support |
| Model selection | ✅ Full | Per-request model |
| Agent selection | ✅ Full | build, plan, general, explore |
| Abort/cancellation | ✅ Full | AbortSignal support |
| Structured output | ⚠️ Partial | Native `json_schema`; use fallback |
| Custom tools | ❌ None | Server-side only |

#### Supported Models

```typescript
// Anthropic models
opencode("anthropic/claude-sonnet-4-5-20250929");
opencode("anthropic/claude-haiku-4-5-20251001");
opencode("anthropic/claude-opus-4-5-20251101");

// OpenAI models
opencode("openai/gpt-5.3-codex-spark");
opencode("openai/gpt-5.1");

// Google Gemini models
opencode("google/gemini-3-pro-preview");
opencode("google/gemini-2.5-flash");

// Z.ai, MiniMax, Kimi
opencode("zai-coding-plan/glm-5");
opencode("minimax-coding-plan/MiniMax-M2.5");
opencode("kimi-for-coding/k2p5");
```

#### Installation

```bash
npm install ai-sdk-provider-opencode-sdk ai@^6.0.0
```

#### Usage Example

```typescript
import { generateText } from "ai";
import { opencode } from "ai-sdk-provider-opencode-sdk";

const result = await generateText({
  model: opencode("openai/gpt-5.3-codex-spark"),
  prompt: "What is the capital of France?",
});

console.log(result.text);
```

#### Quality Assessment

| Criteria | Rating | Notes |
|----------|--------|-------|
| **Maintenance** | ⭐⭐⭐⭐ | Updated few days ago, 15 versions |
| **Community** | ⭐⭐⭐⭐⭐ | 74,795 weekly downloads |
| **Documentation** | ⭐⭐⭐⭐⭐ | Comprehensive examples, type declarations |
| **Stability** | ⭐⭐⭐⭐ | AI SDK v6 support, version compatibility matrix |

#### Benefits for Our Workflow

- **Integration Flexibility**: Use OpenCode models in existing Vercel AI SDK projects
- **Multi-Provider**: Single interface for multiple AI providers
- **Session Continuity**: Maintain context across multiple calls
- **Type Safety**: Full TypeScript support

#### Potential Concerns

- Structured output requires fallback pattern for strict reliability
- Custom tools not supported (server-side only)
- Requires OpenCode CLI installed and configured

---

### 4. opencode-swarm

**Repository:** [zaxbysauce/opencode-swarm](https://github.com/zaxbysauce/opencode-swarm)  
**npm:** `opencode-swarm`  
**Version:** 7.74.2 (very actively maintained, 480 versions)  
**License:** MIT

#### Purpose

A comprehensive multi-agent orchestration plugin that turns a single AI coding session into an **architect-led team of specialized agents**. Implements gated execution where code never ships without reviewer and test engineer approval.

#### Functionality

- **Specialized Agents**: 18+ core, optional, and conditional agents (architect, coder, reviewer, test_engineer, critic, explorer, sme, docs, designer, etc.)
- **Gated Pipeline**: Code must pass reviewer + test engineer before shipping
- **DEEP_DIVE Protocol**: High-rigor, on-demand codebase audit
- **External Skill Curation**: Opt-in discovery, quarantine, and promotion of external skills
- **PR Monitor**: GitHub PR subscription and background polling

#### Key Features

| Feature | Description |
|---------|-------------|
| **Agent Roster** | architect, coder, reviewer, test_engineer, critic, explorer, sme, docs, designer, critic_oversight, critic_sounding_board, critic_drift_verifier, critic_hallucination_verifier, curator_init, curator_phase, council_generalist, council_skeptic, council_domain_expert |
| **Quality Gates** | syntax_check, placeholder_scan, sast_scan, sbom_generate, quality_budget, build_check, incremental_verify |
| **Execution Modes** | Balanced (default), Turbo, Lean Turbo, Full-Auto |
| **Shell Write Detection** | POSIX/PowerShell/cmd static analysis |
| **Scope Enforcement** | Cross-process persistence with TTL expiry |
| **Context Budget Guard** | Monitors and manages context injection |
| **Resumable Sessions** | All state saved to `.swarm/` |

#### Execution Modes

| Mode | Safety | Speed | Use Case |
|------|--------|-------|----------|
| **Balanced** (default) | High | Medium | Everyday development |
| **Turbo** | Medium | Fast | Rapid iteration |
| **Lean Turbo** | High | Fast | Parallel non-conflicting tasks |
| **Full-Auto** | Deterministic + oversight | Fast | Unattended runs |

#### Installation

```bash
bunx opencode-swarm install
```

#### Commands

```bash
/swarm help [command]    # List all commands or get detailed help
/swarm status            # Current phase and task
/swarm show-plan [N]     # Full plan or filtered by phase
/swarm agents            # Registered agents and models
/swarm diagnose          # Health check
/swarm evidence [task]   # Test and review results
/swarm reset --confirm   # Clear swarm state
```

#### Quality Assessment

| Criteria | Rating | Notes |
|----------|--------|-------|
| **Maintenance** | ⭐⭐⭐⭐⭐ | 480 versions, updated recently |
| **Community** | ⭐⭐⭐⭐ | Active development, comprehensive docs |
| **Documentation** | ⭐⭐⭐⭐⭐ | Extensive docs (architecture, configuration, modes) |
| **Stability** | ⭐⭐⭐⭐ | Mature architecture, extensive testing |

#### Benefits for Our Workflow

- **Enterprise-Grade Quality**: Built-in security scanning, SAST, dependency audit
- **Multi-Agent Coordination**: Specialized agents for different tasks
- **Resumable Work**: State persistence enables long-running projects
- **Free Tier Compatible**: Works with OpenCode Zen's free model roster

#### Potential Concerns

- **Complexity**: Significant learning curve for full feature set
- **Resource Usage**: Multiple agents can increase token consumption
- **Configuration Overhead**: Requires careful configuration for team workflows
- **Potential Overkill**: May be excessive for simple tasks

#### Recommendation

**Pilot First**: Start with a small team project to evaluate fit before broader adoption. The complexity and resource requirements warrant careful evaluation.

---

### 5. opencode-slim-system

**Repository:** [SK-DEV-AI/opencode-slim-system](https://github.com/SK-DEV-AI/opencode-slim-system)  
**npm:** `opencode-slim-system`  
**Version:** 2.0.14 (stable)  
**License:** MIT

#### Purpose

Reduces per-request token overhead by replacing OpenCode's bundled system prompt and built-in tool descriptions with compact versions. Saves **~9,700 tokens per request** (~1,400 from system prompt + ~8,300 from tool descriptions).

#### Functionality

- **System Prompt Replacement**: Compact default prompt (~240 tokens)
- **Tool Description Slimming**: 17 built-in tool descriptions optimized
- **Per-Model Customization**: Different prompts/descriptions for different models
- **Self-Update Notification**: Automatic version checking

#### Key Features

| Feature | Description |
|---------|-------------|
| **Token Savings** | ~9,700 tokens per request |
| **Tool Coverage** | 17 built-in OpenCode tools (v1.15.x) |
| **Model-Specific** | Per-model prompt and description files |
| **TUI Sidebar** | Shows slim count, version, update indicator |
| **Drift Detection** | CI workflow for maintainer use |

#### Token Savings Breakdown

| Component | Tokens Saved |
|-----------|--------------|
| System Prompt | ~1,400 |
| Tool Descriptions | ~8,300 |
| **Total** | **~9,700** |

#### Installation

```json
// ~/.config/opencode/opencode.jsonc
{
  "plugin": ["opencode-slim-system"]
}

// ~/.config/opencode/tui.json
{
  "plugin": ["opencode-slim-system"]
}
```

#### Configuration

```json
{
  "plugin": [
    ["opencode-slim-system", {
      "exclude": ["websearch"],
      "toolsDir": "/home/user/.config/opencode/slim-tools/"
    }]
  ]
}
```

#### Quality Assessment

| Criteria | Rating | Notes |
|----------|--------|-------|
| **Maintenance** | ⭐⭐⭐⭐ | Updated a while ago, 39 versions |
| **Community** | ⭐⭐⭐ | 108 weekly downloads |
| **Documentation** | ⭐⭐⭐⭐ | Clear README with architecture diagram |
| **Stability** | ⭐⭐⭐⭐ | Simple, focused functionality |

#### Benefits for Our Workflow

- **Immediate Cost Savings**: Reduces token usage significantly
- **No Behavior Change**: Same functionality, less overhead
- **Customizable**: Edit prompts and descriptions as needed
- **Model-Aware**: Different optimizations for different models

#### Potential Concerns

- **Drift Risk**: OpenCode updates may change tool descriptions
- **Slimmed Prompts**: May lose some context nuance
- **Configuration Required**: Per-model customization needs setup

---

## Additional Notable Plugins

Based on our research, these plugins are also worth considering:

### Authentication Plugins

| Plugin | Purpose | Recommendation |
|--------|---------|----------------|
| `@vymalo/opencode-oauth2` | Use existing converse api plan instead of opencode API billing | Useful for teams in adorsys |
| `@vymalo/opencode-models-info` | Auto-discovering models from a /v1/models endpoint | Useful for teams in adorsys |


### Memory & Context Plugins

| Plugin | Purpose | Recommendation |
|--------|---------|----------------|
| `opencode-mem` | Persistent memory across sessions | Essential for long-running projects |
| `opencode-supermemory` | Persistent memory using Supermemory | Alternative memory solution |
| `opencode-dynamic-context-pruning` | Optimize token usage by pruning obsolete context | Recommended for long sessions |

### Workflow Plugins

| Plugin | Purpose | Recommendation |
|--------|---------|----------------|
| `opencode-worktree` | Zero-friction git worktrees | Useful for parallel development |
| `opencode-background-agents` | Claude Code-style background agents | For async delegation |
| `opencode-notify` | Native OS notifications | Essential for task completion awareness |

### Security Plugins

| Plugin | Purpose | Recommendation |
|--------|---------|----------------|
| `envsitter-guard` | Prevent .env leaks | Recommended for security |
| `opencode-vibeguard` | Redact secrets/PII before LLM calls | Enterprise security requirement |

### Development Plugins

| Plugin | Purpose | Recommendation |
|--------|---------|----------------|
| `opencode-morph-fast-apply` | 10x faster code editing | Performance optimization |
| `opencode-firecrawl` | Web scraping via Firecrawl CLI | For web data extraction |
| `opencode-pty` | Background processes in PTY | For long-running processes |

---

## Compatibility Matrix

### Environment Compatibility

| Plugin | VSCode | IntelliJ | CLI | Notes |
|--------|--------|----------|-----|-------|
| `opencode-skills-collection` | ✅ | ✅ | ✅ | Works everywhere |
| `opencode-subagent-statusline` | ⚠️ | ⚠️ | ✅ | TUI-specific, requires terminal |
| `ai-sdk-provider-opencode-sdk` | ✅ | ✅ | ✅ | SDK, environment-agnostic |
| `opencode-swarm` | ✅ | ✅ | ✅ | Works everywhere |
| `opencode-slim-system` | ✅ | ✅ | ✅ | Works everywhere |

### OpenCode Version Compatibility

| Plugin | Minimum Version | Recommended | Notes |
|--------|-----------------|-------------|-------|
| `opencode-skills-collection` | v1.0.110+ | Latest | SkillPointer requires recent OpenCode |
| `opencode-subagent-statusline` | v1.15.x+ | Latest | TUI plugin architecture |
| `ai-sdk-provider-opencode-sdk` | AI SDK v5/v6 | AI SDK v6 | Version-specific |
| `opencode-swarm` | v1.15.x+ | Latest | Extensive hooks usage |
| `opencode-slim-system` | v1.15.x+ | Latest | Tool definition hooks |

---

## Recommendations

### Immediate Adoption (High Priority)

#### 1. opencode-subagent-statusline

**Why**: Essential visibility for any multi-agent work. Low risk, high value.

**Installation**:
```json
// ~/.config/opencode/tui.json
{
  "$schema": "https://opencode.ai/tui.json",
  "plugin": ["opencode-subagent-statusline"]
}
```

**Use Cases**:
- Monitor background tasks
- Debug failed subagents
- Track token usage

#### 2. opencode-slim-system

**Why**: Immediate token savings with no behavior change. Low risk, measurable benefit.

**Installation**:
```json
// ~/.config/opencode/opencode.jsonc
{
  "plugin": ["opencode-slim-system"]
}
```

**Use Cases**:
- Reduce per-request costs
- Optimize context window usage
- Customize prompts per model

### Workflow Enhancement (Medium Priority)

#### 3. opencode-skills-collection

**Why**: Ready-to-use skills for common tasks. Extensible for team-specific needs.

**Installation**:
```json
{
  "plugin": ["opencode-skills-collection@latest"]
}
```

**Use Cases**:
- Code review workflows
- Testing patterns
- Documentation generation
- Security filtering for enterprise

#### 4. ai-sdk-provider-opencode-sdk

**Why**: Enables OpenCode models in existing Vercel AI SDK projects.

**Installation**:
```bash
npm install ai-sdk-provider-opencode-sdk ai@^6.0.0
```

**Use Cases**:
- Integrate OpenCode into existing applications
- Multi-provider abstraction
- Session management

### Evaluation Required (Pilot First)

#### 5. opencode-swarm

**Why**: Complex orchestration with significant learning curve. Requires careful evaluation.

**Recommendation**: Start with a small pilot project before broader adoption.

**Installation**:
```bash
bunx opencode-swarm install
```

**Use Cases**:
- Complex multi-component projects
- Enterprise-grade quality gates
- Long-running development tasks
- Teams requiring formal review processes

**Pilot Plan**:
1. Select one non-critical project
2. Configure for Balanced mode
3. Evaluate over 2-4 weeks
4. Assess team feedback and resource usage
5. Decide on broader rollout

---

## Appendix: Plugin Configuration Examples

### Global Configuration

```json
// ~/.config/opencode/opencode.json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": [
    "opencode-skills-collection@latest",
    "opencode-slim-system",
    "opencode-mem"
  ]
}
```

### TUI Configuration

```json
// ~/.config/opencode/tui.json
{
  "$schema": "https://opencode.ai/tui.json",
  "plugin": [
    "opencode-subagent-statusline"
  ]
}
```

### Project-Level Configuration

```json
// .opencode/opencode.json
{
  "plugin": [
    "./plugins/custom-workflow.ts"
  ]
}
```

### Swarm Configuration

```json
// ~/.config/opencode/opencode-swarm.json
{
  "agents": {
    "architect": { "model": "anthropic/claude-opus-4-6" },
    "coder": { "model": "minimax-coding-plan/MiniMax-M2.5" },
    "reviewer": { "model": "zai-coding-plan/glm-5" }
  },
  "execution_mode": "balanced",
  "gates": {
    "syntax_check": { "enabled": true },
    "sast_scan": { "enabled": true }
  }
}
```

---

## References

- [OpenCode Official Documentation](https://opencode.ai/docs/)
- [OpenCode Plugin Documentation](https://opencode.ai/docs/plugins/)
- [OpenCode Ecosystem](https://opencode.ai/docs/ecosystem)
- [Awesome OpenCode](https://github.com/awesome-opencode/awesome-opencode)
- [Composio: Best OpenCode Plugins](https://composio.dev/content/best-opencode-plugins)