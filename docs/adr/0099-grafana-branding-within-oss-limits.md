# ADR-0099: Brand Grafana within OSS limits; do not white-label

**Status:** Accepted
**Date:** 2026-07-27
**Deciders:** @stephane-segning

## Context

Grafana is now the primary window onto the platform — model serving, GPU fleet,
gateway usage and cost — and is used by people outside the platform team. It
should look like an adorsys tool rather than a stock Grafana install.

The assumption going in was that Grafana can be configured for this. It cannot,
not in the way expected, and the constraint has two independent parts that are
worth writing down because both are easy to rediscover the hard way.

**1. White-labeling is Grafana Enterprise.** The `[white_labeling]` configuration
section — custom logo, login background, footer links, application title, favicon
— exists only in Grafana Enterprise. This deployment runs the OSS image
(`grafana/grafana:12.3.1`, verified live). Setting those keys in `grafana.ini` on
OSS is **silently ignored**: no error, no warning, no effect.

**2. This Grafana is stateless, which rules out the UI-level options.**
`persistence.enabled: false` (ADR-0023) means Grafana's SQLite database is an
emptyDir and is destroyed on every pod roll. Anything stored there does not
survive: the **organisation name**, the org's **home dashboard preference**, and
org-level **theme** preference are all database rows. Setting them through the UI
or API appears to work and then silently reverts — arguably worse than not being
able to set them at all.

What remains durable is `grafana.ini` itself, because it is configuration
delivered by the chart, plus anything provisioned through grafana-operator CRs.

## Decision

**Brand what the OSS configuration surface reaches, and stop there. Do not
white-label, and do not fake it by overwriting Grafana's static assets.**

Four changes, all durable across pod rolls:

| Change | Mechanism | Where |
|---|---|---|
| adorsys landing page | `grafana.ini [users] home_page` → a provisioned dashboard | ai-helm-values + ai-helm |
| Default theme pinned | `grafana.ini [users] default_theme: dark` | ai-helm-values |
| No Grafana Labs news feed | `[news] news_feed_enabled: false` | ai-helm-values |
| No phoning home | `[analytics] reporting_enabled / check_for_updates / feedback_links_enabled: false` | ai-helm-values |

The landing page carries the branding the chrome cannot: the adorsys logo in a
text panel, the brand red on stat thresholds, and — more usefully than either —
orientation, since someone opening Grafana is normally looking for the right
dashboard rather than a number.

⚠️ **The home page is set with `[users] home_page`, not the org's home-dashboard
preference**, for the statelessness reason above. `[dashboards]
default_home_dashboard_path` was the other candidate and was rejected: it needs a
JSON file mounted inside the pod, which means a ConfigMap and a mount ordered
before Grafana starts, whereas `home_page` needs only a URL and works with
dashboards already provisioned by grafana-operator.

This creates a **cross-repo contract**: `home_page` in `ai-helm-values` points at
uid `adorsys-platform-home` provisioned from `ai-helm`. The dashboard must exist
first, or every user lands on a 404. Both sides carry a comment saying so.

## Consequences

**Positive**

- Grafana opens on an adorsys page with the logo, brand colour, and links to
  every dashboard — which is most of the felt difference.
- The landing page is dashboards-as-code (ADR-0008), so it survives pod rolls and
  is reviewed like everything else.
- The platform stops pulling grafana.com's news feed into an internal tool and
  stops phoning home for update checks and usage reporting from this cluster.
- The limitation is now written down. The next person who assumes the logo is a
  config setting will find this instead of spending an afternoon on it.

**Negative**

- **The Grafana logo, login page, favicon and browser title remain Grafana's.**
  This is the honest state: the product still identifies as Grafana in the places
  a first-time visitor looks first.
- `home_page` redirects rather than genuinely replacing the home dashboard, so
  the breadcrumb reads as a normal dashboard, not "Home".
- One more cross-repo contract to keep (the dashboard uid).

**Neutral / follow-ups**

- If full white-labeling is genuinely wanted, it is a **licence purchase**, not an
  engineering task. That is a budget conversation with a clear input: Grafana
  Enterprise pricing versus how much the logo matters.
- Should Grafana ever gain persistence, the org name and org preferences become
  available and this ADR should be revisited.

## Alternatives considered

- **Overwrite Grafana's static assets** (mount over
  `/usr/share/grafana/public/img/grafana_icon.svg`, `fav32.png`) — technically
  works today and was explicitly rejected. It is unsupported, it breaks silently
  whenever an image bump renames or re-hashes those assets, it puts a binary blob
  under GitOps, and the failure mode is a broken-image icon in production with no
  alert. Cosmetics are not worth an upgrade-fragile hack in the observability
  stack we rely on during incidents.
- **Inject CSS at the proxy** (Traefik middleware rewriting the HTML) — rejected
  for the same fragility plus a new failure mode in the request path of the tool
  used to debug outages.
- **Fork the Grafana image** with assets replaced — rejected: it makes us
  responsible for rebuilding on every Grafana CVE, which is a real ongoing cost
  for a logo.
- **Buy Grafana Enterprise** — not rejected, deferred. It is the only supported
  route to real white-labeling, and it should be decided on its full feature set
  and price, not bought for branding alone.
- **Set org name / home dashboard via the API on startup** (a Job) — rejected:
  it would have to re-run after every pod roll to survive the emptyDir, which is
  a reconciliation loop we would have to write and maintain for a cosmetic
  setting.

## Related

- Constrained by [ADR-0023](0023-grafana-stateless-no-pvc.md) (stateless Grafana)
- [ADR-0008](0008-python-dashboard-generation.md) — the landing page is generated
- [ADR-0045](0045-scrape-first-dashboard-sourcing.md) — dashboard sourcing policy
- Charts: `charts/observability-dashboards` (dashboard + folder),
  `ai-helm-values` `environments/prod/values/grafana.yaml` (`grafana.ini`)
