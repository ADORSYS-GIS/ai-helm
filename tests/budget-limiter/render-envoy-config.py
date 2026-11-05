#!/usr/bin/env python3
"""Render a static Envoy bootstrap that mounts the SHIPPED budget-limiter.lua verbatim.

Reads charts/core-gateway/files/budget-limiter.lua — the same bytes the chart embeds in the
EnvoyExtensionPolicy — so the harness can never drift from what deploys.

The filter reads ext_authz DYNAMIC METADATA, not headers, so a real Authorino would normally be
required to produce any input at all. Instead a FAKE METADATA SOURCE runs ahead of it on every
listener: a tiny Lua filter that reads `x-test-budget` (a JSON-ish spec) and writes the
corresponding table into the `envoy.filters.http.ext_authz` namespace under the key `budget`,
exactly as Authorino's `response.success.dynamicMetadata` does. That filter exists only here; it is
not part of anything that deploys, and it is deliberately the only difference between this harness
and production.

THE ACCESS LOG IS THE CHART'S OWN. Every listener carries an access log whose JSON format and
`matches` predicate are lifted out of `helm template` of this repo's charts/core-gateway with
`budgetLimiter.enabled=true` — the same `format.json` (all ~55 fields, including the four
`%DYNAMIC_METADATA(lightbridge.budget_limiter:…)%` operators ai-helm#1097 added) that
templates/envoy-proxy.yaml hands Envoy Gateway. Two differences from prod, both deliberate and
both irrelevant to what is being asserted:
  * the sink is a FILE logger on stdout, not the OTLP/gRPC sink (`docker logs` is the collector).
    Envoy's substitution-format operators are parsed and validated identically for every sink;
    only the rendering of an ABSENT value differs — a typed JSON sink writes `null`, prod's OTel
    attribute sink stringifies to `-` (which is what the incident rows showed).
  * `preserve_external_request_id: true`, so a test can correlate its own `x-request-id` to a log
    row. Prod lets Envoy mint the id; nothing in the filter reads it.

Five listeners, so one Envoy run covers all the evidence:
  10100  enforce    -> the script as it ships, BUDGET_LIMITER_CONFIG.shadow = false
  10101  shadow     -> the same script, shadow = true (must refuse nothing, ever)
  10102  noconfig   -> the same script with NO config table at all: proves the safe default is
                      shadow, so a templating mistake cannot start refusing paid traffic
  10103  raising    -> enforce, with error() injected into enforce(), to prove the pcall guard
                      refuses instead of passing the request through
  10104  unguarded  -> the raising script with the pcall guard removed, to prove the guard is
                      load-bearing (Envoy's own Lua-error default is fail-OPEN)
"""

import pathlib
import subprocess
import sys

import yaml

HERE = pathlib.Path(__file__).parent
REPO = HERE.parent.parent
CHART = REPO / "charts/core-gateway"
SCRIPT = (CHART / "files/budget-limiter.lua").read_text()

RAISING = SCRIPT.replace(
    "local function enforce(handle)\n  local budget = budgetMetadata(handle)",
    'local function enforce(handle)\n  error("injected fault")\n  local budget = budgetMetadata(handle)',
)
assert RAISING != SCRIPT, "fault injection failed to apply"

UNGUARDED_BODY = """
function envoy_on_request(request_handle)
  enforce(request_handle)
end
"""
UNGUARDED = RAISING.split("function envoy_on_request(request_handle)")[0] + UNGUARDED_BODY

# The fake Authorino. `x-test-budget` is a comma-separated k=v list; absent means "the AuthConfig
# published nothing at all", which is a distinct and important input. An EMPTY value (`k=`) is the
# empty string — the shape both prod AuthConfigs publish for `next_reset_at`/`account_id` when
# there is nothing to say.
FAKE_METADATA = """
function envoy_on_request(request_handle)
  local spec = request_handle:headers():get("x-test-budget")
  if spec == nil or spec == "" then
    return
  end
  local budget = {}
  for pair in spec:gmatch("[^,]+") do
    local k, v = pair:match("^%s*([%w_]+)%s*=%s*(.-)%s*$")
    if k ~= nil then
      if v == "true" then
        budget[k] = true
      elseif v == "false" then
        budget[k] = false
      elseif tonumber(v) ~= nil then
        budget[k] = tonumber(v)
      else
        budget[k] = v
      end
    end
  end
  request_handle:streamInfo():dynamicMetadata():set(
    "envoy.filters.http.ext_authz", "budget", budget)
end
"""

CONFIG_ENFORCE = 'BUDGET_LIMITER_CONFIG = { shadow = false, refill_url = "https://example.test/budget" }\n'
CONFIG_SHADOW = 'BUDGET_LIMITER_CONFIG = { shadow = true, refill_url = "https://example.test/budget" }\n'


def access_log_setting() -> dict:
    """The chart's rendered `EnvoyProxy.spec.telemetry.accessLog.settings[0]`, limiter ON."""
    out = subprocess.run(
        ["helm", "template", "core-gateway", str(CHART), "-n", "envoy-gateway-system",
         "--set", "budgetLimiter.enabled=true"],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        sys.exit(f"helm template failed:\n{out.stderr}")
    for doc in yaml.safe_load_all(out.stdout):
        if doc and doc.get("kind") == "EnvoyProxy":
            settings = doc["spec"]["telemetry"]["accessLog"]["settings"]
            assert len(settings) == 1, settings
            return settings[0]
    sys.exit("no EnvoyProxy in the rendered chart")


SETTING = access_log_setting()
assert SETTING["format"]["type"] == "JSON", SETTING["format"]
FORMAT_JSON = SETTING["format"]["json"]
assert "budget.decision" in FORMAT_JSON, "the limiter's access-log fields did not render"
(MATCH_CEL,) = SETTING["matches"]


def indent(text: str, spaces: int) -> str:
    pad = " " * spaces
    return "\n".join(pad + line if line else pad for line in text.splitlines())


def lua_filter(name: str, script: str) -> str:
    return f"""          - name: {name}
            typed_config:
              "@type": type.googleapis.com/envoy.extensions.filters.http.lua.v3.Lua
              default_source_code:
                inline_string: |
{indent(script, 18)}
"""


def access_log() -> str:
    fmt = yaml.safe_dump(FORMAT_JSON, default_flow_style=False, sort_keys=False)
    return f"""          access_log:
          - name: envoy.access_loggers.file
            filter:
              extension_filter:
                name: envoy.access_loggers.extension_filters.cel
                typed_config:
                  "@type": type.googleapis.com/envoy.extensions.access_loggers.filters.cel.v3.ExpressionFilter
                  expression: {MATCH_CEL!r}
            typed_config:
              "@type": type.googleapis.com/envoy.extensions.access_loggers.file.v3.FileAccessLog
              path: /dev/stdout
              log_format:
                json_format:
{indent(fmt, 18)}
"""


def listener(name: str, port: int, script: str) -> str:
    return f"""  - name: {name}
    address:
      socket_address: {{address: 0.0.0.0, port_value: {port}}}
    filter_chains:
    - filters:
      - name: envoy.filters.network.http_connection_manager
        typed_config:
          "@type": type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager
          stat_prefix: {name}
          preserve_external_request_id: true
{access_log()}          route_config:
            name: local
            virtual_hosts:
            - name: all
              domains: ["*"]
              routes:
              - match: {{prefix: "/"}}
                route: {{cluster: upstream}}
          http_filters:
{lua_filter("envoy.filters.http.lua.fake_ext_authz", FAKE_METADATA)}{lua_filter("envoy.filters.http.lua.budget", script)}          - name: envoy.filters.http.router
            typed_config:
              "@type": type.googleapis.com/envoy.extensions.filters.http.router.v3.Router
"""


# The fake model backend: its own listener, reached through a real cluster, so an allowed request
# is `response_code_details: via_upstream` exactly as in prod — and NOT `direct_response`. That
# distinction is the incident's whole signature (ai-helm-values#367: 500 + `direct_response`
# means Envoy Gateway's ROUTER answered because the controller rewrote the route; no filter was
# involved), so the harness must not blur it by serving the upstream as a direct response itself.
UPSTREAM = """  - name: upstream
    address:
      socket_address: {address: 127.0.0.1, port_value: 10199}
    filter_chains:
    - filters:
      - name: envoy.filters.network.http_connection_manager
        typed_config:
          "@type": type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager
          stat_prefix: upstream
          route_config:
            name: local
            virtual_hosts:
            - name: all
              domains: ["*"]
              routes:
              - match: {prefix: "/"}
                direct_response:
                  status: 200
                  body: {inline_string: "UPSTREAM-REACHED\\n"}
          http_filters:
          - name: envoy.filters.http.router
            typed_config:
              "@type": type.googleapis.com/envoy.extensions.filters.http.router.v3.Router
"""

config = f"""admin:
  address:
    socket_address: {{address: 0.0.0.0, port_value: 9902}}
static_resources:
  clusters:
  - name: upstream
    type: STATIC
    load_assignment:
      cluster_name: upstream
      endpoints:
      - lb_endpoints:
        - endpoint:
            address:
              socket_address: {{address: 127.0.0.1, port_value: 10199}}
  listeners:
{UPSTREAM}
{listener("enforce", 10100, CONFIG_ENFORCE + SCRIPT)}
{listener("shadow", 10101, CONFIG_SHADOW + SCRIPT)}
{listener("noconfig", 10102, SCRIPT)}
{listener("raising", 10103, CONFIG_ENFORCE + RAISING)}
{listener("unguarded", 10104, CONFIG_ENFORCE + UNGUARDED)}
"""

out = HERE / "envoy.yaml"
out.write_text(config)
print(f"wrote {out} ({len(config)} bytes; access-log format has {len(FORMAT_JSON)} fields)", file=sys.stderr)
