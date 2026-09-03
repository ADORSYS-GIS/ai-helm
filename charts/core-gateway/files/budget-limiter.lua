-- The Dynamic Budget Limiter's enforcement half.
-- lightbridge-authz ADR-0034, lightbridge-authz#658.
--
-- Authorino calls authz-budget's mTLS-only `GET /budget/v1/remaining` as an AuthConfig `metadata`
-- step and publishes the answer as ext_authz DYNAMIC METADATA. This filter is the consumer: it
-- reads that metadata and refuses the request with 402 when the account's ledger balance is spent.
-- Nothing here computes a balance; it compares one number to zero.
--
-- WHY DYNAMIC METADATA AND NOT A HEADER. A success header is a REQUEST header, visible to the
-- upstream and — on any path where Authorino fails to stamp it — supplied by the client. That is
-- the exact hole model-policy.lua's "ANTI-SPOOFING" section has to defend against with duplicate-
-- header checks. Dynamic metadata is internal to the filter chain: it is never emitted to the
-- client and does not exist inbound, so there is nothing to spoof. This filter therefore has no
-- anti-spoofing logic, by construction rather than by discipline.
--
-- INPUT: dynamic metadata, namespace "envoy.filters.http.ext_authz", key "budget"
--   enforced          bool    is this plane in scope? main AuthConfig true, internal false
--   known             bool    did the budget read actually answer? (false = 503 / timeout / absent)
--   remaining_micros  number  ceiling - spend, in micro-USD; SIGNED, may be negative
--   next_reset_at     string  RFC3339, when the balance next changes on its own
--   account_id        string  the BUDGET account id (the `account_id` claim, not `sub`)
--
-- INPUT: header x-ai-eg-model — the model the AI Gateway's ext_proc parsed out of the body. Used
-- for exactly one thing: telling "this request never went through the budget AuthConfig because it
-- is not a model request" apart from "this request should have budget metadata and does not".
--
-- CONFIG: a `BUDGET_LIMITER_CONFIG` table the chart prepends to this script (see
-- envoyextensionpolicy-billing-period.yaml). Absent, every field falls back to the SAFEST value —
-- shadow ON, so a templating mistake cannot start refusing traffic.
--   shadow      bool    true: compute and record the decision, refuse nothing
--   refill_url  string  where the 402 body tells the user to go
--
-- DECISION TABLE (every branch explicit; no fallthrough)
--   enforced | known | remaining | model    | outcome
--   ---------+-------+-----------+----------+-------------------------------------------------
--   metadata absent  |           | absent   | ALLOW  not a metered request — the public model-
--                    |           |          |        catalog paths the AuthConfig's `when` gate
--                    |           |          |        skips, and the /mcp/* routes that carry
--                    |           |          |        their own SecurityPolicy
--   metadata absent  |           | present  | 503    a metered model request that did not pass
--                    |           |          |        the AuthConfig which publishes the budget:
--                    |           |          |        the chain is misconfigured or misordered
--   false    | any   | any       | any      | ALLOW  internal plane — out of scope for refills
--                    |           |          |        (lightbridge-authz#658 §0.1)
--   true     | false | any       | any      | 503    the balance is UNKNOWABLE right now. NOT 402:
--                    |           |          |        our outage is not the user's spent budget
--   true     | true  | > 0       | any      | ALLOW
--   true     | true  | <= 0      | any      | 402    budget_exhausted
--   shadow mode      | any       | any      | ALLOW  decision recorded, request continues
--   script raises    | any       | any      | 503    see the pcall guard at the bottom
--
-- FILTER POSITION. Envoy Gateway v1.8.2 assigns a fixed order to every HTTP filter it generates
-- (internal/xds/translator/httpfilters.go, newOrderedHTTPFilter): ext_authz = 5, Lua = 12 + index.
-- So this always runs AFTER Authorino has written its dynamic metadata. EG accepts exactly ONE
-- EnvoyExtensionPolicy per targetRef, which is why this is a third `lua` list entry on the
-- existing policy rather than a new resource — see that file's header comment for the incident
-- that established the rule.

local META_IN = "envoy.filters.http.ext_authz"
local META_KEY = "budget"
local META_OUT = "lightbridge.budget_limiter"

local MODEL_HEADER = "x-ai-eg-model"

-- Absent config = shadow ON, no refill URL. The unsafe direction (enforcing) must require an
-- explicit, deliberate value; a templating mistake must not start refusing paid traffic.
--
-- A PLAIN GLOBAL READ, and it must stay one. This line used to be
-- `rawget(_G, "BUDGET_LIMITER_CONFIG")`, which took the whole gateway down on 2026-09-03
-- (ai-helm-values#367/#368). Envoy Gateway does not just ship a Lua script to the data plane:
-- its CONTROL PLANE runs it first, in gopher-lua, against mock handles, under
-- internal/gatewayapi/luavalidator (strict is the default and this chart does not set
-- EnvoyProxy.spec.luaValidation). That validator's security.lua NILS `rawget`, `rawset`,
-- `setmetatable`, `getmetatable`, `load`, `loadstring`, `require`, `dofile`, `loadfile`,
-- `package`, `debug` -- and `_G` itself. So `rawget(_G, …)` raised "attempt to call a
-- non-function object" at the top of the chunk, `buildLuas` failed, and EG rewrote EVERY route
-- on this Gateway to `directResponse: 500` (internal/gatewayapi/envoyextensionpolicy.go: "Lua
-- extension doesn't have a fail open option, so fail the route if there is a lua error").
-- Envoy never loaded the filter at all, which is why the access log showed
-- `response_code_details: direct_response` with `budget_decision: -` and the proxy logged
-- nothing about Lua.
--
-- A plain read is equivalent here (the Envoy Lua filter's global table carries no `__index`),
-- and it survives both runtimes. `tests/envoy-gateway-lua/run.sh` is the gate: it runs EG's own
-- translator over the rendered chart and fails on exactly this class of defect.
local CONFIG = BUDGET_LIMITER_CONFIG or {}
local SHADOW = CONFIG.shadow ~= false
local REFILL_URL = CONFIG.refill_url or ""

local function jsonEscape(value)
  local escaped = tostring(value):gsub("\\", "\\\\")
  escaped = escaped:gsub('"', '\\"')
  escaped = escaped:gsub("%c", function(char)
    return string.format("\\u%04x", string.byte(char))
  end)
  return escaped
end

-- Observability only. Wrapped so a metadata write can never change a decision.
local function setMeta(handle, key, value)
  pcall(function()
    handle:streamInfo():dynamicMetadata():set(META_OUT, key, value)
  end)
end

local function record(handle, decision, reason, remaining)
  setMeta(handle, "decision", decision)
  setMeta(handle, "reason", reason)
  if remaining ~= nil then
    setMeta(handle, "remaining_micros", remaining)
  end
  setMeta(handle, "shadow", SHADOW)
end

local function allow(handle, reason, remaining)
  record(handle, "allow", reason, remaining)
end

-- The single refusal path. In shadow mode it records the decision and CONTINUES: the whole point
-- of shadow is to measure the false-positive rate of a rule that can 402 real paying traffic,
-- which needs the rule live on every request and acting on none of them.
local function deny(handle, status, body, reason, remaining)
  record(handle, "deny", reason, remaining)
  if SHADOW then
    handle:logInfo("budget limiter (shadow) would refuse " .. status .. ": " .. reason)
    return
  end
  handle:logWarn("budget limiter refused request (" .. reason .. ")")
  handle:respond({ [":status"] = status, ["content-type"] = "application/json" }, body)
end

local function exhaustedBody(accountId, nextResetAt)
  return '{"error":"budget_exhausted"' ..
    ',"account_id":"' .. jsonEscape(accountId) .. '"' ..
    ',"remaining_micros":0' ..
    ',"next_reset_at":"' .. jsonEscape(nextResetAt) .. '"' ..
    ',"refill_url":"' .. jsonEscape(REFILL_URL) .. '"' ..
    ',"message":"This account has no budget left for the current period. ' ..
    'Top up, or wait for the next reset."}'
end

local function unavailableBody(reason)
  return '{"error":"budget_unavailable"' ..
    ',"reason":"' .. jsonEscape(reason) .. '"' ..
    ',"message":"The remaining budget for this account could not be determined. ' ..
    'This is not a spending limit; retry shortly."}'
end

-- Returns the budget metadata table, or nil when the ext_authz filter published none.
local function budgetMetadata(handle)
  local ns = handle:streamInfo():dynamicMetadata():get(META_IN)
  if ns == nil then
    return nil
  end
  return ns[META_KEY]
end

local function enforce(handle)
  local budget = budgetMetadata(handle)

  if budget == nil then
    local model = handle:headers():get(MODEL_HEADER)
    if model == nil or model == "" then
      -- Not a metered model request: an MCP route with its own SecurityPolicy, or one of the
      -- unauthenticated model-catalog paths the main AuthConfig's `when` gate skips. Nothing to
      -- meter, and no model backend is reachable without the model header anyway.
      return allow(handle, "no_budget_context")
    end
    -- A model request that did not pass the AuthConfig which publishes the budget. Waving it
    -- through would make every misordered or half-deployed chain silently unmetered.
    return deny(handle, "503", unavailableBody("budget_metadata_absent"), "budget_metadata_absent")
  end

  if budget.enforced ~= true then
    -- The internal plane (LibreChat, cron jobs, k8s SAs) authenticates differently and is out of
    -- scope for ledger budgets; its own AuthConfig publishes `enforced: false` explicitly rather
    -- than omitting the metadata, so "out of scope" and "misconfigured" stay distinguishable.
    return allow(handle, "not_enforced_on_this_plane")
  end

  if budget.known ~= true then
    -- The ledger or the spend source could not be read. This is OUR outage, and it must not be
    -- reported to the user as an exhausted budget: different status, different message, different
    -- runbook. authz-budget has already ridden out its own grace window before reaching here.
    return deny(handle, "503", unavailableBody("budget_unknown"), "budget_unknown")
  end

  local remaining = tonumber(budget.remaining_micros)
  if remaining == nil then
    -- `known: true` with an unusable number means the two sides have drifted. Agree with the
    -- strict side, exactly as model-policy.lua does for an unrecognised policy value.
    return deny(handle, "503", unavailableBody("budget_malformed"), "budget_malformed")
  end

  if remaining > 0 then
    return allow(handle, "within_budget", remaining)
  end

  return deny(
    handle,
    "402",
    exhaustedBody(budget.account_id or "", budget.next_reset_at or ""),
    "budget_exhausted",
    remaining
  )
end

function envoy_on_request(request_handle)
  local ok, err = pcall(enforce, request_handle)
  if not ok then
    -- Envoy's own default for an uncaught Lua error is to log it and CONTINUE the filter chain --
    -- i.e. fail OPEN. An enforcement point that cannot run must refuse instead. In shadow mode it
    -- still only logs: shadow must never be able to break traffic, not even by crashing.
    request_handle:logErr("budget limiter raised: " .. tostring(err))
    if SHADOW then
      return
    end
    pcall(function()
      request_handle:respond(
        { [":status"] = "503", ["content-type"] = "application/json" },
        unavailableBody("budget_limiter_error")
      )
    end)
  end
end
