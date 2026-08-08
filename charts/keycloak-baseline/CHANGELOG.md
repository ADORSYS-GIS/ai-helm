# Changelog

## [0.5.1](https://github.com/ADORSYS-GIS/ai-helm/compare/keycloak-baseline-v0.5.0...keycloak-baseline-v0.5.1) (2026-08-08)


### Bug Fixes

* **webank-training:** require NVIDIA runtime ([#911](https://github.com/ADORSYS-GIS/ai-helm/issues/911)) ([f2861a9](https://github.com/ADORSYS-GIS/ai-helm/commit/f2861a9713f796157a29bd62324a40ce8145bfb9))

## [0.5.0](https://github.com/ADORSYS-GIS/ai-helm/compare/keycloak-baseline-0.4.0...keycloak-baseline-v0.5.0) (2026-08-02)


### Features

* **65:** coder deployment ([#657](https://github.com/ADORSYS-GIS/ai-helm/issues/657)) ([00db61e](https://github.com/ADORSYS-GIS/ai-helm/commit/00db61e8d91486aa302ca698d4aed07ec0921fba))
* **apps:** gate the Longhorn UI with a role-restricted oauth2-proxy (ADR-0093) ([#771](https://github.com/ADORSYS-GIS/ai-helm/issues/771)) ([f7a64ef](https://github.com/ADORSYS-GIS/ai-helm/commit/f7a64ef128c7ec290bb886b93e5a5857221545b1))
* deploy LakeFS, Argo Workflows, MLflow (mlops platform, ADR-0085) ([#706](https://github.com/ADORSYS-GIS/ai-helm/issues/706)) ([76e30c9](https://github.com/ADORSYS-GIS/ai-helm/commit/76e30c96ec8f9d608e00882213d99e786fa699b5))
* **homepage:** add central-hub dashboard gated by oauth2-proxy ([#758](https://github.com/ADORSYS-GIS/ai-helm/issues/758)) ([fcf15e6](https://github.com/ADORSYS-GIS/ai-helm/commit/fcf15e6ca398363de2f5e4fc1f1d6e1b42982d0c))
* **lakefs-proxy:** Keycloak SSO for LakeFS via a session shim (ADR-0090) ([#759](https://github.com/ADORSYS-GIS/ai-helm/issues/759)) ([42688d2](https://github.com/ADORSYS-GIS/ai-helm/commit/42688d2c8d1c42a0a3e3ca2a6af25047a345d719))


### Bug Fixes

* **keycloak-baseline:** rename longhorn client scope to longhorn_groups ([#774](https://github.com/ADORSYS-GIS/ai-helm/issues/774)) ([c23cb79](https://github.com/ADORSYS-GIS/ai-helm/commit/c23cb79d1d5a54cd646a6c6fe6b00dc77ae263b1))
* **keycloak:** make mlflow_roles claim multivalued ([#716](https://github.com/ADORSYS-GIS/ai-helm/issues/716)) ([d01b76a](https://github.com/ADORSYS-GIS/ai-helm/commit/d01b76a0fe104e4872eb4d71df2ef3a9a511996e))
* **lakefs:** drop oauth2-proxy child + proxy secret + dead keycloak client ([#755](https://github.com/ADORSYS-GIS/ai-helm/issues/755)) ([4ca6eb8](https://github.com/ADORSYS-GIS/ai-helm/commit/4ca6eb8f0b4881d1dff0bf58e021d846a7b5843f))
