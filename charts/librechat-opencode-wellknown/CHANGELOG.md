# Changelog

## [2.2.0](https://github.com/ADORSYS-GIS/ai-helm/compare/librechat-opencode-wellknown-v2.1.0...librechat-opencode-wellknown-v2.2.0) (2026-08-22)


### Features

* add qwen3-coder-30b-a3b-local to the picker and raise its context to 12288 ([#919](https://github.com/ADORSYS-GIS/ai-helm/issues/919)) ([36c29c8](https://github.com/ADORSYS-GIS/ai-helm/commit/36c29c89836edf81dbdebfa61e0f9696c886a2f6))
* **ai-models:** force DeepInfra service_tier=priority; retire deepseek-v4-flash/-pro for -0731 (ADR-0117) ([#894](https://github.com/ADORSYS-GIS/ai-helm/issues/894)) ([59a7ab4](https://github.com/ADORSYS-GIS/ai-helm/commit/59a7ab46f7f37d2da357ca01e8333e51c2446ca8))
* **inference:** deploy Qwen3-4B (Q6_K, llama.cpp) as the fleet coding model ([26f23e3](https://github.com/ADORSYS-GIS/ai-helm/commit/26f23e3f117930fdfbb61cc53824fc4aa6059e7b))
* **inference:** deploy Qwen3-4B (Q6_K, llama.cpp) as the fleet coding model ([c19ee2a](https://github.com/ADORSYS-GIS/ai-helm/commit/c19ee2a5c2ffcd26a37f61c756d19e925e329002))


### Bug Fixes

* **ai-models:** advertise qwen3-coder-30b-a3b input window as 12288 ([4738725](https://github.com/ADORSYS-GIS/ai-helm/commit/47387251233ecc327e0ab5acc94ba104e4b00f34))
* **ai-models:** derive opencode's reasoning caps from the catalog (ADR-0125) ([#971](https://github.com/ADORSYS-GIS/ai-helm/issues/971)) ([52a8355](https://github.com/ADORSYS-GIS/ai-helm/commit/52a8355abf96625a343add1704ad1a5bba2dd792))
* **inference:** raise qwen3-coder-30b-a3b context window to 16384 ([ffb10bb](https://github.com/ADORSYS-GIS/ai-helm/commit/ffb10bb2d3c2601264f088ef80b678d02a3c8c99))
* **inference:** raise qwen3-coder-30b-a3b context window to 16384 ([2ace27b](https://github.com/ADORSYS-GIS/ai-helm/commit/2ace27b415b32042aeda59c5ab1534ac125a697a))
* **webank-training:** require NVIDIA runtime ([#911](https://github.com/ADORSYS-GIS/ai-helm/issues/911)) ([f2861a9](https://github.com/ADORSYS-GIS/ai-helm/commit/f2861a9713f796157a29bd62324a40ce8145bfb9))

## [2.1.0](https://github.com/ADORSYS-GIS/ai-helm/compare/librechat-opencode-wellknown-v2.0.0...librechat-opencode-wellknown-v2.1.0) (2026-08-02)


### Features

* **homepage:** discovery annotations for LibreChat + opencode well-known ([#766](https://github.com/ADORSYS-GIS/ai-helm/issues/766)) ([b246d26](https://github.com/ADORSYS-GIS/ai-helm/commit/b246d26259fa1ddcc2011454a0e85d880ae05114))
* **librechart:** hide internal models from the opencode picker via modelsInfoHideTextOnly ([#800](https://github.com/ADORSYS-GIS/ai-helm/issues/800)) ([5bf9468](https://github.com/ADORSYS-GIS/ai-helm/commit/5bf9468f8e6a0f37a7f304c128553a33b596e264))
* **librechat-opencode-wellknown:** cap reasoning effort at low by default ([fcd9046](https://github.com/ADORSYS-GIS/ai-helm/commit/fcd9046909da3c3e66787078673688a4000bd185))


### Bug Fixes

* **librechat-opencode-wellknown:** bump [@vymalo](https://github.com/vymalo) plugins to 0.11.0, drop modelsInfoHideTextOnly ([#848](https://github.com/ADORSYS-GIS/ai-helm/issues/848)) ([c1eba63](https://github.com/ADORSYS-GIS/ai-helm/commit/c1eba63c7d06aee1d0b7d3bdb6ecd84df4d29858))
* **librechat-opencode-wellknown:** bump [@vymalo](https://github.com/vymalo) plugins to 0.12.0, enable modelsInfoHideUnmatched ([#850](https://github.com/ADORSYS-GIS/ai-helm/issues/850)) ([fa3df68](https://github.com/ADORSYS-GIS/ai-helm/commit/fa3df686dae31bf46706afe3d36806b6bcb94bba))
* **librechat-opencode-wellknown:** drop reasoning caps on Anthropic-via-DeepInfra models ([aa81c5c](https://github.com/ADORSYS-GIS/ai-helm/commit/aa81c5cd947268c69af983223cf09b7d908843d2))


### Documentation

* refresh arc42/architecture (CD + uncolor mermaid) and reorganize the docs tree ([#654](https://github.com/ADORSYS-GIS/ai-helm/issues/654)) ([79ee808](https://github.com/ADORSYS-GIS/ai-helm/commit/79ee808197679c48373d9ac38810856cf0f4213b))
