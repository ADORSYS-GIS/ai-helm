# DNS-01 wildcard certs cannot be issued under `ai.camer.digital`

**Date:** 2026-07-31 · **Status:** Resolved (2026-08-23) — see [Resolution](#resolution-2026-08-23) below
**For:** @stephane-segning (owns `home-os` `charts/cert` and the DNS zones)
**Found by:** the Coder workspace-wildcard work (ADR-0083 follow-up)

## Resolution (2026-08-23)

**Option A was shipped**, not B or C: `home-os` [#138](https://github.com/whythatfunction/home-os/pull/138)/[#139](https://github.com/whythatfunction/home-os/pull/139) added a dedicated `cert-route53` ClusterIssuer (kept on its OWN issuer rather than a second solver bolted onto `cert-cloudflare`, after a related incident showed cert-manager validates every solver's `secretRef` when reconciling the *issuer* — a momentarily-missing Route53 credential would otherwise take the Cloudflare issuer's other ~20 certs down with it). It's enabled + ESO-credentialed (`route53-secret`) only for `cert-remote`/`home-remote`, covers `dnsZones: [ai.camer.digital, ai.kivoyo.com]`, and is verified `Ready=True` live.

But `traefik/ai-certificate` — the Certificate this whole audit is about — was **not** repointed at it. Investigating the reissue (home-os [#140](https://github.com/whythatfunction/home-os/pull/140)/[#141](https://github.com/whythatfunction/home-os/pull/141)) found it was dead config: none of its 5 SANs were ever actually requested by anything hitting `traefik/traefik-gateway`. Its only real consumer, knative-serving, serves hostnames under `mlops.camer.digital` — no `.ai`, not delegated, a zone the certificate never even listed. It was **deleted**, not reissued, and replaced by a correctly-scoped `serverless-gateway-certificate` (`*.mlops.camer.digital`, `cert-cloudflare`, no Route53 needed).

Separately, this document's own "nothing is broken *yet* — no workload consumes the secret" (below) held all the way through: the real per-app hostnames under the delegated zone (`mlflow.mlops.ai.camer.digital`, `lakefs.mlops.ai.camer.digital`, `argo-workflows.mlops.ai.camer.digital`, `coder.ai.camer.digital`) were never blocked by any of this — they're single-hostname HTTP-01 certs (`cert-home-cert-http`), unaffected by NS delegation, confirmed `Ready=True` live throughout.

Tracked via [ADORSYS-GIS/ai-helm#993](https://github.com/ADORSYS-GIS/ai-helm/issues/993) (closed 2026-08-27). Two follow-ups remain open:
- [#1050](https://github.com/ADORSYS-GIS/ai-helm/issues/1050) — the "Evidence this has recurred" cleanup below was a one-time pass on 2026-07-31; `ai-certificate` kept retrying for another 23 days after that (until its 2026-08-23 deletion), almost certainly regenerating the same orphaned TXT records. Not yet reconfirmed clean.
- [#1051](https://github.com/ADORSYS-GIS/ai-helm/issues/1051) — keeping `ai-helm/CLAUDE.md`'s cert-manager entry in sync with this resolution (done alongside this update).

The rest of this document is kept as-is: it's the accurate root-cause analysis and was the actual basis for the fix.

## TL;DR

`cert-cloudflare` is our only DNS-01 issuer, and it can only validate names in
zones **Cloudflare serves**. `ai.camer.digital` is NS-delegated to **AWS Route53**,
so every DNS-01 challenge for a name under it stalls forever. The
`traefik/ai-certificate` wildcard has been in this state for **9 days** and has
never once succeeded.

Nothing is broken *yet* — no workload consumes the secret. This is a fix-before-
someone-depends-on-it item, not an outage.

ai-helm has already routed around it for Coder (see "Precedent" below); this
document is about the remaining `traefik/ai-certificate` and the general fix.

## The stuck object

```
kubectl -n traefik get certificate ai-certificate
NAME             READY   SECRET                    AGE
ai-certificate   False   wildcard-ai-server-tls    9d
```

- Created **2026-07-22T12:17** — the same day `cloudflare-secret` was
  ESO-provisioned into `kube-system`. This looks like the DNS-01 rollout attempt,
  and it silently never completed.
- Owner: ArgoCD app **`traefik-remote`**
  (`argocd.argoproj.io/tracking-id: traefik-remote:cert-manager.io/Certificate:traefik/ai-certificate`).
  Not an ai-helm object — hence this handover.
- `issuerRef: cert-cloudflare` (ClusterIssuer)
- Secret `wildcard-ai-server-tls` **does not exist**, and no Ingress or
  IngressRoute in the cluster references it. Impact today is nil.

All five challenges have been `pending` since creation:

```
coder-ai.ai.camer.digital          :: Waiting for DNS-01 challenge propagation … not yet propagated
mlops.ai.camer.digital             :: Waiting for DNS-01 challenge propagation … not yet propagated
ai.camer.digital                   :: Waiting for DNS-01 challenge propagation … not yet propagated
serverless.mlops.ai.camer.digital  :: Waiting for DNS-01 challenge propagation … not yet propagated
```

## Root cause

`camer.digital` is a Cloudflare zone, but three subdomains are **delegated away**:

| Name | Authoritative NS |
|---|---|
| `camer.digital` | Cloudflare `lennox/virginia.ns.cloudflare.com` |
| `ai.camer.digital` | **AWS Route53** `ns-{409,556,1502,1914}.awsdns-*` |
| `coder-ai.camer.digital` | **AWS Route53** `ns-{157,976,1492,1562}.awsdns-*` |
| `observe.camer.digital` | Google Cloud DNS `ns-cloud-d*.googledomains.com` |

Every SAN on `ai-certificate` resolves its SOA to Route53:

```
ai.camer.digital                    zone-SOA=ns-1502.awsdns-59.org.
coder-ai.ai.camer.digital           zone-SOA=ns-1502.awsdns-59.org.
mlops.ai.camer.digital              zone-SOA=ns-1502.awsdns-59.org.
serverless.mlops.ai.camer.digital   zone-SOA=ns-1502.awsdns-59.org.
```

So the failure mode is:

1. cert-manager calls the Cloudflare API to create `_acme-challenge.<name>` — and
   it **succeeds**. The `Challenge` reports `Presented: true`.
2. The TXT record lands in the Cloudflare `camer.digital` zone, where it is
   **never served**: Route53 is authoritative for that subtree.
3. The self-check queries the real nameservers, sees nothing, and waits forever.

The trap is that step 1 succeeding makes everything *look* healthy. There is no
error anywhere — only a challenge that never leaves `pending`.

**Confirming a name before pointing DNS-01 at it:**

```bash
dig +short NS <parent-of-your-wildcard>
```

Anything other than Cloudflare nameservers ⇒ `cert-cloudflare` cannot issue for it.

### Evidence this has recurred

The Cloudflare `camer.digital` zone had accumulated **nine** orphaned
`_acme-challenge` TXT records from repeated attempts — for `ai`, `coder-ai`,
`coder-ai.ai`, `mlops` and `serverless.mlops`. I deleted them on 2026-07-31 after
verifying each name's SOA was non-Cloudflare (so all nine were inert). A backup of
their contents was taken; they will simply regenerate while `ai-certificate` keeps
retrying.

## Why this cannot be fixed in ai-helm

`home-os` `charts/cert` owns the ClusterIssuers, and it defines **only** a
Cloudflare DNS-01 solver (`charts/cert/templates/cluster-issuer.cloudflare.yaml`,
gated on `solvers.cloudflare`). There is no Route53 solver template and no
`cnameStrategy` knob. ai-helm only *references* issuers by name.

The obvious shortcut does not work either: the one AWS credential in-cluster
(`secret-store-system/awssm-secret`, IAM user `k8s-cluster-secret-manager`) is
**denied** Route53 —

```
AccessDenied … not authorized to perform: route53:ListHostedZones
```

— so it cannot be reused for a Route53 solver. A new credential is required.

## Options

### Option A — Route53 DNS-01 solver in `home-os` (most direct)

Add a `cert-route53` ClusterIssuer alongside the Cloudflare one. Fixes every name
under `ai.camer.digital` permanently and needs no DNS record changes.

1. Create an AWS IAM user/role with `route53:GetChange`,
   `route53:ChangeResourceRecordSets` and `route53:ListHostedZonesByName`, scoped
   to the `ai.camer.digital` hosted zone.
2. Put the credentials in `ssegning-aws` and surface them as a `route53-secret`
   in `kube-system` via the existing `cert-remote` ExternalSecret.
3. Add `charts/cert/templates/cluster-issuer.route53.yaml` mirroring the
   Cloudflare template, with `solvers.route53` in `values.yaml`:

```yaml
solvers:
  - dns01:
      route53:
        region: us-east-1
        hostedZoneID: <ai.camer.digital zone id>
        accessKeyIDSecretRef:  { name: route53-secret, key: access-key-id }
        secretAccessKeySecretRef: { name: route53-secret, key: secret-access-key }
```

4. Repoint `traefik/ai-certificate` at `cert-route53`.

**Cost:** a new IAM credential. **Benefit:** the only option that makes
`ai.camer.digital` a first-class DNS-01 domain.

### Option B — `_acme-challenge` CNAME delegation (no new credentials)

Keep using `cert-cloudflare` by delegating just the challenge records out of
Route53 and into the Cloudflare zone.

1. In the Route53 `ai.camer.digital` zone, one CNAME per name needing a cert:

```
_acme-challenge.ai.camer.digital.                  CNAME  _acme-challenge.ai.camer.digital.camer.digital.
_acme-challenge.mlops.ai.camer.digital.            CNAME  _acme-challenge.mlops.ai.camer.digital.camer.digital.
_acme-challenge.serverless.mlops.ai.camer.digital. CNAME  _acme-challenge.serverless.mlops.ai.camer.digital.camer.digital.
```

2. Set `cnameStrategy: Follow` on the Cloudflare solver in
   `charts/cert/templates/cluster-issuer.cloudflare.yaml`:

```yaml
solvers:
  - dns01:
      cnameStrategy: Follow
      cloudflare:
        email: …
        apiKeySecretRef: { name: cloudflare-secret, key: api-token }
```

**Cost:** a manual CNAME per certified name — easy to forget for the next one.
**Benefit:** no new credentials; `cnameStrategy: Follow` is harmless for names
already in Cloudflare, so it can be enabled globally.

### Option C — move the names to Cloudflare

Either remove the `ai.camer.digital` NS delegation so Cloudflare serves it (needs
an audit of everything already in the Route53 zone), or put new wildcards directly
under `camer.digital`. This is what ai-helm did for Coder — see below.

## Recommendation

**Option A** if `ai.camer.digital` is staying on Route53 long term — it is the only
one that stops this recurring, and it removes the per-name footgun. **Option B** is
a reasonable stopgap if provisioning an IAM credential is slow; enabling
`cnameStrategy: Follow` costs nothing and can ship ahead of the CNAMEs.

Whichever is chosen, `dig +short NS <parent>` should become a reflex before any
new DNS-01 `Certificate`.

## Precedent: how ai-helm worked around it

Coder needed a wildcard for public workspace URLs. Rather than wait on this, the
wildcard was moved to **`*.coder-ws.camer.digital`** — directly under the
Cloudflare-served apex — and issued in about 90 seconds with the existing
`cert-cloudflare` issuer. That is Option C, applied to one app.

The rationale and the trap are documented in
[`docs/integrations/coder-workspace-urls.md`](../integrations/coder-workspace-urls.md),
and the gotcha is recorded in ai-helm's `CLAUDE.md` cert-manager entry.

## Also worth a look: a possible typo

The SAN **`*.coder-ai.ai.camer.digital`** has `ai` twice. The delegated zone is
`coder-ai.camer.digital` (no `.ai.`), and Coder's own hostname is
`coder.ai.camer.digital`. `coder-ai.ai.camer.digital` does resolve — via the
Route53 wildcard, not a record of its own — so this may be unintended.

It is moot for Coder either way: workspace apps now live on
`*.coder-ws.camer.digital` and the dashboard host uses HTTP-01. If nothing else
needs it, **drop that SAN** rather than carry it through the fix.

## Verification once fixed

```bash
kubectl -n traefik get certificate ai-certificate          # READY=True
kubectl -n traefik get order,challenge                     # empty
kubectl -n traefik get secret wildcard-ai-server-tls \
  -o jsonpath='{.data.tls\.crt}' | base64 -d \
  | openssl x509 -noout -issuer -ext subjectAltName
```

If a challenge still reports `Presented: true` plus `not yet propagated`, the TXT
is still going to a provider that is not authoritative — re-read the root cause
above. Deleting and recreating the `Certificate` will not help.

Then clear the orphaned TXT records from the Cloudflare `camer.digital` zone; they
accumulate two per attempt.

## References

- [`docs/integrations/coder-workspace-urls.md`](../integrations/coder-workspace-urls.md) — the trap, and the Coder workaround
- `home-os` `charts/cert` — ClusterIssuer definitions (`cert` + `cert-remote` apps)
- ADR-0083 — Coder re-introduction
- [cert-manager: ACME DNS-01](https://cert-manager.io/docs/configuration/acme/dns01/) — `cnameStrategy`, Route53 and Cloudflare solver reference
