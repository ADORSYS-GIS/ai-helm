# Migrations

Permanent record of meaningful one-way changes — cutovers, replatforms, upgrades,
and point-in-time audits. When you delete an app, swap a backing store, rename a
public host, or upgrade a component, add a file here; future-you will not
remember why. See the [docs index](../README.md) for the other categories.

| File | What changed |
|---|---|
| [phoenix-to-tempo.md](phoenix-to-tempo.md) | Arize Phoenix removed; LLM tracing now via Grafana Tempo (ADR-0002) |
| [2026-linode-to-hetzner-cutover.md](2026-linode-to-hetzner-cutover.md) | Linode→Hetzner cutover + domain rename `ai-v2`→`ai` (ADR-0025) |
| [2026-hetzner-cutover.md](2026-hetzner-cutover.md) | Hetzner cutover change-log + live fix-verification status + open items |
| [2026-currency-audit.md](2026-currency-audit.md) | Helm chart + Kubernetes API + tooling currency audit, mid-2026 |
| [2026-06-07-observability-datasource-audit.md](2026-06-07-observability-datasource-audit.md) | Live diagnosis + fixes for Grafana datasource breakages (Tempo port, Loki labels, Mimir ring) |
| [2026-07-31-dns01-route53-delegation-audit.md](2026-07-31-dns01-route53-delegation-audit.md) | ✅ Resolved 2026-08-23 — `cert-route53` ClusterIssuer shipped (home-os#138/#139); `traefik/ai-certificate` deleted as dead config, not reissued (home-os#140/#141). Root cause + remediation options + resolution |
| [2026-06-10-mcp-external-server-proxy-debug.md](2026-06-10-mcp-external-server-proxy-debug.md) | External-MCP-through-gateway failures + the AIEG v0.6.0→v0.7.0 upgrade + repro |
| [architectural-shift-main-to-magical-bohr.md](architectural-shift-main-to-magical-bohr.md) | The full `main → claude/magical-bohr-390242` shift (8 shifts) — **historical** |
