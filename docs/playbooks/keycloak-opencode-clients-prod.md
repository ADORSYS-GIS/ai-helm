# OpenCode Clients on Production Keycloak — Configuration & Test Record

**Ticket:** [ADORSYS-GIS/ai-helm#586](https://github.com/ADORSYS-GIS/ai-helm/issues/586)
**Environment:** production Keycloak (`camer-digital` realm)
**Mode:** manual configuration via Admin Console — production does **not** run
the declarative keycloak-baseline/config-cli pipeline (verified: no CronJobs /
Helm releases in the prod `keycloak` namespace). This document is therefore
the authoritative record for recreating the setup if the realm is ever rebuilt.

Related: [PR #1037](https://github.com/ADORSYS-GIS/ai-helm/pull/1037) holds the
same client definitions declaratively (values.yaml) for any GitOps-managed
environment; [demo script](keycloak-opencode-cli-demo-script.md) adds a local
end-to-end walkthrough.

---

## 1. Hostnames and endpoints

Verified against the live OIDC discovery endpoint
(`/realms/camer-digital/.well-known/openid-configuration`):

| Host | Role |
|---|---|
| **`auth.verif.fyi`** | **The issuer.** Admin console *and* all protocol endpoints (device authorization, token). Everything below uses it |


```bash
export ISSUER=https://auth.verif.fyi/realms/camer-digital   # used throughout
```

⚠️ **Issuer is a one-way door:** whatever issuer value gets configured into the
OpenCode plugin / AI gateway must match token `iss` claims forever. Decide
before anything hardcodes it.

---

## 2. Client 1 — `opencode-cli` (public, human login)

Purpose: device-code login (+ browser auth-code) for the OpenCode CLI, with
offline refresh so CLI sessions survive restarts.

Admin Console: <https://auth.verif.fyi/admin/camer-digital/console/#/camer-digital/clients>

### 2.1 Create

1. **Clients → Create client**
2. *General settings*: Client type **OpenID Connect**, Client ID **`opencode-cli`**, Name **OpenCode CLI**
3. *Capability config*:

   | Switch | Value |
   |---|---|
   | Client authentication | **OFF** (public) |
   | Client authorization | OFF |
   | Standard flow | **ON** |
   | Direct access grants | OFF |
   | Implicit flow | OFF |
   | Service account roles | OFF |
   | **OAuth 2.0 Device Authorization Grant** | **ON** |

4. *Login settings*: Valid redirect URIs `http://localhost:*`, `http://127.0.0.1:*`;
   Web origins `http://localhost:*` → Save

### 2.2 Post-create settings

5. **Client scopes** tab → **Add client scopes** → mark as **Optional**:
   `offline_access` (required for the refresh story), optionally also
   `organization`, `microprofile-jwt`
6. Still in **Client scopes** → open **`opencode-cli-dedicated`** → **Add mapper → By configuration → Audience**:

   | Field | Value |
   |---|---|
   | Name | `opencode-exchange-audience` |
   | Included Client Audience | `opencode-exchange` |
   | Add to ID token / access token | OFF / **ON** |

   Why: Standard Token Exchange V2 rejects an exchanger that is not inside the
   subject token's `aud` ("Client is not within the token audience"). This
   mapper is what puts it there.

No secret exists for this client — public clients authenticate with PKCE, not secrets.

---

## 3. Client 2 — `opencode-exchange` (confidential, machine)

Purpose: swaps a human's `opencode-cli` token (+ a `project_id`) for a JWT
sealed with `account_id` / `project_id` by the `lightbridge-keycloak-spi`
provider (already deployed server-side in prod via the StatefulSet's
`install-spi` initContainer).

### 3.1 Create

1. **Clients → Create client**
2. Client ID **`opencode-exchange`**, Name **OpenCode Exchange**
3. *Capability config*:

   | Switch | Value |
   |---|---|
   | Client authentication | **ON** (confidential) |
   | Standard flow | ON |
   | Direct access grants / Implicit / Service accounts | OFF |
   | **Standard Token Exchange** | **ON** |

4. *Login settings*: leave redirect URIs / web origins empty → Save

### 3.2 Post-create settings

5. **Credentials** tab → copy the generated secret into the team vault **immediately**.
   The console never shows it again after you navigate away, and with no ESO in
   prod this vault entry is the only recovery path. Consumers (plugin/gateway)
   receive `client_id=opencode-exchange` + this secret from the vault.
6. **Advanced** tab → *Allow refresh token in Standard Token Exchange* stays **No**
   (we only mint short-lived access tokens).
7. **Client scopes** → `opencode-exchange-dedicated` → **Add mapper → By
   configuration** → select the **Lightbridge context** mapper type → name
   `lightbridge-context`, enable all three claims (access / ID / userinfo).
   If the type is absent from the dropdown (custom SPI mappers without UI
   metadata can't be added by clicking), import just that one mapper via
   **Partial import** of the client JSON from
   [PR #1037](https://github.com/ADORSYS-GIS/ai-helm/pull/1037)'s rendered values.
8. No fine-grained admin permissions are needed anywhere — STE V2 does not use
   them.

---

## 4. Production test record

All requests run against `$ISSUER` (= `https://auth.verif.fyi/realms/camer-digital`).

### Step 1 — device authorization

```bash
VERIFIER=$(python3 -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b'=').decode())")
CHALLENGE=$(python3 -c "import hashlib,base64; print(base64.urlsafe_b64encode(hashlib.sha256('$VERIFIER'.encode()).digest()).rstrip(b'=').decode())")

curl -s -X POST $ISSUER/protocol/openid-connect/auth/device \
  -d "client_id=opencode-cli" \
  -d "scope=openid profile offline_access" \
  -d "code_challenge=$CHALLENGE" \
  -d "code_challenge_method=S256"
```

Expected: JSON with `device_code`, `user_code`, `verification_uri_complete`,
`expires_in: 600`. **Proves:** device grant enabled, PKCE accepted, scopes grantable.

### Step 2 — human approval

Open `verification_uri_complete`, sign in with a real account, approve.

**Proves:** the real login/approval UX path works end-to-end.

### Step 3 — poll for tokens

```bash
curl -s -X POST $ISSUER/protocol/openid-connect/token \
  -d "grant_type=urn:ietf:params:oauth:grant-type:device_code" \
  -d "client_id=opencode-cli" \
  -d "device_code=<DEVICE_CODE>" \
  -d "code_verifier=$VERIFIER"
```

Expected: `access_token`, `refresh_token`, `expires_in: 300`,
`scope: openid profile email offline_access`.
**Proves:** PKCE binding enforced (a stolen `device_code` alone is useless);
offline session established.

### Step 4 — offline refresh

```bash
curl -s -X POST $ISSUER/protocol/openid-connect/token \
  -d "grant_type=refresh_token" \
  -d "client_id=opencode-cli" \
  -d "refresh_token=<REFRESH_TOKEN>"
```

Expected: new `access_token` + rotated `refresh_token`, no interaction.
**Proves:** sessions outlive access-token expiry — the reason `offline_access` exists.

### Step 5 — project-scoped token exchange

```bash
AT=<access_token from step 3>

curl -s -X POST $ISSUER/protocol/openid-connect/token \
  -u "opencode-exchange:<CLIENT_SECRET_FROM_VAULT>" \
  -d "grant_type=urn:ietf:params:oauth:grant-type:token-exchange" \
  -d "subject_token=$AT" \
  -d "subject_token_type=urn:ietf:params:oauth:token-type:access_token" \
  -d "project_id=<project-you-belong-to>"
```

Decode the returned `access_token` (jwt.io or):

```bash
python3 -c "
import json, base64, sys
p = json.loads(base64.urlsafe_b64decode(sys.argv[1].split('.')[1] + '=='))
print(json.dumps({k: p.get(k) for k in ['iss','azp','aud','sub','account_id','project_id']}, indent=2))
" "<EXCHANGED_ACCESS_TOKEN>"
```

Expected payload:

```json
{
  "iss":        "https://auth.verif.fyi/realms/camer-digital",
  "azp":        "opencode-exchange",
  "sub":        "<same user id as the subject token>",
  "account_id": "<resolved from the membership backend>",
  "project_id": "<the requested project>"
}
```

**Proves (all at once):** secret valid · Standard Token Exchange active ·
audience policy satisfied by the mapper · **the SPI intercepted the grant and
called the real resolver** · resolver's membership decision sealed into
`account_id`/`project_id` claims · user identity preserved through the exchange.

### Step 6 — fail-closed check

Repeat step 5 with `-d "client_id=opencode-cli"` and **no** `-u` basic auth.

Expected rejection:

```json
{"error":"invalid_request","error_description":"Standard token exchange is not enabled for the requested client"}
```

**Proves:** public clients can never mint service tokens — the boundary holds.

### Result triage

| Symptom | Root cause |
|---|---|
| `Standard token exchange is not enabled…` | STE switch not saved on `opencode-exchange` |
| `Client is not within the token audience` | Audience mapper missing/wrong on `opencode-cli` |
| `access_denied` mentioning membership/context | SPI working correctly — account isn't a member of that project |
| `invalid_client` | Wrong/rotated secret on `opencode-exchange` |
| `authorization_pending` while polling | Normal until approval (or code expired > 10 min) |

---

## 5. Out of scope of these tests

- The plugin's own UI flow (owned by the plugin repo) — here only the protocol was exercised
- Downstream acceptance of exchanged tokens by the AI gateway (its own validation suite)
- Edge security behaviour: replay, revocation, concurrent sessions
