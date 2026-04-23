-- Unit tests for gateway-auth plugin.
--
-- Scope: pure contract assertions that protect backend.md §6.0 / §6.3.1 from
-- drift -- every failure branch must produce the unified envelope with the
-- right (errorCode, category) pair. We deliberately do NOT try to recreate a
-- full APISIX runtime; anything needing real nginx belongs in smoke tests
-- (scripts/smoke.sh) or an integration harness.

package.path = "./?.lua;./stubs/?.lua;" .. package.path

local mocks = require("stubs.install_mocks")
local ngx_stub = require("stubs.ngx_stub")

local function load_plugin()
    mocks.install()
    package.loaded["apisix.plugins.gateway-auth"] = nil
    -- Path: gateway/custom/apisix/plugins/gateway-auth.lua; from tests/ we
    -- reach it via a relative dofile -- require() would need package path
    -- munging that confuses the stubs above.
    local plugin = dofile("../custom/apisix/plugins/gateway-auth.lua")
    return plugin
end

local function decode(s)
    return require("cjson.safe").decode(s)
end

describe("gateway-auth", function()
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

    describe("should_skip_csrf", function()
        it("mirrors is_safe_method — contract lives on method alone", function()
            -- CRITICAL: must NOT branch on cookie presence. See gateway.md §5.2.
            assert.is_true(plugin._private.should_skip_csrf("GET"))
            assert.is_false(plugin._private.should_skip_csrf("POST"))
        end)
    end)

    describe("should_retry", function()
        it("retries on transient transport errors", function()
            local should_retry = plugin._private.should_retry
            assert.is_true(should_retry("connect() failed: connection refused"))
            assert.is_true(should_retry("upstream timeout"))
            assert.is_true(should_retry("connection closed"))
        end)

        it("does not retry on nil or on permanent errors", function()
            local should_retry = plugin._private.should_retry
            assert.is_false(should_retry(nil))
            assert.is_false(should_retry("unexpected introspection status"))
        end)
    end)

    describe("write_error (envelope contract — backend.md §6.0)", function()
        local write_error
        before_each(function() write_error = plugin._private.write_error end)

        local function capture_write_error(status, rid, msg, ec, cat)
            local ok, exit_status = ngx_stub.pcall_with_exit(function()
                write_error(status, rid, msg, ec, cat)
            end)
            assert.is_true(ok, "write_error did not exit cleanly: " .. tostring(exit_status))
            assert.equals(status, exit_status)

            local body = decode(ngx_stub.captured.body or "")
            return body
        end

        it("produces the §6.0 envelope with errorCode and category in details", function()
            local body = capture_write_error(401, "rid-abc", "Authentication required",
                "GATEWAY_AUTH_REQUIRED", "AUTH")

            assert.equals(401, body.code)
            assert.equals("Authentication required", body.message)
            assert.equals("rid-abc", body.requestId)
            assert.is_table(body.details)
            assert.equals("GATEWAY_AUTH_REQUIRED", body.details.errorCode)
            assert.equals("AUTH", body.details.category)

            assert.equals(401, ngx_stub.captured.status)
            assert.equals("rid-abc", ngx_stub.captured.headers["X-Request-Id"])
            assert.equals("application/json; charset=utf-8", ngx_stub.captured.headers["Content-Type"])
        end)

        it("does NOT emit apiVersion or top-level errorCode (§9 refactor)", function()
            local body = capture_write_error(403, "rid", "x", "GATEWAY_CSRF_INVALID", "AUTH")
            assert.is_nil(body.apiVersion)
            assert.is_nil(body.errorCode)    -- top-level is forbidden; lives only under details
        end)

        -- §6.3.1 gateway-side errorCode/category registry. If any of these
        -- drift, the matrix in docs/development/backend.md is out of sync
        -- with the implementation and the frontend two-tier dispatch breaks.
        local registry = {
            { 403, "GATEWAY_CSRF_INVALID",           "AUTH" },
            { 401, "GATEWAY_AUTH_REQUIRED",          "AUTH" },
            { 503, "GATEWAY_INTROSPECT_UNAVAILABLE", "UPSTREAM" },
        }
        for _, row in ipairs(registry) do
            local status, ec, cat = row[1], row[2], row[3]
            it(("registry entry %d/%s/%s round-trips unchanged"):format(status, ec, cat), function()
                local body = capture_write_error(status, "rid", "m", ec, cat)
                assert.equals(status, body.code)
                assert.equals(ec, body.details.errorCode)
                assert.equals(cat, body.details.category)
            end)
        end
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
    end)

    describe("clear_identity_headers", function()
        it("strips every X-Auth-* header, not only the known ones", function()
            -- Contract: enumerating known names is unsafe. See gateway.md §3.2.
            ngx_stub.install({
                headers = {
                    ["x-auth-user-id"] = "9999",      -- attacker-supplied
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
            -- Must NOT clear unrelated headers
            assert.is_nil(ngx_stub.captured.req_headers_cleared["host"])
        end)
    end)

    describe("ensure_request_id", function()
        it("propagates an inbound X-Request-Id unchanged and echoes it on the response", function()
            ngx_stub.install({ headers = { ["X-Request-Id"] = "inbound-123" } })
            local rid = plugin._private.ensure_request_id()
            assert.equals("inbound-123", rid)
            assert.equals("inbound-123", ngx_stub.captured.headers["X-Request-Id"])
        end)

        it("mints a new X-Request-Id when absent and sets both req+resp headers", function()
            ngx_stub.install({ headers = {} })
            local rid = plugin._private.ensure_request_id()
            assert.is_string(rid)
            assert.is_true(#rid > 0)
            assert.equals(rid, ngx_stub.captured.headers["X-Request-Id"])
            assert.equals(rid, ngx_stub.captured.req_headers_set["X-Request-Id"])
        end)
    end)
end)
