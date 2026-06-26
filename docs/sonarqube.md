# SonarQube (Community Build) — deployment & runbook

The *why* is [ADR-0065](adr/0065-sonarqube-community-build-with-branch-plugin.md);
this is the *how*. SonarQube runs on `home-remote` in the `sonarqube` namespace as
an App-of-Apps orchestrator mirroring `lightbridge` (ADR-0019/0026).

## Shape

```
charts/sonarqube/          orchestrator (controlPlane) → 3 child Applications:
  ├─ sonarqube-secrets     wave 0 — ExternalSecrets (S3 backup, GitHub App, monitoring passcode)
  ├─ sonarqube-db          wave 1 — CNPG Cluster `sonarqube-db` + barman + ScheduledBackup + Database
  └─ sonarqube-app         wave 2 — upstream SonarSource chart (Community Build image + branch-plugin)
```

- **ai-helm** owns the chart logic (`charts/sonarqube*`), the `charts/apps`
  `sonarqube` entry (`controlPlane: true`, `chart: sonarqube`), and the Keycloak
  SAML client (`charts/keycloak-baseline`, client `sonarqube`).
- **ai-helm-values** (private) owns the workload values
  (`environments/prod/values/sonarqube-app.yaml`) and the deps overlay
  (`environments/prod/deps/sonarqube/` — ingress Certificate + the
  CiliumNetworkPolicies). **Values-repo-first.**

## The version contract (read this before any upgrade)

SonarQube here is **NOT** a float-from-OCI workload. Free **Community Build**
can't do inline PR decoration, so we add the third-party
[`community-branch-plugin`](https://github.com/mc1arke/sonarqube-community-branch-plugin),
whose `major.minor` **must match** the Community Build version and which **lags
the monthly Community Build train**. Therefore:

- Pinned pair today: **Community Build `26.5.0.122743` ↔ plugin `26.5.0`**
  (`community.buildNumber` + the `plugins.install` jar + the two `-javaagent`
  `env` filenames in `sonarqube-app.yaml`).
- **Bump all three together**, only after a matching plugin release exists.
- SonarQube is **excluded from argocd-image-updater** — never let it auto-bump
  ahead of the plugin (mismatch ⇒ the web/CE JVM fails to start under the agent).
- The chart's default image is the **paid Server** line; `community.enabled: true`
  + `community.buildNumber` selects the free `…-community` image.

## Out-of-band prerequisites (do these BEFORE merging)

1. **GitHub App** — register a custom GitHub App (org-installed) with the
   permissions for checks/PR decoration; note the **App ID** and download the
   **private key (PEM)**.
2. **Secrets in `ssegning-aws`** (secret-first — else ExternalSecrets sit in
   `SecretSyncedError`):
   - `ai/camer/digital/prod/env`: `sonarqube_db_password`,
     `sonarqube_github_app_id`, `sonarqube_github_app_private_key`,
     `sonarqube_monitoring_passcode`.
   - `prod/meta/test-app`: reuses the shared `s3_backup_cnpg_client_id` /
     `s3_backup_cnpg_secret` (no new property).
3. **Node sysctl** — set `vm.max_map_count=524288` on the Hetzner workers
   (hetzner-k8s). The chart's privileged `initSysctl` is **disabled**
   (`initSysctl.enabled: false`) to stay within k3s `baseline` PSS, so embedded
   Elasticsearch needs the sysctl at node level or it fails its bootstrap check.
   *Fallback:* re-enable `initSysctl` + label the `sonarqube` namespace
   `privileged` via `charts/apps` `global.namespacePodSecurity`.
4. **Realm SAML cert** — fill `sonar.auth.saml.certificate.secured` in
   `sonarqube-app.yaml` from the camer-digital realm SAML descriptor:
   `https://accounts.camer.digital/realms/camer-digital/protocol/saml/descriptor`.
5. **ai-helm-values first** — merge `environments/prod/{values,deps}/sonarqube*`
   to `ai-helm-values` `main` **before** the ai-helm `charts/apps` entry merges.

## Merge order

1. `ai-helm-values`: add the values file + deps overlay → merge to `main`.
2. `ai-helm`: merge the charts + `charts/apps` entry → OCI publish → ArgoCD syncs
   `aii-sonarqube` (the orchestrator) → its 3 children sync by wave.

## Post-deploy (one-time)

- **GitHub App binding** — Administration → DevOps Platform Integrations →
  **GitHub**: create a configuration with the App ID + private key (the
  `sonarqube-github` Secret holds them) and bind each project to its repo. This
  is runtime config (the `/api/alm_settings` API), **not** a chart value. The
  branch-plugin uses this ALM config to decorate PRs.
- **SAML login** — verify a round-trip via the Keycloak `sonarqube` SAML client.
  The SAML attribute names (`login`/`name`/`email`/`groups`) are a contract
  between the Keycloak client's protocolMappers (`charts/keycloak-baseline`) and
  the `sonar.auth.saml.user.*` / `.group.name` properties — keep them in sync.

## CI integration (in-cluster runners)

Runners run `sonar-scanner` against the **internal** Service
(`http://sonarqube-sonarqube.sonarqube.svc:9000` — or via the ingress host),
passing `sonar.pullrequest.key` / `.branch` / `.base` (the branch-plugin makes
Community Build accept them) plus `SONAR_TOKEN` + `SONAR_HOST_URL`. The **server**
posts the decoration via the GitHub App. The Cilium policy allows in-cluster
ingress on `:9000`, so no public scanner endpoint is required.

## Database / backups

CNPG `sonarqube-db` (2 instances, 10Gi) backs up via barman to Hetzner Object
Storage `s3://ssegning-k8s-state/sonarqube-db` (jobs:1 + gzip + 7d retention —
the same Hetzner rate-limit lessons as lightbridge-db). `kubectl -n sonarqube get
cluster,scheduledbackup`.

## Networking

The `sonarqube` namespace is **not** covered by the hetzner-k8s deny baseline;
instead the two CiliumNetworkPolicies in the deps overlay make the app + db pods
default-deny and allow exactly: DNS, `api.github.com:443` (decoration), the DB
`:5432`, Hetzner S3 (db backups), kube-apiserver (CNPG), and in-cluster ingress
on `:9000` / scrape on `:9187`.

## Troubleshooting

- **Pods won't start, ES `max virtual memory areas vm.max_map_count [65530] too
  low`** → the node sysctl (prereq 3) isn't set. Set it, or use the privileged
  fallback.
- **Web/CE crash on boot under `-javaagent`** → branch-plugin ↔ Community Build
  version mismatch, or the jar filename in the `env` agent path ≠ the
  `plugins.install` asset name.
- **ExternalSecrets `SecretSyncedError`** → a `ssegning-aws` property is missing
  (prereq 2).
- **PR decoration silent** → the GitHub App ALM binding (post-deploy step) isn't
  configured, or the project isn't bound to its repo, or egress to
  `api.github.com` is blocked (check the `sonarqube-app` CiliumNetworkPolicy).
- **SAML loop / "fail"** → attribute-name mismatch between the Keycloak client
  mappers and `sonar.auth.saml.*`, or a stale realm cert in `.certificate.secured`.
