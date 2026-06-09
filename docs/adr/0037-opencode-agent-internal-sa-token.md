# ADR-0037: opencode-k8s-agent authenticates via the internal plane + its own SA token

**Status:** Accepted
**Date:** 2026-06-09
**Deciders:** @stephane-segning

## Context

`opencode-k8s-agent` (the 12-hourly AI cluster-health CronJob) reached the model
gateway over the **external** plane (`api.ai.camer.digital/v1`) and authenticated
with a **Keycloak `client_credentials`** flow — the `@vymalo/opencode-oauth2`
opencode plugin, fed by `OAUTH2_*` env + a `KEYCLOAK_CLIENT_SECRET` in the
`opencode-k8s-agent-secret`. That tied an in-cluster job to a Keycloak client +
secret it had no need for: ADR-0021 already defines an **internal plane**
(`api-internal` listener, `core-gateway-internal` ClusterIP) for in-cluster
callers, with two credentials by lifecycle — long-running services use a static
apiKey (LibreChat), **one-time jobs use their projected k8s SA token**
(`kubernetesTokenReview`, audience `core-gateway-internal`). The agent is a
CronJob — the SA-token path fits exactly and needs no secret at all.

## Decision

Move the agent onto the **internal plane**, authenticated by the CronJob's **own
projected ServiceAccount token** — no Keycloak, no apiKey secret:

- **Transport = LibreChat's** (ADR-0021): `OPENCODE_BASE_URL` →
  `https://core-gateway-internal.envoy-gateway-system.svc.cluster.local/v1`, with
  the internal CA trusted via `NODE_EXTRA_CA_CERTS=/etc/internal-ca/ca.crt`
  (a `self-signed-ca` Certificate's `ca.crt`, from a new deps overlay
  `environments/{base,prod}/deps/opencode-k8s-agent`).
- **Credential = the SA token** (differs from LibreChat, which is long-running and
  uses a static apiKey): a **projected `serviceAccountToken` volume** (audience
  `core-gateway-internal`, app-template `type: custom`) mounted at
  `/var/run/secrets/gateway-token/token`. The container `command` is overridden to
  `export OPENCODE_API_KEY="$(cat …/token)"; exec /bin/bash /config/run.sh`, so the
  upstream `run.sh` `envsubst`s the token into `opencode.json` as the Bearer.
- **opencode.json** drops the `@vymalo/opencode-oauth2` plugin for a static
  `apiKey: "${OPENCODE_API_KEY}"` — done in the agent repo
  ([ADORSYS-GIS/opencode-k8s-agent#6](https://github.com/ADORSYS-GIS/opencode-k8s-agent/pull/6),
  pinned by SHA) because the chart's `configMaps.runtime` override is all-or-nothing
  (overriding one file would drop the bundled `run.sh`/`prompt.md`).
- The internal AuthConfig stamps the SA identity → `x-billing-plan: "internal"`
  (uncapped tier); `x-account-id` = the SA username.
- `opencode-k8s-agent-secret` (ESO) now needs **only `APPRISE_URLS`** (notification
  channels); `OPENCODE_API_KEY` + `KEYCLOAK_CLIENT_SECRET` are gone.

## Consequences

**Positive**

- No Keycloak client/secret and no apiKey secret for the agent — the credential is
  the cluster-issued, short-lived (1h), auto-expiring SA token. Exactly ADR-0021's
  one-time-job design.
- One fewer secret property to provision; the remaining `opencode-k8s-agent-secret`
  is notification-only.
- The agent leaves the public LB path; its model traffic stays in-cluster.

**Negative**

- The agent now depends on the internal gateway listener + the internal CA being
  present (they are — LibreChat uses the same). A new `self-signed-ca` Certificate
  runs in `monitoring`.
- The opencode.json fix lives on an unmerged PR branch SHA; a **squash-merge will
  orphan that SHA** — re-pin `charts/apps/values.yaml` `targetRevision` to the
  merge commit once #6 lands.

**Neutral / follow-ups**

- Verify on deploy that `monitoring` → `envoy-gateway-system` (the internal
  gateway ClusterIP) is reachable; if a Cilium baseline blocks it, add a
  `CiliumNetworkPolicy` to the deps overlay (as alloy/eg do).
- Still requires `APPRISE_URLS` in the secret for the report to be delivered
  (apprise-api kept lean, ADR-0036).

## Alternatives considered

- **Static internal apiKey (literal "like LibreChat")** — workable, but adds an
  apiKey secret (gateway-side + consumer-side) to manage; the SA token removes the
  secret entirely and is the ADR-0021 mechanism for Jobs. Rejected for the agent.
- **Keep the external plane + Keycloak** — rejected: couples an in-cluster job to a
  Keycloak client/secret the internal plane makes unnecessary.
- **Override opencode.json from ai-helm** — rejected: the chart's `configMaps`
  override is all-or-nothing, so it would mean vendoring `run.sh`/`prompt.md` into
  `charts/apps/values.yaml` (drift). The agent-repo PR is cleaner.

## Related

- Builds on: [ADR-0021](./0021-burst-budget-billing-and-dual-plane-authconfigs.md)
  (internal plane, SA-token path), [ADR-0018](./0018-umbrella-apps-and-env-overlays.md)
  (deps overlay); relates to [ADR-0036](./0036-remove-apprise-notification-path.md).
- PR: [ADORSYS-GIS/opencode-k8s-agent#6](https://github.com/ADORSYS-GIS/opencode-k8s-agent/pull/6) (static bearer).
- Files: `charts/apps/values.yaml` (opencode-k8s-agent app),
  `environments/{base,prod}/deps/opencode-k8s-agent/`.
</content>
