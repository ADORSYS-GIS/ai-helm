---
description: Type check all TypeScript code
agent: orchestrator-agent
---

Run TypeScript type checking across all packages:
- Run pnpm typecheck for all workspaces
- Collect all TypeScript errors

For each error:
- Show file path and line number
- Explain the type mismatch
- Suggest the correct type or fix

Focus on common issues:
- Missing return types on functions
- Implicit 'any' types
- Incorrect generic usage
- Interface/Type mismatches
- Module resolution errors

Verify all packages compile without errors.