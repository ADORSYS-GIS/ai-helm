---
description: Test KYC Manager admin app
agent: kyc-manager-agent
---

Run tests for the KYC Manager admin app:
- Run pnpm --filter @azamra/kyc-mgr test (unit tests)
- Run pnpm --filter @azamra/kyc-mgr test:bdd (BDD tests)
- Run pnpm --filter @azamra/kyc-mgr test:e2e (E2E tests)

Analyze test results:
- Unit test pass/fail counts
- BDD scenario results
- E2E test results (Playwright)
- Coverage percentages

For failing tests:
- Identify test name and location
- Analyze error messages and stack traces
- Check for Next.js-specific issues
- Debug tRPC integration

Check admin-specific features:
- Authentication/authorization
- KYC verification workflows
- Protected route guards

Report test status and any failures with suggested fixes.