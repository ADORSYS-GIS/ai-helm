# Keycloak `opencode-cli` + Token Exchange — Local E2E Test Guide

**Ticket:** [ADORSYS-GIS/ai-helm#586](https://github.com/ADORSYS-GIS/ai-helm/issues/586)
**Branch:** `586-ticket-keycloak-opencode-cli-client-and-spi-deployment`
**Scope:** Reproduce the production Keycloak architecture locally (k3s) and prove,
end-to-end, that the two new realm clients work exactly as designed:

| Client | Type | Purpose |
|---|---|---|
| `opencode-cli` | public | Device-code login (+ PKCE, offline refresh) for the OpenCode CLI |
| `opencode-exchange` | confidential | Standard Token Exchange (STE) that seals `account_id` / `project_id` claims via `lightbridge-keycloak-spi` |

Everything below was executed and verified against **Keycloak 26.6.4** +
**lightbridge-keycloak-spi v0.1.2** (the same SPI version running in
production).

---

## 0. Prerequisites

- A local **k3s** cluster reachable via kubectl context **`default`**
  (`kubectl config get-contexts` — never point these steps at `hetzner-prod`).
- Tools: `helm`, `kubectl`, `curl`, `python3`, a browser.
- Port **8080 free** on localhost.
- The ticket branch checked out (chart contains the two new clients).
- Outbound internet (the SPI init-container downloads release jars from GitHub).

> **Why an init-container?** The SPI image on GHCR is private; production uses
> the same pattern — stock `quay.io/keycloak/keycloak` image plus an
> `install-spi` init container that downloads the v0.1.2 jars into
> `/opt/keycloak/providers`. We replicate prod faithfully.

---

## 1. Deploy local Keycloak + SPI + resolver stub

### 1.1 Namespace and admin secret

```bash
kubectl --context default create namespace keycloak --dry-run=client -o yaml | kubectl --context default apply -f -
kubectl --context default -n keycloak create secret generic keycloak-admin \
  --from-literal=password=localadmin --dry-run=client -o yaml | kubectl --context default apply -f -
```

### 1.2 Resolver stub (stands in for lightbridge-authz)

Production calls `POST /idp/v1/resolve-context` on the lightbridge-authz OPA
server. Locally we stub it with WireMock returning a fixed membership result.

```bash
cat <<'EOF' > /tmp/opencode-resolve-context.json
{
  "request": { "method": "POST", "urlPath": "/idp/v1/resolve-context" },
  "response": {
    "status": 200,
    "headers": { "Content-Type": "application/json" },
    "jsonBody": { "account_id": "acc-local-42", "project_id": "proj-local-99" }
  }
}
EOF
kubectl --context default -n keycloak create configmap wiremock-mappings \
  --from-file=resolve-context.json=/tmp/opencode-resolve-context.json --dry-run=client -o yaml |
  kubectl --context default apply -f -

cat <<'EOF' | kubectl --context default -n keycloak apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: wiremock
  labels: { app: wiremock }
spec:
  replicas: 1
  selector: { matchLabels: { app: wiremock } }
  template:
    metadata: { labels: { app: wiremock } }
    spec:
      containers:
        - name: wiremock
          image: wiremock/wiremock:3.9.1
          args: ["--verbose"]
          ports: [{ containerPort: 8080 }]
          volumeMounts:
            - { name: mappings, mountPath: /home/wiremock/mappings }
      volumes:
        - name: mappings
          configMap: { name: wiremock-mappings }
---
apiVersion: v1
kind: Service
metadata:
  name: wiremock
spec:
  selector: { app: wiremock }
  ports: [{ port: 8080, targetPort: 8080 }]
EOF
```

### 1.3 Keycloak with the SPI (production deployment pattern)

```bash
cat <<'EOF' | kubectl --context default -n keycloak apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: keycloak
  labels: { app: keycloak }
spec:
  replicas: 1
  selector: { matchLabels: { app: keycloak } }
  template:
    metadata: { labels: { app: keycloak } }
    spec:
      initContainers:
        - name: install-spi
          image: busybox
          command: ["/bin/sh"]
          args:
            - -c
            - |
              set -ex
              V=0.1.2
              B=https://github.com/ADORSYS-GIS/lightbridge-keycloak-spi/releases/download/v$V
              wget -qO /spi/spi-common.jar $B/spi-common-$V.jar
              wget -qO /spi/context-client.jar $B/context-client-$V.jar
              wget -qO /spi/token-exchange.jar $B/token-exchange-$V.jar
              wget -qO /spi/protocol-mapper.jar $B/protocol-mapper-$V.jar
              ls -lash /spi
          volumeMounts:
            - { name: spi-volume, mountPath: /spi }
      containers:
        - name: keycloak
          image: quay.io/keycloak/keycloak:26.6.4
          args: ["start-dev"]
          env:
            - { name: KEYCLOAK_ADMIN, value: admin }
            - { name: KEYCLOAK_ADMIN_PASSWORD, value: localadmin }
            # Same env contract as the production StatefulSet; only the
            # resolver URL and credentials differ (stubbed here).
            - { name: LIGHTBRIDGE_RESOLVER_BASE_URL, value: "http://wiremock.keycloak.svc.cluster.local:8080" }
            - { name: LIGHTBRIDGE_AUTH_MODE, value: BASIC }
            - { name: LIGHTBRIDGE_BASIC_USERNAME, value: authorino }
            - { name: LIGHTBRIDGE_BASIC_PASSWORD, value: stub-pass }
            - { name: LIGHTBRIDGE_ALLOWED_REALMS, value: camer-digital }
          ports: [{ containerPort: 8080 }]
          readinessProbe:
            httpGet: { path: /, port: 8080 }
            initialDelaySeconds: 20
          volumeMounts:
            - { name: spi-volume, mountPath: /opt/keycloak/providers }
      volumes:
        - name: spi-volume
          emptyDir: {}
---
apiVersion: v1
kind: Service
metadata:
  name: keycloak
spec:
  selector: { app: keycloak }
  ports: [{ port: 8080, targetPort: 8080 }]
EOF
kubectl --context default -n keycloak rollout status deploy/keycloak deploy/wiremock --timeout=420s
```

### 1.4 Verify the SPI loaded — **Checkpoint A**

```bash
kubectl --context default -n keycloak exec deploy/keycloak -- ls /opt/keycloak/providers/
kubectl --context default -n keycloak logs deploy/keycloak | grep -i lightbridge
```

**Expected output:**

```
context-client.jar
protocol-mapper.jar
spi-common.jar
token-exchange.jar
```

and in the logs:

```
KC-SERVICES0047: lightbridge-context-mapper (...) is implementing the internal SPI protocol-mapper ...
KC-SERVICES0047: lightbridge-standard (...) is implementing the internal SPI oauth2-token-exchange ...
Lightbridge token-exchange provider initialized: resolver=http://wiremock.keycloak.svc.cluster.local:8080/idp/v1/resolve-context, authMode=BASIC, projectIdParam=project_id, allowedRealms=[camer-digital], timeoutMs=5,000
```

**Interpretation:** both SPI providers registered (mapper + token-exchange),
and the provider factory picked up the env contract (resolver URL, Basic auth,
`project_id` parameter, realm allow-list).

✅ *Proves:* the same SPI binaries as production load and initialize correctly.
Without this, every later step would fail with "no token-exchange provider".

---

## 2. Install the chart (realm import)

```bash
helm --kube-context default upgrade --install keycloak-baseline charts/keycloak-baseline -n keycloak

# The chart ships realm config via a CronJob; trigger one import manually:
kubectl --context default -n keycloak delete job keycloak-baseline-manual --ignore-not-found
kubectl --context default -n keycloak create job --from=cronjob/keycloak-baseline keycloak-baseline-manual
kubectl --context default -n keycloak wait --for=condition=complete job/keycloak-baseline-manual --timeout=180s
```

### 2.1 Verify both clients imported — **Checkpoint B**

```bash
kubectl --context default -n keycloak exec deploy/keycloak -- \
  /opt/keycloak/bin/kcadm.sh config credentials \
  --server http://localhost:8080 --realm master --user admin --password localadmin

kubectl --context default -n keycloak exec deploy/keycloak -- \
  /opt/keycloak/bin/kcadm.sh get clients -r camer-digital -q clientId=opencode-cli

kubectl --context default -n keycloak exec deploy/keycloak -- \
  /opt/keycloak/bin/kcadm.sh get clients -r camer-digital -q clientId=opencode-exchange
```

**Expected (key fields):**

| Field | `opencode-cli` | `opencode-exchange` |
|---|---|---|
| `publicClient` | `true` | `false` |
| device grant attr | `"true"` | absent |
| `pkce.code.challenge.method` | `S256` | — |
| `standard.token.exchange.enabled` | — | `"true"` |
| `protocolMappers[].protocolMapper` | `oidc-audience-mapper` (`included.client.audience: opencode-exchange`) | `lightbridge-context-mapper` |

**Interpretation:** GitOps import works; the confidential/STE constraint and
the audience mapper made it through the template rendering.

✅ *Proves:* the chart itself (the actual deliverable of this ticket) produces
the intended realm state declaratively.

⚠️ If the job fails with *"Unsupported standard token exchange settings …
client must be confidential"* — the exchange client was made public; that
combination is rejected by Keycloak/config-cli by design.

---

## 3. Local-only realm adjustments

Two values in the chart are tuned for production and must be overridden
locally (they are **not** chart bugs):

```bash
# Advertise localhost instead of https://accounts.camer.digital
kubectl --context default -n keycloak exec deploy/keycloak -- \
  /opt/keycloak/bin/kcadm.sh update realms/camer-digital \
  -s 'attributes={"frontendUrl":"http://localhost:8080"}' -s verifyEmail=false

# Test user (email pre-verified, no required actions)
kubectl --context default -n keycloak exec deploy/keycloak -- \
  /opt/keycloak/bin/kcadm.sh create users -r camer-digital \
  -s username=local-tester -s enabled=true -s email=local-tester@example.com \
  -s emailVerified=true -s firstName=Local -s lastName=Tester

UID2=$(kubectl --context default -n keycloak exec deploy/keycloak -- \
  /opt/keycloak/bin/kcadm.sh get users -r camer-digital -q username=local-tester \
  | python3 -c "import json,sys;print(json.load(sys.stdin)[0]['id'])")

kubectl --context default -n keycloak exec deploy/keycloak -- \
  /opt/keycloak/bin/kcadm.sh update users/$UID2 -r camer-digital -s 'requiredActions=[]'
kubectl --context default -n keycloak exec deploy/keycloak -- \
  /opt/keycloak/bin/kcadm.sh set-password -r camer-digital --userid $UID2 \
  --new-password 'LocalTest!2026'
```

Credentials: `local-tester@example.com` / `LocalTest!2026`.

> ⚠️ **Drift warning:** the chart's config-cli CronJob reconciles the realm
> **every hour at :00** and will revert these manual edits. If your test window
> crosses an hour boundary, re-run the `update realms` command above.

---

## 4. Device-code login (`opencode-cli`) — **Checkpoint C**

```bash
kubectl --context default -n keycloak port-forward svc/keycloak 8080:8080 >/tmp/kc-pf.log 2>&1 &

# PKCE pair (S256)
VERIFIER=$(python3 -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b'=').decode())")
CHALLENGE=$(python3 -c "import hashlib,base64; print(base64.urlsafe_b64encode(hashlib.sha256('$VERIFIER'.encode()).digest()).rstrip(b'=').decode())")
echo "$VERIFIER" > /tmp/pkce-verifier.txt

# Device authorization request
curl -s -X POST http://localhost:8080/realms/camer-digital/protocol/openid-connect/auth/device \
  -d "client_id=opencode-cli" \
  -d "scope=openid profile offline_access" \
  -d "code_challenge=$CHALLENGE" \
  -d "code_challenge_method=S256"
```

**Expected:** JSON with `device_code`, `user_code` (e.g. `ZHYL-ACXC`),
`verification_uri`, `expires_in: 600`, `interval: 5`.

Open the printed URL (append `?user_code=<USER_CODE>`), sign in with the test
credentials, approve. Then poll:

```bash
DEVICE_CODE=<device_code from previous response>
curl -s -X POST http://localhost:8080/realms/camer-digital/protocol/openid-connect/token \
  -d "grant_type=urn:ietf:params:oauth:grant-type:device_code" \
  -d "client_id=opencode-cli" \
  -d "device_code=$DEVICE_CODE" \
  -d "code_verifier=$(cat /tmp/pkce-verifier.txt)"
```

**Expected:** `access_token`, `refresh_token` (present because of
`offline_access`), `expires_in: 300`,
`scope: openid profile email offline_access`.

Save them for the next phase:

```bash
curl -s … > /tmp/tokens.json   # or copy manually
```

**Interpretation:** public client + device grant + PKCE + offline refresh all
work end-to-end through the imported client — this is exactly the flow the
OpenCode CLI plugin performs.

✅ *Proves:* AC "OpenCode CLI can authenticate users via device-code flow".

Failure modes worth knowing:

| Symptom | Meaning |
|---|---|
| `authorization_pending` | Normal while waiting for user approval — keep polling |
| `invalid_grant` after approval | PKCE verifier mismatch, or code expired (> 10 min) |
| Login page shows 404 / prod hostname | `frontendUrl` override missing (section 3) |
| "Failed to send email" at login | `verifyEmail` override missing, or user still has `VERIFY_EMAIL` required action |

---

## 5. Offline refresh — **Checkpoint D**

```bash
RT=$(python3 -c 'import json;print(json.load(open("/tmp/tokens.json"))["refresh_token"])')
curl -s -X POST http://localhost:8080/realms/camer-digital/protocol/openid-connect/token \
  -d "grant_type=refresh_token" -d "client_id=opencode-cli" -d "refresh_token=$RT"
```

**Expected:** fresh `access_token` **and a rotated `refresh_token`**, no user
interaction.

**Interpretation:** long-lived CLI sessions survive access-token expiry — the
reason `offline_access` is requested.

✅ *Proves:* AC "offline/session refresh works".

---

## 6. Token exchange with project context (`opencode-exchange`) — **Checkpoint E**

This is the heart of the ticket. The human token is exchanged for a
service-scoped token whose `account_id` / `project_id` were resolved by the SPI
calling the (stubbed) backend.

```bash
AT=$(python3 -c 'import json;print(json.load(open("/tmp/tokens.json"))["access_token"])')

curl -s -X POST http://localhost:8080/realms/camer-digital/protocol/openid-connect/token \
  -u "opencode-exchange:opencode-exchange-local-dev-secret" \
  -d "grant_type=urn:ietf:params:oauth:grant-type:token-exchange" \
  -d "subject_token=$AT" \
  -d "subject_token_type=urn:ietf:params:oauth:token-type:access_token" \
  -d "project_id=proj-local-99"
```

Decode the returned `access_token`:

```bash
EXCHANGED=<access_token from exchange response>
python3 -c "
import json, base64, sys
p = json.loads(base64.urlsafe_b64decode(sys.argv[1].split('.')[1] + '=='))
print(json.dumps({k: p.get(k) for k in ['iss','azp','aud','sub','account_id','project_id']}, indent=2))
" "$EXCHANGED"
```

**Expected output:**

```json
{
  "iss":       "http://localhost:8080/realms/camer-digital",
  "azp":       "opencode-exchange",
  "aud":       "account",
  "sub":       "<same user id as the human token>",
  "account_id": "acc-local-42",
  "project_id": "proj-local-99"
}
```

**Interpretation, claim by claim:**

| Claim | Value | What it proves |
|---|---|---|
| `azp` | `opencode-exchange` | The confidential exchanger performed the grant |
| `sub` | unchanged user id | Identity preserved through the exchange |
| `account_id` | `acc-local-42` | **Came from the SPI → WireMock resolver call** — the value only exists in the stub response, so its presence proves the full resolver round-trip happened |
| `project_id` | `proj-local-99` | Requested project echoed back after membership resolution |

You can also see the resolver call in the WireMock logs:

```bash
kubectl --context default -n keycloak logs deploy/wiremock | grep resolve-context
```

✅ *Proves:* AC "Source-audience token exchange seals account/project context".
This is the exact contract consumed downstream by the AI gateway.

---

## 7. Negative tests (fail-closed behaviour) — **Checkpoint F**

### 7.1 Exchange against a non-STE client must be rejected

```bash
curl -s -X POST http://localhost:8080/realms/camer-digital/protocol/openid-connect/token \
  -d "client_id=opencode-cli" \
  -d "grant_type=urn:ietf:params:oauth:grant-type:token-exchange" \
  -d "subject_token=$AT" \
  -d "subject_token_type=urn:ietf:params:oauth:token-type:access_token" \
  -d "project_id=proj-local-99"
```

**Expected:**

```json
{"error":"invalid_request","error_description":"Standard token exchange is not enabled for the requested client"}
```

**Interpretation:** the public CLI client cannot mint service tokens; exchange
is gated to the dedicated confidential client.

### 7.2 Exchanger outside subject-token audience must be rejected

Temporarily remove the audience mapper from `opencode-cli` in
`charts/keycloak-baseline/values.yaml`, re-import (section 2), obtain a fresh
human token, and retry the exchange. **Expected:**

```json
{"error":"access_denied","error_description":"Client is not within the token audience"}
```

Restore the mapper afterwards. **Interpretation:** STE V2 enforces that the
exchanging client appears in the subject token's `aud`; the audience mapper in
the chart is therefore *required*, not cosmetic.

---

## 8. Verdict matrix — what "done" looks like

| # | Checkpoint | Pass condition | Ticket question answered |
|---|---|---|---|
| A | §1.4 SPI loads | Provider-factory init log lists resolver/BASIC/`project_id`/realms | Is the prod SPI usable as deployed? |
| B | §2.1 Clients imported | Table in §2.1 matches | Does the chart produce the intended realm state? |
| C | §4 Device login | Tokens issued, PKCE enforced, refresh token present | Can the OpenCode CLI authenticate? |
| D | §5 Refresh | New AT + rotated RT, no interaction | Do sessions survive expiry? |
| E | §6 Exchange | `account_id`/`project_id` in exchanged JWT, sourced from resolver | Does context sealing work end-to-end? |
| F | §7 Negative | Both unauthorized exchanges rejected cleanly | Is the feature fail-closed? |

**All six green ⇒ the ticket's deliverable (realm configuration for
`opencode-cli` + `opencode-exchange` + SPI integration) is proven working
against the same Keycloak and SPI versions as production.**

Out of scope for this local test (tracked separately): production rollout of
the real resolver endpoint/secret (ESO), and any change to the SPI itself.

---

## 9. Cleanup

```bash
kubectl --context default -n keycloak delete deploy/keycloak deploy/wiremock \
  svc/keycloak svc/wiremock cm/wiremock-mappings job/keycloak-baseline-manual --ignore-not-found
helm --kube-context default uninstall keycloak-baseline -n keycloak
pkill -f "port-forward svc/keycloak"
rm -f /tmp/tokens.json /tmp/pkce-verifier.txt /tmp/opencode-resolve-context.json
```

---

## 10. Troubleshooting quick reference

| Symptom | Cause | Fix |
|---|---|---|
| `ImagePullBackOff` on `ghcr.io/adorsys-gis/lightbridge-keycloak-spi` | GHCR image is private | Use the init-container pattern from §1.3 (downloads public release jars) |
| Manual realm edits vanish within the hour | Config-cli CronJob reconciles drift at :00 | Expected GitOps behaviour; re-apply local overrides, or pause the CronJob |
| `verification_uri` shows `https://accounts.camer.digital` | Realm `frontendUrl` from chart values | Apply the §3 override |
| "Failed to send email" during login | `verifyEmail=true` + no SMTP locally | §3 override + ensure user has no `VERIFY_EMAIL` required action |
| Exchange → `Client is not within the token audience` | Audience mapper missing from `opencode-cli` tokens | Restore mapper (§7.2); refresh the human token afterwards — mappers apply at issuance |
| Exchange → `Standard token exchange is not enabled…` | Using the public client instead of `opencode-exchange` | Use the confidential client + secret (§6) |
| Port-forward silently dead after pod restart | kubectl process tied to old pod | Re-run the `port-forward` command |
