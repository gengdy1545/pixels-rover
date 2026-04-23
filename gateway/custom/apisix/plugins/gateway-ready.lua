-- gateway-ready: APISIX plugin that aggregates upstream /health probes for
-- the `/gateway/ready` readiness endpoint.
--
-- Contract (see docs/development/gateway.md §4.1):
--   * Scope: system-level readiness (load-balancer drain / K8s readinessProbe /
--     compose smoke), NOT liveness. Liveness is `/gateway/live` and MUST
--     remain upstream-free.
--   * Semantics: boolean AND over each registered probe's `/health`. Any
--     probe that is not HTTP 200 -> overall 503. No degraded/warning tier.
--   * Coverage: only "each upstream process is alive and its /health returns
--     an allowed status code". Default is HTTP 200; browser UI probes may opt
--     into 3xx redirects explicitly. Does NOT reflect DB/schema/LLM/3rd-party
--     reachability; those belong to per-service `/health` (backend.md §7.1) and to the cold-start
--     `scripts/smoke.sh` that talks to MySQL directly (todolist.md §15).
--   * Configuration: `probes[]` is an *instance config* of this plugin on
--     the `/gateway/ready` route. Adding a new upstream service means
--     TWO simultaneous edits (see gateway.md §7 step 7):
--       (a) add a new `internal` location `/__ready_probe/<service>` in
--           `apisix.yaml` / `config.yaml.template` that `proxy_pass`-es to
--           the service's `/health`;
--       (b) append one entry to this plugin's `probes[]` for that route.
--
-- Timeout model:
--   Per-probe timeout enforcement lives in the nginx internal location
--   (`proxy_connect_timeout` / `proxy_read_timeout`), NOT in Lua -- the
--   OpenResty `ngx.location.capture_multi` API does not expose per-subrequest
--   timeouts. The `timeout_ms` / `total_timeout_ms` fields below are the
--   declarative contract that *must* be mirrored by those nginx directives;
--   they are not enforced by this plugin directly.
--
-- Response envelope follows backend.md §6.0:
--   200: { code: 200, message: "ready", requestId, data: { components[], elapsedMs } }
--   503: { code: 503, message: "...",    requestId, details: { errorCode:
--         "GATEWAY_NOT_READY", category: "UPSTREAM", hint, components[], elapsedMs } }

local cjson = require("cjson.safe")
local core = require("apisix.core")
local random = require("resty.random")
local stringx = require("resty.string")
local error_code_registry = require("apisix.plugins.error_code_registry")

local plugin_name = "gateway-ready"

-- See error_code_registry.lua for the full rationale on KNOWN_ERROR_CODES. Short
-- version: this is the ground truth of which errorCodes this plugin may
-- emit; init() asserts it is a subset of gateway/error-codes.json.
local KNOWN_ERROR_CODES = {
    "GATEWAY_NOT_READY",
}

local probe_schema = {
    type = "object",
    properties = {
        name = {
            type = "string",
            minLength = 1,
            description = "label exposed in `details.components[].name`, also used in logs",
        },
        uri = {
            type = "string",
            pattern = "^/",
            description = "internal location path (e.g. /__ready_probe/auth)",
        },
        timeout_ms = {
            type = "integer",
            minimum = 1,
            maximum = 10000,
            default = 1000,
            description = "declarative per-probe budget; MUST be mirrored by proxy_*_timeout on the corresponding internal location",
        },
        success_statuses = {
            type = "array",
            items = {
                type = "integer",
                minimum = 100,
                maximum = 599,
            },
            default = { 200 },
            description = "HTTP statuses treated as ready for this probe. Defaults to [200].",
        },
    },
    required = { "name", "uri" },
}

local schema = {
    type = "object",
    properties = {
        probes = {
            type = "array",
            items = probe_schema,
            default = {},
            description = "ordered list of internal probe locations to aggregate",
        },
        total_timeout_ms = {
            type = "integer",
            minimum = 1,
            maximum = 30000,
            default = 2000,
            description = "declarative aggregate budget; mirrored by nginx directives",
        },
    },
}

local _M = {
    version = 0.1,
    priority = 500,
    name = plugin_name,
    schema = schema,
}

local function build_request_id()
    local bytes = random.bytes(16, true)
    if bytes then
        return stringx.to_hex(bytes)
    end
    return tostring(ngx.now()):gsub("%.", "") .. tostring(math.random(100000, 999999))
end

local function ensure_request_id()
    local headers = ngx.req.get_headers()
    local request_id = headers["X-Request-Id"] or headers["x-request-id"]
    if not request_id or request_id == "" then
        request_id = build_request_id()
    end
    ngx.header["X-Request-Id"] = request_id
    return request_id
end

local function write_json(status, body)
    ngx.status = status
    ngx.header.content_type = "application/json"
    ngx.say(cjson.encode(body))
    return ngx.exit(status)
end

-- Pure helper extracted for unit testing: given a probes[] config and the
-- parallel responses[] array from ngx.location.capture_multi, compute the
-- response envelope (status, body) without touching ngx.* output APIs.
-- Kept internal-only because the gateway-ready contract is route-scoped and
-- should not be consumed elsewhere.
local function build_verdict(probes, responses, request_id, elapsed_total_ms)
    local components = {}
    local any_failed = false
    for i, probe in ipairs(probes) do
        local resp = responses[i]
        local status = (resp and resp.status) or 0
        local success_statuses = probe.success_statuses or { 200 }
        local healthy = false
        for _, expected in ipairs(success_statuses) do
            if status == expected then
                healthy = true
                break
            end
        end
        if not healthy then
            any_failed = true
        end
        components[i] = {
            name = probe.name,
            uri = probe.uri,
            httpCode = status,
            status = healthy and "UP" or "DOWN",
        }
    end

    if any_failed then
        return 503, {
            code = 503,
            message = "One or more upstream probes not ready",
            requestId = request_id,
            details = {
                errorCode = "GATEWAY_NOT_READY",
                category = "UPSTREAM",
                hint = "at least one upstream /health probe returned non-200; check components[]",
                components = components,
                elapsedMs = elapsed_total_ms,
            },
        }
    end

    return 200, {
        code = 200,
        message = "ready",
        requestId = request_id,
        data = {
            components = components,
            elapsedMs = elapsed_total_ms,
        },
    }
end

-- An empty probes list makes aggregation meaningless. By contract, a gateway
-- with no registered upstream probe is NOT ready -- this forces operators to
-- explicitly configure coverage when onboarding services.
local function empty_probes_body(request_id)
    return {
        code = 503,
        message = "No upstream probes registered",
        requestId = request_id,
        details = {
            errorCode = "GATEWAY_NOT_READY",
            category = "UPSTREAM",
            hint = "gateway-ready plugin has an empty probes[] list; see gateway.md §7 step 7",
            components = {},
        },
    }
end

-- Same fail-closed contract as other gateway plugins:
-- if the registry is missing or out of sync, /gateway/ready stops serving
-- rather than produce an unregistered errorCode.
function _M.init()
    error_code_registry.assert_registered(plugin_name, KNOWN_ERROR_CODES)
end

function _M.check_schema(conf)
    return core.schema.check(schema, conf)
end

function _M.access(conf, ctx)
    local _ = ctx
    local request_id = ensure_request_id()
    local probes = conf.probes or {}

    if #probes == 0 then
        core.log.warn("gateway-ready: no probes configured on this route; returning 503")
        return write_json(503, empty_probes_body(request_id))
    end

    local requests = {}
    for i, probe in ipairs(probes) do
        requests[i] = {
            probe.uri,
            {
                method = ngx.HTTP_GET,
                ctx = ngx.ctx,
                copy_all_vars = false,
                share_all_vars = false,
            },
        }
    end

    local start = ngx.now()
    local responses = { ngx.location.capture_multi(requests) }
    local elapsed_total_ms = math.floor((ngx.now() - start) * 1000 + 0.5)

    local status, body = build_verdict(probes, responses, request_id, elapsed_total_ms)
    return write_json(status, body)
end

-- Exposed strictly for unit tests.
_M._private = {
    build_verdict = build_verdict,
    empty_probes_body = empty_probes_body,
}

return _M
