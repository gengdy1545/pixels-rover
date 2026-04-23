-- Unit tests for gateway-ready plugin.
--
-- Scope: the pure build_verdict helper + the empty-probes envelope. Full
-- integration (ngx.location.capture_multi dispatch, nginx timeouts) is
-- covered by scripts/smoke.sh, not here.

package.path = "./?.lua;./stubs/?.lua;" .. package.path

local mocks = require("stubs.install_mocks")
local ngx_stub = require("stubs.ngx_stub")

local function load_plugin()
    mocks.install()
    package.loaded["apisix.plugins.gateway-ready"] = nil
    return dofile("../custom/apisix/plugins/gateway-ready.lua")
end

describe("gateway-ready", function()
    local plugin

    before_each(function()
        ngx_stub.install({ headers = {}, method = "GET" })
        plugin = load_plugin()
    end)

    after_each(function()
        ngx_stub.reset()
        mocks.uninstall()
    end)

    describe("empty_probes_body", function()
        it("returns the 503 envelope mandated by backend.md §6.0", function()
            local body = plugin._private.empty_probes_body("rid-xyz")
            assert.equals(503, body.code)
            assert.equals("No upstream probes registered", body.message)
            assert.equals("rid-xyz", body.requestId)
            assert.equals("GATEWAY_NOT_READY", body.details.errorCode)
            assert.equals("UPSTREAM", body.details.category)
            assert.is_table(body.details.components)
            assert.equals(0, #body.details.components)
        end)
    end)

    describe("build_verdict", function()
        local build_verdict
        before_each(function() build_verdict = plugin._private.build_verdict end)

        local probes = {
            { name = "auth",      uri = "/__ready_probe/auth" },
            { name = "assistant", uri = "/__ready_probe/assistant" },
        }

        it("returns 200 + UP components when every probe is 200", function()
            local status, body = build_verdict(probes, {
                { status = 200 }, { status = 200 },
            }, "rid", 12)
            assert.equals(200, status)
            assert.equals(200, body.code)
            assert.equals("ready", body.message)
            assert.equals(12, body.data.elapsedMs)
            assert.equals(2, #body.data.components)
            assert.equals("UP", body.data.components[1].status)
            assert.equals("UP", body.data.components[2].status)
        end)

        it("returns 503 + DOWN marker when any probe is non-200", function()
            local status, body = build_verdict(probes, {
                { status = 200 }, { status = 500 },
            }, "rid", 42)
            assert.equals(503, status)
            assert.equals("GATEWAY_NOT_READY", body.details.errorCode)
            assert.equals("UPSTREAM", body.details.category)
            assert.equals("UP", body.details.components[1].status)
            assert.equals("DOWN", body.details.components[2].status)
            assert.equals(500, body.details.components[2].httpCode)
        end)

        it("treats a missing response as DOWN with httpCode=0", function()
            -- capture_multi returns nil on subrequest error; we must not crash.
            local status, body = build_verdict(probes, {
                { status = 200 }, nil,
            }, "rid", 1)
            assert.equals(503, status)
            assert.equals(0, body.details.components[2].httpCode)
            assert.equals("DOWN", body.details.components[2].status)
        end)

        it("never emits apiVersion or top-level errorCode in the 503 body (§9)", function()
            local _, body = build_verdict(probes, { { status = 503 }, { status = 200 } }, "rid", 0)
            assert.is_nil(body.apiVersion)
            assert.is_nil(body.errorCode)
        end)
    end)
end)
