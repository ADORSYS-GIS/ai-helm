# Changelog

## [0.2.0](https://github.com/ADORSYS-GIS/ai-helm/compare/aisix-v0.1.0...aisix-v0.2.0) (2026-09-04)


### Features

* **aisix:** add the aisix chart — /v1/responses → chat-completions bridge ([#1108](https://github.com/ADORSYS-GIS/ai-helm/issues/1108)) ([fd1b577](https://github.com/ADORSYS-GIS/ai-helm/commit/fd1b577cfc4923ceafb54b125a17e932e76c10a3))
* **aisix:** give AISIX's telemetry its real names — endpoint label, dashboard, alerts ([#1112](https://github.com/ADORSYS-GIS/ai-helm/issues/1112)) ([e91cd57](https://github.com/ADORSYS-GIS/ai-helm/commit/e91cd57ec9dddce54fef4f30d414f07f9ff8861a))
* **aisix:** HA shape — 2 replicas, PDB, anti-affinity, surge-only rollout, envFromSecrets ([#1111](https://github.com/ADORSYS-GIS/ai-helm/issues/1111)) ([ae38009](https://github.com/ADORSYS-GIS/ai-helm/commit/ae3800966297881e74d0a958fc42af0128bac523))


### Bug Fixes

* **aisix:** disable service links — AISIX_PORT breaks the config loader ([#1110](https://github.com/ADORSYS-GIS/ai-helm/issues/1110)) ([886ebf7](https://github.com/ADORSYS-GIS/ai-helm/commit/886ebf7030d28803884229c27d42152b16b56e94))
* **webank-training:** require NVIDIA runtime ([#911](https://github.com/ADORSYS-GIS/ai-helm/issues/911)) ([f2861a9](https://github.com/ADORSYS-GIS/ai-helm/commit/f2861a9713f796157a29bd62324a40ce8145bfb9))


### Documentation

* **aisix:** the capacity runbook is `aisix.md` now, not `aisix-spike.md` ([#1113](https://github.com/ADORSYS-GIS/ai-helm/issues/1113)) ([3b5f133](https://github.com/ADORSYS-GIS/ai-helm/commit/3b5f133d3522bd4a95c72689c27277e9530a4d62))
* **core-gateway:** record the budget limiter as enforcing, and AISIX as fleet-wide ([#1117](https://github.com/ADORSYS-GIS/ai-helm/issues/1117)) ([ed4ffa8](https://github.com/ADORSYS-GIS/ai-helm/commit/ed4ffa82fe3caf0af2a7dd1974f4fb84f687ada9))
