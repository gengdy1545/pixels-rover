-- Minimal ngx stub for busted-based unit tests of APISIX plugins.
--
-- Usage:
--   local ngx_stub = require("stubs.ngx_stub")
--   ngx_stub.install({
--       headers = { ["X-Request-Id"] = "abc" },
--       method = "POST",
--   })
--   -- ...require the plugin, drive it, then assert on ngx_stub.captured.*
--   ngx_stub.reset()
--
-- Covers the surface that gateway-auth / gateway-ready touch. Intentionally
-- simple -- if a plugin starts needing more ngx APIs, extend here explicitly
-- rather than silently no-op'ing; a quiet no-op mask is how real regressions
-- leak past unit tests.

local M = {}

M.captured = {}

local function reset_captured()
    M.captured = {
        status = nil,
        headers = {},
        body = nil,
        exit_status = nil,
        log = {},
        req_headers_set = {},
        req_headers_cleared = {},
    }
end

reset_captured()

local function build_ngx(opts)
    opts = opts or {}
    local req_headers = opts.headers or {}
    local method = opts.method or "GET"

    -- Lower-case lookup to match APISIX / ngx behaviour
    local function lookup_header(name)
        return req_headers[name] or req_headers[string.lower(name)]
    end

    local req = {
        get_method = function() return method end,
        get_headers = function()
            -- Return a shallow copy so plugin code can iterate safely
            local copy = {}
            for k, v in pairs(req_headers) do copy[k] = v end
            return copy
        end,
        set_header = function(name, value)
            M.captured.req_headers_set[name] = value
            req_headers[name] = value
        end,
        clear_header = function(name)
            M.captured.req_headers_cleared[name] = true
            req_headers[name] = nil
            req_headers[string.lower(name)] = nil
        end,
    }

    local header = setmetatable({}, {
        __index = function(_, k) return M.captured.headers[k] end,
        __newindex = function(_, k, v) M.captured.headers[k] = v end,
    })

    local shared = {
        gateway_auth_cache = {
            _data = {},
            get = function(self, k) return self._data[k] end,
            set = function(self, k, v, _ttl) self._data[k] = v end,
        },
    }

    local ngx = {
        status = nil,
        header = header,
        req = req,
        var = { remote_addr = "127.0.0.1", scheme = "http", host = "testserver" },
        now = function() return 1700000000 end,
        time = function() return 1700000000 end,
        say = function(body)
            M.captured.body = body
        end,
        exit = function(status)
            M.captured.exit_status = status
            error({ _exit = true, status = status })
        end,
        log = function(level, ...)
            table.insert(M.captured.log, { level = level, args = { ... } })
        end,
        HTTP_GET = "GET",
        ERR = 4,
        WARN = 5,
        INFO = 7,
        DEBUG = 8,
        ctx = {},
        shared = shared,
        location = {
            capture_multi = function(requests)
                -- Overridden per-test via monkeypatch; default fails loudly.
                error("ngx.location.capture_multi not stubbed for this test")
            end,
        },
        sha256_bin = function(s) return s end,
    }

    -- ngx.status is readable/writable; proxy through captured for assertions
    setmetatable(ngx, {
        __index = function(t, k)
            if k == "status" then return rawget(t, "_status") end
            return rawget(t, k)
        end,
        __newindex = function(t, k, v)
            if k == "status" then
                rawset(t, "_status", v)
                M.captured.status = v
                return
            end
            rawset(t, k, v)
        end,
    })

    return ngx
end

function M.install(opts)
    reset_captured()
    _G.ngx = build_ngx(opts)
    return _G.ngx
end

function M.reset()
    reset_captured()
    _G.ngx = nil
end

-- Helper: invoke fn and swallow the ngx.exit pseudo-exception so assertions
-- can run against M.captured.* afterwards.
function M.pcall_with_exit(fn)
    local ok, err = pcall(fn)
    if not ok and type(err) == "table" and err._exit then
        return true, err.status
    end
    return ok, err
end

return M
