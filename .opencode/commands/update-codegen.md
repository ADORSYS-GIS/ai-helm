---
description: Regenerate API clients from OpenAPI specifications
agent: api-agent
subtask: true
---

Regenerate API clients from OpenAPI specifications:
- Verify OpenAPI spec locations: openapi/frontend/*.yaml and openapi/admin/*.yaml
- Run pnpm --filter @azamra/api-rest codegen (frontend client)
- Run pnpm --filter @azamra/api-rest-admin codegen (admin client)

Analyze generated changes:
- Run git diff to see what changed
- Identify breaking changes in generated code
- Note new endpoints, changed types, removed fields

Fix breaking changes:
- Update imports if file structure changed
- Fix type errors from changed interfaces
- Update hook implementations in @azamra/hooks

Test the changes:
- Run pnpm typecheck
- Run pnpm lint
- Run pnpm --filter @azamra/hooks test

Report summary of changes and test status.