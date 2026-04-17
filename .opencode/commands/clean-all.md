---
description: Clean all build artifacts and caches
agent: orchestrator-agent
---

Clean all build artifacts, caches, and temporary files:
- Run pnpm store prune to clean store
- Clear Metro cache: pnpm --filter @azamra/mobile exec expo start -c
- Remove .expo directory
- Remove .next directory from kyc-mgr
- Remove dist/ directories from packages
- Remove coverage/ directories

Verify clean state:
- Run pnpm install
- Run pnpm build
- Confirm no unexpected errors

Report what was cleaned and any recommendations.