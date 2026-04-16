---
description: Create a new UI component with full structure
agent: ui-system-agent
subtask: true
---

Create a new UI component named **$ARGUMENTS** following the project structure:

Create directory and files:
- packages/ui/src/components/$ARGUMENTS/cva.tsx
- packages/ui/src/components/$ARGUMENTS/types.tsx
- packages/ui/src/components/$ARGUMENTS/component.tsx
- packages/ui/src/components/$ARGUMENTS/index.tsx

Implement following AGENTS.md guidelines:
- Use variant-based styling (never accept className props)
- Use theme tokens only (primary, secondary, accent, error, success)
- Use cn() utility for class composition
- User-visible text must use i18n t('key')

Handle platform splitting if needed:
- Create .web.tsx variant for expo-* imports
- Share cva variants and types between platforms

Verify architectural compliance:
- No hardcoded colors
- No plain text strings
- Proper TypeScript types

Run pnpm typecheck and report completion with usage example.