-- gateway-auth: APISIX plugin enforcing the web-edge auth contract.
--
-- Contract (see docs/development/gateway.md §5.1 / §5.4):
--   * Browser is the only first-class client of the gateway.
--   * Access credential is ONLY carried via the `access_token` cookie;
--     `Authorization: Bearer <jwt>` at the gateway is explicitly unsupported
--     and MUST NOT be reintroduced. Server-to-server calls bypass this plugin
--     entirely and use `X-Internal-Auth` on the internal subnet.
--   * CSRF is enforced for every non-safe method independent of cookie state.

local cjson = require("cjson.safe")
local cookie = require("resty.cookie")
local core = require("apisix.core")
local http = require("resty.http")
local random = require("resty.random")
local stringx = require("resty.string")
local error_code_registry = require("apisix.plugins.error_code_registry")

local plugin_name = "gateway-auth"

-- Every GATEWAY_* / INTERNAL_* errorCode this plugin may emit. Kept as an
-- explicit list (not scraped from source) because (a) Lua has no AST-stable
-- grep, (b) this is the ground truth scripts/check-contracts.py also
-- cross-verifies against both the plugin source and gateway/error-codes.json,
-- forming a closed three-way loop: source literals ⊆ KNOWN ⊆ registry.
-- Adding a new errorCode to the plugin MUST also add it here AND to
-- gateway/error-codes.json; missing either entry fails plugin init.
local KNOWN_ERROR_CODES = {
    "GATEWAY_AUTH_REQUIRED",
    "GATEWAY_CSRF_INVALID",
    "GATEWAY_INTROSPECT_UNAVAILABLE",
}

local schema = {
    type = "object",
    properties = {
        introspection_url = {
            type = "string",
            minLength = 1,
        },
        internal_auth_secret = {
            type = "string",
            minLength = 1,
        },
        require_auth = {
            type = "boolean",
            default = true,
        },
        csrf_protect = {
            type = "boolean",
            default = true,
        },
        positive_cache_ttl = {
            type = "integer",
            minimum = 1,
            default = 2,
        },
        negative_cache_ttl = {
            type = "integer",
            minimum = 0,
            default = 1,
        },
    },
    required = { "introspection_url" },
}

local _M = {
    version = 0.1,
    priority = 2500,
    name = plugin_name,
    schema = schema,
}

local function get_header(name)
    local headers = ngx.req.get_headers()
    return headers[name] or headers[string.lower(name)]
end

local function get_cookie_value(name)
    local ck, err = cookie:new()
    if not ck then
        core.log.error("failed to create cookie reader: ", err)
        return nil
    end

    local value, get_err = ck:get(name)
    if get_err then
        core.log.error("failed to read cookie ", name, ": ", get_err)
        return nil
    end

    if value == "" then
        return nil
    end
    return value
end

local function build_request_id()
    local bytes = random.bytes(16, true)
    if bytes then
        return stringx.to_hex(bytes)
    end
    return tostring(ngx.now()):gsub("%.", "") .. tostring(math.random(100000, 999999))
end

local function ensure_request_id()
    local request_id = get_header("X-Request-Id")
    if not request_id or request_id == "" then
        request_id = build_request_id()
        ngx.req.set_header("X-Request-Id", request_id)
    end
    ngx.header["X-Request-Id"] = request_id
    return request_id
end

local function set_forwarded_headers()
    local remote_addr = ngx.var.remote_addr or ""
    local forwarded_for = get_header("X-Forwarded-For")
    if forwarded_for and forwarded_for ~= "" then
        forwarded_for = forwarded_for .. ", " .. remote_addr
    else
        forwarded_for = remote_addr
    end

    ngx.req.set_header("X-Forwarded-For", forwarded_for)
    ngx.req.set_header("X-Forwarded-Proto", ngx.var.scheme or "http")
    ngx.req.set_header("X-Forwarded-Host", get_header("Host") or ngx.var.host or "")
end

-- Strip ALL client-supplied `X-Auth-*` headers before we inject authoritative
-- identity. Enumerating only known names (X-Auth-User-Id / X-Auth-User-Email /
-- X-Auth-Session-Id) is unsafe: any future `X-Auth-<Attr>` would silently pass
-- through and become client-forgeable. See gateway.md §3.2.
local function clear_identity_headers()
    local headers = ngx.req.get_headers()
    for name, _ in pairs(headers) do
        -- ngx.req.get_headers() returns keys lower-cased by default; match both
        -- just in case a future lua-nginx version changes normalization.
        if type(name) == "string"
            and (string.sub(name, 1, 7) == "X-Auth-"
                 or string.sub(name, 1, 7) == "x-auth-") then
            ngx.req.clear_header(name)
        end
    end
end

local function is_safe_method(method)
    return method == "GET" or method == "HEAD" or method == "OPTIONS"
end

-- CSRF enforcement MUST be driven by route config + HTTP method alone; it MUST
-- NOT branch on "does this request happen to carry auth cookies". Reason: on
-- routes like POST /api/v1/auth/refresh and POST /api/v1/auth/logout that
-- require CSRF even before the browser-side state is fully populated, skipping
-- the check for "no cookie" requests is exploitable. See gateway.md §5.2.
local function should_skip_csrf(method)
    return is_safe_method(method)
end

-- Unified failure envelope (backend.md §6.0):
--   top-level `code` MUST equal the HTTP status; `details.errorCode` and
--   `details.category` are **both** mandatory on non-2xx responses. Call sites
--   are responsible for passing error_code/category from §6.3.1's registry —
--   this function intentionally does not default them, because a silent
--   fallback would let a new failure branch ship with a missing errorCode and
--   degrade the frontend's §6.3.2 two-tier dispatch to the generic 5xx path.
local function write_error(status, request_id, message, error_code, category)
    ngx.status = status
    ngx.header["Content-Type"] = "application/json; charset=utf-8"
    ngx.header["X-Request-Id"] = request_id
    ngx.say(cjson.encode({
        code = status,
        message = message,
        requestId = request_id,
        details = {
            errorCode = error_code,
            category = category,
        },
    }))
    return ngx.exit(status)
end

local function should_retry(err)
    if not err then
        return false
    end
    return string.find(err, "timeout", 1, true) ~= nil
        or string.find(err, "closed", 1, true) ~= nil
        or string.find(err, "connect", 1, true) ~= nil
        or string.find(err, "refused", 1, true) ~= nil
end

local function cache_lookup(cache, key)
    local payload = cache:get(key)
    if not payload then
        return nil
    end
    return cjson.decode(payload)
end

local function cache_store(cache, key, payload, ttl)
    local encoded = cjson.encode(payload)
    if not encoded then
        return
    end
    cache:set(key, encoded, ttl)
end

local function introspect(conf, token, request_id)
    local cache = ngx.shared.gateway_auth_cache
    local cache_key = "introspect:" .. stringx.to_hex(ngx.sha256_bin(token))
    if cache then
        local cached = cache_lookup(cache, cache_key)
        if cached then
            return cached, nil
        end
    end

    local internal_auth_secret = conf.internal_auth_secret or os.getenv("INTERNAL_INTROSPECTION_SECRET")
    if not internal_auth_secret or internal_auth_secret == "" then
        core.log.error("INTERNAL_INTROSPECTION_SECRET is not configured")
        return nil, "introspection_unavailable"
    end

    local body = cjson.encode({
        token = token,
        tokenTypeHint = "access",
    })

    local res
    local err

    for attempt = 1, 2 do
        local httpc = http.new()
        httpc:set_timeouts(200, 500, 800)
        res, err = httpc:request_uri(conf.introspection_url, {
            method = "POST",
            body = body,
            headers = {
                ["Content-Type"] = "application/json",
                ["X-Internal-Auth"] = internal_auth_secret,
                ["X-Request-Id"] = request_id,
            },
            keepalive = true,
            ssl_verify = false,
        })

        if res then
            break
        end

        if attempt == 2 or not should_retry(err) then
            break
        end
    end

    if not res then
        return nil, "introspection_unavailable"
    end

    if res.status ~= 200 then
        core.log.error("unexpected introspection status: ", res.status)
        return nil, "introspection_unavailable"
    end

    -- Per backend.md §8.6.1, the introspection endpoint returns the standard ApiResponse
    -- envelope (no RFC 7662 bare-schema exemption). The token-state object lives under
    -- `data`; we unwrap here and cache only the inner payload so downstream code in
    -- `access()` can keep using `payload.active / userId / email / sessionId` unchanged.
    local decoded = cjson.decode(res.body or "")
    if not decoded or type(decoded.data) ~= "table" or decoded.data.active == nil then
        core.log.error("invalid introspection response body")
        return nil, "introspection_unavailable"
    end

    local payload = decoded.data

    local ttl = conf.negative_cache_ttl
    if payload.active then
        ttl = conf.positive_cache_ttl
    end
    if cache then
        cache_store(cache, cache_key, payload, ttl)
    end

    return payload, nil
end

local function apply_csrf(conf, request_id)
    if not conf.csrf_protect then
        return nil
    end

    if should_skip_csrf(ngx.req.get_method()) then
        return nil
    end

    local csrf_cookie = get_cookie_value("XSRF-TOKEN")
    local csrf_header = get_header("X-XSRF-TOKEN")
    if not csrf_cookie or not csrf_header or csrf_cookie ~= csrf_header then
        return write_error(403, request_id, "CSRF validation failed",
            "GATEWAY_CSRF_INVALID", "AUTH")
    end

    return nil
end

-- init() runs once per worker when APISIX's plugin loader initialises this
-- plugin. We use it to assert the error-code registry is present, parseable,
-- and superset of the literals the plugin may emit. A failure here crashes
-- plugin load, which is the desired fail-closed behaviour: if the registry
-- has drifted from the plugin source, auth-protected routes refuse to serve
-- rather than emit an unregistered errorCode.
function _M.init()
    error_code_registry.assert_registered(plugin_name, KNOWN_ERROR_CODES)
end

function _M.check_schema(conf)
    return core.schema.check(schema, conf)
end

function _M.access(conf, ctx)
    local _ = ctx
    local request_id = ensure_request_id()

    clear_identity_headers()
    set_forwarded_headers()

    local access_cookie = get_cookie_value("access_token")

    local csrf_err = apply_csrf(conf, request_id)
    if csrf_err then
        return csrf_err
    end

    if not conf.require_auth then
        return
    end

    -- Access credential is cookie-only by contract; any `Authorization` header
    -- present on the request is ignored here.
    local token = access_cookie
    if not token then
        return write_error(401, request_id, "Authentication required",
            "GATEWAY_AUTH_REQUIRED", "AUTH")
    end

    local payload, err = introspect(conf, token, request_id)
    if err then
        return write_error(503, request_id, "Authentication service unavailable",
            "GATEWAY_INTROSPECT_UNAVAILABLE", "UPSTREAM")
    end

    if not payload.active then
        return write_error(401, request_id, "Authentication required",
            "GATEWAY_AUTH_REQUIRED", "AUTH")
    end

    if not payload.userId or not payload.email then
        -- From the gateway's POV this is indistinguishable from an upstream
        -- contract violation, so we collapse it onto GATEWAY_INTROSPECT_UNAVAILABLE
        -- rather than minting a new errorCode. See §6.3.1 registry.
        return write_error(503, request_id, "Authentication service returned incomplete identity",
            "GATEWAY_INTROSPECT_UNAVAILABLE", "UPSTREAM")
    end

    ngx.req.set_header("X-Auth-User-Id", tostring(payload.userId))
    ngx.req.set_header("X-Auth-User-Email", tostring(payload.email))
    if payload.sessionId and payload.sessionId ~= "" then
        ngx.req.set_header("X-Auth-Session-Id", tostring(payload.sessionId))
    else
        ngx.req.clear_header("X-Auth-Session-Id")
    end
end

-- Exposed strictly for unit tests (gateway/tests/spec/gateway_auth_spec.lua).
-- Not part of the plugin's public API; do NOT consume these from other plugins
-- or from APISIX core — if you need any of these, promote them to a real
-- sibling module with a documented contract instead.
_M._private = {
    write_error = write_error,
    is_safe_method = is_safe_method,
    should_skip_csrf = should_skip_csrf,
    should_retry = should_retry,
    apply_csrf = apply_csrf,
    ensure_request_id = ensure_request_id,
    clear_identity_headers = clear_identity_headers,
}

return _M
