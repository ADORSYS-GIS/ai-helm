---
description: Create a new mobile app screen with navigation
agent: mobile-agent
---

Create a new mobile screen named **$ARGUMENTS**:

Determine route structure:
- Tab screen: /(tabs)/$ARGUMENTS
- Stack screen: /$ARGUMENTS

Create screen file in apps/mobile/src/app/

Implement following AGENTS.md guidelines:
- Use Expo Router file-based routing
- Use only @azamra/ui components
- NEVER import from 'react-native' directly
- No className props (use variants)
- All visible text via t('key') from @azamra/i18n

Add navigation integration:
- Import from expo-router
- Use useLocalSearchParams() for params
- Use useRouter() for navigation

Integrate business logic from @azamra/hooks/*

Run pnpm mobile and verify all interactions work.

Report screen location and navigation path.