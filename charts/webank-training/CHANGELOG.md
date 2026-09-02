# Changelog

## [0.3.0](https://github.com/ADORSYS-GIS/ai-helm/compare/webank-training-v0.2.0...webank-training-v0.3.0) (2026-09-02)


### ⚠ BREAKING CHANGES

* **webank-training:** `models[].lakefs.model.storageNamespace` is now a required value (fails closed via `required` if absent) — every model entry in consuming values files (e.g. ai-helm-values) needs a `s3://` storage namespace added under `lakefs.model` before upgrading. Separately, dataset- build steps no longer read `training.gpu.resources`/`nodeSelector`/ `tolerations`/`runtimeClassName` at all; any existing values override aimed at dataset-build sizing must move to the new `training.datasetBuild.resources` key or it will silently stop applying to dataset-build (it still applies to `*-train`, unchanged).

### Features

* **webank-training:** allocate GPUs to dataset builds ([5779190](https://github.com/ADORSYS-GIS/ai-helm/commit/5779190c6aada13767ce69dc3079099d67f36dcb))
* **webank-training:** bring the MIDV-2020 dataset-build template under GitOps ([#1006](https://github.com/ADORSYS-GIS/ai-helm/issues/1006)) ([5a8c706](https://github.com/ADORSYS-GIS/ai-helm/commit/5a8c706bd9b07e9bb0bc4acbbcdfa29a8789004f))
* **webank-training:** expose dataset-build knobs as workflow parameters ([#1005](https://github.com/ADORSYS-GIS/ai-helm/issues/1005)) ([c899f47](https://github.com/ADORSYS-GIS/ai-helm/commit/c899f475a29118590d7d13c9e15713d657a83502))
* **webank-training:** gate dataset-build publish on a real readiness-gate step ([#999](https://github.com/ADORSYS-GIS/ai-helm/issues/999)) ([e8e8a23](https://github.com/ADORSYS-GIS/ai-helm/commit/e8e8a23ae388c19058c4141fcf8b4ef1b8ea09a1))
* **webank-training:** render fixed dataset builds ([#921](https://github.com/ADORSYS-GIS/ai-helm/issues/921)) ([fa80813](https://github.com/ADORSYS-GIS/ai-helm/commit/fa808138ab379738ef2812b25c9e0e665691bb4c))


### Bug Fixes

* **webank-training:** call released repository bootstrap ([#918](https://github.com/ADORSYS-GIS/ai-helm/issues/918)) ([43e5ecc](https://github.com/ADORSYS-GIS/ai-helm/commit/43e5ecc3ed967013fc7e7502edcfe5804b26bfd4))
* **webank-training:** correct GPU placement contract; implement ADR-0114 priority preemption ([#891](https://github.com/ADORSYS-GIS/ai-helm/issues/891)) ([b045b69](https://github.com/ADORSYS-GIS/ai-helm/commit/b045b69a4163e86aa7c4e45edae4e4f7a93c08f6))
* **webank-training:** disable ungated dataset-build publish by default ([#984](https://github.com/ADORSYS-GIS/ai-helm/issues/984)) ([f24126a](https://github.com/ADORSYS-GIS/ai-helm/commit/f24126acdc31383425403cf4d8597911405ba356))
* **webank-training:** mount a writable /workspace on dataset-build and train pods ([#954](https://github.com/ADORSYS-GIS/ai-helm/issues/954)) ([bf023ea](https://github.com/ADORSYS-GIS/ai-helm/commit/bf023ea1f8adcb57fff42297040fd87bcd1cc054))
* **webank-training:** render portable GPU runtime ([#915](https://github.com/ADORSYS-GIS/ai-helm/issues/915)) ([9d1ea7d](https://github.com/ADORSYS-GIS/ai-helm/commit/9d1ea7d539b082ffcd7393f6aa62f23cab01ade2))
* **webank-training:** repoint push-candidate at fixed-candidate publish, drop dataset-build GPU ([#945](https://github.com/ADORSYS-GIS/ai-helm/issues/945)) ([70f607b](https://github.com/ADORSYS-GIS/ai-helm/commit/70f607b17de761a6bf60e1263bd4e0a5b542ad81))
* **webank-training:** require explicit GPU requests ([#896](https://github.com/ADORSYS-GIS/ai-helm/issues/896)) ([025a662](https://github.com/ADORSYS-GIS/ai-helm/commit/025a662b9277bf6a80e49288dfab82ca3d8ae974))
* **webank-training:** require NVIDIA runtime ([#911](https://github.com/ADORSYS-GIS/ai-helm/issues/911)) ([f2861a9](https://github.com/ADORSYS-GIS/ai-helm/commit/f2861a9713f796157a29bd62324a40ce8145bfb9))
* **webank-training:** require NVIDIA runtime ([#911](https://github.com/ADORSYS-GIS/ai-helm/issues/911)) ([0086e5d](https://github.com/ADORSYS-GIS/ai-helm/commit/0086e5d899c4370c493a2db54f24dc68e321ce4a))
* **webank-training:** restore dataset-build GPU placement ([#949](https://github.com/ADORSYS-GIS/ai-helm/issues/949)) ([b52269b](https://github.com/ADORSYS-GIS/ai-helm/commit/b52269b0a724a065e8f05210361bf37e48cfdda3))
* **webank-training:** split dataset-build image from training.image ([#953](https://github.com/ADORSYS-GIS/ai-helm/issues/953)) ([54bb3af](https://github.com/ADORSYS-GIS/ai-helm/commit/54bb3aff549fabf1f954d23bdf3a975bc4e72f46))

## [0.2.0](https://github.com/ADORSYS-GIS/ai-helm/compare/webank-training-v0.1.1...webank-training-v0.2.0) (2026-08-02)


### Features

* **training:** expose model workflow catalogue ([80fdd5e](https://github.com/ADORSYS-GIS/ai-helm/commit/80fdd5e9bf9a1f469c205ac5b75eaa0214544d6a))
* **training:** expose per-model Argo workflows ([677bfd1](https://github.com/ADORSYS-GIS/ai-helm/commit/677bfd122497649fa2c120c023c5cea94c7cb3ef))
* **webank-training:** add detector run template ([#847](https://github.com/ADORSYS-GIS/ai-helm/issues/847)) ([f1b0733](https://github.com/ADORSYS-GIS/ai-helm/commit/f1b0733c369eda48f6df8607e1771495d60a9795))
* **webank-training:** bootstrap detector dataset ([#884](https://github.com/ADORSYS-GIS/ai-helm/issues/884)) ([5fd2bc3](https://github.com/ADORSYS-GIS/ai-helm/commit/5fd2bc3d7330958d40e52e2c2bcaebcc7ef25367))
* **webank-training:** deploy governed GPU workflow ([#818](https://github.com/ADORSYS-GIS/ai-helm/issues/818)) ([cdb76ee](https://github.com/ADORSYS-GIS/ai-helm/commit/cdb76ee844d4ecf48d421c72ea7dd8d0528fb41f))
* **webank-training:** pin lakefs routes per model ([#870](https://github.com/ADORSYS-GIS/ai-helm/issues/870)) ([71c401f](https://github.com/ADORSYS-GIS/ai-helm/commit/71c401fdc45904124d9446802200419feb8c9e1f))
* **webank-training:** place dataset builds on GPU nodes ([5bdca7a](https://github.com/ADORSYS-GIS/ai-helm/commit/5bdca7ad6fe168454c776f7f0c1ac787af46e94c))


### Bug Fixes

* **webank-training:** clarify document detector submission ([#851](https://github.com/ADORSYS-GIS/ai-helm/issues/851)) ([2f47d3d](https://github.com/ADORSYS-GIS/ai-helm/commit/2f47d3dfd2e9dd2e402ce7c0e9864587a8f6dea1))
* **webank-training:** enforce GPU placement ([#849](https://github.com/ADORSYS-GIS/ai-helm/issues/849)) ([d1b3537](https://github.com/ADORSYS-GIS/ai-helm/commit/d1b3537d61b7662e93685e3ad87f31e62d18554f))
* **webank-training:** publish submission contract update ([#852](https://github.com/ADORSYS-GIS/ai-helm/issues/852)) ([91e6d16](https://github.com/ADORSYS-GIS/ai-helm/commit/91e6d16ae60b9d50bb7a69ee1916730a01349cc9))
