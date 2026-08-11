# Verify the LibreChat Coder scaffold flow end-to-end (Ticket #832)

Step-by-step runbook to prove the Ticket #832 acceptance criteria against a live
environment. Use it to record **verification evidence** and tick the ticket's
deliverables / acceptance criteria.

**Prerequisites / dependencies**
- PR #937 (ai-helm) + PR #220 (ai-helm-values) merged (values-repo-first), or the
  equivalent applied manually.
- The `coder` DB agent present in LibreChat (post `agent-seed` Job run).
- The **pre-baked Coder template** (`node-scaffold`) provisioned (ADR-0124) and
  the in-workspace **OpenCode** agent reachable with Keycloak client-creds.
- A Coder session token + the `coder` CLI, or direct REST access to Coder.

---

## Acceptance criteria (what we must prove)

1. **Given** a user asks LibreChat to scaffold an app, **when** the agent runs,
   **then** a Coder workspace is created and the in-workspace AI agent receives
   scaffolding instructions.
2. **Given** the scaffold is complete, **when** the link is returned, **then** it
   is clickable and the app boots.

---

## 0. Pre-flight: environment + dependency checks

```bash
# 1. Coder reachable + session valid
CODER_URL=https://coder.ai.camer.digital
TOKEN=<scoped token>
curl -fsS -H "Coder-Session-Token: $TOKEN" "$CODER_URL/api/v2/users/me" | head -c 200; echo

# 2. The template exists
curl -fsS -H "Coder-Session-Token: $TOKEN" "$CODER_URL/api/v2/organizations" \
  | python3 -c 'import sys,json; print([o["id"] for o in json.load(sys.stdin)])'
# then list templates for the org id:
# curl -fsS -H "Coder-Session-Token: $TOKEN" "$CODER_URL/api/v2/organizations/<org>/templates"
# → expect a `node-scaffold` entry.

# 3. LibreChat has the coder agent
# get the LibreChat agent list (needs a LibreChat bearer token / UI Agents page)
curl -fsS -H "Authorization: Bearer $TOKEN_LIBRECHAT" "$LIBRECHAT_URL/api/agents?limit=200" \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); a=d if isinstance(d,list) else d.get("data",d.get("agents",[])); print([x["name"] for x in a])'
# → expect `coder` present.
```

**Gate:** if the `node-scaffold` template or the `coder` agent is missing, stop —
these are prerequisites, not test failures. Provision them first (ADR-0124 /
agent-seed Job).

---

## 1. Verify the agent can spin up a Coder workspace (deliverable 3 + AC1 first half)

Drive the flow the `coder` agent would run. Use the stable REST contract
(ADR-0121) — not the experimental MCP.

```bash
ORG=<org-id>
# create a workspace from the template (name must be ≤~40 chars; avoid the 63-char hostname edge)
WSNAME="ci-scaffold-$(date +%s)"

curl -fsS -X POST -H "Coder-Session-Token: $TOKEN" -H "Content-Type: application/json" \
  "$CODER_URL/api/v2/users/me/workspace" \
  -d "{\"template_id\":\"$ORG\",\"name\":\"$WSNAME\"}" \
  # ^ template_id is the template UUID from the templates list; use the real id.
  | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("id"), d.get("status",""))'

# poll the workspace build until Ready (build status → running → ready)
WSID=<workspace-id>
for i in $(seq 1 30); do
  st=$(curl -fsS -H "Coder-Session-Token: $TOKEN" "$CODER_URL/api/v2/workspaces/$WSID" \
        | python3 -c 'import sys,json; print(json.load(sys.stdin).get("latest_build",{}).get("status",""))')
  echo "build=$st"; [ "$st" = "running" ] || [ "$st" = "ready" ] && break; sleep 5
done
```

**Pass:** a workspace is created and transitions to running/ready.
**Evidence:** workspace id + final build status.

---

## 2. Verify scaffolding + the app boots (deliverable 5 + AC2)

Execute the in-workspace OpenCode agent to scaffold, then confirm the dev server
answers on :3000. (Exact exec push varies by executor — here a representative
script invoke inside the workspace; confirm the stable agent-exec endpoint for
your Coder version.)

```bash
# run the scaffold orchestration inside the workspace
CODER_URL=$CODER_URL CODER_TOKEN=$TOKEN \
  CODER_SCAFFOLD_TEMPLATE=node-scaffold \
  tools/coder-scaffold/scaffold.sh    # or the equivalent in-workspace command

# then health-check the dev server
curl -fsS -o /dev/null -w "http=%{http_code}\n" http://localhost:3000   # inside the workspace
# → expect 200
```

**Pass:** the dev server on :3000 returns HTTP 200, and the scaffolded app
(Next.js + tRPC + Keycloak) is present in the workspace.
**Evidence:** scaffold log + the :3000 HTTP 200.

---

## 3. Verify port share + a reachable link (deliverable 6 + AC2)

Because port sharing is a Coder **server-side** REST call (ADR-0121) that an
in-pod script can't make without a token, publish here and confirm reachability.

```bash
curl -fsS -X POST -H "Coder-Session-Token: $TOKEN" -H "Content-Type: application/json" \
  "$CODER_URL/api/v2/workspaces/$WSID/port-share" \
  -d '{"agent_name":"main","port":3000,"share_level":"authenticated","protocol":"http"}'

# read the full URL from Coder (prefer this over hand-assembling)
curl -fsS -H "Coder-Session-Token: $TOKEN" "$CODER_URL/api/v2/workspaces/$WSID/port-share" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin))'
# build the wildcard URL: https://3000--main--<wsname>--<user>.coder-ws.camer.digital

# reachability (unauthenticated should be 303 → auth-redirect, NOT 200; with a valid
# session it should be 200)
curl -sS -o /dev/null -w "no-session=%{http_code}\n" "https://3000--main--$WSNAME--<user>.coder-ws.camer.digital/"
# → expect 303 (layer 3 = "authenticated" protection working)
```

**Pass (security + reachability):**
- No session → **303** (proves `authenticated` is enforced — P1 control working).
- With a valid user session → **200**.

**Evidence:** the port-share response + the 303/200 pair.

---

## 4. End-to-end via LibreChat UI (deliverables 3–6, the real acceptance path)

1. In LibreChat, ask **`converse`** (or mention `@coder`):
   *"Scaffold a Next.js + tRPC + Keycloak app and give me a preview link."*
2. Watch the agent: workspace created → in-workspace agent run → link returned.
3. Open the returned link in a **private/incognito window** → confirm it asks to
   authenticate (303 → login) rather than loading unauthenticated.
4. Log in → confirm the app renders.

**Pass:** a real user gets a clickable link that authenticates and boots.
**Evidence:** a screenshot or the returned URL + the no-session 303.

---

## 5. Teardown

```bash
# revoke the share (restores owner-only / removes public exposure)
curl -fsS -X DELETE -H "Coder-Session-Token: $TOKEN" -H "Content-Type: application/json" \
  "$CODER_URL/api/v2/workspaces/$WSID/port-share" -d '{"agent_name":"main","port":3000}'

# optionally stop/delete the workspace
curl -fsS -X PUT -H "Coder-Session-Token: $TOKEN" -H "Content-Type: application/json" \
  "$CODER_URL/api/v2/workspaces/$WSID/stop" || true
```

Confirm the URL flips back to 303 (no longer shared).

---

## Recording evidence on the ticket

When all pass, on Ticket #832 mark checked and fill `Verification Evidence`:

| Deliverable | Evidence |
|---|---|
| Agent spins up a workspace | workspace id + build→ready |
| In-workspace agent receives instructions | scaffold log / transcript |
| Scaffolded app boots | :3000 HTTP 200 |
| Reachable link returned | URL + no-session 303 / session 200 |
| (AC1) workspace → agent instructed | step 4 transcript |
| (AC2) link clickable + boots | step 4 screenshot |

Then close the ticket.

---

## Known gaps / risks to record

- `AgentAPI` (framing in the ticket) is not the verified mechanism here — the
  in-workspace **OpenCode** agent is what's available; verify via that path.
- Requires the `node-scaffold` template + in-workspace OpenCode to be **deployed**
  (ADR-0124 follow-up) — if absent, block and provision first.
- Exact stable agent-exec endpoint must be confirmed for the live Coder version.
