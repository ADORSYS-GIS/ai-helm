# Changelog

## [0.4.0](https://github.com/ADORSYS-GIS/ai-helm/compare/lightbridge-db-v0.3.0...lightbridge-db-v0.4.0) (2026-09-02)


### ⚠ BREAKING CHANGES

* **lightbridge-db:** raise storage 5Gi -> 20Gi (production outage) ([#1059](https://github.com/ADORSYS-GIS/ai-helm/issues/1059))

### Features

* deploy lightbridge-governance (AI governance platform) ([#933](https://github.com/ADORSYS-GIS/ai-helm/issues/933)) ([24bf612](https://github.com/ADORSYS-GIS/ai-helm/commit/24bf612ee74a1c4f48df36633c92035432a3f8ad))
* **lightbridge-db:** provision lightbridge-authz-usage's database as a Database CR ([#1009](https://github.com/ADORSYS-GIS/ai-helm/issues/1009)) ([f6eeb25](https://github.com/ADORSYS-GIS/ai-helm/commit/f6eeb25f5fbb0e2bb4f321c13c253c2e6786b576))
* **mlops:** give the mlops namespace its own dedicated CNPG cluster (Stage 2) ([#957](https://github.com/ADORSYS-GIS/ai-helm/issues/957)) ([bfd6a00](https://github.com/ADORSYS-GIS/ai-helm/commit/bfd6a0001f12919ef5f900fc41f2867ac2b12199))


### Bug Fixes

* **lightbridge-db:** raise max_connections and memory headroom ([#956](https://github.com/ADORSYS-GIS/ai-helm/issues/956)) ([f28355f](https://github.com/ADORSYS-GIS/ai-helm/commit/f28355f1520829496a25d1c625a6ae43f489fa73))
* **lightbridge-db:** raise storage 20Gi -&gt; 40Gi ([#1060](https://github.com/ADORSYS-GIS/ai-helm/issues/1060)) ([aa9cb8e](https://github.com/ADORSYS-GIS/ai-helm/commit/aa9cb8ee570d365ad369aedb5eddab2e2050be4c))
* **lightbridge-db:** raise storage 5Gi -&gt; 20Gi (production outage) ([#1059](https://github.com/ADORSYS-GIS/ai-helm/issues/1059)) ([5a971da](https://github.com/ADORSYS-GIS/ai-helm/commit/5a971dac31f05af6e6f1fda0975ee55cd4b2b22c))
* **mlflow:** drop dead lightbridge-main-db role, sync docs for cutover ([#959](https://github.com/ADORSYS-GIS/ai-helm/issues/959)) ([fb1e32d](https://github.com/ADORSYS-GIS/ai-helm/commit/fb1e32dd30a9aa67fb41bc96e677f8a73c9cdb11))
* **webank-training:** require NVIDIA runtime ([#911](https://github.com/ADORSYS-GIS/ai-helm/issues/911)) ([f2861a9](https://github.com/ADORSYS-GIS/ai-helm/commit/f2861a9713f796157a29bd62324a40ce8145bfb9))

## [0.3.0](https://github.com/ADORSYS-GIS/ai-helm/compare/lightbridge-db-v0.2.0...lightbridge-db-v0.3.0) (2026-08-02)


### Features

* **65:** coder deployment ([#657](https://github.com/ADORSYS-GIS/ai-helm/issues/657)) ([00db61e](https://github.com/ADORSYS-GIS/ai-helm/commit/00db61e8d91486aa302ca698d4aed07ec0921fba))
* deploy LakeFS, Argo Workflows, MLflow (mlops platform, ADR-0085) ([#706](https://github.com/ADORSYS-GIS/ai-helm/issues/706)) ([76e30c9](https://github.com/ADORSYS-GIS/ai-helm/commit/76e30c96ec8f9d608e00882213d99e786fa699b5))


### Bug Fixes

* **mlflow:** add dedicated mlflow_oidc database for the oidc-auth plugin ([#754](https://github.com/ADORSYS-GIS/ai-helm/issues/754)) ([29f6795](https://github.com/ADORSYS-GIS/ai-helm/commit/29f679506e5b3adec98ef0abeeef646b7473538c))
