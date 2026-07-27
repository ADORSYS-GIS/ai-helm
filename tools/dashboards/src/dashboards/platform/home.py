"""adorsys AI Platform — the landing dashboard (GENERATED SOURCE).

Grafana's home page. Reached because `grafana.ini` `[users] home_page` points at
this dashboard's URL, which is the only mechanism available to us: the usual
route — setting a home dashboard in the org's preferences — is stored in
Grafana's database, and this Grafana runs **stateless** (`persistence.enabled:
false`, ADR-0023), so anything written to that database is lost on every pod
roll. `[dashboards] default_home_dashboard_path` is the other option and needs a
JSON file inside the pod; `home_page` needs nothing but a URL, so it wins.

Deliberately an ORIENTATION page rather than a metrics wall. Someone landing here
is usually trying to find the right dashboard, not read a number — so it leads
with links, and carries only the few live figures that answer "is the platform
up?" at a glance. The detailed boards do the detail.

Branding note: adorsys colours are applied where Grafana OSS allows it — panel
text and thresholds — not chrome. Logo, login page and app title are Grafana
Enterprise features; see ADR-0099.

    uv run dashboards build

ADR: ADR-0008 (Python dashboard generation), ADR-0099 (branding).
"""

from __future__ import annotations

import json

from grafana_foundation_sdk.builders import common as cb
from grafana_foundation_sdk.builders import dashboard as db
from grafana_foundation_sdk.builders import prometheus, stat, text
from grafana_foundation_sdk.cog.encoder import JSONEncoder
from grafana_foundation_sdk.models import common as cm
from grafana_foundation_sdk.models import dashboard as dm
from grafana_foundation_sdk.models import text as tm

from dashboards._common import MIMIR_UID

OUTPUT_PATH: str = "charts/observability-dashboards/files/platform/home.json"

MIMIR_DS = dm.DataSourceRef(type_val="prometheus", uid=MIMIR_UID)

# The UID is a CONTRACT: `grafana.ini` `[users] home_page` in ai-helm-values
# points at /d/<this uid>/. Changing it silently breaks the home page.
DASHBOARD_UID = "adorsys-platform-home"

# adorsys brand red, used for threshold/accent colour where OSS Grafana permits.
BRAND = "#e2001a"


def _prom(expr, *, legend="", ref_id="A", instant=True):
    q = prometheus.Dataquery().expr(expr).ref_id(ref_id).datasource(MIMIR_DS)
    q = q.instant() if instant else q.range()
    if legend:
        q = q.legend_format(legend)
    return q


def _thresholds(*colors):
    steps = [dm.Threshold(color=c, value=v) for c, v in colors]
    return db.ThresholdsConfig().mode(dm.ThresholdsMode.ABSOLUTE).steps(steps)


def _stat(*, title, expr, unit, grid, thresholds, legend=""):
    h, w, x, y = grid
    return (
        stat.Panel()
        .title(title)
        .datasource(MIMIR_DS)
        .grid_pos(dm.GridPos(h=h, w=w, x=x, y=y))
        .unit(unit)
        .thresholds(thresholds)
        .reduce_options(cb.ReduceDataOptions().calcs(["lastNotNull"]).fields("").values(False))
        .text_mode(cm.BigValueTextMode.AUTO)
        .color_mode(cm.BigValueColorMode.VALUE)
        .graph_mode(cm.BigValueGraphMode.NONE)
        .with_target(_prom(expr, legend=legend))
    )


def _text(*, title, content, grid):
    h, w, x, y = grid
    return (
        text.Panel()
        .title(title)
        .grid_pos(dm.GridPos(h=h, w=w, x=x, y=y))
        .mode(tm.TextMode.MARKDOWN)
        .content(content)
    )


_HEADER = """
<div style="display:flex;align-items:center;gap:16px">
  <img src="https://avatars.githubusercontent.com/u/1760904?s=280&v=4"
       alt="adorsys" style="height:56px;border-radius:8px"/>
  <div>
    <div style="font-size:22px;font-weight:600;line-height:1.2">adorsys · AI Platform</div>
    <div style="opacity:.7">Camer Digital — gateway, models and the GPU fleet</div>
  </div>
</div>
"""

_NAV_MODELS = """
### Model serving

- [**GPU Fleet** — cards and the models on them](/d/gpu-fleet-attribution/)
- [**vLLM Inference**](/d/vllm-perf-dashboard/) — the fast tier
- [**llama.cpp Inference**](/d/llamacpp-perf-dashboard/) — the quality tier
- [**NVIDIA DCGM**](/d/nvidia-dcgm-12239/) — per-card health

Two GPUs, one model each. A third enabled model queues rather than sharing a card.
"""

# ⚠️ These UIDs are a contract with the other generators — they were taken from
# the built JSON, not guessed. Four of them were wrong on the first pass and
# produced dead links on the home page; `uv run dashboards build` then checking
# `.uid` in charts/observability-dashboards/files/*/*.json is how to confirm.
_NAV_GATEWAY = """
### Gateway & usage

- [**My usage**](/d/my-usage/) — your own spend
- [**Cost by model**](/d/envoy-ai-gateway-cost-by-model/) · [**Users: tokens & cost**](/d/envoy-ai-gateway-user-tokens-cost/)
- [**Chat overview**](/d/envoy-ai-gateway-chat-overview/) · [**Chats by user**](/d/envoy-ai-gateway-chats-by-user/)
- [**Rate-limit quota**](/d/envoy-ai-gateway-ratelimit-quota/) — live budget counters
- [**App scoreboard**](/d/envoy-ai-gateway-scoreboard/) · [**User directory**](/d/envoy-ai-gateway-user-directory/)

Every model — SaaS or self-hosted — is reached through one gateway, which is where
identity, budgets, rate limits and metering are applied.
"""

_NAV_HELP = """
### Where things are documented

- **`inference-ops`** — how to add, replace, measure or roll back a model;
  runbooks; benchmark reports; the GPU fleet reference.
- **`ai-helm`** — the charts and the ADRs behind them.

A model is a ~15-line catalog entry (ADR-0094). If you are about to copy a chart,
stop and read that ADR first.
"""


def _dashboard():
    return (
        db.Dashboard("adorsys · AI Platform")
        .uid(DASHBOARD_UID)
        .tags(["platform", "home", "adorsys"])
        .description(
            "Landing page for the AI platform. Orientation first: where the "
            "dashboards are and where things are documented, plus the handful of "
            "figures that answer 'is it up?'. Set as the Grafana home page via "
            "grafana.ini [users] home_page — org preferences cannot be used "
            "because this Grafana is stateless (ADR-0023). "
            "GENERATED — source: tools/dashboards/src/dashboards/platform/home.py."
        )
        .timezone("browser")
        .editable()
        .refresh("1m")
        .time("now-6h", "now")
        .with_panel(_text(title="", content=_HEADER, grid=(4, 24, 0, 0)))
        # ── Is it up? ───────────────────────────────────────────────────────
        # `or vector(0)` on the model count: if the scrape targets disappear the
        # bare query returns no data and the panel reads "No data" rather than 0,
        # which is the one case worth noticing.
        .with_panel(
            _stat(
                title="Models serving",
                expr='count(up{namespace="inference"} == 1) or vector(0)',
                unit="short",
                grid=(4, 6, 0, 4),
                thresholds=_thresholds(("red", None), ("green", 1)),
            )
        )
        .with_panel(
            _stat(
                title="GPUs reporting",
                expr="count(DCGM_FI_DEV_GPU_TEMP) or vector(0)",
                unit="short",
                grid=(4, 6, 6, 4),
                thresholds=_thresholds(("red", None), ("green", 2)),
            )
        )
        .with_panel(
            _stat(
                title="Hottest GPU",
                expr="max(DCGM_FI_DEV_GPU_TEMP) or vector(0)",
                unit="celsius",
                grid=(4, 6, 12, 4),
                thresholds=_thresholds(("green", None), ("yellow", 75), (BRAND, 85)),
            )
        )
        .with_panel(
            _stat(
                title="Busiest card (VRAM)",
                expr="max(DCGM_FI_DEV_FB_USED) or vector(0)",
                unit="decmbytes",
                grid=(4, 6, 18, 4),
                thresholds=_thresholds(("green", None), ("yellow", 17000), (BRAND, 19500)),
            )
        )
        # ── Orientation ─────────────────────────────────────────────────────
        .with_panel(_text(title="", content=_NAV_MODELS, grid=(9, 8, 0, 8)))
        .with_panel(_text(title="", content=_NAV_GATEWAY, grid=(9, 8, 8, 8)))
        .with_panel(_text(title="", content=_NAV_HELP, grid=(9, 8, 16, 8)))
    )


def build():
    return json.loads(json.dumps(_dashboard().build(), cls=JSONEncoder))
