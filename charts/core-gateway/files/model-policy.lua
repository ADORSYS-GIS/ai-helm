-- Per-project model-allowlist enforcement.
-- ai-helm-values#292, ai-helm ADR-0133, lightbridge-authz ADR-0018.
--
-- This is the CONSUMER half of the split PR ai-helm-values#288 made: Authorino resolves the
-- project's model policy and publishes it, and this filter applies it to the model the AI
-- Gateway extracted from the request body. Authorino owns everything that needs no model
-- name (deny_all, unrecognised values -> 403 at the edge); this owns list membership.
--
-- INPUT HEADERS
--   x-model-policy    allow_all | allowlist | ""   Authorino, stamped unconditionally
--   x-allowed-models  comma-joined model ids       Authorino, stamped unconditionally
--   x-ai-eg-model     the model parsed out of the body by the AI Gateway ext_proc
--
-- CONTRACT (verbatim from environments/prod/values/security-policies.yaml, where these
-- headers are defined):
--   x-model-policy == "allow_all"  -> every model permitted; x-allowed-models is ignored
--   x-model-policy == "allowlist"  -> the requested model MUST appear in x-allowed-models;
--                                     an EMPTY list permits NOTHING (the ADR-0018
--                                     inversion; pre-#418 an empty list meant "everything")
--   x-model-policy == ""           -> no project context (internal plane); no restriction
--
-- READ x-model-policy FIRST, ALWAYS. x-allowed-models on its own is ambiguous: "" means
-- "everything" under allow_all and "nothing" under allowlist. A consumer that only looks at
-- the list gets the deny-everything case exactly backwards.
--
-- FILTER POSITION. Envoy Gateway v1.8.2 assigns a fixed order to every HTTP filter it
-- generates (internal/xds/translator/httpfilters.go, newOrderedHTTPFilter): ext_authz = 5,
-- Lua = 12 + index, EnvoyExtensionPolicy ext_proc = 100 + index, router last. The AI
-- Gateway's own ext_proc is injected ahead of that table entirely (observed as filter 1 on
-- the external chain). So this script always runs AFTER Authorino and AFTER the AI Gateway
-- processor, and sees both halves of the decision.
--
-- WHY IT IS ATTACHED GATEWAY-WIDE, AND WHAT THAT COSTS. Envoy Gateway accepts exactly one
-- EnvoyExtensionPolicy per targetRef, so this shares the Gateway-scoped policy with the
-- billing-period Lua. It therefore runs on every route on every listener, including routes
-- that legitimately never see Authorino (the MCP routes carry their own SecurityPolicy; the
-- two public model-catalog paths are skipped by the main AuthConfig's own `when` gate).
-- That is why "no x-model-policy" is not, by itself, a denial — see the table below.
--
-- DECISION TABLE (every branch is explicit; there is no fallthrough)
--   x-model-policy | x-ai-eg-model | outcome
--   ---------------+---------------+---------------------------------------------------
--   absent         | absent        | ALLOW  not a model request and no policy to apply
--   absent         | present       | DENY   a model request that did not pass the
--                  |               |        AuthConfig which stamps the policy: the chain
--                  |               |        is misconfigured or misordered, and a model
--                  |               |        request must never be waved through on that
--   ""             | any           | ALLOW  internal plane, no project context
--   allow_all      | any           | ALLOW
--   allowlist      | absent/empty  | DENY   the model cannot be determined, and this
--                  |               |        project is restricted to an explicit list
--   allowlist      | in list       | ALLOW
--   allowlist      | not in list   | DENY
--   allowlist      | (list empty)  | DENY   ADR-0018: an empty allowlist permits nothing
--   anything else  | any           | DENY   Authorino already refuses these; if one gets
--                  |               |        here the two sides have drifted -- agree with
--                  |               |        the strict side
--   any input header sent more than once | DENY  see anti-spoofing below
--   script raises  | any           | DENY   see the pcall guard at the bottom
--
-- ANTI-SPOOFING. Authorino emits success headers as a bare HeaderValueOption with no
-- AppendAction (pkg/service/auth.go, buildResponseHeaders), which Envoy's ext_authz client
-- routes to CheckResponse.headers_to_set -- an OVERWRITE of whatever the client sent, not an
-- append. Both headers are stamped on EVERY success path of BOTH AuthConfigs (constant ""
-- on the internal one) precisely so there is no path on which a client-supplied copy
-- survives.
--
-- Belt and braces, because that guarantee lives upstream of this file and could regress:
-- any of the three input headers arriving MORE THAN ONCE is refused outright. That is not
-- tidiness, it was measured. Envoy's Lua headers:get() concatenates duplicate entries with
-- "," , so a request carrying the real `x-allowed-models: gemma-4` alongside a
-- client-supplied `x-allowed-models: minimax-m3` reads back as "gemma-4,minimax-m3" and the
-- spoofed model passes membership. The first version of this script allowed exactly that --
-- observed against envoyproxy/envoy:distroless-v1.38.3, which is what closed it.
-- getNumValues() is a method on Envoy's Lua header object; the PR's harness exercises it on
-- that same image. If it ever went away the pcall guard would turn it into a 403 -- loud and
-- immediate, not a silent bypass.

local POLICY_HEADER = "x-model-policy"
local ALLOWED_HEADER = "x-allowed-models"
local MODEL_HEADER = "x-ai-eg-model"

local POLICY_ALLOW_ALL = "allow_all"
local POLICY_ALLOWLIST = "allowlist"

local META_NAMESPACE = "lightbridge.model_policy"

local function trim(value)
  return (value:gsub("^%s+", ""):gsub("%s+$", ""))
end

local function jsonEscape(value)
  local escaped = value:gsub("\\", "\\\\")
  escaped = escaped:gsub('"', '\\"')
  escaped = escaped:gsub("%c", function(char)
    return string.format("\\u%04x", string.byte(char))
  end)
  return escaped
end

-- Observability only. Wrapped so that a metadata write can never change a decision.
local function setMeta(handle, key, value)
  pcall(function()
    handle:streamInfo():dynamicMetadata():set(META_NAMESPACE, key, value)
  end)
end

local function allow(handle, reason)
  setMeta(handle, "decision", "allow")
  setMeta(handle, "reason", reason)
end

local function deny(handle, reason, message)
  setMeta(handle, "decision", "deny")
  setMeta(handle, "reason", reason)
  handle:logWarn("model policy denied request (" .. reason .. "): " .. message)
  handle:respond(
    { [":status"] = "403", ["content-type"] = "application/json" },
    '{"error":{"message":"' .. jsonEscape(message) ..
      '","type":"invalid_request_error","param":"model","code":"model_not_allowed"}}'
  )
end

-- Exact, case-sensitive membership over a comma-joined list. An empty or whitespace-only
-- list has no members, so it permits nothing -- which is the ADR-0018 semantics, reached
-- here by construction rather than by a special case.
local function isMember(list, model)
  for candidate in list:gmatch("[^,]+") do
    if trim(candidate) == model then
      return true
    end
  end
  return false
end

local function headerValue(headers, name)
  local raw = headers:get(name)
  if raw == nil then
    return nil
  end
  return trim(raw)
end

-- A single value, or nothing. More than one entry means someone appended to a header this
-- filter's decision is built on, so there is no honest value to read.
local function isDuplicated(headers, name)
  return headers:getNumValues(name) > 1
end

local function enforce(handle)
  local headers = handle:headers()

  for _, name in ipairs({ POLICY_HEADER, ALLOWED_HEADER, MODEL_HEADER }) do
    if isDuplicated(headers, name) then
      return deny(handle, "duplicate_header",
        "conflicting '" .. name .. "' headers were supplied with this request")
    end
  end

  local policy = headerValue(headers, POLICY_HEADER)
  local model = headerValue(headers, MODEL_HEADER)

  if policy == nil then
    if model == nil or model == "" then
      -- Not a model request: an MCP route with its own SecurityPolicy, or one of the two
      -- unauthenticated model-catalog paths the main AuthConfig's `when` gate skips.
      -- Nothing to police, and no model backend is reachable without the model header.
      return allow(handle, "no_policy_context")
    end
    return deny(handle, "policy_header_absent",
      "model policy could not be determined for this request")
  end

  if policy == "" then
    return allow(handle, "no_project_context")
  end

  if policy == POLICY_ALLOW_ALL then
    return allow(handle, "allow_all")
  end

  if policy ~= POLICY_ALLOWLIST then
    return deny(handle, "policy_unrecognised",
      "model policy is not recognised by the gateway")
  end

  if model == nil or model == "" then
    return deny(handle, "model_undeterminable",
      "the requested model could not be determined, and this project is restricted to " ..
      "an explicit model allowlist")
  end

  local allowed = headerValue(headers, ALLOWED_HEADER) or ""
  if not isMember(allowed, model) then
    return deny(handle, "model_not_in_allowlist",
      "model '" .. model .. "' is not permitted for this project")
  end

  return allow(handle, "allowlist_member")
end

function envoy_on_request(request_handle)
  local ok, err = pcall(enforce, request_handle)
  if not ok then
    -- Envoy's own default for an uncaught Lua error is to log it and CONTINUE the filter
    -- chain -- i.e. fail open. An enforcement point that cannot run must refuse instead.
    request_handle:logErr("model policy enforcement raised: " .. tostring(err))
    pcall(function()
      request_handle:respond(
        { [":status"] = "403", ["content-type"] = "application/json" },
        '{"error":{"message":"model policy enforcement failed",' ..
          '"type":"invalid_request_error","param":"model","code":"model_not_allowed"}}'
      )
    end)
  end
end
