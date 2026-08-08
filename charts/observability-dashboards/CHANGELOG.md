# Changelog

## [0.3.0](https://github.com/ADORSYS-GIS/ai-helm/compare/observability-dashboards-v0.2.0...observability-dashboards-v0.3.0) (2026-08-08)


### Features

* **ai-gateway:** align limits and budget observability ([cdb9099](https://github.com/ADORSYS-GIS/ai-helm/commit/cdb9099c76b0ef25af1d9e496603386df456e61c))
* **bservability:** ingest provider billing into grafana for invoice reconciliation ([#926](https://github.com/ADORSYS-GIS/ai-helm/issues/926)) ([ef16565](https://github.com/ADORSYS-GIS/ai-helm/commit/ef16565a37c95b61ffb6ed1e6aa35c1bce8456c9))
* **observability:** add Grafana dashboard PDF export via dashboard-r… ([#902](https://github.com/ADORSYS-GIS/ai-helm/issues/902)) ([69f93fb](https://github.com/ADORSYS-GIS/ai-helm/commit/69f93fb1dd5feb433b6624594c08bd85f5753c10))
* **observability:** add weekly/monthly/raw period filters to cost dashboards ([d1dd5fb](https://github.com/ADORSYS-GIS/ai-helm/commit/d1dd5fbea8e56db7721dfcfce2faf2cb72a86ee2))
* **obsev:** ingest provider billing into grafana for invoice reconciliation ([#929](https://github.com/ADORSYS-GIS/ai-helm/issues/929)) ([fcfde15](https://github.com/ADORSYS-GIS/ai-helm/commit/fcfde157f8236e3817bc7f3843c77cd1b9391e86))


### Bug Fixes

* **dashboards:** My-Usage dashboard modifications ([#856](https://github.com/ADORSYS-GIS/ai-helm/issues/856)) ([1248169](https://github.com/ADORSYS-GIS/ai-helm/commit/1248169f650b04a257e37fe4eefa7f28a3d1963a))
* **observability:** provider billing period format ([#931](https://github.com/ADORSYS-GIS/ai-helm/issues/931)) ([aec8f50](https://github.com/ADORSYS-GIS/ai-helm/commit/aec8f50ea7a013daca80079f8c54f918da23c9b4))
* **webank-training:** require NVIDIA runtime ([#911](https://github.com/ADORSYS-GIS/ai-helm/issues/911)) ([f2861a9](https://github.com/ADORSYS-GIS/ai-helm/commit/f2861a9713f796157a29bd62324a40ce8145bfb9))

## [0.2.0](https://github.com/ADORSYS-GIS/ai-helm/compare/observability-dashboards-v0.1.0...observability-dashboards-v0.2.0) (2026-08-02)


### Features

* **dashboards:** personal usage dashboard with folder-level RBAC (ADR-0077) ([#585](https://github.com/ADORSYS-GIS/ai-helm/issues/585)) ([a7ab6b9](https://github.com/ADORSYS-GIS/ai-helm/commit/a7ab6b9779b6f0b76608ab77ce840365791f74bd))
* **observability-dashboards:** show billing-period rotation on the ratelimit census table ([#865](https://github.com/ADORSYS-GIS/ai-helm/issues/865)) ([3b1c69d](https://github.com/ADORSYS-GIS/ai-helm/commit/3b1c69d31d27617958defe68b369c796e6ae1a70))
* **observability:** adorsys landing dashboard as the Grafana home page ([1342e1b](https://github.com/ADORSYS-GIS/ai-helm/commit/1342e1b6e5b679d928f8f524db5a857acbfeed8a))
* **observability:** alert on models that publish no metrics at all ([7d6a90a](https://github.com/ADORSYS-GIS/ai-helm/commit/7d6a90aac2a4080f189d321208cd3b92b9705be5))
* **observability:** dashboards for both model-serving engines ([9964b68](https://github.com/ADORSYS-GIS/ai-helm/commit/9964b6814d2b64da5e39e0772937b4af2e111ac2))
* **observability:** enable the discord-stephane contact point ([6c2eba9](https://github.com/ADORSYS-GIS/ai-helm/commit/6c2eba9af0330c607a71b71137727f2d9b54e33e))
* **observability:** GPU dashboards + hardware alerts; fix DCGM honorLabels ([03ad783](https://github.com/ADORSYS-GIS/ai-helm/commit/03ad783a32a79fe41a4f749675584d955008fd7e))
* **observability:** GPU telemetry + model-serving alerts to a second Discord ([e5320db](https://github.com/ADORSYS-GIS/ai-helm/commit/e5320dbdc58e3bd564d4f05fb11b604f16c30ec0))
* **observability:** team Discord becomes the default contact point ([d065372](https://github.com/ADORSYS-GIS/ai-helm/commit/d0653723e9c2a2564780d09d4635e00286c19272))


### Bug Fixes

* **observability-dashboards:** calendar-align scoreboard budget-burn queries ([#861](https://github.com/ADORSYS-GIS/ai-helm/issues/861)) ([3077a64](https://github.com/ADORSYS-GIS/ai-helm/commit/3077a64cdf858f460853669427b6a04b07439711))
* **observability-dashboards:** drop model dimension from ratelimit quota board ([#696](https://github.com/ADORSYS-GIS/ai-helm/issues/696)) ([f62e995](https://github.com/ADORSYS-GIS/ai-helm/commit/f62e995a33f938ee82f9efb409114cb6af8689da))
* **observability-dashboards:** fix extractFields format + delimiters on ratelimit census ([#866](https://github.com/ADORSYS-GIS/ai-helm/issues/866)) ([1d8743e](https://github.com/ADORSYS-GIS/ai-helm/commit/1d8743e3f6871b5b85c4fc8c1f247e740471960c))
* **observability:** a missing webhook secret took down ALL alert routing ([516b6d0](https://github.com/ADORSYS-GIS/ai-helm/commit/516b6d077927a92c6d656fa09609bc59e07d6254))
* **observability:** panels rendering nothing on duplicate refIds ([e49629e](https://github.com/ADORSYS-GIS/ai-helm/commit/e49629e3508e0914d344288e8ac413681b4c12f0))
* **observability:** provision webhook secrets even while the contact point is off ([790b131](https://github.com/ADORSYS-GIS/ai-helm/commit/790b13159650134863605a1e4a8ca74056e9df24))
* **observability:** rate-limit quota dashboard filters by calendar billing_period ([cc59ce2](https://github.com/ADORSYS-GIS/ai-helm/commit/cc59ce2004076cfdb803868249e22dbf550a0dce))
* **observability:** rate-limit quota dashboard filters by calendar billing_period ([#862](https://github.com/ADORSYS-GIS/ai-helm/issues/862)) ([cc59ce2](https://github.com/ADORSYS-GIS/ai-helm/commit/cc59ce2004076cfdb803868249e22dbf550a0dce))


### Documentation

* refresh arc42/architecture (CD + uncolor mermaid) and reorganize the docs tree ([#654](https://github.com/ADORSYS-GIS/ai-helm/issues/654)) ([79ee808](https://github.com/ADORSYS-GIS/ai-helm/commit/79ee808197679c48373d9ac38810856cf0f4213b))
