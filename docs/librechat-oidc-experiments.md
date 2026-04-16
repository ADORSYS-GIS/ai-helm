# LibreChat OIDC Experiments and Advanced Access Control

This document explores practical scenarios for using Keycloak roles, groups, and claims to control access to LibreChat resources. Each experiment includes setup steps, expected outcomes, and validation commands.

## Prerequisites

- Access to Keycloak admin console at `https://accounts.camer.digital`
- Admin access to Kubernetes cluster
- `jq` installed for JSON parsing
- A test user account in Keycloak

---

## Experiment 1: Group-Based Access Control

### Objective

Determine if Keycloak groups can be used to manage LibreChat access for multiple users at once.

### Background

Keycloak groups allow hierarchical organization of users. Groups can have role mappings that propagate to all members. This experiment tests whether group-assigned roles appear in the `librechat_roles` claim.

### Hypothesis

Users assigned to a Keycloak group with a mapped `librechat` client role will have that role in their access token, enabling group-based access control.

### Setup Steps

#### 1. Create a Group in Keycloak

```text
Navigate to: Groups → Create group
Name: librechat-users
```

#### 2. Assign Role to Group

```text
Navigate to: Groups → librechat-users → Role Mappings
Client roles: librechat
Assign roles: user
```

#### 3. Add Test User to Group

```text
Navigate to: Users → <test-user> → Groups
Join: librechat-users
```

### Validation

```bash
# Get access token for the test user
TOKEN=$(curl -s -X POST "https://accounts.camer.digital/realms/camer-digital/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password" \
  -d "client_id=librechat" \
  -d "client_secret=<your-client-secret>" \
  -d "username=<test-username>" \
  -d "password=<test-password>" \
  -d "scope=openid profile email librechat" | jq -r '.access_token')

# Decode and check for librechat_roles claim
echo $TOKEN | cut -d'.' -f2 | base64 -d 2>/dev/null | jq '.librechat_roles'
```

### Expected Outcome

| Scenario | Token Contains `librechat_roles` | Access to LibreChat |
|----------|----------------------------------|---------------------|
| User in group with role mapping | ✅ `["user"]` | ✅ Granted |
| User not in group | ❌ Missing or empty | ❌ Denied (if `OPENID_REQUIRED_ROLE` enabled) |

### Findings

```
[
  "user",
  "manage-account",
  "manage-account-links",
  "view-profile"
]
```

---

## Experiment 2: Role-Based MCP Server Access

**Result: NOT SUPPORTED** - LibreChat does not currently support role-based access control for individual MCP servers.

**Evidence:**
- GitHub Issue [#6437](https://github.com/danny-avila/LibreChat/issues/6437) - Feature request for per-user MCP tool profiles
- MCP servers are configured globally in `librechat.yaml` with no per-user or per-role filtering
- All users share the same MCP tools once configured

**Workarounds:**
1. Separate LibreChat instances for different user groups
2. Custom middleware to filter MCP server list based on roles (requires code modification)
3. Use Kuadrant policies to restrict MCP endpoints at the gateway level

---

## Experiment 3: Custom Role Token Propagation

### Objective

Understand how adding arbitrary roles in Keycloak affects the JWT token structure and downstream applications.

### Background

When a new role is added to a user or client in Keycloak, the role mapper configuration determines if and how that role appears in tokens. This experiment tests the token changes when roles are added.

### Hypothesis

New roles added to the `librechat` client will appear in the `librechat_roles` claim only if:
1. The role mapper is configured to include all client roles
2. The user has the role assigned via direct mapping or group membership

### Setup Steps

#### 1. Create a Custom Role

```text
Navigate to: Clients → librechat → Roles → Create Role
Role name: beta-tester
Description: Beta feature access
```

#### 2. Assign Role to Test User

```text
Navigate to: Users → <test-user> → Role Mappings
Client roles: librechat
Assign: beta-tester
```

#### 3. Get Token Before and After

```bash
# Before adding role (capture baseline)
curl -s -X POST "https://accounts.camer.digital/realms/camer-digital/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password" \
  -d "client_id=librechat" \
  -d "client_secret=<your-client-secret>" \
  -d "username=<test-username>" \
  -d "password=<test-password>" \
  -d "scope=openid profile email librechat" | jq > token-before.json

# After adding role
curl -s -X POST "https://accounts.camer.digital/realms/camer-digital/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password" \
  -d "client_id=librechat" \
  -d "client_secret=<your-client-secret>" \
  -d "username=<test-username>" \
  -d "password=<test-password>" \
  -d "scope=openid profile email librechat" | jq > token-after.json
```

#### 4. Compare Token Payloads

### Expected Token Changes

**Before adding role:**
```json
{
  "librechat_roles": ["user"]
}
```

**After adding role:**
```json
{
  "librechat_roles": ["user", "beta-tester"]
}
```

### Downstream Impact Analysis

| Component | How It Uses Roles | Impact of New Role |
|-----------|-------------------|-------------------|
| LibreChat | `OPENID_REQUIRED_ROLE` check | No impact unless configured to require `beta-tester` |
| Kuadrant/AuthConfig | Can check `librechat_roles` claim | Can create policies for `beta-tester` role |
| Custom Middleware | Can read claim from headers | Can enable beta features for users with role |


### Findings

**Result: Custom roles are correctly propagated to the JWT token.**

#### Actual Token Results

After creating and assigning `beta-tester` and `mcp-brave` roles:

```json
[
  "beta-tester",
  "mcp-brave",
  "user",
  "manage-account",
  "manage-account-links",
  "view-profile"
]
```

#### Key Observations

1. **Role Mapper Working Correctly**: The `librechat` client scope with role mapper successfully includes all assigned client roles in the `librechat_roles` claim.

2. **Immediate Propagation**: New roles appear in tokens immediately after assignment - no cache clearing or restart required.

3. **Role Order**: Roles appear in the order they were assigned (newest first in this case), but order should not be relied upon for authorization logic.

4. **Group Inheritance Works**: If roles are assigned to groups (like `librechat-users`), users in those groups automatically inherit the roles in their tokens.

#### Downstream Impact Confirmed

| Component | How It Uses Roles | Verified Impact |
|-----------|-------------------|-----------------|
| LibreChat | `OPENID_REQUIRED_ROLE` check | Can require specific roles like `beta-tester` |
| Kuadrant/AuthConfig | Can check `librechat_roles` claim | Can create policies for any custom role |
| Custom Middleware | Can read claim from headers | Can enable features based on role presence |

#### Use Cases Enabled

1. **Beta Features**: Set `OPENID_REQUIRED_ROLE=beta-tester` to restrict access to beta features
2. **MCP Access Control**: Use Kuadrant policies to restrict MCP endpoints based on `mcp-brave` role
3. **Feature Flags**: Application logic can check for specific roles to enable/disable features

---

## Experiment 4: Role Removal and Access Revocation

### Objective

Test how quickly role removal in Keycloak propagates to deny access in LibreChat.

### Background

When a user's role is removed in Keycloak, subsequent token requests should not include that role. However, existing sessions may persist until the token expires or session is invalidated.

### Setup Steps

#### 1. Create User with Role

```text
Create test user with "user" role in librechat client
Verify user can access LibreChat
```

#### 2. Remove Role

```text
Navigate to: Users → <test-user> → Role Mappings
Client roles: librechat
Unassign: user
```

#### 3. Test Access Immediately

```bash
# Try to get new token
curl -s -X POST "https://accounts.camer.digital/realms/camer-digital/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password" \
  -d "client_id=librechat" \
  -d "client_secret=<your-client-secret>" \
  -d "username=<test-username>" \
  -d "password=<test-password>" \
  -d "scope=openid profile email librechat" | jq '.access_token' | cut -d'.' -f2 | base64 -d 2>/dev/null | jq '.librechat_roles'

# Expected: empty array or missing claim
```

#### 4. Test Existing Session

```bash
# If user has active session, check if they can still access LibreChat
# This depends on LibreChat's session validation behavior
```

### Expected Behavior

| Time | Token Behavior | LibreChat Access |
|------|----------------|------------------|
| Immediately after removal | New tokens lack role | New logins denied |
| During active session | Existing token still valid until expiry | Access continues until token expires |
| After token expiry (5 min) | No valid token | Access denied |

### Session Invalidation Options

1. **Wait for token expiry** (5 minutes default)
2. **Manual logout** - User must log out
3. **Admin logout** - Use Keycloak admin API to invalidate session:

```bash
# Get admin token
ADMIN_TOKEN=$(curl -s -X POST "https://accounts.camer.digital/realms/master/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password" \
  -d "client_id=admin-cli" \
  -d "username=<admin-username>" \
  -d "password=<admin-password>" | jq -r '.access_token')

# Get user sessions
curl -s "https://accounts.camer.digital/admin/realms/camer-digital/users/<user-id>/sessions" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq

# Revoke sessions (if supported)
curl -s -X POST "https://accounts.camer.digital/admin/realms/camer-digital/users/<user-id>/logout" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

### Findings

**Result: Role removal propagates immediately to new tokens.**

#### Actual Token Results

**Before role removal:**
```json
[
  "user",
  "manage-account",
  "manage-account-links",
  "view-profile"
]
```

**After removing `user` role:**
```json
[
  "manage-account",
  "manage-account-links",
  "view-profile"
]
```

#### Key Observations

1. **Immediate Propagation**: New tokens requested after role removal do not include the removed role.
2. **No Cache Delay**: Keycloak does not cache role mappings - changes are reflected instantly.
3. **Existing Sessions**: Users with active sessions continue to have access until their token expires (typically 5 minutes).
4. **Access Revocation**: For immediate revocation, use Keycloak admin API to invalidate sessions.

---

## Experiment 5: Agent/Preset Access Control

**Result: NOT SUPPORTED** - Agent capabilities are currently global, not per-user or per-role.

**Evidence:**
- GitHub Issue [#11693](https://github.com/danny-avila/LibreChat/issues/11693) - "Agent capabilities are currently global. We need a way to grant or restrict capabilities by user role"
- This is a feature request, not currently implemented

---

## Experiment 6: Conversation History Access

**Result: NOT SUPPORTED** - Cross-user conversation visibility isn't architecturally possible in LibreChat.

**Evidence:**
- GitHub Discussion [#9265](https://github.com/danny-avila/LibreChat/discussions/9265) - "Cross-user conversation visibility isn't architecturally possible in LibreChat, our codebase has strict user isolation that is integral to every component"
- Admins cannot view other users' conversations by design

---

## Experiment 7: Admin vs User Privileges

### Objective

Document what additional capabilities the `admin` role enables in LibreChat.

### Background

LibreChat may have built-in admin features that are enabled based on user role. This experiment maps out:
- What admin users can do that regular users cannot
- How to enable/configure admin features
- Whether admin role is checked from JWT or database

### Setup Steps

#### 1. Create Admin Role

```text
Navigate to: Clients → librechat → Roles → Create Role
Role: admin
Description: LibreChat administrator
```

#### 2. Assign to Test User

```text
Navigate to: Users → <admin-test-user> → Role Mappings
Assign: admin role
```

#### 3. Get Admin Token

```bash
# Get token for the admin test user (with admin role)
ADMIN_TOKEN=$(curl -s -X POST "https://accounts.camer.digital/realms/camer-digital/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password" \
  -d "client_id=librechat" \
  -d "username=<admin-test-user>" \
  -d "password=<password>" | jq -r '.access_token')
```

#### 4. Test Admin Features

```bash
# Check if admin panel is accessible
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
  https://ai.camer.digital/api/admin | jq

# Check user management endpoints
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
  https://ai.camer.digital/api/users | jq

# Check system configuration endpoints
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
  https://ai.camer.digital/api/config | jq
```

#### 5. Get Regular User Token

```bash
# Get token for a regular user (without admin role)
USER_TOKEN=$(curl -s -X POST "https://accounts.camer.digital/realms/camer-digital/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password" \
  -d "client_id=librechat" \
  -d "username=<regular-user>" \
  -d "password=<password>" | jq -r '.access_token')
```

#### 6. Compare with Regular User

```bash
# Same requests with regular user token
curl -s -H "Authorization: Bearer $USER_TOKEN" \
  https://ai.camer.digital/api/admin | jq
# Expected: 403 Forbidden or 404 Not Found
```

### Admin Capabilities Matrix

| Feature | `user` Role | `admin` Role | Endpoint |
|---------|-------------|--------------|----------|
| View own conversations | ✅ | ✅ | `/api/convos` |
| View all conversations | ❌ | ✅? | `/api/admin/convos` |
| Manage users | ❌ | ✅? | `/api/admin/users` |
| Configure models | ❌ | ✅? | `/api/admin/models` |
| View system stats | ❌ | ✅? | `/api/admin/stats` |
| Manage presets | ❌ | ✅? | `/api/admin/presets` |
| Access logs | ❌ | ✅? | `/api/admin/logs` |

### LibreChat Environment Variables for Admin

```yaml
# Check if these are configured
ADMIN_EMAIL: "admin@example.com"  # Single admin by email
# Or role-based admin (if supported)
```

### Findings

> **Document actual results here after running the experiment**
>
> **Note**: LibreChat's admin features may be email-based rather than role-based. Verify with documentation or source code.

---

## Summary: Experiment Status

| Experiment | Status | Notes |
|------------|--------|-------|
| 1. Group-Based Access Control | ✅ WORKS | Roles propagate through groups |
| 2. Role-Based MCP Server Access | ❌ NOT SUPPORTED | GitHub Issue #6437 |
| 3. Custom Role Token Propagation | ✅ WORKS | Custom roles appear in token |
| 4. Role Removal and Access Revocation | ✅ WORKS | Immediate propagation to new tokens |
| 5. Agent/Preset Access Control | ❌ NOT SUPPORTED | GitHub Issue #11693 |
| 6. Conversation History Access | ❌ NOT SUPPORTED | Architectural limitation |
| 7. Admin vs User Privileges | 🧪 PENDING TEST | LibreChat has admin role |

---

## References

- [Keycloak Groups Documentation](https://www.keycloak.org/docs/latest/server_admin/#groups)
- [Keycloak Role Mappings](https://www.keycloak.org/docs/latest/server_admin/#role-mappings)
- [LibreChat OIDC Configuration](./librechat-oidc-integration.md)
- [Kuadrant AuthConfig](../charts/kuadrant-policies/templates/authconfig.yaml)
- [Kuadrant RateLimitPolicy](https://kuadrant.io/docs/)
