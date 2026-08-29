---
description: Debug and fix a failing test
---

Debug the failing test: **$ARGUMENTS**

Run the specific failing test:
- Run pnpm --filter @azamra/hooks vitest run $ARGUMENTS
- Capture the full error output

Analyze the error:
- What is the assertion failure?
- What is the stack trace?
- Is it test setup or implementation bug?

Examine test and implementation code:
- Check test setup (beforeEach, mocks)
- Understand expected behavior

Suggest fix:
- Provide specific code changes
- Consider if fix affects other tests

Verify the fix:
- Run the specific test again
- Run related tests for regression

Report root cause, fix applied, and verification results.