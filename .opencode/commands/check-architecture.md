---
description: Verify architectural compliance across codebase
agent: orchestrator-agent
---

Verify the codebase follows architectural rules from AGENTS.md:

Check for react-native imports in apps:
- Grep for "from 'react-native'" in apps/
- Report violations in app views/screens

Check for className props:
- Grep for "className=" in apps/
- Report files that should use variants

Check for hardcoded colors:
- Grep for "bg-[:#]" and "text-[:#]" in packages/ui

Check for literal user-visible strings:
- Find text in JSX not using t('...')

Verify component structure:
- Check each component has: cva.tsx, types.tsx, component.tsx, index.tsx

Run circular dependency checks:
- Run pnpm --filter @azamra/hooks lint:cycles
- Run pnpm --filter @azamra/platform lint:cycles

Write findings to plans/arch-assessments-<date>.md