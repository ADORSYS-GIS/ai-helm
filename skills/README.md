# LibreChat skills

Shared **SKILL.md** skills synced into the Converse (LibreChat) deployment via
GitHub skill sync (`config.skillSync` in
[`charts/librechat-app/values.yaml`](../charts/librechat-app/values.yaml) —
source `ai-helm-skills`, path `skills`). They are exposed read-only to every
LibreChat user with Skills enabled and are available to agents (the `skills`
agent capability).

## Layout

Each skill is its own folder with a `SKILL.md`:

```text
skills/
  code-review/
    SKILL.md
    references/          # optional supporting files
```

`SKILL.md` carries YAML frontmatter (`name`, `description`) followed by the
skill body. The `description` is what LibreChat matches on to decide relevance,
so make it specific about *when* to use the skill.

⚠️ **`name` must be kebab-case** — `^[a-z0-9][a-z0-9-]*$`, ≤64 chars, not
starting `anthropic-`/`claude-`, and not a reserved word (`help`, `clear`,
`compact`, `model`, `exit`, `quit`, `settings`, `anthropic`, `claude`).
`description` ≤1024 chars, body ≤100k.

⚠️ **The sync validates frontmatter against a strict allowlist** — only these
keys are permitted: `name`, `description`, `when-to-use`, `allowed-tools`,
`arguments`, `argument-hint`, `user-invocable`, `disable-model-invocation`,
`always-apply`/`alwaysApply`, `model`, `effort`, `context`, `agent`, `paths`,
`shell`, `hooks`, `version`, `license`, `metadata`. **Any other key
(e.g. `displayTitle`, `title`) fails sync** with `[GitHubSkillSync] … Skill
validation failed`. There is no frontmatter field for a pretty display name in a
synced skill — the skill shows under its `name`.

## Adding a skill

1. Create `skills/<kebab-name>/SKILL.md` with `name` + `description` frontmatter.
2. Keep the body actionable (checklists/procedures beat prose).
3. Merge to `main` — LibreChat picks it up on the next sync (hourly, or on pod
   start). No chart change needed to add a skill.

Format reference: <https://www.librechat.ai/docs/features/skills>
