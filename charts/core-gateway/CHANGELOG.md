# Changelog

## [0.4.0](https://github.com/ADORSYS-GIS/ai-helm/compare/core-gateway-v0.3.0...core-gateway-v0.4.0) (2026-09-02)


### Features

* **core-gateway:** add additive weekly sub-budget to stop front-loading ([#909](https://github.com/ADORSYS-GIS/ai-helm/issues/909)) ([bc1c5dc](https://github.com/ADORSYS-GIS/ai-helm/commit/bc1c5dc7c5ca9f0aa92c0ccfa9fccc5458e5b40e))
* **core-gateway:** add debug exporter to both otel collectors ([8666636](https://github.com/ADORSYS-GIS/ai-helm/commit/8666636442477887acff27ecc24acc7cd30f25ab))
* **core-gateway:** add debug exporter to both otel collectors ([9e0b382](https://github.com/ADORSYS-GIS/ai-helm/commit/9e0b38295963e0756aba0d132c425fd293115411))
* **core-gateway:** enforce the per-project model allowlist in a Lua filter ([#1039](https://github.com/ADORSYS-GIS/ai-helm/issues/1039)) ([c23aafc](https://github.com/ADORSYS-GIS/ai-helm/commit/c23aafc4258e096a290c2c8e2fcab239bcfcfe69))
* **core-gateway:** make redactExtproc a values-repo toggle, not a chart release ([#908](https://github.com/ADORSYS-GIS/ai-helm/issues/908)) ([e1d9b7f](https://github.com/ADORSYS-GIS/ai-helm/commit/e1d9b7f45eb6cc21192ab1cb4f5c3e5a91592975))
* **core-gateway:** restore access-log fan-out to lightbridge-authz-usage ([#1008](https://github.com/ADORSYS-GIS/ai-helm/issues/1008)) ([dd41417](https://github.com/ADORSYS-GIS/ai-helm/commit/dd4141753bd97d60e1838ee73056de8bd6e38ca5))
* **core-gateway:** wire the redact-extproc sidecar (ADR-0116) ([#900](https://github.com/ADORSYS-GIS/ai-helm/issues/900)) ([e7ea902](https://github.com/ADORSYS-GIS/ai-helm/commit/e7ea902447a783795e8531f4d15d745ea73643cd))


### Bug Fixes

* **core-gateway:** add missing -collector suffix to usage otel accessLog sink ([#1010](https://github.com/ADORSYS-GIS/ai-helm/issues/1010)) ([4ec9667](https://github.com/ADORSYS-GIS/ai-helm/commit/4ec966767b3137fb9fb450e82365c3c3a11b1c9f))
* **core-gateway:** merge the redact ext_proc filter into ONE EnvoyExtensionPolicy ([#903](https://github.com/ADORSYS-GIS/ai-helm/issues/903)) ([0c22d79](https://github.com/ADORSYS-GIS/ai-helm/commit/0c22d79fde2ae1f1db863f45a96dd9bd1e72cd3d))
* **core-gateway:** put the redact-extproc secret in the DATA-PLANE namespace ([#901](https://github.com/ADORSYS-GIS/ai-helm/issues/901)) ([3a72b92](https://github.com/ADORSYS-GIS/ai-helm/commit/3a72b922897a8646b03cd9dc044b1de70b67a22c))
* **core-gateway:** responseHoldBackBytes was silently overriding the upstream fix ([#936](https://github.com/ADORSYS-GIS/ai-helm/issues/936)) ([e6f96db](https://github.com/ADORSYS-GIS/ai-helm/commit/e6f96db118f4946246e09d996fef1d56a6fb0c56))
* **core-gateway:** stop collateral-dropping small spans on the traces collector ([1f75a84](https://github.com/ADORSYS-GIS/ai-helm/commit/1f75a8433d19939935d96823dd3058cfe9ffc884))
* **core-gateway:** stop collateral-dropping small spans on the traces collector ([a6e4791](https://github.com/ADORSYS-GIS/ai-helm/commit/a6e47919d81a62f84b54e40c56f667a5dc556ec6))
* **core-gateway:** stop hardcoding redact-extproc image tag in chart ([#906](https://github.com/ADORSYS-GIS/ai-helm/issues/906)) ([700c3d1](https://github.com/ADORSYS-GIS/ai-helm/commit/700c3d18492ad095dc5d82d0410a42a2f76d9490))
* **core-gateway:** use send_batch_size: 1, not an invalid max_size cap ([1b16b2e](https://github.com/ADORSYS-GIS/ai-helm/commit/1b16b2e9c348e9cbc5b2b7923bd0f081f88c9171))
* **otel:** raise traces collector memory_limiter for larger multimodal spans ([#1013](https://github.com/ADORSYS-GIS/ai-helm/issues/1013)) ([f57625c](https://github.com/ADORSYS-GIS/ai-helm/commit/f57625c6c702b35818117021943d6c4b52c32b1e))
* **redact-proc:** fix replace streamed with buffered ([#905](https://github.com/ADORSYS-GIS/ai-helm/issues/905)) ([2493483](https://github.com/ADORSYS-GIS/ai-helm/commit/2493483bb1925e42b115437981cf10392ec44ae4))
* **webank-training:** require NVIDIA runtime ([#911](https://github.com/ADORSYS-GIS/ai-helm/issues/911)) ([f2861a9](https://github.com/ADORSYS-GIS/ai-helm/commit/f2861a9713f796157a29bd62324a40ce8145bfb9))


### Documentation

* **core-gateway:** clarify debug.enabled scope vs internal log level ([3db7d25](https://github.com/ADORSYS-GIS/ai-helm/commit/3db7d255acbdd7105313f4346caa69648a12e94b))

## [0.3.0](https://github.com/ADORSYS-GIS/ai-helm/compare/core-gateway-v0.2.0...core-gateway-v0.3.0) (2026-08-02)


### Features

* **ai-models:** restore the $50 free tier and remove per-minute limiting ([893b848](https://github.com/ADORSYS-GIS/ai-helm/commit/893b848e2a535f4cd91979bc65dbd4d8579a4e0f))
* **rate-limit:** add enterprise billing tier for lightbridge API-key plans ([#663](https://github.com/ADORSYS-GIS/ai-helm/issues/663)) ([8edaa90](https://github.com/ADORSYS-GIS/ai-helm/commit/8edaa906994a6beccce25ca3d59169c3ceeebbfa))


### Bug Fixes

* **core-gateway:** calendar-align monthly budget windows (ADR-0111) ([#859](https://github.com/ADORSYS-GIS/ai-helm/issues/859)) ([b6d240e](https://github.com/ADORSYS-GIS/ai-helm/commit/b6d240e23e2cdfb7a1ae234fe3a53562e35b3a1c))
* **core-gateway:** make rate-limit plan order append-only, not sorted (ADR-0084) ([#695](https://github.com/ADORSYS-GIS/ai-helm/issues/695)) ([057555e](https://github.com/ADORSYS-GIS/ai-helm/commit/057555ed54ce38cf8b909ec629fa716a9b035dcc))
* **core-gateway:** unit Year so billing period is the only rotation (ADR-0112) ([#869](https://github.com/ADORSYS-GIS/ai-helm/issues/869)) ([196702d](https://github.com/ADORSYS-GIS/ai-helm/commit/196702d5dd5d61b7b411a8f3ce545d5e2500b5f5))


### Performance

* **core-gateway:** make trace sampling configurable, default 1% ([ba16e5e](https://github.com/ADORSYS-GIS/ai-helm/commit/ba16e5e8746b18936493fdb63dfce65a6b4a8f9e))


### Documentation

* refresh arc42/architecture (CD + uncolor mermaid) and reorganize the docs tree ([#654](https://github.com/ADORSYS-GIS/ai-helm/issues/654)) ([79ee808](https://github.com/ADORSYS-GIS/ai-helm/commit/79ee808197679c48373d9ac38810856cf0f4213b))

## [0.2.0](https://github.com/ADORSYS-GIS/ai-helm/compare/core-gateway-0.1.0...core-gateway-v0.2.0) (2026-07-10)


### Features

* **core-gateway:** trace-log correlation + scoped AI Gateway tracing ([#630](https://github.com/ADORSYS-GIS/ai-helm/issues/630)) ([7b77cc9](https://github.com/ADORSYS-GIS/ai-helm/commit/7b77cc9996f8a41d6e4d4764778a2e7edb977bb3))


### Bug Fixes

* **core-gateway:** trace all gateway traffic — per-route sampling doesn't exist ([#632](https://github.com/ADORSYS-GIS/ai-helm/issues/632)) ([d8162e4](https://github.com/ADORSYS-GIS/ai-helm/commit/d8162e4f35b5917fcccf1e9aa745e111ff2bf7df))
