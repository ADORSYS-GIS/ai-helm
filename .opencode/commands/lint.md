---
description: Lint and format all code across the monorepo
agent: orchestrator-agent
---

Run linting and formatting across all packages:
- Run pnpm lint to check all code
- Run pnpm format to format all code
- Review any linting errors or warnings

For each error:
- Identify file and line number
- Explain why it's an error
- Suggest the correct fix

Focus on:
- Import organization violations
- Naming convention issues
- Unsorted Tailwind classes
- TypeScript type errors
- Biome-specific rule violations

Ensure all code passes linting before proceeding.