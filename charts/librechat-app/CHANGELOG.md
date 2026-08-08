# Changelog

## [1.2.0](https://github.com/ADORSYS-GIS/ai-helm/compare/librechat-app-v1.1.0...librechat-app-v1.2.0) (2026-08-08)


### Features

* **librechat-code-interpreter:** self-host LibreChat Code Interpreter (ADR-0122) ([#941](https://github.com/ADORSYS-GIS/ai-helm/issues/941)) ([9e14d02](https://github.com/ADORSYS-GIS/ai-helm/commit/9e14d02aa2da38c6213580c60312c6dbabee674c))


### Bug Fixes

* **webank-training:** require NVIDIA runtime ([#911](https://github.com/ADORSYS-GIS/ai-helm/issues/911)) ([f2861a9](https://github.com/ADORSYS-GIS/ai-helm/commit/f2861a9713f796157a29bd62324a40ce8145bfb9))

## [1.1.0](https://github.com/ADORSYS-GIS/ai-helm/compare/librechat-app-v1.0.0...librechat-app-v1.1.0) (2026-08-02)


### Features

* **671:** ticket coder mcp integration working ([#685](https://github.com/ADORSYS-GIS/ai-helm/issues/685)) ([fe2de06](https://github.com/ADORSYS-GIS/ai-helm/commit/fe2de0645980919b1358bd55fb984a0629bb276a))
* connect qwen2-vl-2b to Envoy Gateway and LibreChat ([#721](https://github.com/ADORSYS-GIS/ai-helm/issues/721)) ([86b5a24](https://github.com/ADORSYS-GIS/ai-helm/commit/86b5a242e1171e50e562494f2f5baa37f6464ca4))
* **homepage:** discovery annotations for LibreChat + opencode well-known ([#766](https://github.com/ADORSYS-GIS/ai-helm/issues/766)) ([b246d26](https://github.com/ADORSYS-GIS/ai-helm/commit/b246d26259fa1ddcc2011454a0e85d880ae05114))
* **librechart:** move librechat-app config to ai-helm-values (ADR-0087) ([#728](https://github.com/ADORSYS-GIS/ai-helm/issues/728)) ([ba482bd](https://github.com/ADORSYS-GIS/ai-helm/commit/ba482bdb25303277f0730b06b4da8e51562aa93c))
* **librechat-app:** agent-seed — equip agents with skills + MCP; add security-review skill ([#742](https://github.com/ADORSYS-GIS/ai-helm/issues/742)) ([e472987](https://github.com/ADORSYS-GIS/ai-helm/commit/e47298764fe1d7d46100bb7dd8328a99b182423f))
* **librechat-app:** agent-seed — prune platform-authored agents not in the fleet ([#739](https://github.com/ADORSYS-GIS/ai-helm/issues/739)) ([3a3e842](https://github.com/ADORSYS-GIS/ai-helm/commit/3a3e8420b6dcd3a67ffde7f4d1984b357444fad5))
* **librechat-app:** agent-seed Job + ADR-0088 (system-user author + visibility) ([#733](https://github.com/ADORSYS-GIS/ai-helm/issues/733)) ([c70cb22](https://github.com/ADORSYS-GIS/ai-helm/commit/c70cb22fae74820a952c6634f8da3a07551a34a5))
* **librechat-app:** enable Code Interpreter (LIBRECHAT_CODE_API_KEY via ESO) ([#734](https://github.com/ADORSYS-GIS/ai-helm/issues/734)) ([0345994](https://github.com/ADORSYS-GIS/ai-helm/commit/034599409345c2d948b0d5586a62e0f5febbeb96))
* **librechat-app:** roll pods on config change via a checksum marker (Option A) ([#731](https://github.com/ADORSYS-GIS/ai-helm/issues/731)) ([28c104b](https://github.com/ADORSYS-GIS/ai-helm/commit/28c104b769b8d20c3f8920e120688e3eceb455eb))
* **librechat-app:** sync SKILL.md skills from ai-helm via GitHub skill sync ([#724](https://github.com/ADORSYS-GIS/ai-helm/issues/724)) ([4706da2](https://github.com/ADORSYS-GIS/ai-helm/commit/4706da27f2a59d4a9deb369b0c1c66b31fa54a59))
* **librechat-app:** token config, gateway MCPs, offline_access + agent-fleet ADR ([#722](https://github.com/ADORSYS-GIS/ai-helm/issues/722)) ([ea0c2fe](https://github.com/ADORSYS-GIS/ai-helm/commit/ea0c2fe67b53d54130a724f38ab8aaae265e3788))
* **librechat:** add coder_mcp MCP server(OAuth2, streamable-http). ([#682](https://github.com/ADORSYS-GIS/ai-helm/issues/682)) ([2798659](https://github.com/ADORSYS-GIS/ai-helm/commit/279865923e0d9e6521e32ef965990db1feef67af))


### Bug Fixes

* **librechat-app:** agent-seed — grant ACL by Mongo _id, not public id ([#738](https://github.com/ADORSYS-GIS/ai-helm/issues/738)) ([7d4bed6](https://github.com/ADORSYS-GIS/ai-helm/commit/7d4bed6d73041b09167dc619aeb580cbc5ece5f4))
* **librechat-app:** agent-seed — send a browser User-Agent (uaParser) ([#735](https://github.com/ADORSYS-GIS/ai-helm/issues/735)) ([6fefe29](https://github.com/ADORSYS-GIS/ai-helm/commit/6fefe298d41ff2cd1659c12e5c067425edfd5d1c))
* **librechat-app:** agent-seed — use the generic resource-ACL endpoint ([#736](https://github.com/ADORSYS-GIS/ai-helm/issues/736)) ([d897a28](https://github.com/ADORSYS-GIS/ai-helm/commit/d897a2845be6c3ee8e58461d745329aa1de6f114))
* **librechat-app:** harden LibreChat Deployment securityContext (Trivy KSV-0118) ([#737](https://github.com/ADORSYS-GIS/ai-helm/issues/737)) ([12b733e](https://github.com/ADORSYS-GIS/ai-helm/commit/12b733e745827f89bbb8f06bbe740bc1d07003f7))
* **librechat-app:** serve icon assets from public S3, not the raw GitHub repo ([#725](https://github.com/ADORSYS-GIS/ai-helm/issues/725)) ([ca3e9a2](https://github.com/ADORSYS-GIS/ai-helm/commit/ca3e9a252bcce13b76867747adda6b876c23a640))
