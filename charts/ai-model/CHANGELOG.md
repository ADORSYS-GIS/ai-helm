# Changelog

## [1.2.0](https://github.com/ADORSYS-GIS/ai-helm/compare/ai-model-v1.1.0...ai-model-v1.2.0) (2026-08-02)


### Features

* **ai-model:** project quota-tier + envelope rate-limit rules, append-only ([aeefad0](https://github.com/ADORSYS-GIS/ai-helm/commit/aeefad0d4f499eb9585f0879f846277c93a06cf6))
* **ai-models:** block GLM-5.2 on the external gateway host only ([#594](https://github.com/ADORSYS-GIS/ai-helm/issues/594)) ([d5f6cdd](https://github.com/ADORSYS-GIS/ai-helm/commit/d5f6cddebefffc79bb3512a48fe9b8a67bee8717))
* **ai-models:** restore the $50 free tier and remove per-minute limiting ([893b848](https://github.com/ADORSYS-GIS/ai-helm/commit/893b848e2a535f4cd91979bc65dbd4d8579a4e0f))
* **deploy:** Deploying  model for generating  image (vlm) ([d21f438](https://github.com/ADORSYS-GIS/ai-helm/commit/d21f438cadc6e5cc29fd2c183d274271a6579374))
* **deploy:** Deploying  model for generating  image (vlm) ([dad5541](https://github.com/ADORSYS-GIS/ai-helm/commit/dad554118970f3506ecbad3bf2c808f1f3db41ca))
* **deploy:** Deploying  model for generating  image (vlm) ([f21ca5f](https://github.com/ADORSYS-GIS/ai-helm/commit/f21ca5f2fd0b55936e528cc1d579f5bbb3ab0495))
* Deploying  model for generating  image (vlm) ([47c59a2](https://github.com/ADORSYS-GIS/ai-helm/commit/47c59a20f2f323d0e9f4a1f847bcccc7777e04f4))


### Bug Fixes

* **ai-model:** convert lint-values-internal plans to ordered-list form ([#860](https://github.com/ADORSYS-GIS/ai-helm/issues/860)) ([fb48875](https://github.com/ADORSYS-GIS/ai-helm/commit/fb48875c5de5ab5cde91a4597b47a9fdc95737e3))
* **ai-model:** flatPerRequest emitted an int literal, wedging the whole Gateway reconcile ([67b5076](https://github.com/ADORSYS-GIS/ai-helm/commit/67b5076307bf910ec6aa376c79c0f24a888b3b97))
* **ai-model:** scope disableExternal models out of /v1/models via AIGatewayRoute hostnames ([#797](https://github.com/ADORSYS-GIS/ai-helm/issues/797)) ([80b102a](https://github.com/ADORSYS-GIS/ai-helm/commit/80b102ab8b4c9f4bb25d965222d9d552a31c197e))
* **core-gateway:** calendar-align monthly budget windows (ADR-0111) ([#859](https://github.com/ADORSYS-GIS/ai-helm/issues/859)) ([b6d240e](https://github.com/ADORSYS-GIS/ai-helm/commit/b6d240e23e2cdfb7a1ae234fe3a53562e35b3a1c))
* **core-gateway:** unit Year so billing period is the only rotation (ADR-0112) ([#869](https://github.com/ADORSYS-GIS/ai-helm/issues/869)) ([196702d](https://github.com/ADORSYS-GIS/ai-helm/commit/196702d5dd5d61b7b411a8f3ce545d5e2500b5f5))
* **observability:** panels rendering nothing on duplicate refIds ([e49629e](https://github.com/ADORSYS-GIS/ai-helm/commit/e49629e3508e0914d344288e8ac413681b4c12f0))

## [1.1.0](https://github.com/ADORSYS-GIS/ai-helm/compare/ai-model-v1.0.0...ai-model-v1.1.0) (2026-07-10)


### Features

* **core-gateway:** trace-log correlation + scoped AI Gateway tracing ([#630](https://github.com/ADORSYS-GIS/ai-helm/issues/630)) ([7b77cc9](https://github.com/ADORSYS-GIS/ai-helm/commit/7b77cc9996f8a41d6e4d4764778a2e7edb977bb3))


### Bug Fixes

* **core-gateway:** trace all gateway traffic — per-route sampling doesn't exist ([#632](https://github.com/ADORSYS-GIS/ai-helm/issues/632)) ([d8162e4](https://github.com/ADORSYS-GIS/ai-helm/commit/d8162e4f35b5917fcccf1e9aa745e111ff2bf7df))
