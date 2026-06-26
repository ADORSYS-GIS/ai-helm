# ADR-0065: Deploy SonarQube Community Build + community-branch-plugin for free inline PR decoration

**Status:** Proposed
**Date:** 2026-06-27
**Deciders:** @stephane-segning

## Context

We want a self-hosted SonarQube for code-quality gates with **inline pull-request
decoration** (check-runs + line-level comments) driven by a **custom GitHub App**,
running as a workload on `home-remote`. Two constraints collide:

- **Cost.** Native branch & PR analysis is the headline paywall of **SonarQube
  Server** (Developer Edition+, paid). The free **SonarQube Community Build** does
  **single-branch analysis only** — it rejects `sonar.pullrequest.*` scanner
  parameters outright.
- **Inline decoration is a hard requirement** (not just a pass/fail check), so the
  cheaper "stock server + runner posts a project-level quality-gate check" model is
  out.

Version reality (researched 2026-06): since **24.12** the two product lines are
**deliberately unaligned with no mapping** — Community Build uses calendar
versioning `YY.M.0.build` (latest `26.6.0.123539`, monthly cadence), Server uses
`2026.x` LTA-style. The official `sonarqube` Helm chart (latest `2026.3.1`) tracks
the **Server** image by default. Inline PR analysis on the *free* build is only
possible via the third-party **`mc1arke/sonarqube-community-branch-plugin`**, whose
`major.minor` must match the Community Build version (plugin `26.5.0` ↔ SonarQube
`26.5.x`) and which **trails the monthly Community Build train by ~a release**.

CI runners are **in-cluster self-hosted** (like `opencode-k8s-agent`), and we already
mint GitHub App installation tokens in CI via `lightbridge-repo-auth` (GHA OIDC →
Authorino). The platform IdP is Keycloak (`accounts.camer.digital`).

## Decision

**Run SonarQube Community Build (free) with the `community-branch-plugin` for inline
PR decoration**, deployed as an App-of-Apps orchestrator mirroring `lightbridge`
(ADR-0019/0026). Specifically:

- **Edition:** Community Build, **not** Server. Use the upstream SonarSource `sonarqube`
  chart (`2026.3.x`, templating only) but **override `image` to a `…-community` tag** —
  the chart's default `appVersion` is the paid Server line.
- **Inline decoration:** install `community-branch-plugin` via the chart's
  `plugins.install` init-container (downloads the jar into the plugins volume — **no
  custom image**, consistent with the repo rule), and wire its `-javaagent` opts into
  the web + CE processes (`SONAR_WEB_JAVAADDITIONALOPTS` / `SONAR_CE_JAVAADDITIONALOPTS`).
- **Version lockstep:** pin Community Build ↔ plugin at matching `major.minor`
  (start at **`26.5.0.x` ↔ `26.5.0`**, both confirmed to exist) and **exclude
  SonarQube from argocd-image-updater auto-bump** — bump the pair deliberately, in
  lockstep, only after the matching plugin release lands. A mismatched pair fails to
  start under the agent.
- **GitHub App on the server:** the custom GitHub App is configured as SonarQube's
  DevOps-Platform (ALM) integration; the server posts the decoration. Credentials
  (App ID + private-key PEM) land via an in-chart ExternalSecret; the server gets a
  Cilium egress allow to `api.github.com:443`.
- **Scanners:** in-cluster runners run `sonar-scanner` with `sonar.pullrequest.*`
  params + `SONAR_TOKEN` + `SONAR_HOST_URL` over the **cluster-internal** Service
  (no public scanner endpoint). The server does the decoration.
- **UI SSO:** native **SAML** against Keycloak (`sonar.auth.saml.*` + a Keycloak SAML
  client in `charts/keycloak-baseline`) — not the third-party OIDC plugin. Local admin
  for bootstrap.
- **Database:** a CNPG `Cluster` (`charts/sonarqube-db`, copy of `lightbridge-db`) with
  Barman backups to Hetzner Object Storage; the bundled bitnami Postgres is disabled
  (`postgresql.enabled: false` + `jdbcOverwrite`).
- **Layout:** orchestrator `charts/sonarqube` (controlPlane) → `sonarqube-secrets`
  (wave 0) + `sonarqube-db` (wave 1) + the upstream chart as the app child (wave 2);
  children target `home-remote`. Per ADR-0055/0056, workload values + the deps overlay
  (Certificate `sonarqube.camer.digital` + CiliumNetworkPolicy) live in `ai-helm-values`.

## Consequences

**Positive**
- Inline, line-level PR decoration with true PR-scoped (new-code) analysis, at **$0
  license cost**.
- Reuses every established pattern: CNPG + Barman, App-of-Apps split, ESO secrets,
  Keycloak SSO, deps-overlay cert + Cilium. Low novelty.
- No custom image — the plugin and SAML are off-the-shelf jar installs.

**Negative**
- **SonarQube becomes a manually-bumped, version-coupled app**, not a float-from-OCI
  one: Community Build ↔ plugin lockstep, excluded from image-updater. Monthly upgrades
  are a deliberate two-value bump gated on the plugin's (lagging) release.
- The plugin **re-enables a feature Sonar gates commercially** — a ToS grey area the
  maintainer accepts knowingly.
- The server now has **outbound GitHub egress** + holds the GitHub App private key —
  a wider blast radius than a stock, egress-free server would have.
- Embedded Elasticsearch needs `vm.max_map_count ≥ 524288`; the chart's `initSysctl`
  runs privileged, which k3s `baseline` PSS blocks (see follow-ups).

**Neutral / follow-ups**
- Prefer setting `vm.max_map_count` as a **node sysctl in `hetzner-k8s`** over labelling
  the `sonarqube` namespace `privileged` (`global.namespacePodSecurity`) — keeps the app
  namespace unprivileged.
- Out-of-band, **secret-first / values-repo-first**: register + install the GitHub App;
  add `github_app_id`, `github_app_private_key`, `sonarqube_db_password`,
  `sonarqube_monitoring_passcode` to `ssegning-aws`; land `environments/prod/{values,deps}/
  sonarqube` on `ai-helm-values` `main` — all **before** the `charts/apps` entry merges,
  or ExternalSecrets sit in `SecretSyncedError` / `ignoreMissingValueFiles` falls back to
  defaults.
- If the lockstep maintenance proves too costly, the exit is **Developer Edition** (paid,
  native) — write a superseding ADR.

## Alternatives considered

- **SonarQube Developer Edition (paid).** Native PR decoration, no plugin, no
  version-coupling, no grey area. Rejected: license cost; the free path meets the
  requirement.
- **Stock Community Build + runner-posted project-level quality-gate check** (no plugin;
  runner reads `qualitygates/project_status` and posts a check via the GH App token it
  already holds). Architecturally cleaner — stock server floats from OCI, no GitHub
  egress, no lockstep — but yields only a **project-level pass/fail check, not inline
  diff decoration**, and analysis is whole-project not PR-scoped. Rejected: inline
  decoration is a hard requirement.
- **Native SonarQube OIDC plugin for SSO** instead of SAML. Rejected: SAML is built into
  Community Build and Keycloak speaks it natively — fewer jars, one less third-party
  coupling.
- **Single monolithic chart** (app + bundled Postgres). Rejected: the bundled bitnami
  Postgres has no Barman backups/HA, and the repo standard is CNPG + the App-of-Apps
  lifecycle split (DB / secrets / app sync and roll back independently).

## Related

- Docs: `docs/sonarqube.md` (the *how* — to be written), `CLAUDE.md` (sysctl +
  version-lockstep gotchas).
- Charts/files touched: `charts/sonarqube`, `charts/sonarqube-db`,
  `charts/sonarqube-secrets`, `charts/apps/values.yaml`, `charts/keycloak-baseline/values.yaml`.
- Cross-repo: `ai-helm-values` (`environments/prod/{values,deps}/sonarqube`),
  `hetzner-k8s` (node `vm.max_map_count` sysctl).
- Builds on: [0017](./0017-home-remote-destination-invariant.md),
  [0018](./0018-umbrella-apps-and-env-overlays.md),
  [0026](./0026-lightbridge-orchestrator-split.md),
  [0055](./0055-oci-charts-and-image-updater-writeback-to-values-repo.md),
  [0056](./0056-workload-values-in-ai-helm-values.md).
</content>
</invoke>
