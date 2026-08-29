---
description: Test the hooks package with detailed analysis
agent: hooks-agent
subtask: true
---

Run comprehensive tests for the hooks package:
- Run pnpm --filter @azamra/hooks test
- Run pnpm --filter @azamra/hooks test:coverage
- Analyze test results (passing/failing counts, coverage percentages)
- Verify mock implementations (expo-*, react-native, API, storage)

For each failing test:
- Show test name and file
- Analyze error message
- Identify root cause
- Suggest specific code fixes

Check for test patterns:
- Proper setup and teardown
- Meaningful test names
- Edge case coverage

Ensure 100% coverage for critical hooks and provide recommendations.