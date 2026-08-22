# Changelog

## [2.1.0](https://github.com/ADORSYS-GIS/ai-helm/compare/apps-v2.0.0...apps-v2.1.0) (2026-08-22)


### Features

* **apps:** float lightbridge-governance's images via argocd-image-updater ([#939](https://github.com/ADORSYS-GIS/ai-helm/issues/939)) ([13dd0ed](https://github.com/ADORSYS-GIS/ai-helm/commit/13dd0edb47996b925f174a4b6893f197ce045f4d))
* deploy lightbridge-governance (AI governance platform) ([#933](https://github.com/ADORSYS-GIS/ai-helm/issues/933)) ([24bf612](https://github.com/ADORSYS-GIS/ai-helm/commit/24bf612ee74a1c4f48df36633c92035432a3f8ad))
* **governance:** deploy censgate/redact-gateway as an internal canary (ADR-0113) ([#889](https://github.com/ADORSYS-GIS/ai-helm/issues/889)) ([623be27](https://github.com/ADORSYS-GIS/ai-helm/commit/623be275b8398319cca54c92f0678c1625fe6f01))
* **librechat-code-interpreter:** self-host LibreChat Code Interpreter (ADR-0122) ([#941](https://github.com/ADORSYS-GIS/ai-helm/issues/941)) ([9e14d02](https://github.com/ADORSYS-GIS/ai-helm/commit/9e14d02aa2da38c6213580c60312c6dbabee674c))
* **lightbridge-ci:** add mcp controller baseline ([#922](https://github.com/ADORSYS-GIS/ai-helm/issues/922)) ([1b58948](https://github.com/ADORSYS-GIS/ai-helm/commit/1b58948591d79b6a6a2a6cbbc7a8f79cc7a0057f))
* **redact-gateway:** replace the censgate canary with a first-party proxy (ADR-0115) ([#892](https://github.com/ADORSYS-GIS/ai-helm/issues/892)) ([3ecec8a](https://github.com/ADORSYS-GIS/ai-helm/commit/3ecec8a171b632412b0bf02e480534bf634bebe9))
* **z-image-proxy:** nginx/njs proxy injects b64_json for LibreChat image gen (ticket [#843](https://github.com/ADORSYS-GIS/ai-helm/issues/843)) ([dbfd3eb](https://github.com/ADORSYS-GIS/ai-helm/commit/dbfd3eb5fa2a6c109ddca8842ffa1f0c6e29a833))


### Bug Fixes

* **core-gateway:** pin chart to 0.3.146, rolling back ADR-0116 sidecar ([#907](https://github.com/ADORSYS-GIS/ai-helm/issues/907)) ([edd200b](https://github.com/ADORSYS-GIS/ai-helm/commit/edd200b9ad2fa762c35c64f0ac9453d56ff132dd))
* **imageupdater:** activate the CRD controller for lightbridge-governance ([#940](https://github.com/ADORSYS-GIS/ai-helm/issues/940)) ([b7fa107](https://github.com/ADORSYS-GIS/ai-helm/commit/b7fa10702975f9c307210405f794766adfc9b89f))
* **librechat-code-interpreter:** move Replace=false override to app-level syncPolicy ([#952](https://github.com/ADORSYS-GIS/ai-helm/issues/952)) ([7f0e468](https://github.com/ADORSYS-GIS/ai-helm/commit/7f0e46836493e282d778d3546bee6614cff89f9a))
* **webank-training:** correct GPU placement contract; implement ADR-0114 priority preemption ([#891](https://github.com/ADORSYS-GIS/ai-helm/issues/891)) ([b045b69](https://github.com/ADORSYS-GIS/ai-helm/commit/b045b69a4163e86aa7c4e45edae4e4f7a93c08f6))
* **webank-training:** require NVIDIA runtime ([#911](https://github.com/ADORSYS-GIS/ai-helm/issues/911)) ([f2861a9](https://github.com/ADORSYS-GIS/ai-helm/commit/f2861a9713f796157a29bd62324a40ce8145bfb9))

## [2.0.0](https://github.com/ADORSYS-GIS/ai-helm/compare/apps-v1.2.0...apps-v2.0.0) (2026-08-02)


### ⚠ BREAKING CHANGES

* **inference:** the charts are published under new OCI names (oci://ghcr.io/adorsys-gis/charts/{inference,inference-server}) and the ArgoCD Application is renamed model-serving -> inference. Two operational consequences, both accepted deliberately:
* **lightbridge-ci:** remove Restate egress — reconciler drain is the sole egress (ADR-0093) ([#664](https://github.com/ADORSYS-GIS/ai-helm/issues/664))

### Features

* **658:** Deploy llmd and evaluate ([#662](https://github.com/ADORSYS-GIS/ai-helm/issues/662)) ([bf2221b](https://github.com/ADORSYS-GIS/ai-helm/commit/bf2221ba1b2191c964354e189326de4920129f6d))
* **65:** coder deployment ([#657](https://github.com/ADORSYS-GIS/ai-helm/issues/657)) ([00db61e](https://github.com/ADORSYS-GIS/ai-helm/commit/00db61e8d91486aa302ca698d4aed07ec0921fba))
* **665:** ticket deploy a model in prod with lmcache ([#668](https://github.com/ADORSYS-GIS/ai-helm/issues/668)) ([ad40fdc](https://github.com/ADORSYS-GIS/ai-helm/commit/ad40fdcd57701fc207b8b32386355e3dc77afc3f))
* **apps:** add Longhorn for the Hetzner Robot GPU nodes (ADR-0092) ([#769](https://github.com/ADORSYS-GIS/ai-helm/issues/769)) ([fba11cd](https://github.com/ADORSYS-GIS/ai-helm/commit/fba11cde0777da1c204bc05d66343ce39682ff1e))
* **apps:** deploy NVIDIA k8s-device-plugin to Hetzner GPU nodes via ArgoCD ([#753](https://github.com/ADORSYS-GIS/ai-helm/issues/753)) ([7a6ec0e](https://github.com/ADORSYS-GIS/ai-helm/commit/7a6ec0ea2d6f2aa6c361f7bc482866c49d40dab9))
* **apps:** gate the Longhorn UI with a role-restricted oauth2-proxy (ADR-0093) ([#771](https://github.com/ADORSYS-GIS/ai-helm/issues/771)) ([f7a64ef](https://github.com/ADORSYS-GIS/ai-helm/commit/f7a64ef128c7ec290bb886b93e5a5857221545b1))
* deploy LakeFS, Argo Workflows, MLflow (mlops platform, ADR-0085) ([#706](https://github.com/ADORSYS-GIS/ai-helm/issues/706)) ([76e30c9](https://github.com/ADORSYS-GIS/ai-helm/commit/76e30c96ec8f9d608e00882213d99e786fa699b5))
* Deploy Z-image-Turbo in new cluster ([15a9c6b](https://github.com/ADORSYS-GIS/ai-helm/commit/15a9c6ba3a9a15219264d34024b9cafc5a42c212))
* **deploy:** Deploying  model for generating  image (vlm) ([dad5541](https://github.com/ADORSYS-GIS/ai-helm/commit/dad554118970f3506ecbad3bf2c808f1f3db41ca))
* **deploy:** Deploying  model for generating  image (vlm) ([f21ca5f](https://github.com/ADORSYS-GIS/ai-helm/commit/f21ca5f2fd0b55936e528cc1d579f5bbb3ab0495))
* Deploying  model for generating  image (vlm) ([47c59a2](https://github.com/ADORSYS-GIS/ai-helm/commit/47c59a20f2f323d0e9f4a1f847bcccc7777e04f4))
* **homepage:** add central-hub dashboard gated by oauth2-proxy ([#758](https://github.com/ADORSYS-GIS/ai-helm/issues/758)) ([fcf15e6](https://github.com/ADORSYS-GIS/ai-helm/commit/fcf15e6ca398363de2f5e4fc1f1d6e1b42982d0c))
* **lci:** notifier role — controller, egress NetworkPolicy, metrics, A2A push token secret (ADR-0079) ([#628](https://github.com/ADORSYS-GIS/ai-helm/issues/628)) ([475198d](https://github.com/ADORSYS-GIS/ai-helm/commit/475198dba71d5dd9eee7228930919e1c53fa13af))
* **lightbridge-ci:** remove Restate egress — reconciler drain is the sole egress (ADR-0093) ([#664](https://github.com/ADORSYS-GIS/ai-helm/issues/664)) ([a4f708e](https://github.com/ADORSYS-GIS/ai-helm/commit/a4f708ecbbfd7b451cfdad7d53eb2d7beddf4064))
* **lightbridge-code-intellignece:** add GitLab configuration to lightbridge-code-intelligence chart ([b7f07b6](https://github.com/ADORSYS-GIS/ai-helm/commit/b7f07b655abbe34552ff51993c2556d50db0129c))
* **model-serving:** deploy the qwen2.5 & qwen3-4b model with lmcache. ([#666](https://github.com/ADORSYS-GIS/ai-helm/issues/666)) ([ca67f9c](https://github.com/ADORSYS-GIS/ai-helm/commit/ca67f9cc745f69c42b4fb59dc150700eef425990))
* **model-serving:** deploy Z-Image-Turbo as sole GPU model on Hetzner fleet ([acae1a4](https://github.com/ADORSYS-GIS/ai-helm/commit/acae1a4694c4347767fb94a6435756b7c9546b2c))
* **model-serving:** image generation on the fleet, via a third engine profile ([efdd62f](https://github.com/ADORSYS-GIS/ai-helm/commit/efdd62fe99a2c855000cc95d4174cb228a6a0fcf))
* **observability:** GPU dashboards + hardware alerts; fix DCGM honorLabels ([03ad783](https://github.com/ADORSYS-GIS/ai-helm/commit/03ad783a32a79fe41a4f749675584d955008fd7e))
* **observability:** GPU telemetry + model-serving alerts to a second Discord ([e5320db](https://github.com/ADORSYS-GIS/ai-helm/commit/e5320dbdc58e3bd564d4f05fb11b604f16c30ec0))
* **webank-training:** deploy governed GPU workflow ([#818](https://github.com/ADORSYS-GIS/ai-helm/issues/818)) ([cdb76ee](https://github.com/ADORSYS-GIS/ai-helm/commit/cdb76ee844d4ecf48d421c72ea7dd8d0528fb41f))


### Bug Fixes

* **apps:** attach an S3-cred deps overlay to mongodb-backup ([#882](https://github.com/ADORSYS-GIS/ai-helm/issues/882)) ([f24bf5f](https://github.com/ADORSYS-GIS/ai-helm/commit/f24bf5f0d941f9a2c07663817f8f43a74b4751d3))
* **apps:** correct finalizer — resources-finalizer.argocd.argoproj.io ([b4112d8](https://github.com/ADORSYS-GIS/ai-helm/commit/b4112d8e3bd22caa8671a8501bc8d54eb5421f38))
* **apps:** disable model-serving-zimage-turbo -- its image does not exist ([#804](https://github.com/ADORSYS-GIS/ai-helm/issues/804)) ([73f4b15](https://github.com/ADORSYS-GIS/ai-helm/commit/73f4b15d1ce66972e6791d3173086df296cf4d37))
* **argocd:** change opencode-k8s-agent targetRevision ([#650](https://github.com/ADORSYS-GIS/ai-helm/issues/650)) ([5714bfb](https://github.com/ADORSYS-GIS/ai-helm/commit/5714bfbaff6e021993667aa89ca614dff8829097))
* **docs:** update stale charts/coder-db references, remove dead coder-db-role secret, add CNPG playbook ([a3ac602](https://github.com/ADORSYS-GIS/ai-helm/commit/a3ac6020f48cf7d201e3d1cf2b5bcd48dadcbd2a))
* **model-serving-zimage-turbo:** add GPU node tolerations to resolve scheduling failure. ([#799](https://github.com/ADORSYS-GIS/ai-helm/issues/799)) ([f7e7758](https://github.com/ADORSYS-GIS/ai-helm/commit/f7e775874193882634af4786183d2ee5e0fa8588))
* **model-serving:** restore the LocalAI image tier, delete the chart that displaced it (ADR-0106) ([d457203](https://github.com/ADORSYS-GIS/ai-helm/commit/d457203dba79648b35b8a3e0a05d3cd390688059)), closes [#803](https://github.com/ADORSYS-GIS/ai-helm/issues/803)
* **webank-training:** enforce GPU placement ([#849](https://github.com/ADORSYS-GIS/ai-helm/issues/849)) ([d1b3537](https://github.com/ADORSYS-GIS/ai-helm/commit/d1b3537d61b7662e93685e3ad87f31e62d18554f))


### Refactoring

* **inference:** rename model-serving/model-server to inference/inference-server (ADR-0107) ([bbeb7df](https://github.com/ADORSYS-GIS/ai-helm/commit/bbeb7dfc5536820a6fe642cdc77fd0eff52dea6b))
* update comments and remove GitLab integration from values.yaml ([865fffe](https://github.com/ADORSYS-GIS/ai-helm/commit/865fffef70ebdca07c28e403cd33da3ffe910352))
* update comments and remove GitLab integration from values.yaml and externalsecret.yaml ([130f839](https://github.com/ADORSYS-GIS/ai-helm/commit/130f839e13ae4363c23947d93d14dfbda30d1ded))


### Documentation

* refresh arc42/architecture (CD + uncolor mermaid) and reorganize the docs tree ([#654](https://github.com/ADORSYS-GIS/ai-helm/issues/654)) ([79ee808](https://github.com/ADORSYS-GIS/ai-helm/commit/79ee808197679c48373d9ac38810856cf0f4213b))

## [1.2.0](https://github.com/ADORSYS-GIS/ai-helm/compare/apps-1.1.0...apps-v1.2.0) (2026-07-10)


### Features

* **apps:** deploy Stakater Reloader (opt-in) for cert-rotation restarts ([#634](https://github.com/ADORSYS-GIS/ai-helm/issues/634)) ([3077f22](https://github.com/ADORSYS-GIS/ai-helm/commit/3077f2271dc2fd602efd6f749ce2646ac50eece1))
