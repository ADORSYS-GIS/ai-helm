---
description: Run full test suite with coverage analysis
agent: orchestrator-agent
---

Run the complete test suite and analyze coverage:
- Run pnpm test:coverage (all tests with coverage)
- Analyze coverage output for each package
- Identify packages with coverage below 80%
- For packages/hooks and packages/platform: ensure 100% coverage
- List all failing tests with error details

For each failure:
- Analyze the root cause
- Suggest specific fixes
- Consider edge cases not covered

Then verify coverage:
- >85% overall coverage
- All tests passing
- Zero type errors

If any failures occur, suggest fixes or escalate.