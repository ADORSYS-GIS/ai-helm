---
description: Review code changes for a pull request
agent: code-reviewer
subtask: true
---

Review the current code changes for this pull request:
- Run git diff or git diff HEAD~1 for recent changes

Analyze changes systematically:
- Identify affected packages/apps
- Determine type of changes (feature, bug fix, refactor)
- Check for architectural violations

Check for AGENTS.md compliance:
- NO react-native imports in app views/screens
- NO className props in app views/screens
- NO literal user-visible strings
- NO hardcoded colors in classnames
- Kebab-case filenames
- Import organization correct

Security review:
- Verify no secrets in code
- Check input validation
- Review API endpoint security

Test coverage:
- Check if tests were added for new code
- Verify test quality and coverage

Provide feedback with issues found, specific fixes, and approval status.