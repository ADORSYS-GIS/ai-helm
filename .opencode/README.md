# OpenCode setup in `ai-helm`

This directory holds this repo's OpenCode configuration. It is **not** a
multi-agent system for an app monorepo — the canonical agent and CI rules live in
[`.github/workflows/opencode.yml`](../.github/workflows/opencode.yml), and
repo-wide guidance lives in [`CLAUDE.md`](../CLAUDE.md). Read those; this file
only points at them.

## What is actually here

**`.opencode/opencode.json`** defines one provider, **`lightbridge`**
(`@ai-sdk/openai-compatible`). Its `baseURL` comes from the `LIGHTBRIDGE_BASE_URL`
env var and its bearer key from `LIGHTBRIDGE_API_KEY`. It lists the available
models with their context/output limits and (where set) per-token costs —
families include GLM (`glm-5`, `glm-5p1`), Kimi (`kimi-k2.5`,
`kimi-k2-thinking`, `kimi-k2-instruct-0905`), MiniMax (`minimax-m2p5`), Gemini
(2.5 / 3 / 3.1 variants), GPT (`gpt-5-mini`, `gpt-5-nano`, `gpt-5-3-codex`,
`gpt-5-1-codex-mini`), Qwen (`qwen3-8b`, `qwen3-vl-30b-a3b-*`) and DeepSeek
(`deepseek-v3p2`).

It also defines two **hidden primary agents**, both at `temperature: 0.1`:

| Agent | Model | Trigger |
|---|---|---|
| `auto-review` | `lightbridge/gemini-3.1-flash-lite` | PR open/sync |
| `manual-review` | `lightbridge/kimi-k2.5` | `/oc` or `/opencode` |

**Root `opencode.json`** additionally describes the `camer-digital` provider
(`https://api.ai.camer.digital/v1`, key from `CAMER_DIGITAL_API_KEY`) with the
`adorsys-reviewer` / `adorsys-reviewer-pro` models.

**`.roo/mcp.json`** exists but is an empty stub (`mcpServers` with no entries).

**`skills/`** (repo root) holds the LibreChat `SKILL.md` skills synced via
`config.skillSync` — see [`skills/README.md`](../skills/README.md) for the
frontmatter rules and layout.

> The stale "Azamra monorepo" content is **not** confined to the predecessor of
> this file: the git-tracked `.opencode/agents/` (10 files) and
> `.opencode/commands/` (27 files) trees are remnants of that same unrelated
> project. They reference paths and packages absent from this repo (`apps/mobile`,
> `apps/kyc-mgr`, `packages/ui`, `@azamra/*`); all 10 `.opencode/agents/` files
> name a `cdigital-test` provider that is defined nowhere here (the only providers
> are `lightbridge` and `camer-digital`), while the `.opencode/commands/` files do
> **not** reference it (they carry the stale paths/packages only). Those two
> directories should **not** be
> trusted or followed; the canonical rules in
> [`.github/workflows/opencode.yml`](../.github/workflows/opencode.yml) and
> [`CLAUDE.md`](../CLAUDE.md) are the authority.
