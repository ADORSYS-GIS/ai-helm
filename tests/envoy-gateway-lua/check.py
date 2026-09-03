#!/usr/bin/env python3
"""Run Envoy Gateway's OWN translator over the rendered core-gateway chart.

Why this exists — the 2026-09-03 gateway outage (ai-helm-values#367 / #368).

A `lua` entry on an EnvoyExtensionPolicy is not just shipped to the data plane. Envoy Gateway's
CONTROL PLANE executes it first, in gopher-lua, against mock stream handles, under
`internal/gatewayapi/luavalidator` — `LuaValidation: Strict` is the default and this chart does
not set `EnvoyProxy.spec.luaValidation`. That sandbox nils `rawget`, `rawset`, `setmetatable`,
`getmetatable`, `load`, `loadstring`, `require`, `dofile`, `loadfile`, `package`, `debug` and
`_G`. A script that uses any of them loads fine in Envoy's LuaJIT and is REJECTED by the
controller.

The consequence is not "the filter is skipped". `buildLuas` returning an error makes EG rewrite
**every route on the targeted Gateway** to `directResponse: 500`
(`internal/gatewayapi/envoyextensionpolicy.go`: *"Lua extension doesn't have a fail open option,
so fail the route if there is a lua error"*). The whole gateway answers 500 with
`response_code_details: direct_response`, and the proxy logs nothing about Lua because it never
loaded a Lua filter at all.

`tests/budget-limiter/` and `tests/model-policy/` replay the shipped `.lua` through a real Envoy.
Neither can see this: the failure is upstream of Envoy, in the controller. This is the check that
can — it is EG's real translator at the pinned version, not a re-implementation.

Asserts, for every case:
  1. every EnvoyExtensionPolicy is `Accepted: True`
  2. no route in the IR carries `directResponse.statusCode: 500`

Invoked by run.sh, which supplies the egctl binary.
"""

from __future__ import annotations

import copy
import json
import pathlib
import subprocess
import sys
import tempfile

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
CHART = REPO / "charts" / "core-gateway"

# Cluster-scoped or Gateway-scoped inputs egctl needs; everything else the chart renders
# (Certificates, PodMonitors, collectors…) is noise the translator does not read.
KINDS = {"GatewayClass", "Gateway", "EnvoyProxy", "EnvoyExtensionPolicy", "Backend"}

# A stand-in for the model routes the ai-model chart attaches to this Gateway. Its only job is to
# be a route that EG can rewrite to a 500 direct response, which is the symptom being asserted on.
PROBE = yaml.safe_load(
    """
- apiVersion: gateway.networking.k8s.io/v1
  kind: HTTPRoute
  metadata:
    name: probe-chat-completions
    namespace: envoy-gateway-system
  spec:
    parentRefs:
      - name: core-gateway
        namespace: envoy-gateway-system
    rules:
      - matches:
          - path:
              type: PathPrefix
              value: /v1/chat/completions
        backendRefs:
          - name: probe-upstream
            port: 80
- apiVersion: v1
  kind: Service
  metadata:
    name: probe-upstream
    namespace: envoy-gateway-system
  spec:
    ports:
      - port: 80
        protocol: TCP
        targetPort: 80
"""
)


def render(sets: list[str]) -> list[dict]:
    cmd = ["helm", "template", "core-gateway", str(CHART), "-n", "envoy-gateway-system"]
    for s in sets:
        cmd += ["--set", s]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"helm template failed:\n{out.stderr}")
    docs = [d for d in yaml.safe_load_all(out.stdout) if d and d.get("kind") in KINDS]
    for d in docs:
        if d["kind"] == "GatewayClass":
            # cluster-scoped; the chart stamps a namespace that egctl rejects
            d["metadata"].pop("namespace", None)
    return docs + copy.deepcopy(PROBE)


def translate(egctl: str, docs: list[dict]) -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
        yaml.safe_dump_all(docs, fh, default_flow_style=False)
        path = fh.name
    out = subprocess.run(
        [egctl, "x", "translate", "--from", "gateway-api", "--to", "gateway-api,ir",
         "-o", "json", "-f", path, "-n", "envoy-gateway-system"],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        sys.exit(f"egctl x translate failed:\n{out.stderr}")
    return json.loads(out.stdout)


def lua_entry_count(docs: list[dict]) -> int:
    return sum(len((d.get("spec") or {}).get("lua") or []) for d in docs
               if d["kind"] == "EnvoyExtensionPolicy")


def failures(result: dict) -> list[str]:
    problems: list[str] = []

    for pol in result.get("envoyExtensionPolicies") or []:
        name = pol["metadata"]["name"]
        for anc in (pol.get("status") or {}).get("ancestors") or []:
            for cond in anc.get("conditions") or []:
                if cond.get("type") == "Accepted" and cond.get("status") != "True":
                    problems.append(
                        f"EnvoyExtensionPolicy/{name} Accepted={cond.get('status')} "
                        f"({cond.get('reason')}): {' '.join((cond.get('message') or '').split())}"
                    )

    for ir in (result.get("xdsIR") or {}).values():
        for listener in ir.get("http") or []:
            for route in listener.get("routes") or []:
                dr = route.get("directResponse") or {}
                if dr.get("statusCode") == 500:
                    problems.append(
                        f"route {route.get('name')} was rewritten to directResponse 500 — "
                        f"EG fails every route on the Gateway closed when a policy does not translate"
                    )

    return problems


def main() -> int:
    if len(sys.argv) != 2:
        sys.exit("usage: check.py <path-to-egctl>")
    egctl = sys.argv[1]

    cases = [
        # (label, helm --set overrides)
        ("chart defaults (budget limiter off)", []),
        ("budget limiter on, shadow mode", ["budgetLimiter.enabled=true", "budgetLimiter.shadowMode=true"]),
        # Stage 3 is a values flip away; it must translate today, not on the night it ships.
        ("budget limiter on, ENFORCING", ["budgetLimiter.enabled=true", "budgetLimiter.shadowMode=false"]),
        ("redact ext_proc off", ["redactExtproc.enabled=false", "budgetLimiter.enabled=true"]),
    ]

    failed = 0
    for label, sets in cases:
        docs = render(sets)
        problems = failures(translate(egctl, docs))
        entries = lua_entry_count(docs)
        if problems:
            failed += 1
            print(f"FAIL  {label}  ({entries} lua entries)")
            for p in problems:
                print(f"      {p}")
        else:
            print(f"PASS  {label}  ({entries} lua entries accepted, no route forced to 500)")

    print()
    print("═════════════════════════════════════════════════════════════════════════════")
    print(f"cases: {len(cases)}   failed: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
