# Sandboxing opencode

> **Posture (current):** the org-wide opencode config ([`opencode-well-known.md`](./opencode-well-known.md))
> is pushed to users who run opencode **on their own machines**, where it executes
> with **their full user permissions**. We do **not** sandbox it at the platform
> layer today. This note records *why* a sandbox can't live in the config, the
> options that actually contain the agent, and the recommendation. No sandbox is
> built yet — this is guidance + a decision-on-record.

## Why the permission config is not a sandbox

opencode's `agent.*.permission.bash` allow/deny rules match the **command
string**, not what the process does once it runs. So allow-listing any wrapper —
`npm */pnpm */bun */yarn */cargo */trunk *` — is effectively **arbitrary-code
execution**: `npm run <script>`, `npm exec`, `pnpm exec`, `bun x`, `cargo run`, a
`build.rs`, or a postinstall hook can delete files (or exfiltrate, or anything)
**without ever invoking `rm`**. `"rm *": ask` therefore only catches a *directly
typed* `rm` — a casual-mistake guard, not a boundary. No per-command rule can
close this; it's inherent to string-matched permissions over code-execution
tools. (See the ⚠️ note in [`opencode-well-known.md`](./opencode-well-known.md)
§ *Agents & tool scoping*.)

## opencode has no native OS sandbox

Checked against opencode source (1.17.x): the only "sandbox" concept is
**git-worktree isolation** (`project.addSandbox` registers a worktree directory).
That's **recoverability**, not containment — there is no `bubblewrap` / `seccomp`
/ `sandbox-exec` / namespace isolation; the bash tool spawns commands in the cwd
with the user's permissions. Real containment must come from **around** opencode.

## Options that actually contain it

| Option | Contains | Cost | Where |
|---|---|---|---|
| **git worktree** (opencode-native) | nothing — makes deletes `git restore`-able | ~free | client |
| **OS sandbox wrapper** — `sandbox-exec` (macOS) / `bubblewrap`/`firejail` (Linux) around the opencode process | FS + network at the OS level | fiddly, per-OS, brittle | client |
| **Devcontainer / container image** — opencode + toolchain baked in, project bind-mounted, egress restricted to the gateway | agent can only touch the mounted project + reach `api.ai.camer.digital` | moderate; portable & reproducible | client (org image) |
| **Hosted ephemeral opencode** — one pod per user/session in-cluster | strongest; cluster controls FS *and* egress | high; re-stands-up a workspace platform | **ai-helm / cluster** |

## Recommendation

- **Local users (now):** run opencode inside a **devcontainer / container** —
  opencode + Node + Rust/`trunk` preinstalled, the project bind-mounted, and
  egress locked to the gateway. This contains the agent regardless of the
  permission rules and is portable. At minimum, work in a **git worktree** with
  everything committed so any destructive action is `git restore`-able. This is
  the pragmatic answer to the "agent routes `rm` through `npm`" hole.
- **Platform (future, if needed):** **hosted ephemeral opencode** is the
  strongest and is genuinely ai-helm's wheelhouse — per-session pods, nothing on
  the user's machine, and the cluster's **Cilium default-deny-egress baseline**
  already gives precise egress control. But it effectively revives a
  **workspace platform**, which the org deliberately removed
  ([ADR-0027](./adr/0027-mcps-orchestrator-split-and-coder-removal.md), Coder
  removal). Pursue it only via a **dedicated ADR** that re-opens that decision
  with the sandboxing motivation; don't bolt it on as a chart.

## What this is not

This does **not** add a sandbox. It records that (a) the pushed config is a
convenience/friction layer, not a security boundary, and (b) containment is the
**run environment's** job. If/when local-container guidance or a hosted workspace
is wanted, that's a follow-up (an org image + doc, or a new ADR respectively).

## See also

- [`opencode-well-known.md`](./opencode-well-known.md) — the org-wide opencode config (permissions, agents, the friction-not-sandbox note)
- [ADR-0048](./adr/0048-global-browser-plugin-and-per-agent-tool-injection.md) — agent topology + per-agent tool injection
- [ADR-0027](./adr/0027-mcps-orchestrator-split-and-coder-removal.md) — Coder (workspace platform) removal, which a hosted-opencode route would reverse
