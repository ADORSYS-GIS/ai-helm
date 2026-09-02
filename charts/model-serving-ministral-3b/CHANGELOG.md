# Changelog

## [0.1.2](https://github.com/ADORSYS-GIS/ai-helm/compare/model-serving-ministral-3b-v0.1.1...model-serving-ministral-3b-v0.1.2) (2026-09-02)


### Bug Fixes

* **webank-training:** require NVIDIA runtime ([#911](https://github.com/ADORSYS-GIS/ai-helm/issues/911)) ([f2861a9](https://github.com/ADORSYS-GIS/ai-helm/commit/f2861a9713f796157a29bd62324a40ce8145bfb9))

## [0.1.1](https://github.com/ADORSYS-GIS/ai-helm/compare/model-serving-ministral-3b-v0.1.0...model-serving-ministral-3b-v0.1.1) (2026-08-02)


### Bug Fixes

* **model-serving:** Caddy exec crashloop take 3 — no seccomp (baseline PSS) ([#745](https://github.com/ADORSYS-GIS/ai-helm/issues/745)) ([c80a4f1](https://github.com/ADORSYS-GIS/ai-helm/commit/c80a4f14f66d02046e3379f032e8532ba50d704b))
* **model-serving:** Caddy exec crashloop take 4 — no securityContext at all ([#746](https://github.com/ADORSYS-GIS/ai-helm/issues/746)) ([4eb4c92](https://github.com/ADORSYS-GIS/ai-helm/commit/4eb4c92b14a3249fe9f6a68dea3915d3e85b0904))
* **model-serving:** Caddy exec crashloop, take 2 — seccomp also sets no_new_privs ([#744](https://github.com/ADORSYS-GIS/ai-helm/issues/744)) ([b0c6956](https://github.com/ADORSYS-GIS/ai-helm/commit/b0c69561f2d7c0c5d0879c5e8111d49729948563))
* **model-serving:** Caddy sidecar exec crashloop (fcap + no_new_privs) ([#743](https://github.com/ADORSYS-GIS/ai-helm/issues/743)) ([fa110ba](https://github.com/ADORSYS-GIS/ai-helm/commit/fa110baaa3906981718a16d348a0f10d8b69474a))
* **model-serving:** remove the redundant Caddy sidecar from the vLLM charts ([#747](https://github.com/ADORSYS-GIS/ai-helm/issues/747)) ([ffb1999](https://github.com/ADORSYS-GIS/ai-helm/commit/ffb1999c86f8778297e8d1d51ab207163f5f7f7a))
* **security:** render-then-scan Trivy gate + harden the &gt;=1.28 charts ([#741](https://github.com/ADORSYS-GIS/ai-helm/issues/741)) ([2ad9815](https://github.com/ADORSYS-GIS/ai-helm/commit/2ad981560b190ae09bf7f5b5719109cee490ec9b))


### Documentation

* refresh arc42/architecture (CD + uncolor mermaid) and reorganize the docs tree ([#654](https://github.com/ADORSYS-GIS/ai-helm/issues/654)) ([79ee808](https://github.com/ADORSYS-GIS/ai-helm/commit/79ee808197679c48373d9ac38810856cf0f4213b))
