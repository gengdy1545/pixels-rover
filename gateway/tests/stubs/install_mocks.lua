-- Register mock modules in package.loaded BEFORE the plugin is require()'d
-- so that `local core = require("apisix.core")` etc. see our stubs instead
-- of trying to load real APISIX internals (which pull in a full runtime).
--
-- Keep this file intentionally short: each stub is the *minimum* API surface
-- the plugins actually use. When a plugin starts needing more, extend the
-- stub here rather than masking it in the plugin itself.

local function fake_cookie_value(t) return t._cookies end

-- State injected per-test via M.set_cookies / M.set_introspection_response
local M = {
    _cookies = {},
    _introspection = nil,    -- function(opts) -> res, err
}

-- cjson.safe is NOT stubbed: we want the real encoder so tests assert the
-- actual JSON bytes the plugin would emit. The APISIX base image ships
-- lua-cjson, which busted picks up naturally via the OpenResty lua path.

local resty_cookie = {}
resty_cookie.__index = resty_cookie
function resty_cookie:get(name)
    local v = M._cookies[name]
    if v == nil then return nil, nil end
    return v, nil
end
function resty_cookie.new() return setmetatable({}, resty_cookie), nil end

local resty_http = {}
function resty_http.new()
    return {
        set_timeouts = function() end,
        request_uri = function(_, url, opts)
            if M._introspection then
                return M._introspection(url, opts)
            end
            return nil, "no_introspection_stub"
        end,
    }
end

local resty_random = {
    bytes = function(n) return string.rep("a", n) end,
}

local resty_string = {
    to_hex = function(s)
        return (s or ""):gsub(".", function(c)
            return string.format("%02x", string.byte(c))
        end)
    end,
}

local apisix_core = {
    log = {
        error = function(...) end,
        warn = function(...) end,
        info = function(...) end,
    },
    schema = {
        check = function(_schema, _conf) return true, nil end,
    },
    table = {
        new = function(_narr, _nrec) return {} end,
    },
}

function M.install()
    package.loaded["resty.cookie"] = resty_cookie
    package.loaded["resty.http"] = resty_http
    package.loaded["resty.random"] = resty_random
    package.loaded["resty.string"] = resty_string
    package.loaded["apisix.core"] = apisix_core
end

function M.uninstall()
    package.loaded["resty.cookie"] = nil
    package.loaded["resty.http"] = nil
    package.loaded["resty.random"] = nil
    package.loaded["resty.string"] = nil
    package.loaded["apisix.core"] = nil
end

function M.set_cookies(cookies) M._cookies = cookies or {} end
function M.set_introspection(fn) M._introspection = fn end
function M.clear() M._cookies = {}; M._introspection = nil end

return M
