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

local plugin_name = "gateway-auth"

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

local function clear_identity_headers()
    ngx.req.clear_header("X-Auth-User-Id")
    ngx.req.clear_header("X-Auth-User-Email")
    ngx.req.clear_header("X-Auth-Session-Id")
end

local function is_safe_method(method)
    return method == "GET" or method == "HEAD" or method == "OPTIONS"
end

local function should_skip_csrf(method, access_cookie, refresh_cookie)
    if is_safe_method(method) then
        return true
    end
    if access_cookie or refresh_cookie then
        return false
    end
    return true
end

local function write_error(status, request_id, message)
    ngx.status = status
    ngx.header["Content-Type"] = "application/json; charset=utf-8"
    ngx.header["X-Request-Id"] = request_id
    ngx.say(cjson.encode({
        code = status,
        message = message,
        requestId = request_id,
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

    local decoded = cjson.decode(res.body or "")
    if not decoded or decoded.active == nil then
        core.log.error("invalid introspection response body")
        return nil, "introspection_unavailable"
    end

    local ttl = conf.negative_cache_ttl
    if decoded.active then
        ttl = conf.positive_cache_ttl
    end
    if cache then
        cache_store(cache, cache_key, decoded, ttl)
    end

    return decoded, nil
end

local function apply_csrf(conf, request_id, access_cookie, refresh_cookie)
    if not conf.csrf_protect then
        return nil
    end

    if should_skip_csrf(ngx.req.get_method(), access_cookie, refresh_cookie) then
        return nil
    end

    local csrf_cookie = get_cookie_value("XSRF-TOKEN")
    local csrf_header = get_header("X-XSRF-TOKEN")
    if not csrf_cookie or not csrf_header or csrf_cookie ~= csrf_header then
        return write_error(403, request_id, "CSRF validation failed")
    end

    return nil
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
    local refresh_cookie = get_cookie_value("refresh_token")

    local csrf_err = apply_csrf(conf, request_id, access_cookie, refresh_cookie)
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
        return write_error(401, request_id, "Authentication required")
    end

    local payload, err = introspect(conf, token, request_id)
    if err then
        return write_error(503, request_id, "Authentication service unavailable")
    end

    if not payload.active then
        return write_error(401, request_id, "Authentication required")
    end

    if not payload.userId or not payload.email then
        return write_error(503, request_id, "Authentication service returned incomplete identity")
    end

    ngx.req.set_header("X-Auth-User-Id", tostring(payload.userId))
    ngx.req.set_header("X-Auth-User-Email", tostring(payload.email))
    if payload.sessionId and payload.sessionId ~= "" then
        ngx.req.set_header("X-Auth-Session-Id", tostring(payload.sessionId))
    else
        ngx.req.clear_header("X-Auth-Session-Id")
    end
end

return _M
