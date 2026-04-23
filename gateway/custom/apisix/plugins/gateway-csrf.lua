-- gateway-csrf: APISIX edge guard for browser unsafe-method CSRF.
--
-- Identity/session decisions belong to Ory Kratos + Ory Oathkeeper. This
-- plugin deliberately does not validate credentials, cache sessions, or inject
-- X-Auth-* headers. It only protects the browser edge before APISIX proxies
-- protected API traffic to Oathkeeper:
--   * strip any client-supplied X-Auth-* headers;
--   * enforce double-submit CSRF for unsafe methods;
--   * preserve request id and forwarded headers for downstream audit logs.

local cjson = require("cjson.safe")
local cookie = require("resty.cookie")
local core = require("apisix.core")
local random = require("resty.random")
local stringx = require("resty.string")
local error_code_registry = require("apisix.plugins.error_code_registry")

local plugin_name = "gateway-csrf"

local KNOWN_ERROR_CODES = {
    "GATEWAY_CSRF_INVALID",
}

local schema = {
    type = "object",
    properties = {
        csrf_protect = {
            type = "boolean",
            default = true,
        },
    },
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

-- Strip every client-supplied X-Auth-* header before Oathkeeper runs. The
-- authoritative identity headers are written only by Oathkeeper's mutator.
local function clear_identity_headers()
    local headers = ngx.req.get_headers()
    for name, _ in pairs(headers) do
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

local function should_skip_csrf(method)
    return is_safe_method(method)
end

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

    local csrf_err = apply_csrf(conf, request_id)
    if csrf_err then
        return csrf_err
    end
end

_M._private = {
    write_error = write_error,
    is_safe_method = is_safe_method,
    should_skip_csrf = should_skip_csrf,
    apply_csrf = apply_csrf,
    ensure_request_id = ensure_request_id,
    clear_identity_headers = clear_identity_headers,
}

return _M
