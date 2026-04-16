# OpenCode Agent System

This directory contains OpenCode-specific configuration for the multi-agent development system for this Azamra monorepo.

## Agent Architecture

The project uses 10 specialized agents designed for working in this codebase:

### Primary Agents (switch with Tab)
- **mobile-agent** - Mobile app development (apps/mobile)
- **kyc-manager-agent** - KYC Manager admin app (apps/kyc-mgr)
- **orchestrator-agent** - Architecture coordination and reviews

These three agents are configured with `mode: all`, so they can be selected directly and also invoked from other agents when cross-domain work is needed.

### Shared Agents (invoke with @)
- **ui-system-agent** - UI component system (packages/ui)
- **hooks-agent** - Service layer hooks (packages/hooks)
- **platform-agent** - Platform & security layer (packages/platform)
- **api-agent** - API integration (packages/api-rest)
- **shared-agent** - Cross-cutting concerns (i18n, contracts, tw-preset)
- **code-reviewer** - General code reviews
- **meta-agent** - Agent configuration updates

## Commands

Commands are invoked with `/` in the TUI:

**Project-wide:**
- `/test` - Run full test suite with coverage
- `/lint` - Lint and format all code
- `/typecheck` - Type check all TypeScript
- `/check-architecture` - Verify architectural compliance

**Testing:**
- `/test-hooks` - Test hooks package
- `/test-mobile` - Test mobile app
- `/test-kyc` - Test KYC Manager
- `/debug-test <file>` - Debug failing test

**Development:**
- `/create-component <name>` - Create new UI component
- `/create-hook <name>` - Create new custom hook
- `/create-screen <name>` - Create new mobile screen
- `/find-bug <feature>` - Investigate and find bug

**Maintenance:**
- `/review-pr` - Review PR changes
- `/update-codegen` - Regenerate API clients
- `/update-agents` - Update agents from AGENTS.md
- `/upgrade-deps` - Upgrade dependencies
- `/clean-all` - Clean build artifacts

## Agent Coordination

The agents follow a layer structure:

```
Layer 1 (Foundation): platform-agent, api-agent, shared-agent
        ↓
Layer 2 (Shared): ui-system-agent, hooks-agent
        ↓
Layer 3 (Apps): mobile-agent, kyc-manager-agent
        ↓
orchestrator-agent (coordinates across layers)
```

Agents invoke each other via the Task tool. The orchestrator-agent coordinates breaking changes and ensures architectural compliance.

## Agent Updates

When AGENTS.md changes, run `/update-agents` to update agent configurations. The meta-agent will:
1. Parse AGENTS.md for new conventions
2. Update agent prompts
3. Ensure consistency
4. Report changes made

## Configuration

- **Agents**: `.opencode/agents/*.md` - Agent definitions
- **Commands**: `.opencode/commands/*.md` - Command definitions

## Config Notes

- Command frontmatter `agent:` must reference an OpenCode agent name such as `ui-system-agent` or `code-reviewer`, not a model id.
- Models belong on agents and use the configured `cdigital-test` provider prefix, for example `cdigital-test/glm-5`.
- Subagent-style commands use `subtask: true` so reviews and scoped workflows do not pollute the active session.

## Usage

1. **Start a session**: Run `opencode` in the project root
2. **Switch agents**: Press Tab to cycle between primary agents
3. **Invoke agents**: Type `@agent-name` (e.g., `@mobile-agent`)
4. **Run commands**: Type `/command-name` (e.g., `/test`)

## Model Assignments

Each agent uses a model optimized for its domain on the `cdigital-test` provider:
- **Complex UI/Security**: `cdigital-test/gemini-2.5-pro`
- **Business Logic**: `cdigital-test/kimi-k2-thinking`
- **API/Integration**: `cdigital-test/deepseek-v3p2`
- **Shared/General**: `cdigital-test/qwen3-8b`, `cdigital-test/glm-5`

See individual agent files for specific configurations.
