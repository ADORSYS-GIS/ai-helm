# Changelog

## [3.0.0](https://github.com/ADORSYS-GIS/ai-helm/compare/ai-models-v2.0.0...ai-models-v3.0.0) (2026-08-02)


### ⚠ BREAKING CHANGES

* **inference:** the charts are published under new OCI names (oci://ghcr.io/adorsys-gis/charts/{inference,inference-server}) and the ArgoCD Application is renamed model-serving -> inference. Two operational consequences, both accepted deliberately:

### Features

* **665:** ticket deploy a model in prod with lmcache ([#668](https://github.com/ADORSYS-GIS/ai-helm/issues/668)) ([ad40fdc](https://github.com/ADORSYS-GIS/ai-helm/commit/ad40fdcd57701fc207b8b32386355e3dc77afc3f))
* **ai-model:** project quota-tier + envelope rate-limit rules, append-only ([aeefad0](https://github.com/ADORSYS-GIS/ai-helm/commit/aeefad0d4f499eb9585f0879f846277c93a06cf6))
* **ai-models:** add adorsys-tiny -- free ($0) alias for qwen3-vl-4b-thinking ([#812](https://github.com/ADORSYS-GIS/ai-helm/issues/812)) ([48e8d04](https://github.com/ADORSYS-GIS/ai-helm/commit/48e8d04714521cdda779768390a88f3b7847cab0))
* **ai-models:** add MiMo V2.5(-Pro), Ornith-1.0-35B, MiniMax M3, Claude Sonnet 5/Fable 5 catalog entries ([#641](https://github.com/ADORSYS-GIS/ai-helm/issues/641)) ([45a456d](https://github.com/ADORSYS-GIS/ai-helm/commit/45a456d19fc03f00e890db6e557fc6851e4aaada))
* **ai-models:** block GLM-5.2 on the external gateway host only ([#594](https://github.com/ADORSYS-GIS/ai-helm/issues/594)) ([d5f6cdd](https://github.com/ADORSYS-GIS/ai-helm/commit/d5f6cddebefffc79bb3512a48fe9b8a67bee8717))
* **ai-models:** federate qwen3-vl-4b-thinking -- load-gated, measured ([#811](https://github.com/ADORSYS-GIS/ai-helm/issues/811)) ([0f60e9f](https://github.com/ADORSYS-GIS/ai-helm/commit/0f60e9ff8fd93f5fd88bdaf54b02be71fbe7b61b))
* **ai-models:** federate z-image-turbo — load-gated, measured, priced ([550ad1b](https://github.com/ADORSYS-GIS/ai-helm/commit/550ad1b699da36664455e8c2ee38fbfc7b331ffe))
* **ai-models:** restore the $50 free tier and remove per-minute limiting ([893b848](https://github.com/ADORSYS-GIS/ai-helm/commit/893b848e2a535f4cd91979bc65dbd4d8579a4e0f))
* **ai-models:** suffix internal-only models with `-internal` ([b9f622d](https://github.com/ADORSYS-GIS/ai-helm/commit/b9f622da9f03b01b9c6875a933abd01ae4cb1fcd))
* connect qwen2-vl-2b to Envoy Gateway and LibreChat ([#721](https://github.com/ADORSYS-GIS/ai-helm/issues/721)) ([86b5a24](https://github.com/ADORSYS-GIS/ai-helm/commit/86b5a242e1171e50e562494f2f5baa37f6464ca4))
* Deploy Z-image-Turbo in new cluster ([15a9c6b](https://github.com/ADORSYS-GIS/ai-helm/commit/15a9c6ba3a9a15219264d34024b9cafc5a42c212))
* **deploy:** Deploying  model for generating  image (vlm) ([ab7f88a](https://github.com/ADORSYS-GIS/ai-helm/commit/ab7f88a7852da90659d8e642b49a5853b5d7798b))
* **deploy:** Deploying  model for generating  image (vlm) ([dad5541](https://github.com/ADORSYS-GIS/ai-helm/commit/dad554118970f3506ecbad3bf2c808f1f3db41ca))
* **deploy:** Deploying  model for generating  image (vlm) ([f21ca5f](https://github.com/ADORSYS-GIS/ai-helm/commit/f21ca5f2fd0b55936e528cc1d579f5bbb3ab0495))
* Deploying  model for generating  image (vlm) ([47c59a2](https://github.com/ADORSYS-GIS/ai-helm/commit/47c59a20f2f323d0e9f4a1f847bcccc7777e04f4))
* federate the fast tier, enable vLLM CORS, price from measurement ([e201caa](https://github.com/ADORSYS-GIS/ai-helm/commit/e201caa31a5b9cb0a63391411a7279a154e536d8))
* **model-serving:** deploy the qwen2.5 & qwen3-4b model with lmcache. ([#666](https://github.com/ADORSYS-GIS/ai-helm/issues/666)) ([ca67f9c](https://github.com/ADORSYS-GIS/ai-helm/commit/ca67f9cc745f69c42b4fb59dc150700eef425990))
* **model-serving:** deploy Z-Image-Turbo as sole GPU model on Hetzner fleet ([acae1a4](https://github.com/ADORSYS-GIS/ai-helm/commit/acae1a4694c4347767fb94a6435756b7c9546b2c))
* **model-serving:** image generation on the fleet, via a third engine profile ([efdd62f](https://github.com/ADORSYS-GIS/ai-helm/commit/efdd62fe99a2c855000cc95d4174cb228a6a0fcf))
* **rate-limit:** add enterprise billing tier for lightbridge API-key plans ([#663](https://github.com/ADORSYS-GIS/ai-helm/issues/663)) ([8edaa90](https://github.com/ADORSYS-GIS/ai-helm/commit/8edaa906994a6beccce25ca3d59169c3ceeebbfa))


### Bug Fixes

* **ai-models:** adorsys-tiny needs minBackends: 1 ([#813](https://github.com/ADORSYS-GIS/ai-helm/issues/813)) ([712a034](https://github.com/ADORSYS-GIS/ai-helm/commit/712a034d5972398ec6fc3351c23737d399ae8bb0))
* **ai-model:** scope disableExternal models out of /v1/models via AIGatewayRoute hostnames ([#797](https://github.com/ADORSYS-GIS/ai-helm/issues/797)) ([80b102a](https://github.com/ADORSYS-GIS/ai-helm/commit/80b102ab8b4c9f4bb25d965222d9d552a31c197e))
* **ai-models:** correct the GPU cost basis — €184/mo was ~18% low (ADR-0104) ([44185a8](https://github.com/ADORSYS-GIS/ai-helm/commit/44185a8760bf8cd8a4f6b33151753c648b1c5a65))
* **ai-models:** reclassify mimo-v2p5-pro + minimax-m3 as reasoning models ([b7dbe4e](https://github.com/ADORSYS-GIS/ai-helm/commit/b7dbe4e8e6585c8c5f68b3db38c5702324f7d7bb))
* **ai-models:** remove z-image-turbo-local entirely -- its backend host is dead ([#814](https://github.com/ADORSYS-GIS/ai-helm/issues/814)) ([dd37478](https://github.com/ADORSYS-GIS/ai-helm/commit/dd374781546475aea45942a308cd09b12a5d8273))
* **ai-models:** stage z-image-turbo behind its load gate (ADR-0101) ([444c7d8](https://github.com/ADORSYS-GIS/ai-helm/commit/444c7d86cc0dcd5134d92e6fd6128c14dbc41ae5))
* **ai-models:** stop advertising models external clients cannot use ([c70f4e9](https://github.com/ADORSYS-GIS/ai-helm/commit/c70f4e9a5c977332dede9a38087a0b15d729b145))
* **inference:** gate the image engine's startup probe on a real generation (ADR-0109) ([3294646](https://github.com/ADORSYS-GIS/ai-helm/commit/3294646286cd4d1d23876f7ea5b4450f5a18ef97))
* **librechat-opencode-wellknown:** drop reasoning caps on Anthropic-via-DeepInfra models ([aa81c5c](https://github.com/ADORSYS-GIS/ai-helm/commit/aa81c5cd947268c69af983223cf09b7d908843d2))
* **model-serving:** MODELS_CONFIG_FILE, not PRELOAD_MODELS_CONFIG ([f85b878](https://github.com/ADORSYS-GIS/ai-helm/commit/f85b8780293e883b68eb2f9c26b1c16fec2149df))
* **model-serving:** restore the known-good gallery config — service first ([f3dab7d](https://github.com/ADORSYS-GIS/ai-helm/commit/f3dab7d4d63ceb45343ba124870d9f67c879dce4))
* **model-serving:** restore the LocalAI image tier, delete the chart that displaced it (ADR-0106) ([d457203](https://github.com/ADORSYS-GIS/ai-helm/commit/d457203dba79648b35b8a3e0a05d3cd390688059)), closes [#803](https://github.com/ADORSYS-GIS/ai-helm/issues/803)
* **model-serving:** stop fighting the gallery for one filename ([25bb104](https://github.com/ADORSYS-GIS/ai-helm/commit/25bb1044ef8970c1b70b21f950be77eb6c1ca02b))
* **zimage-turbo:** resolve merge conflicts, clean up auth remnants, finalize chart ([353d98a](https://github.com/ADORSYS-GIS/ai-helm/commit/353d98a788e3210842d8c5e11bac4b8ff5c76686))


### Performance

* **model-serving:** own the LocalAI model config — 8 steps, params on the GPU ([3c61b01](https://github.com/ADORSYS-GIS/ai-helm/commit/3c61b0161f2c3f763dad616791ea85e55baa5e6f))
* **model-serving:** the tuning works — 2.9x faster, and price it from that ([1b984c8](https://github.com/ADORSYS-GIS/ai-helm/commit/1b984c87ec0a0468134dca334ae97a1530936206))


### Refactoring

* **ai-models:** comment out the home-GPU models; `-local` now means the fleet ([734b479](https://github.com/ADORSYS-GIS/ai-helm/commit/734b479fe46298d7c81848e6ba787f3aebb0b24d))
* **inference:** rename model-serving/model-server to inference/inference-server (ADR-0107) ([bbeb7df](https://github.com/ADORSYS-GIS/ai-helm/commit/bbeb7dfc5536820a6fe642cdc77fd0eff52dea6b))


### Documentation

* refresh arc42/architecture (CD + uncolor mermaid) and reorganize the docs tree ([#654](https://github.com/ADORSYS-GIS/ai-helm/issues/654)) ([79ee808](https://github.com/ADORSYS-GIS/ai-helm/commit/79ee808197679c48373d9ac38810856cf0f4213b))
* **roi:** ai-helm return on investment business case ([96e7753](https://github.com/ADORSYS-GIS/ai-helm/commit/96e7753ccfb90b4757a76a1301d8e51fb93160a8))
