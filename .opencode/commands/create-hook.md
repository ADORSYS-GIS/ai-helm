---
description: Create a new custom hook following project patterns
agent: hooks-agent
subtask: true
---

Create a new hook named **use$ARGUMENTS**:

Determine correct domain folder:
- auth, app-lock, asset, keypair, legal, portfolio, prices, trade, wallet, wishlist

Create hook file: packages/hooks/src/{domain}/use-$ARGUMENTS.ts

Implement following existing patterns:
- Use TanStack Query for server state (useQuery, useMutation)
- Use TanStack DB for client state if needed
- Specify explicit return types
- Error handling via Result type or meta.toastOptions

Create test file: use-$ARGUMENTS.test.ts
- Mock external dependencies
- Test success, error, and loading states
- Aim for 100% coverage

Export from domain index.ts

Verify:
- Run pnpm --filter @azamra/hooks test
- Run pnpm typecheck
- No circular dependencies

Report completion with usage example.
