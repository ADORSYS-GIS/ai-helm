# MCP external-server proxy debug + AIEG v0.6.0 → v0.7.0 upgrade (2026-06-10)

**Status:** RESOLVED — **final fix = [ADR-0040](adr/0040-external-mcps-via-caddy-normalizing-proxy.md)**
(`release-2026.06.10-v04`): all three external MCPs (context7, firecrawl, refero)
go through per-MCP in-cluster **Caddy normalizing proxies**. Point-in-time
change-log of the whole investigation; durable contracts in
[ADR-0038](adr/0038-mcp-oauth-protected-resource-metadata.md),
[ADR-0040](adr/0040-external-mcps-via-caddy-normalizing-proxy.md),
[ADR-0027](adr/0027-mcps-orchestrator-split-and-coder-removal.md).

> ## ✅ FINAL resolution (supersedes the ADR-0039 EnvoyPatchPolicy below)
> The investigation went through three fixes; only the last stuck:
> 1. AIEG v0.6→v0.7 upgrade (`-v01`) — red herring (mcpproxy unchanged).
> 2. EnvoyPatchPolicy SNI injection ([ADR-0039](adr/0039-mcp-external-backend-tls-envoypatchpolicy.md), `-v02`) —
>    fixed firecrawl/refero **TLS**, but brittle, BoringSSL-only (context7's ECDSA
>    cert still failed), and **didn't fix refero's empty tools** (it returns a
>    JSON body mislabeled `text/event-stream`, so the mcpproxy's SSE parser yields
>    nothing — [envoyproxy/ai-gateway#2218](https://github.com/envoyproxy/ai-gateway/issues/2218)).
> 3. **[ADR-0040](adr/0040-external-mcps-via-caddy-normalizing-proxy.md) (`-v04`) — the real fix:**
>    front each external MCP with an in-cluster **Caddy** proxy (`mode:
>    proxiedExternal`). Caddy does the upstream TLS (Go TLS → **handles context7's
>    ECDSA cert** that BoringSSL rejected), injects the credential, and rewrites
>    refero's response `Content-Type → application/json` so the mcpproxy parses it.
>    External MCPs become reliable in-cluster plain-HTTP backends (like
>    brave/terraform); the EnvoyPatchPolicy is removed. Validated live: refero 8
>    tools, context7 ECDSA handshake OK, firecrawl 19 tools.
>
> The sections below are the investigation trail (incl. the discarded mcpproxy-bug
> and EnvoyPatchPolicy stages).

> ## ⚠️ ACTUAL root cause (supersedes the §4 mcpproxy-bug hypothesis below)
> The §4 "AIEG mcpproxy runtime bug (#1924/#1996/#1938)" theory was **wrong**,
> and the AIEG v0.6.0→v0.7.0 upgrade (§5–6, `release-2026.06.10-v01`)
> consequently **did not fix it** — a useful negative result, and v0.7.0 is the
> right baseline regardless. The real cause, traced through the live Envoy config
> dump:
>
> **AIEG stamps a placeholder `dummy.transport_socket` (empty `UpstreamTlsContext`
> — no SNI, no CA) on the cluster it generates for each external HTTPS MCP
> backend, and EG's `BackendTLSPolicy` / inline `Backend.spec.tls.sni` never reach
> it** (EG's Backend-TLS translation runs before AIEG's extension hook creates the
> cluster — verified: inline `spec.tls.sni` had zero effect). So the gateway opens
> upstream TLS with **empty SNI** → CDN-fronted MCP servers can't select a cert →
> handshake fails (`ssl.connection_error`, `0` handshakes) → "failed to create MCP
> session to any backend". Self-hosted plain-HTTP MCPs (brave, terraform) have no
> TLS hop, so they were never affected. My earlier "in-cluster replay works"
> (§3) succeeded only because `curl`/`openssl` set SNI themselves — bypassing the
> broken Envoy socket.
>
> **The fix ([ADR-0039](adr/0039-mcp-external-backend-tls-envoypatchpolicy.md)):**
> an `EnvoyPatchPolicy` (runs last in the xDS pipeline) replaces the dummy socket
> with a real `envoy.transport_sockets.tls` carrying SNI + system-CA validation.
> **Verified live before shipping:** with the patch, `refero` returns `200`s
> (`upstream_rq_2xx`), `firecrawl` handshakes succeed (`ssl.handshake>0`,
> `connection_error=0`).
>
> **Per-cert split — the key finding:** the patch rescues **RSA-cert** upstreams
> only. **context7 serves an ECDSA cert** (`ecdsa_secp256r1_sha256`) that Envoy's
> **BoringSSL rejects at the handshake** (`BAD_ECC_CERT`; `connection_error` with
> `fail_verify=0`), SNI or not — the exact reason AIEG disabled context7 in their
> own CI ([#1880](https://github.com/envoyproxy/ai-gateway/pull/1880)). firecrawl
> + refero serve RSA certs → they work.
> **context7 was DROPPED** (`release-2026.06.10-v03`, 2026-06-11): self-hosting it
> would need a custom-built image (no usable published context7 HTTP image) +
> Upstash Redis (its v3 HTTP session store) — both against repo constraints.
> Revisit via a published HTTP image or a stdio+supergateway bridge.
>
> Diagnostic recipe: `/config_dump` → the `ai-eg-mcp-br-<name>-<name>/rule/0`
> cluster's `transport_socket` (`dummy.transport_socket` = broken; `sni:""`);
> `/stats` → `cluster.<...br-name...>.ssl.{handshake,connection_error}` +
> `upstream_rq_{2xx,5xx}`; `openssl s_client -servername <host>` → cert key type
> (RSA = patchable, ECDSA = BoringSSL-blocked).
>
> The sections below are kept as the investigation trail (how the wrong theory
> was reached and discarded).

## 1. Symptom

Right after [ADR-0038](adr/0038-mcp-oauth-protected-resource-metadata.md) shipped
MCP-spec OAuth discovery (so `opencode mcp auth` can finally authenticate against
`api.ai.camer.digital/mcp/*`), the **self-hosted** MCPs worked but every
**external hosted** MCP failed downstream of the gateway:

| MCP | mode | symptom |
|---|---|---|
| brave | self-hosted | ✅ authenticates + works |
| terraform | self-hosted | ✅ works |
| context7 | external (`mcp.context7.com`) | ❌ `SSE error: Non-200 status code (400)` |
| firecrawl | external (`mcp.firecrawl.dev`) | ❌ `SSE error: Non-200 status code (400)` |
| refero | external (`api.refero.design`) | ⚠️ session establishes but **lists 0 tools** |

During an `opencode mcp auth` re-auth of context7's expired credentials, the
error was AIEG's `failed to create MCP session to any backend`.

These external MCPs had **almost certainly never worked before** — without the
ADR-0038 discovery surface no client could complete auth to reach them, so this
was the first real end-to-end test, not a regression.

## 2. What we ruled OUT (it is not our config, and not ADR-0038)

The pattern — self-hosted works, all three *external* ones fail — pointed at the
gateway→upstream hop, not the OAuth edge. Confirmed point by point:

1. **Edge OAuth is correct.** `POST /mcp/brave` with no token →
   `401` + `WWW-Authenticate: Bearer error="invalid_token", …,
   resource_metadata="https://api.ai.camer.digital/.well-known/oauth-protected-resource/mcp/brave"`.
   Discovery + JWT verification work.
2. **Upstream credential injection is correctly wired.** The AIEG-generated
   per-backend HTTPRoutes (`ai-eg-mcp-br-<x>-<x>`) each carry a
   `RequestHeaderModifier: Set Authorization: Bearer <token>` + the right path
   rewrite. Verified lengths: `Bearer `(7) + key (ctx7sk… 43 / fc-… 35 / mcp-…
   20) = 50/42/27. Secrets synced (`SecretSynced`), keys valid format.
3. **The inbound Keycloak JWT does not leak upstream.** AIEG v0.6.0 source: the
   MCP proxy builds a fresh request to the internal backend listener and forwards
   only allow-listed `forwardHeaders`; the client JWT is dropped at the proxy
   boundary, then the per-backend `Set: Authorization` injects the upstream
   token. (`internal/mcpproxy/mcpproxy.go`, `internal/controller/mcp_route.go`.)
4. **AIEG sends the correct `Accept`.** `mcpproxy.go:430` sets
   `Accept: application/json, text/event-stream` on upstream POSTs — so the MCP
   406 content-negotiation (`Not Acceptable: Client must accept both …`) is **not**
   how AIEG talks to upstreams.

## 3. The decisive evidence — upstreams are fine

Replaying AIEG's *exact* upstream request from **inside the cluster**
(`converse-mcp` namespace, the same egress the proxy uses) — correct `Accept`,
the injected `Bearer` token, the full `initialize → notifications/initialized →
tools/list` handshake — **every upstream returns its tools**:

| upstream | initialize | tools/list | tools | session |
|---|---|---|---|---|
| refero | 200 | 200 | **8** | stateless (no `Mcp-Session-Id`) |
| context7 | 200 | 200 | **2** | stateful (returns session id) |
| firecrawl (Bearer on `/v2/mcp`) | 200 | 200 | **19** | stateless |
| firecrawl (key-in-path) | 200 | 200 | **19** | stateless |

So: upstreams ✅, credentials ✅, cluster egress ✅, the exact request AIEG makes
✅. **The break is in the AIEG v0.6.0 mcpproxy runtime**, which our Helm charts
don't control. Note the differentiator: **refero and firecrawl are stateless**
streamable-HTTP and **405 on the standalone GET SSE stream** that AIEG opens;
context7 is stateful.

> The mcpproxy runs as a Go HTTP filter inside the controller process (the
> `192.0.2.42:9856` placeholder backend + `--mcpSessionEncryptionSeed`), not as a
> sidecar — so its per-request failures are not in the envoy access log and are
> not logged at `info`. We did not patch the externally-managed install to get
> `debug`; the in-cluster replay above isolates the layer without it.

## 4. Root cause (mapped to AIEG's tracker)

The failures match AIEG's own MCP-proxy bug classes for external hosted
streamable-HTTP servers:

- **refero "0 tools"** ↔ [#1924](https://github.com/envoyproxy/ai-gateway/issues/1924)/[#1980](https://github.com/envoyproxy/ai-gateway/pull/1980):
  a backend that 405s on the GET SSE stream drives a retry loop that
  re-aggregates `tools/list` → empty list (auth is fine; tools vanish).
- **context7 / firecrawl "SSE 400"** ↔ [#1996](https://github.com/envoyproxy/ai-gateway/issues/1996)/[#1997](https://github.com/envoyproxy/ai-gateway/pull/1997)
  (SSE-framed JSON decode) + [#1938](https://github.com/envoyproxy/ai-gateway/issues/1938)/[#1962](https://github.com/envoyproxy/ai-gateway/pull/1962) (compression).
- **"failed to create MCP session to any backend"** = AIEG's aggregate error when
  *every* backend's `initialize` failed on that attempt.

The catch: all of those fixes merged **before** the v0.6.0 tag (2026-05-05), yet
the running `ai-gateway-controller:v0.6.0` (digest `sha256:00ace03…`) still
exhibits them — so it is either a regression, a not-yet-covered edge with these
specific hosted servers (AIEG's *own CI disabled context7* for TLS flakiness,
[#1880](https://github.com/envoyproxy/ai-gateway/pull/1880)), or a new bug.

## 5. Decision: upgrade AIEG v0.6.0 → v0.7.0

AIEG is ArgoCD-managed **from this repo** (`charts/apps` apps `aieg` +
`aieg-crd`, OCI charts `oci://docker.io/envoyproxy/ai-gateway{,-crds}-helm`,
ArgoCD apps `aii-aieg` / `aii-aieg-crd`). Bumped both pins `v0.6.0 → v0.7.0`
(latest, 2026-06-06) in lockstep. This is a version bump + the upstream
bug-fix path; there is **nothing to change in `charts/mcp`/`charts/mcps`** — our
MCP config is correct.

We did **not** take the "keep Authorino + hand-serve static PRM" path — that was
already weighed and rejected in ADR-0038, and it would not have changed the
gateway→upstream proxying that is actually broken.

### v0.7.0 compatibility audit (vs the v0.7.0 git tag)

| check | result |
|---|---|
| Envoy Gateway floor | v1.7.0+ (no upper bound) — we run **v1.8.0** ✅ |
| CRD versions | `v1alpha1` still served, storage stays `v1beta1`, none removed → existing CRs safe ✅ |
| `MCPRoute.securityPolicy.oauth` / `apiKey` / `claimToHeaders` | **byte-for-byte unchanged** → ADR-0038 intact ✅ |
| Controller Helm values | `maxRecvMsgSize`, `mutatingWebhook.certManager`, `extProc.logLevel` unchanged ✅ |
| Only breaking change | `AIGatewayRoute.spec.rules` cap **128 → 15** — N/A: every model route has **1** rule (verified live, max=1) ✅ |
| Behavior change to expect | `tools/list` now hides tools the caller isn't authorized to invoke ([#2106](https://github.com/envoyproxy/ai-gateway/pull/2106)) — expected, not a regression |

### v0.7.0 mcpproxy changes
Only `internal/mcpproxy/sse.go` (the spaceless-SSE decode fix,
[#2155](https://github.com/envoyproxy/ai-gateway/pull/2155)) and `handlers.go`
(tools/list authz) changed. **`mcpproxy.go` and `session.go` are unchanged from
v0.6.0** — so the stateless-server GET-405 path is identical. See §7.

## 6. What shipped

- ai-helm `93bdf28` — `aieg` + `aieg-crd` → v0.7.0 (with the audit captured in
  the value comments), cut as **`release-2026.06.10-v01`**.
- home-os **PR #16** — repoint root `ai-apps-v2` → `release-2026.06.10-v01`
  (follow-up to #15 which shipped `release-2026.06.10` = ADR-0038). Merge rolls
  the root forward to AIEG v0.7.0.

## 7. ⚠️ Open: v0.7.0 is not guaranteed to fix it

v0.7.0's `mcpproxy.go`/`session.go` are identical to v0.6.0, so the
**stateless-server GET-SSE-405 path** (refero/firecrawl) is unchanged; and
context7 emits `data: ` **with** the space, so the spaceless-SSE fix (#2155)
likely won't help it either. v0.7.0 is the correct latest baseline, but:

- **After merging home-os#16**, confirm `aii-aieg`/`aii-aieg-crd` sync to v0.7.0
  and the gateway + model routes stay healthy, then **re-test the four external
  MCPs end-to-end** via opencode (§8).
- **If the externals still fail**, file the reproduction below upstream
  (envoyproxy/ai-gateway) — it is a strong report (upstreams return tools when
  hit directly with AIEG's exact request; fail only through the proxy;
  stateless-405-on-GET).
- **Tangential, low-priority:** the controller logged one transient
  `failed to fetch OAuth authorization server metadata` timeout to
  `auth.verif.fyi` (1 event / 4h, self-recovered). It only degrades the
  AS-metadata discovery document (falls back to a hardcoded Keycloak-shaped one);
  it does not block JWT verification or tool invocation. Watch for recurrence —
  controller→Keycloak egress is occasionally slow.

## 8. Reproduction / verification recipe

```bash
KC=/path/to/hetzner-k8s/kubeconfig   # workloads = home-remote

# 1. Confirm the per-backend apiKey injection is wired (Set Authorization + path)
KUBECONFIG=$KC kubectl -n converse-mcp get httproute ai-eg-mcp-br-context7-context7 -o yaml

# 2. Prove the upstream works when hit EXACTLY as AIEG does, from inside the cluster.
#    (a laptop may not reach mcp.firecrawl.dev; run it in converse-mcp.)
#    Pull the key, then init -> notifications/initialized -> tools/list with
#    `Accept: application/json, text/event-stream` and `Authorization: Bearer <key>`.
#    Expected: refero=8, context7=2, firecrawl=19 tools.

# 3. Edge challenge sanity (ADR-0038):
curl -si https://api.ai.camer.digital/mcp/brave -X POST \
  -H 'Accept: application/json, text/event-stream' -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | grep -i www-authenticate
#   -> Bearer …, resource_metadata="…/.well-known/oauth-protected-resource/mcp/brave"

# 4. End-to-end (the real test): `opencode mcp auth` each server, then use a tool.
```

## 9.5 Postscript (2026-06-11): context7 "Invalid API key" was a token-bind race, NOT a bad key

After the Caddy proxies went live, context7 returned `Error: Invalid API key … keys should
start with 'ctx7sk'` on every doc query — even though the secret value was confirmed correct.
It looked like an unregistered/invalid key. It was not.

**Root cause — a 1-second start race.** The context7 Caddy pod started at `08:33:40Z`; ESO
synced the `context7-token` Secret at `08:33:41Z`, one second later. The credential is wired as
an env var (`MCP_TOKEN` ← `secretKeyRef … optional: true`). With `optional: true`, the kubelet
starts the container even when the secret key is absent — so the pod captured **`MCP_TOKEN=""`**.
Env vars from `secretKeyRef` **bind at pod start and never refresh**, so Caddy kept injecting
`Authorization: Bearer ` (empty) long after ESO populated the Secret. context7 saw no key →
"Invalid API key." firecrawl and refero won the same race that boot, so only context7 was hit.

**Proof the key was always good.** A direct `tools/call query-docs {libraryId:/vercel/next.js}`
against `https://mcp.context7.com/mcp` with `Authorization: Bearer ctx7sk-…1509` returned real
Next.js docs; the same call **through the Caddy proxy** (Caddy injecting the key, no client auth)
also returned real docs once the pod was restarted. The cluster Secret value byte-matched the
dashboard key.

**Immediate fix:** `kubectl -n converse-mcp delete pod <context7-caddy>` — the replacement
re-read the now-populated Secret (`MCP_TOKEN` len 43). (`kubectl delete pod`, not `rollout
restart`, which ArgoCD selfHeal reverts.)

**Durable fix (shipped):** in `charts/mcp` the `MCP_TOKEN` env is now rendered with
`optional: false` (never optional), so a keyed Caddy proxy waits in `ContainerCreating` until ESO
has populated the Secret rather than starting tokenless. Waiting is the honest failure mode — an
anonymous context7/firecrawl is useless anyway. The env (and the Caddyfile `Authorization` header)
are rendered **only** when `externalSecret.enabled: true`; a genuinely keyless MCP sets
`externalSecret.enabled: false` and Caddy proxies anonymously. There is deliberately no
"declared-secret-but-optional" mode (no knob) — that combination is always a footgun.
**Recognise the symptom:** `Invalid API key` (or empty/anonymous behaviour) from a
`proxiedExternal` MCP whose Secret is provably correct, right after a fresh deploy/cluster rebuild
→ check `MCP_TOKEN` length in the running Caddy container
(`kubectl exec … -- sh -c 'printf %s "$MCP_TOKEN" | wc -c'`); len 0 = lost the race.

## 9.6 Postscript (2026-06-11): firecrawl failed because it is a STATELESS MCP server

With context7 and refero working through the gateway, only firecrawl still failed
("failed to create MCP session"). It was **not** the key, the proxy, or the upstream: firecrawl
authenticates and returns all 19 tools when hit directly AND through the Caddy proxy in-cluster.

**Root cause — the AIEG mcpproxy requires a stateful backend.** firecrawl's hosted MCP
(`mcp.firecrawl.dev/v2/mcp`, FastMCP) is **stateless**: it returns **no `Mcp-Session-Id`** on
`initialize`. context7 and refero are stateful (both return one). The AIEG mcpproxy **requires**
the backend session id — it encrypts it into its own client-facing session token to stay
replica-stateless. This is a deliberate, **wontfix** design choice: see
[envoyproxy/ai-gateway#1555](https://github.com/envoyproxy/ai-gateway/issues/1555) ("the
mcp-session-id header should be optional" — closed) and the
[MCP-gateway proposal §session-handling](https://github.com/envoyproxy/ai-gateway/blob/main/docs/proposals/006-mcp-gateway/proposal.md#session-handling):
> All session IDs are encoded into a single (ASCII) session ID, which is then encrypted to avoid
> leaking details.

No backend session id → nothing to encode → "failed to create MCP session."

**Fix (ADR-0040 normalizing-proxy spirit):** `charts/mcp` `proxy.statelessUpstream: true`
synthesizes the session id in Caddy. On the hop that carries no `Mcp-Session-Id` (the `initialize`
hop) Caddy mints a fresh uuid; on every later hop it echoes the gateway-sent session id straight
back — so the value is **unique per session AND stable across it**:

```caddyfile
@hasSession header Mcp-Session-Id *
header @hasSession Mcp-Session-Id {http.request.header.Mcp-Session-Id}
@noSession not header Mcp-Session-Id *
header @noSession Mcp-Session-Id {http.request.uuid}
```

Two Caddy gotchas found while building this (both caught by `caddy validate` + a local run
against the real upstream *before* shipping — do this, do not ship Caddyfile changes blind):
1. **`header_down ?Field` is rejected** — the `?` set-if-missing modifier is only valid on the
   standalone `header` (response) directive, not on `reverse_proxy`'s `header_down`.
2. **`map` only expands placeholders in its `default` output, not in matched branches** — so a
   `map` cannot yield two different *live* values (uuid for one case, the request header for the
   other). The request-matcher form above is the way; both placeholders expand.

Enabled for firecrawl only (`charts/mcps` `firecrawl.mcp.proxy.statelessUpstream: true`);
context7/refero stay stateful and must NOT set it. Validated end-to-end through a local Caddy
against `mcp.firecrawl.dev`: init→uuid minted, subsequent→same id echoed, 19 tools, unique per
session. The one link not reproducible locally (the mcpproxy accepting the synthesized id) is the
exact behaviour #1555 documents it requires.

## 9. References

- [ADR-0038](adr/0038-mcp-oauth-protected-resource-metadata.md) — MCP OAuth discovery (the edge surface, working).
- [ADR-0027](adr/0027-mcps-orchestrator-split-and-coder-removal.md) — the `mcps`/`mcp` chart split.
- AIEG issues/PRs: [#1924](https://github.com/envoyproxy/ai-gateway/issues/1924), [#1980](https://github.com/envoyproxy/ai-gateway/pull/1980), [#1996](https://github.com/envoyproxy/ai-gateway/issues/1996), [#1997](https://github.com/envoyproxy/ai-gateway/pull/1997), [#1938](https://github.com/envoyproxy/ai-gateway/issues/1938), [#1962](https://github.com/envoyproxy/ai-gateway/pull/1962), [#2106](https://github.com/envoyproxy/ai-gateway/pull/2106), [#2155](https://github.com/envoyproxy/ai-gateway/pull/2155), [#1880](https://github.com/envoyproxy/ai-gateway/pull/1880).
- v0.7.0 release notes: https://aigateway.envoyproxy.io/release-notes/v0.7/
