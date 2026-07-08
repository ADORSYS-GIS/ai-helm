# Lightbridge context-resolution SPI — realm wiring runbook

The Keycloak SPI (`adorsys-gis/lightbridge-keycloak-spi`) seals `account_id` /
`project_id` into issued JWTs on a **`project_id` token exchange**. Two of the
three moving parts are GitOps:

| Part | Where | State |
| --- | --- | --- |
| OPA server (`/idp/v1/resolve-context`) | `ai-helm-values` → `lightbridge-app.yaml` (`opa.enabled: true`) | GitOps |
| SPI provider config + truststore | `home-os` → `keycloak-ha` (`LIGHTBRIDGE_*` env) | GitOps |
| Realm: `lightbridge` scope + Standard Token Exchange | **this chart** + **manual** | see below |

> ⚠️ The `camer-digital` realm is **not currently reconciled** by this chart
> (no running `keycloak-config-cli` CronJob / `KeycloakRealmImport`). The
> `lightbridge` client scope + mapper added here are the declarative source of
> truth, but until config-sync is wired they must be applied to the live realm
> manually. Standard Token Exchange is a per-client capability this chart's realm
> template can't yet express, so it is manual either way.

## What the SPI needs in the realm

1. The **`lightbridge` client scope** carrying the `lightbridge-context-mapper`
   protocol mapper (defined in `values.yaml` → `clientScopes.lightbridge`).
2. That scope as a **default scope** on the client that performs the exchange
   (`self-service-mcp-api`).
3. **Standard Token Exchange enabled** on that client.

The SPI provider itself is global (installed via the jars in `keycloak-ha`); no
realm setting selects it — it engages automatically when a `project_id` form
param is present on a standard token exchange.

## Manual apply (kcadm, against the live realm)

```sh
kcadm.sh config credentials --server https://auth.verif.fyi \
  --realm master --user "$KC_ADMIN" --password "$KC_ADMIN_PW"

REALM=camer-digital

# 1. Create the lightbridge client scope
SCOPE_ID=$(kcadm.sh create client-scopes -r "$REALM" -i \
  -s name=lightbridge \
  -s protocol=openid-connect \
  -s 'attributes."include.in.token.scope"=true' \
  -s 'attributes."display.on.consent.screen"=false')

# 2. Add the Lightbridge Context Mapper to the scope
kcadm.sh create "client-scopes/$SCOPE_ID/protocol-mappers/models" -r "$REALM" \
  -s name=lightbridge_context \
  -s protocol=openid-connect \
  -s protocolMapper=lightbridge-context-mapper \
  -s 'config."access.token.claim"=true' \
  -s 'config."id.token.claim"=true' \
  -s 'config."userinfo.token.claim"=true' \
  -s 'config."introspection.token.claim"=true'

# 3. Attach the scope as a default scope on the exchanging client
CID=$(kcadm.sh get clients -r "$REALM" -q clientId=self-service-mcp-api --fields id --format csv --noquotes)
kcadm.sh update "clients/$CID/default-client-scopes/$SCOPE_ID" -r "$REALM"

# 4. Enable Standard Token Exchange on the client (KC 26.2+ capability)
kcadm.sh update "clients/$CID" -r "$REALM" \
  -s 'attributes."standard.token.exchange.enabled"=true'
```

> Admin-console equivalent for step 4: **Clients → self-service-mcp-api →
> Settings → Capability config → Standard Token Exchange → On**. Confirm the
> exact attribute key in your 26.6 console if the kcadm form is rejected.

## Verify end-to-end

```sh
# Get a user access token (subject_token) for self-service-mcp-api, then exchange
# WITH a project_id the user is a member of. Do NOT pass audience=<same client>
# (Keycloak rejects a self-audience with "Requested audience not available").
curl -s https://auth.verif.fyi/realms/camer-digital/protocol/openid-connect/token \
  -d grant_type=urn:ietf:params:oauth:grant-type:token-exchange \
  -d client_id=self-service-mcp-api -d client_secret="$CLIENT_SECRET" \
  -d subject_token="$USER_TOKEN" \
  -d subject_token_type=urn:ietf:params:oauth:token-type:access_token \
  -d project_id="$PROJECT_ID" | jq -r .access_token \
  | cut -d. -f2 | base64 -d 2>/dev/null | jq '{account_id, project_id}'
```

Expected: the exchanged token carries `account_id` + `project_id`. Without the
`project_id` param the claims are absent (the provider only engages on it). An
unknown project / non-member subject → the exchange fails closed (no token).
