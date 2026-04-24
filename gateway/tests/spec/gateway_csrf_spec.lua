-- Unit tests for gateway-csrf plugin.
--
-- Scope: APISIX-edge CSRF and header-sanitisation contracts only. Ory
-- Kratos/Oathkeeper own identity/session decisions.

package.path = "./?.lua;./stubs/?.lua;../custom/?.lua;" .. package.path

local mocks = require("stubs.install_mocks")
local ngx_stub = require("stubs.ngx_stub")

local function load_plugin()
    mocks.install()
    package.loaded["apisix.plugins.gateway-csrf"] = nil
    return dofile("../custom/apisix/plugins/gateway-csrf.lua")
end

local function decode(s)
    return require("cjson.safe").decode(s)
end

describe("gateway-csrf", function()
    local plugin

    before_each(function()
        ngx_stub.install({ headers = {}, method = "GET" })
        plugin = load_plugin()
        mocks.clear()
    end)

    after_each(function()
        ngx_stub.reset()
        mocks.uninstall()
    end)

    describe("is_safe_method", function()
        local is_safe_method
        before_each(function()
            is_safe_method = plugin._private.is_safe_method
        end)

        it("treats GET/HEAD/OPTIONS as safe", function()
            assert.is_true(is_safe_method("GET"))
            assert.is_true(is_safe_method("HEAD"))
            assert.is_true(is_safe_method("OPTIONS"))
        end)

        it("treats state-changing methods as unsafe", function()
            assert.is_false(is_safe_method("POST"))
            assert.is_false(is_safe_method("PUT"))
            assert.is_false(is_safe_method("PATCH"))
            assert.is_false(is_safe_method("DELETE"))
        end)
    end)

    describe("write_error (envelope contract)", function()
        it("produces the unified 403 CSRF envelope", function()
            local ok, exit_status = ngx_stub.pcall_with_exit(function()
                plugin._private.write_error(403, "rid-abc", "CSRF validation failed",
                    "GATEWAY_CSRF_INVALID", "AUTH")
            end)
            assert.is_true(ok)
            assert.equals(403, exit_status)

            local body = decode(ngx_stub.captured.body or "")
            assert.equals(403, body.code)
            assert.equals("CSRF validation failed", body.message)
            assert.equals("rid-abc", body.requestId)
            assert.equals("GATEWAY_CSRF_INVALID", body.details.errorCode)
            assert.equals("AUTH", body.details.category)
            assert.is_nil(body.apiVersion)
            assert.is_nil(body.errorCode)
        end)
    end)

    describe("apply_csrf", function()
        local apply_csrf
        before_each(function() apply_csrf = plugin._private.apply_csrf end)

        it("short-circuits when csrf_protect = false", function()
            local err = apply_csrf({ csrf_protect = false }, "rid")
            assert.is_nil(err)
        end)

        it("allows safe methods regardless of cookie/header", function()
            ngx_stub.install({ method = "GET" })
            local err = apply_csrf({ csrf_protect = true }, "rid")
            assert.is_nil(err)
        end)

        it("rejects POST with missing CSRF cookie as 403 + GATEWAY_CSRF_INVALID", function()
            ngx_stub.install({ method = "POST", headers = {} })
            mocks.set_cookies({})

            local ok, exit_status = ngx_stub.pcall_with_exit(function()
                apply_csrf({ csrf_protect = true }, "rid")
            end)
            assert.is_true(ok)
            assert.equals(403, exit_status)

            local body = decode(ngx_stub.captured.body)
            assert.equals("GATEWAY_CSRF_INVALID", body.details.errorCode)
            assert.equals("AUTH", body.details.category)
        end)

        it("rejects POST when cookie/header mismatch", function()
            ngx_stub.install({
                method = "POST",
                headers = { ["X-XSRF-TOKEN"] = "header-val" },
            })
            mocks.set_cookies({ ["XSRF-TOKEN"] = "cookie-val" })

            local ok, exit_status = ngx_stub.pcall_with_exit(function()
                apply_csrf({ csrf_protect = true }, "rid")
            end)
            assert.is_true(ok)
            assert.equals(403, exit_status)
        end)

        it("passes POST when cookie == header", function()
            ngx_stub.install({
                method = "POST",
                headers = { ["X-XSRF-TOKEN"] = "same" },
            })
            mocks.set_cookies({ ["XSRF-TOKEN"] = "same" })

            local err = apply_csrf({ csrf_protect = true }, "rid")
            assert.is_nil(err)
        end)

        -- Task 11 acceptance (architecture-tasks.md §Task 11):
        -- `X-XSRF-TOKEN` is the ONE canonical CSRF header name. Sending
        -- the retired alternative `X-CSRF-Token` (note casing) with no
        -- `X-XSRF-TOKEN` must still be rejected — the plugin must NOT
        -- recognize the alternative as a fallback, even when cookie
        -- value would otherwise match. Protects against the
        -- finding-#6 "which header is authoritative?" drift from
        -- silently re-entering via a plugin-side one-liner.
        it("rejects POST with X-CSRF-Token (non-canonical) but no X-XSRF-TOKEN", function()
            ngx_stub.install({
                method = "POST",
                headers = { ["X-CSRF-Token"] = "same" },
            })
            mocks.set_cookies({ ["XSRF-TOKEN"] = "same" })

            local ok, exit_status = ngx_stub.pcall_with_exit(function()
                apply_csrf({ csrf_protect = true }, "rid")
            end)
            assert.is_true(ok)
            assert.equals(403, exit_status)

            local body = decode(ngx_stub.captured.body)
            assert.equals("GATEWAY_CSRF_INVALID", body.details.errorCode)
            assert.equals("AUTH", body.details.category)
        end)
    end)

    describe("clear_identity_headers", function()
        it("strips every X-Auth-* header before Oathkeeper writes identity", function()
            ngx_stub.install({
                headers = {
                    ["x-auth-user-id"] = "9999",
                    ["x-auth-user-email"] = "a@b",
                    ["x-auth-session-id"] = "s",
                    ["X-Auth-Custom-Future-Attr"] = "x",
                    ["host"] = "example.com",
                },
            })

            plugin._private.clear_identity_headers()

            assert.is_true(ngx_stub.captured.req_headers_cleared["x-auth-user-id"])
            assert.is_true(ngx_stub.captured.req_headers_cleared["x-auth-user-email"])
            assert.is_true(ngx_stub.captured.req_headers_cleared["x-auth-session-id"])
            assert.is_true(ngx_stub.captured.req_headers_cleared["X-Auth-Custom-Future-Attr"])
            assert.is_nil(ngx_stub.captured.req_headers_cleared["host"])
        end)
    end)

    describe("ensure_request_id", function()
        it("propagates an inbound X-Request-Id unchanged and echoes it", function()
            ngx_stub.install({ headers = { ["X-Request-Id"] = "inbound-123" } })
            local rid = plugin._private.ensure_request_id()
            assert.equals("inbound-123", rid)
            assert.equals("inbound-123", ngx_stub.captured.headers["X-Request-Id"])
        end)

        it("mints a new X-Request-Id when absent", function()
            ngx_stub.install({ headers = {} })
            local rid = plugin._private.ensure_request_id()
            assert.is_string(rid)
            assert.is_true(#rid > 0)
            assert.equals(rid, ngx_stub.captured.headers["X-Request-Id"])
            assert.equals(rid, ngx_stub.captured.req_headers_set["X-Request-Id"])
        end)
    end)
end)
