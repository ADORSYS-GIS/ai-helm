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
import sys

HERE = pathlib.Path(__file__).parent
REPO = HERE.parent.parent
SCRIPT = (REPO / "charts/core-gateway/files/budget-limiter.lua").read_text()

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
# published nothing at all", which is a distinct and important input.
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
          route_config:
            name: local
            virtual_hosts:
            - name: all
              domains: ["*"]
              routes:
              - match: {{prefix: "/"}}
                direct_response:
                  status: 200
                  body: {{inline_string: "UPSTREAM-REACHED\\n"}}
          http_filters:
{lua_filter("envoy.filters.http.lua.fake_ext_authz", FAKE_METADATA)}{lua_filter("envoy.filters.http.lua.budget", script)}          - name: envoy.filters.http.router
            typed_config:
              "@type": type.googleapis.com/envoy.extensions.filters.http.router.v3.Router
"""


config = f"""admin:
  address:
    socket_address: {{address: 0.0.0.0, port_value: 9902}}
static_resources:
  listeners:
{listener("enforce", 10100, CONFIG_ENFORCE + SCRIPT)}
{listener("shadow", 10101, CONFIG_SHADOW + SCRIPT)}
{listener("noconfig", 10102, SCRIPT)}
{listener("raising", 10103, CONFIG_ENFORCE + RAISING)}
{listener("unguarded", 10104, CONFIG_ENFORCE + UNGUARDED)}
"""

out = HERE / "envoy.yaml"
out.write_text(config)
print(f"wrote {out} ({len(config)} bytes)", file=sys.stderr)
