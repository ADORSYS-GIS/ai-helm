---
description: Upgrade all dependencies to latest compatible versions
agent: orchestrator-agent
---

Upgrade dependencies across the monorepo:
- Run pnpm outdated to see available updates
- Review major, minor, and patch updates
- Identify security vulnerabilities

Plan upgrade strategy:
- Prioritize security updates
- Group related packages (React ecosystem, TanStack, etc.)
- Check breaking changes in changelogs

Upgrade and fix breaking changes:
- Update import paths and deprecated APIs
- Adjust configurations and TypeScript types

Verify everything works:
- Run pnpm install
- Run pnpm lint
- Run pnpm typecheck
- Run pnpm test

Report all updated packages and any remaining issues.