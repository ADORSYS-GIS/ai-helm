#!/usr/bin/env python3
"""Render a static Envoy bootstrap that mounts the SHIPPED model-policy.lua verbatim.

Reads charts/core-gateway/files/model-policy.lua -- the same bytes the chart embeds in the
EnvoyExtensionPolicy -- so the harness can never drift from what deploys.

Three listeners, so one Envoy run covers all the evidence:
  10000  guarded   -> the script exactly as it ships (pcall guard active)
  10001  raising   -> the same script with error() injected into enforce(), to prove the
                      guard denies instead of passing the request through
  10002  unguarded -> the raising script with the pcall guard removed, to prove the guard
                      is load-bearing (Envoy's own Lua-error default is fail-OPEN)
"""

import pathlib
import sys

HERE = pathlib.Path(__file__).parent
REPO = HERE.parent.parent
SCRIPT = (REPO / "charts/core-gateway/files/model-policy.lua").read_text()

RAISING = SCRIPT.replace(
    "local function enforce(handle)\n  local headers = handle:headers()",
    "local function enforce(handle)\n  error(\"injected fault\")\n  local headers = handle:headers()",
)
assert RAISING != SCRIPT, "fault injection failed to apply"

UNGUARDED_BODY = """
function envoy_on_request(request_handle)
  enforce(request_handle)
end
"""
UNGUARDED = RAISING.split("function envoy_on_request(request_handle)")[0] + UNGUARDED_BODY


def indent(text: str, spaces: int) -> str:
    pad = " " * spaces
    return "\n".join(pad + line if line else pad for line in text.splitlines())


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
          - name: envoy.filters.http.lua
            typed_config:
              "@type": type.googleapis.com/envoy.extensions.filters.http.lua.v3.Lua
              default_source_code:
                inline_string: |
{indent(script, 18)}
          - name: envoy.filters.http.router
            typed_config:
              "@type": type.googleapis.com/envoy.extensions.filters.http.router.v3.Router
"""


config = f"""admin:
  address:
    socket_address: {{address: 0.0.0.0, port_value: 9901}}
static_resources:
  listeners:
{listener("guarded", 10000, SCRIPT)}
{listener("raising", 10001, RAISING)}
{listener("unguarded", 10002, UNGUARDED)}
"""

out = HERE / "envoy.yaml"
out.write_text(config)
print(f"wrote {out} ({len(config)} bytes)", file=sys.stderr)
