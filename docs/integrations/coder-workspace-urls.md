# Public workspace URLs in Coder (wildcard subdomain apps)

**Status:** Implemented · **Last updated:** 2026-07-31

Coder workspaces are reachable from the public internet on wildcard subdomains,
so an app a developer runs inside a workspace (a Vite dev server, a notebook, an
API) gets a real HTTPS URL without any port-forwarding.

```
https://<port>--<agent>--<workspace>--<user>.coder-ws.camer.digital
```

e.g. a Vite dev server on port 5173 in workspace `demo` owned by `koufan`:
`https://5173--main--demo--koufan.coder-ws.camer.digital`.

The `--` separator and the field order are Coder's own, built in
`coderd/workspaceapps/appurl/appurl.go`. Both DNS and TLS wildcards match exactly
**one** label, so Coder flattens all four identifiers into a single label — that
is what lets one `*.coder-ws.camer.digital` certificate cover every app, in every
workspace, for every user. Notes:

- The `<agent>` segment appears only on raw port-forward URLs. A declared app
  (`subdomain = true` on the template's `coder_app`) is
  `<app-slug>--<workspace>--<user>`.
- An app speaking TLS inside the workspace gets an `s` after the port: `8080s--…`.

> ⚠️ **A DNS label is capped at 63 characters, and the whole
> `port--agent--workspace--user` string is one label.** Exceed it and dashboard
> port-forwarding silently fails for that workspace while everything else looks
> fine. Keep username + workspace name + app slug under ~50 characters combined.
> Current workspaces sit around 45, so there is headroom — but a long username
> plus a long workspace name will find this edge.

Path-based workspace apps are **disabled** (`CODER_DISABLE_PATH_APPS=true`), so
the wildcard is the *only* way to reach a workspace app. If the wildcard cert is
broken, workspace apps are unreachable — there is no fallback.

---

## Finding the public URL of a workspace app

There are two kinds of workspace app and they are addressed differently. Work out
which one you have first — a **declared app** is a `coder_app` resource in the
template; a **raw port** is anything a user just started inside the workspace
(`next dev`, `vite`, `python -m http.server`).

Everything below uses the CLI (`coder login https://coder.ai.camer.digital`) and
its session token for API calls:

```bash
TOKEN=$(cat ~/.config/coderv2/session)
CODER_URL=https://coder.ai.camer.digital
```

> ⚠️ **A reachable URL is not an accessible one.** Both kinds of app default to
> share level `owner` — the URL resolves and serves TLS, but returns **HTTP 303**
> to `/api/v2/applications/auth-redirect` for anyone who is not the owner. A `303`
> means routing is fine and you have an *authorization* question, not a DNS or
> certificate question. Don't go debugging the wildcard.

### Step 1 — identify workspace, owner and agent

```bash
coder list                       # OWNER/WORKSPACE, e.g. kingkoufan/K-workspace
coder show <workspace>           # agent name is the tree node under the resource,
                                 # e.g. "main" in `coder ssh K-workspace.main`
```

The agent name is almost always `main`, but templates can name it anything, and
it is part of the hostname for raw ports — don't assume.

If the CLI is unavailable, the same three facts are on the workspace pod as
labels (needs cluster access, `home-remote`):

```bash
kubectl -n coder get pods \
  -L com.coder.workspace.name,com.coder.user.username,com.coder.agent.name
```

### Step 2a — declared apps: ask the API, don't build the string

For a `coder_app`, Coder computes the hostname itself and exposes it as
`subdomain_name`. **Read that field** rather than assembling it by hand — it
already accounts for the optional agent segment and any prefix.

```bash
WSID=$(curl -sS -H "Coder-Session-Token: $TOKEN" \
  "$CODER_URL/api/v2/users/me/workspace/<workspace>" | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')

curl -sS -H "Coder-Session-Token: $TOKEN" "$CODER_URL/api/v2/workspaces/$WSID" \
| python3 -c '
import sys,json
for r in json.load(sys.stdin)["latest_build"]["resources"]:
    for a in r.get("agents") or []:
        for app in a.get("apps") or []:
            print(f"{app[\"slug\"]:20} subdomain={app.get(\"subdomain\")} "
                  f"share={app.get(\"sharing_level\")} host={app.get(\"subdomain_name\")}")'
```

- `subdomain=True` → the public URL is `https://<subdomain_name>.coder-ws.camer.digital`.
- `subdomain=False` → **the app has no public URL on this deployment.** It is
  path-based, and path apps are disabled here. See the trap below.

### Step 2b — raw ports: build the hostname

Nothing to look up; construct it from step 1:

```
https://<port>--<agent>--<workspace>--<user>.coder-ws.camer.digital
```

A Next.js dev server on port 3000, agent `main`, workspace `K-workspace`, user
`kingkoufan`:

```
https://3000--main--K-workspace--kingkoufan.coder-ws.camer.digital
```

Hostnames are case-insensitive, so the workspace name's capitalisation does not
matter. If the app inside the workspace speaks TLS, use `3000s--…`.

### Step 3 — set the share level

**Declared apps** — set it in the template, then push:

```hcl
resource "coder_app" "my_app" {
  subdomain = true               # required; without it there is no public URL
  share     = "authenticated"    # owner | authenticated | organization | public
  # ...
}
```

**Raw ports** — see the dedicated runbook in the next section.

Share levels: `owner` (default) · `authenticated` (any Coder user on this
deployment) · `organization` · `public` (no auth at all).

---

## Runbook: publishing a dev server publicly, and taking it down

This is the common case — someone runs `next dev` / `vite` / `python -m http.server`
inside a workspace and wants to hand a colleague or a client a link. The port is
reachable the moment the process binds, but it is `owner`-only until you share it.

There is **no CLI subcommand** for this. `coder port-forward` is *local* forwarding
to your own machine, and `coder sharing` shares the whole workspace with named
users — neither publishes a port. Use the dashboard's **Open Ports** panel, or the
API below.

> ⚠️ The route is **singular**: `/port-share`. The plural `/port-shares` returns
> `404 Route not found`, which reads like the feature is missing or unlicensed. It
> is neither — it is a typo.

### Setup

```bash
TOKEN=$(cat ~/.config/coderv2/session)
CODER_URL=https://coder.ai.camer.digital
WSID=$(curl -sS -H "Coder-Session-Token: $TOKEN" \
  "$CODER_URL/api/v2/users/me/workspace/<workspace>" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
```

### Publish

```bash
curl -sS -X POST -H "Coder-Session-Token: $TOKEN" -H "Content-Type: application/json" \
  -d '{"agent_name":"main","port":3000,"share_level":"public","protocol":"http"}' \
  "$CODER_URL/api/v2/workspaces/$WSID/port-share"
```

`protocol` is how Coder should talk to your process **inside** the workspace —
`http` for a normal dev server. Use `https` only if the process itself terminates
TLS (that also changes the hostname to `3000s--…`). Public HTTPS is terminated at
the ingress either way.

Swap `"public"` for `"authenticated"` to require a Coder login instead — a good
default for sharing with colleagues, since it needs no extra work from them and
leaves nothing exposed to the open internet.

### List what is currently shared

```bash
curl -sS -H "Coder-Session-Token: $TOKEN" \
  "$CODER_URL/api/v2/workspaces/$WSID/port-share"
# {"shares":[{"agent_name":"main","port":3000,"share_level":"public",...}]}
```

### Revoke

```bash
curl -sS -X DELETE -H "Coder-Session-Token: $TOKEN" -H "Content-Type: application/json" \
  -d '{"agent_name":"main","port":3000}' \
  "$CODER_URL/api/v2/workspaces/$WSID/port-share"
```

The DELETE body takes only `agent_name` and `port` — no `share_level`. It returns
`200` with an empty body, and takes effect **immediately**: the URL flips from
`200` back to `303 → auth-redirect` on the very next request. Confirm it:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' \
  https://3000--main--<workspace>--<user>.coder-ws.camer.digital/
# 303 = revoked   200 = still public
```

### What "public" actually means here

Be deliberate about this — the exposure is larger than it looks:

- **No authentication at all.** Anyone with the URL reaches the dev server. The
  hostname is guessable (`<port>--<agent>--<workspace>--<username>`), and it appears
  in Certificate Transparency logs only as the wildcard, but the username and
  workspace name are often easy to infer.
- **It is a dev server.** Framework dev servers run with verbose errors, source
  maps, hot-reload websockets and no rate limiting, and frequently hold API keys
  from the workspace's environment. They are not written to face the internet.
- **Shares survive.** A share persists across workspace stop/start and is not
  time-bounded — it stays until explicitly revoked. Revoke when the demo ends
  rather than leaving it up; there is nothing that will clean it up for you.
- **Nothing centrally caps this.** On OSS the enterprise `control_shared_ports`
  restriction is unavailable, so any user can publish any of their own ports at
  `public` and no template setting or admin policy prevents it. Treat this as a
  convention to be socialised, not a control that is enforced.

### Licensing: public sharing works on OSS

We run **unlicensed OSS** (`/api/v2/entitlements` → `has_license: false`), and
`share_level: "public"` still works — verified live. The
`control_shared_ports: not_entitled` entry in the entitlements response is easy to
misread: it does **not** gate sharing. It gates the *enterprise* ability to cap the
maximum share level a template may allow. On OSS every level is available and
nothing can be centrally restricted — worth knowing before telling people to share
ports freely.

---

## Verifying and troubleshooting an app URL

```bash
curl -sS -o /dev/null -w 'http=%{http_code} ssl_verify=%{ssl_verify_result}\n' \
  https://3000--main--K-workspace--kingkoufan.coder-ws.camer.digital/
```

| Result | Meaning |
|---|---|
| `200`, `ssl_verify=0` | Public and working |
| `303` → `auth-redirect` | Routing + TLS fine; share level is `owner`/`authenticated` |
| `403` | Path-based app on a deployment with `CODER_DISABLE_PATH_APPS=true` |
| `TRAEFIK DEFAULT CERT` | The wildcard cert is broken — see the zone section below |
| DNS `NXDOMAIN` | The wildcard `A` record is missing |

### ⚠️ Declared apps must set `subdomain = true`

Because `CODER_DISABLE_PATH_APPS=true`, a `coder_app` with `subdomain = false`
(the Terraform default) is **unreachable** — it returns `403`, with no hint that
the cause is a deployment-level setting rather than the app itself.

The stock `kubernetes` template's `code-server` app ships with `subdomain = false`
and is currently in exactly this state. Any template carrying a declared app needs
`subdomain = true` before its apps work here. Audit them with the step-2a snippet:
anything reporting `subdomain=False` is already broken or will be as soon as
someone tries to open it.

---

## ⚠️ Why workspaces live on `camer.digital`, not under `coder.ai.camer.digital`

This is the single non-obvious thing about this setup, and it has cost real
debugging time more than once. **Do not "tidy" the workspace wildcard back under
the dashboard domain.**

A wildcard certificate can only be issued via an **ACME DNS-01** challenge
(HTTP-01 cannot do wildcards). Our only DNS-01 solver is the `cert-cloudflare`
ClusterIssuer (`home-os` `charts/cert`), which authenticates against the
Cloudflare API. It can therefore only satisfy a challenge for a name in a zone
**Cloudflare actually serves**.

`camer.digital` is on Cloudflare — but several subdomains are **NS-delegated
away** to other providers:

| Name | Authoritative NS |
|---|---|
| `camer.digital` | Cloudflare (`*.ns.cloudflare.com`) |
| `ai.camer.digital` | **AWS Route53** (`ns-{409,556,1502,1914}.awsdns-*`) |
| `coder-ai.camer.digital` | **AWS Route53** (`ns-{157,976,1492,1562}.awsdns-*`) |
| `observe.camer.digital` | Google Cloud DNS (`ns-cloud-d*.googledomains.com`) |

So a `Certificate` for `*.coder.ai.camer.digital` on `cert-cloudflare` fails in a
way that looks like nothing is wrong:

1. cert-manager creates the `_acme-challenge` TXT record via the Cloudflare API —
   it succeeds, and the `Challenge` reports `Presented: true`.
2. The record lands in the Cloudflare `camer.digital` zone, where it is **never
   served** — Route53 is authoritative for `ai.camer.digital`.
3. The self-check never passes. The `Challenge` sits at
   `Waiting for DNS-01 challenge propagation: DNS record for "…" not yet propagated`
   until Let's Encrypt expires the order.

The dashboard hostname `coder.ai.camer.digital` is unaffected because it uses
**HTTP-01** (`cert-home-cert-http`), which validates over the load balancer and
does not care who serves DNS.

**Diagnostic tell:** orphaned `_acme-challenge.*` TXT records accumulating in the
Cloudflare `camer.digital` zone for delegated names. As of this writing the zone
still holds abandoned ones for `ai`, `coder-ai`, `coder-ai.ai`, `mlops`, and
`serverless.mlops` — every past attempt to DNS-01 a delegated name.

Confirm a name's zone before pointing a DNS-01 `Certificate` at it:

```bash
dig +short NS <the-parent-of-your-wildcard>
```

If that returns anything other than Cloudflare nameservers, `cert-cloudflare`
cannot issue for it.

### Secondary benefit

Putting workspace apps on a sibling domain rather than a subdomain of the
dashboard is also Coder's own recommendation: a compromised or hostile workspace
app cannot set or read cookies scoped to `coder.ai.camer.digital`.

### If we ever do need the wildcard under `ai.camer.digital`

Two options, both requiring a `home-os` change (that repo owns the issuers):

- **Route53 DNS-01 ClusterIssuer** — add a `route53` solver to `charts/cert` plus
  an AWS IAM credential with `route53:ChangeResourceRecordSets` on the zone. Note
  the existing in-cluster AWS user (`k8s-cluster-secret-manager`, the ESO
  credential) is **denied** Route53 — it is not reusable for this.
- **CNAME delegation** — add a CNAME in Route53 for
  `_acme-challenge.<name>.ai.camer.digital` pointing at a name inside the
  Cloudflare `camer.digital` zone, and set `cnameStrategy: Follow` on the
  `cert-cloudflare` solver. This would fix `mlops` the same way.

---

## Where each piece lives

| Piece | Repo / path |
|---|---|
| `CODER_WILDCARD_ACCESS_URL`, `CODER_DISABLE_PATH_APPS`, `ingress.wildcardHost`, `ingress.tls.wildcardSecretName` | `ai-helm-values` `environments/prod/values/coder-app.yaml` |
| `coder-wildcard-tls` `Certificate` (dnsNames) | `ai-helm-values` `environments/base/deps/coder/certificates.yaml` |
| Issuer patch → `cert-cloudflare` | `ai-helm-values` `environments/prod/deps/coder/kustomization.yaml` |
| CI reference copy (keep structurally in sync) | `ai-helm` `charts/coder/ci/coder-app.yaml` |
| `cert-cloudflare` ClusterIssuer + `cloudflare-secret` | `home-os` `charts/cert` (app `cert-remote`) |
| Wildcard DNS `A` record | Cloudflare `camer.digital` zone (out-of-band) |

Per ADR-0055/0056 the values live in `ai-helm-values`; `ai-helm` holds only the
chart logic and the CI reference. Cut over **values-repo-first**.

## DNS record required

One record in the Cloudflare `camer.digital` zone, DNS-only (not proxied),
matching the other platform records:

```
*.coder-ws.camer.digital   A   46.225.40.134   (proxied: false)
```

`46.225.40.134` is the Traefik ingress LB. Proxying must stay **off** —
Cloudflare's proxy would terminate TLS in front of us and interfere with the
WebSocket-heavy workspace app traffic.

## Verification (platform side: cert, DNS, ingress)

For verifying a *single app URL* see "Verifying and troubleshooting an app URL"
above; this section is for the platform plumbing.

```bash
# 1. wildcard cert issued
kubectl -n coder get certificate coder-wildcard-tls
kubectl -n coder get order,challenge          # empty once issued

# 2. the SANs are right
kubectl -n coder get secret coder-wildcard-tls -o jsonpath='{.data.tls\.crt}' \
  | base64 -d | openssl x509 -noout -subject -ext subjectAltName

# 3. Traefik serves it (not "TRAEFIK DEFAULT CERT")
echo | openssl s_client -connect 46.225.40.134:443 \
  -servername 5173--main--demo--koufan.coder-ws.camer.digital 2>/dev/null \
  | openssl x509 -noout -subject -issuer

# 4. coderd picked up the env
kubectl -n coder get deploy coder \
  -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="CODER_WILDCARD_ACCESS_URL")]}'
```

Then create a workspace and open a workspace app from the Coder UI — the URL in
the address bar should be a `coder-ws.camer.digital` subdomain with a valid
Let's Encrypt certificate.

### If the challenge stalls

```bash
kubectl -n coder describe challenge
```

`Presented: true` + `not yet propagated` means the TXT went to a provider that is
not authoritative — re-read the zone-delegation section above. Deleting and
recreating the `Certificate` will not help.

## Rollback

Re-enable path-based apps (workspace apps then live under the dashboard host and
need no wildcard cert):

1. Drop `CODER_WILDCARD_ACCESS_URL` and set `CODER_DISABLE_PATH_APPS=false` (or
   remove it) in `environments/prod/values/coder-app.yaml`.
2. Remove `ingress.wildcardHost` and `ingress.tls.wildcardSecretName`.
3. Remove the `coder-wildcard-tls` Certificate from
   `environments/base/deps/coder/certificates.yaml` and its issuer patch from the
   prod kustomization.

Path-based apps are a weaker security posture (workspace apps share the dashboard
origin), which is why subdomain apps are the default here.

## References

- ADR-0019 — App-of-Apps orchestrator pattern (`charts/coder`)
- ADR-0083 — Coder re-introduction
- [`coder-platform-integration.md`](coder-platform-integration.md) — the wider Coder integration
- [Coder docs: wildcard access URL](https://coder.com/docs/admin/setup#wildcard-access-url)
