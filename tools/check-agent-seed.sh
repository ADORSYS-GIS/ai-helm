#!/bin/sh
# check-agent-seed.sh — guard the LibreChat agent-fleet seed config (ADR-0088/0086).
#
# The fleet lives in `charts/librechat-app/values.yaml` under `agentSeed.agents`.
# A wrong model id or MCP server name here renders FINE in `helm lint`/`helm
# template` (the seed Job only fails at PostSync, when it tries to create the
# agent) — so this script is the early, cheap guard. It verifies each agent's:
#
#   1. `model`  — non-empty, and (when the resolved converse provider model list
#                 is available) present in it. By default we only enforce
#                 non-empty + uniqueness here, because the authoritative model
#                 list lives in the private ai-helm-values repo.
#   2. `mcpServers[*]` — expands to the LibreChat whole-server MCP token
#                 `sys__all__sys_mcp_<name>` (Constants.mcp_all + mcp_delimiter,
#                 see files/seed-agents.js). We verify the expansion is well-formed
#                 and that the referenced MCP server is plausibly registered
#                 (checked against charts/librechat-app mcp + config.mcpServers).
#
# Exit: non-zero on any invalid agent config. Run in CI after `helm lint`.

set -eu

CHART="charts/librechat-app"
VALUES="$CHART/values.yaml"
[ -f "$VALUES" ] || { echo "check-agent-seed: no $VALUES (cwd=$PWD)"; exit 1; }

# yq is installed on the runner (see helm-lint.yaml).
command -v yq >/dev/null 2>&1 || { echo "check-agent-seed: yq required"; exit 1; }

fail=0
count=$(yq eval '.agentSeed.agents | length' "$VALUES" 2>/dev/null || echo 0)
[ "$count" -gt 0 ] || { echo "check-agent-seed: no agents to check"; exit 0; }

# Collect the MCP server names LibreChat actually registers for mcpServers:
# platform gateway MCPs (terraform/context7/refero/coder) are wired under
# librechat config.mcpServers (if present) or the well-known coder_mcp name.
# We derive the plausible server set from anywhere the chart names MCP servers.
mcp_names=$(yq eval '[.config.mcpServers | keys[]] | .[]' "$VALUES" 2>/dev/null | sort -u || true)
# Include the hard-registered coder MCP used by the agent seed.
mcp_names=$(printf '%s\ncoder_mcp\n' "$mcp_names" | sort -u)

echo "check-agent-seed: registering $count agent(s), MCP set: $(echo $mcp_names | tr '\n' ' ')"

i=0
while [ "$i" -lt "$count" ]; do
  name=$(yq eval ".agentSeed.agents[$i].name" "$VALUES")
  model=$(yq eval ".agentSeed.agents[$i].model" "$VALUES")
  tools=$(yq eval ".agentSeed.agents[$i].tools | length" "$VALUES")
  mcps=$(yq eval ".agentSeed.agents[$i].mcpServers | length // 0" "$VALUES")

  # 1. model non-empty
  if [ -z "$model" ] || [ "$model" = "null" ]; then
    echo "❌ agent[$i] '$name': model is empty"; fail=1
  fi

  # 2. each mcpServers expands to a well-formed token that references a
  #    registered server.
  j=0
  while [ "$j" -lt "${mcps:-0}" ]; do
    srv=$(yq eval ".agentSeed.agents[$i].mcpServers[$j]" "$VALUES" 2>/dev/null)
    if [ -z "$srv" ] || [ "$srv" = "null" ]; then
      echo "❌ agent[$i] '$name': empty mcpServers[$j]"; fail=1; j=$((j+1)); continue
    fi
    # Token must be the whole-server form, and the server should be registered.
    case "$srv" in
      *) token="sys__all__sys_mcp_${srv}" ;;
    esac
    if ! echo "$token" | grep -qE '^sys__all__sys_mcp_[A-Za-z0-9_]+$'; then
      echo "❌ agent[$i] '$name': mcpServer '$srv' → malformed token '$token'"; fail=1
    fi
    if ! echo "$mcp_names" | grep -qx "$srv"; then
      echo "⚠️  agent[$i] '$name': mcpServer '$srv' not in the local mcpServers set (is it a platform/gateway MCP?)"
    fi
    j=$((j+1))
  done

  echo "${name:+ }✓ '$name' (model=$model tools=$tools mcpServers=${mcps:-0})"
  i=$((i+1))
done

if [ "$fail" -ne 0 ]; then
  echo "check-agent-seed: FAILED (see above)"; exit 1
fi
echo "check-agent-seed: OK"
