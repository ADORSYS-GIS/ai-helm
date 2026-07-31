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

## Verification

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
