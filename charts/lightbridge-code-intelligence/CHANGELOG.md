# Changelog

## [0.9.0](https://github.com/ADORSYS-GIS/ai-helm/compare/lightbridge-code-intelligence-v0.8.0...lightbridge-code-intelligence-v0.9.0) (2026-08-22)


### Features

* **lightbridge-ci:** add mcp controller baseline ([#922](https://github.com/ADORSYS-GIS/ai-helm/issues/922)) ([1b58948](https://github.com/ADORSYS-GIS/ai-helm/commit/1b58948591d79b6a6a2a6cbbc7a8f79cc7a0057f))


### Bug Fixes

* **webank-training:** require NVIDIA runtime ([#911](https://github.com/ADORSYS-GIS/ai-helm/issues/911)) ([f2861a9](https://github.com/ADORSYS-GIS/ai-helm/commit/f2861a9713f796157a29bd62324a40ce8145bfb9))

## [0.8.0](https://github.com/ADORSYS-GIS/ai-helm/compare/lightbridge-code-intelligence-v0.7.1...lightbridge-code-intelligence-v0.8.0) (2026-08-02)


### ⚠ BREAKING CHANGES

* **lightbridge-ci:** remove Restate egress — reconciler drain is the sole egress (ADR-0093) ([#664](https://github.com/ADORSYS-GIS/ai-helm/issues/664))

### Features

* add GitLab integration support with project-specific access tokens and webhook secrets ([f062abd](https://github.com/ADORSYS-GIS/ai-helm/commit/f062abd3e392ad9b45c6ec5d0127386e97ecb6c2))
* add GitLab integration support with project-specific access tokens and webhook secrets ([ec79317](https://github.com/ADORSYS-GIS/ai-helm/commit/ec79317a75ecfa8cf1bf62f30041e16038fc6ade))
* add GitLab project configuration support in control-plane.json ([#688](https://github.com/ADORSYS-GIS/ai-helm/issues/688)) ([214543a](https://github.com/ADORSYS-GIS/ai-helm/commit/214543abcc28f40edf0328ffa7ad46136d8348d5))
* **code-intel:** migrate GitLab project secrets to env-owned ExternalSecret injection ([64da2a9](https://github.com/ADORSYS-GIS/ai-helm/commit/64da2a9eecc6269de6184a4a947fdd5c66eefea0))
* implement file-based GitLab configuration and add env-var secret wiring in Helm chart ([f5e8ed5](https://github.com/ADORSYS-GIS/ai-helm/commit/f5e8ed5c9b3f7d4dddc6a314f7d68e156bc3a8af))
* **lci:** notifier role — controller, egress NetworkPolicy, metrics, A2A push token secret (ADR-0079) ([#628](https://github.com/ADORSYS-GIS/ai-helm/issues/628)) ([475198d](https://github.com/ADORSYS-GIS/ai-helm/commit/475198dba71d5dd9eee7228930919e1c53fa13af))
* **lci:** reconciler reads egress.mode via egress-only config (RFC-0005 Phase A activation) ([#637](https://github.com/ADORSYS-GIS/ai-helm/issues/637)) ([a459d86](https://github.com/ADORSYS-GIS/ai-helm/commit/a459d8608f0997ccdc752eae328c66cd3d145cab))
* **lci:** roll config-reading roles on read-once-at-boot config flips (config-rollout checksum) ([#638](https://github.com/ADORSYS-GIS/ai-helm/issues/638)) ([425fcf9](https://github.com/ADORSYS-GIS/ai-helm/commit/425fcf93adbdd3785263917f2a808e20a617ed17))
* **lightbridge-ci:** remove Restate egress — reconciler drain is the sole egress (ADR-0093) ([#664](https://github.com/ADORSYS-GIS/ai-helm/issues/664)) ([a4f708e](https://github.com/ADORSYS-GIS/ai-helm/commit/a4f708ecbbfd7b451cfdad7d53eb2d7beddf4064))
* **lightbridge-code-intelligence:** add GitLab base URL configuration for dashboard links ([19282de](https://github.com/ADORSYS-GIS/ai-helm/commit/19282defce0437b2353c8b5b13b759f4b7a4a078))
* **lightbridge-code-intelligence:** enable debug logging for control-plane and dispatcher ([#789](https://github.com/ADORSYS-GIS/ai-helm/issues/789)) ([9ceb817](https://github.com/ADORSYS-GIS/ai-helm/commit/9ceb817759e9b7152125e8b422f400ebe5433b80))
* **lightbridge-code-intelligence:** map config.model.&lt;tier&gt;.maxCycles to review.&lt;tier&gt;.max_cycles ([#711](https://github.com/ADORSYS-GIS/ai-helm/issues/711)) ([27574e0](https://github.com/ADORSYS-GIS/ai-helm/commit/27574e0eb16cf1c0e15c30b5e8e9ad27209f6952))
* **lightbridge-code-intelligence:** wire RUNNER_TOKEN_SIGNING_KEY ([#243](https://github.com/ADORSYS-GIS/ai-helm/issues/243), ADR-0092) ([#660](https://github.com/ADORSYS-GIS/ai-helm/issues/660)) ([358d114](https://github.com/ADORSYS-GIS/ai-helm/commit/358d1143d7b9c9b867be95b2ca1f4934c14622f3))
* **lightbridge-code-intelligence:** wire the ADR-0099 opencode overlay through ([#687](https://github.com/ADORSYS-GIS/ai-helm/issues/687)) ([7812420](https://github.com/ADORSYS-GIS/ai-helm/commit/781242067f0c44015f3510a5de67bc1ab54089e6))
* **lightbridge-code-intellignece:** add GitLab configuration to lightbridge-code-intelligence chart ([b7f07b6](https://github.com/ADORSYS-GIS/ai-helm/commit/b7f07b655abbe34552ff51993c2556d50db0129c))
* **lightbridge:** add /api/v2 to CONTROL_PLANE_INTERNAL_URL and AUTH_BACKEND_URL ([#817](https://github.com/ADORSYS-GIS/ai-helm/issues/817)) ([bdfaafc](https://github.com/ADORSYS-GIS/ai-helm/commit/bdfaafcf735f3ba8c10b03a5fa4af198688a5ee4))


### Bug Fixes

* correct formatting in GitLab configuration comments in values.yaml ([c591042](https://github.com/ADORSYS-GIS/ai-helm/commit/c5910425595d95a87d37ca0451e64a811d1aaa2f))
* **lightbridge-code-intelligence:** nest review tiers under presets ([#798](https://github.com/ADORSYS-GIS/ai-helm/issues/798)) ([9484282](https://github.com/ADORSYS-GIS/ai-helm/commit/94842822f829b1c5fa06c4551fdcc7d69276337c))
* remove unnecessary blank line in values.yaml ([91848be](https://github.com/ADORSYS-GIS/ai-helm/commit/91848be93d166e288c2a1079061232772bad2dbd))


### Refactoring

* update comments and remove GitLab integration from values.yaml ([865fffe](https://github.com/ADORSYS-GIS/ai-helm/commit/865fffef70ebdca07c28e403cd33da3ffe910352))
* update comments and remove GitLab integration from values.yaml and externalsecret.yaml ([130f839](https://github.com/ADORSYS-GIS/ai-helm/commit/130f839e13ae4363c23947d93d14dfbda30d1ded))
