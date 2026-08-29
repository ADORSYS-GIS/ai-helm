---
description: Test mobile app components and features
agent: mobile-agent
---

Run tests for the mobile app:
- Run pnpm --filter @azamra/mobile test
- Review component rendering tests
- Check navigation flow tests
- Verify platform-specific code coverage

For each failure:
- Identify affected component/feature
- Debug failure cause
- Suggest platform-specific fixes if needed

Test critical user flows:
- Authentication and enrollment
- Trading operations
- Wallet transactions
- KYC flow
- App lock functionality

Verify integration with @azamra/hooks, @azamra/ui, @azamra/platform.