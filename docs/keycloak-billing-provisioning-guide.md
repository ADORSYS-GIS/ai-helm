# Keycloak Setup Guide: Exporting Billing Plan Claims for Envoy Gateway
This document outlines the step-by-step configuration required in Keycloak to assign users to plans (`free` or `pro`) and export their active plan as a claim inside the JWT token for Envoy Gateway rate limiting.


**Key concepts:**
- **Billing plan** (`billing_plan` claim): Determines rate limits (free/pro/service/internal)
- **Shared monthly budget**: Budget is shared across ALL models per user (not per-model)
- **Per-model burst limits**: Burst limits (requests/min, tokens/min) remain per-model
---

## Step 1: Create the Custom Client Scope

We use a dedicated Client Scope to cleanly inject the rate-limiting tier into the user's Access Token.

1. Log into the **Keycloak Admin Console**.
2. Navigate to **Client Scopes** in the left sidebar menu.
3. Click **Create client scope**.
4. Fill in the following details:
   * **Name**: `billing-plan`
   * **Description**: `Injects user billing plan for Envoy Gateway`
   * **Protocol**: `OpenID Connect`
   * **Type**: `Default` (or `Optional` depending on your client onboarding flow)
5. Click **Save**.

---

## Step 2: Configure the Token Claim Mapper

Next, configure the scope to read the plan attribute from the user's active group and place it into the JWT token.

1. While still inside the `billing-plan` scope configuration, click the **Mappers** tab.
2. Click **Configure a new mapper** (or **Add mapper** > **By configuration**).
3. Select **User Attribute** from the list.
4. Configure the mapper with these exact values:
   * **Name**: `Billing Plan Mapper`
   * **User Attribute**: `plan`
   * **Token Claim Name**: `billing_plan`
   * **Claim JSON Type**: `String`
   * **Add to ID token**: `Off`
   * **Add to access token**: `On`
   * **Add to userinfo**: `Off`
5. Click **Save**.

---

## Step 3: Create Plan Groups and Set Group Attributes

Instead of editing attributes for every user manually, we manage plans via Groups. Users inherit the plan attribute from their group.

1. Go to **Groups** in the left sidebar menu.
2. Click **Create group** and create two groups:
   * `Plan-Free`
   * `Plan-Pro`
3. Click on the **`Plan-Free`** group to manage it:
   * Go to the **Attributes** tab.
   * Add a new attribute: **Key**: `plan` | **Value**: `free`
   * Click **Save**.
4. Go back to the groups list and click on the **`Plan-Pro`** group:
   * Go to the **Attributes** tab.
   * Add a new attribute: **Key**: `plan` | **Value**: `pro`
   * Click **Save**.

---

## Step 4: Link Client Scope to Your Application Client

Ensure your target OIDC Client (the one Envoy Gateway evaluates) includes the new scope.

1. Go to **Clients** in the left sidebar and select your target API client.
2. Click on the **Client Scopes** tab.
3. Click **Add client scope**.
4. Select `billing-plan` from the list.
5. Click **Add** and choose **Default** (ensures it is always included in tokens without the client explicitly asking for it).

---

## Rate Limit Plans

| Plan | Monthly Budget | Requests/min | Tokens/min |
|------|---------------|--------------|------------|
| **free** | $50 | 200 | 1,000,000 |
| **pro** | $200 | 400 | 2,000,000 |
| **service** | uncapped | 600 | 2,000,000 |
| **internal** | uncapped | 600 | 2,000,000 |

**Note:** Monthly budget is shared across ALL models. Burst limits are per-model.

---

## Verification Checklist

To verify the setup is successful:
1. Assign a test user to the `Plan-Pro` group.
2. Generate an Access Token for that user.
3. Inspect the token using a tool like [jwt.io](https://jwt.io).
4. Verify that the decrypted JSON block includes the following claim:
   ```json
   {
     "billing_plan": "pro"
   }
   ```
This claim is now ready to be parsed by Envoy Gateway's `SecurityPolicy` and routed to your rate-limit token bucket service.
