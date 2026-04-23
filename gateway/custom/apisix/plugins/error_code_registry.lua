-- error_code_registry: tiny helper shared by gateway plugins so
-- each plugin can self-check, at plugin-loader init time, that every
-- `GATEWAY_* / INTERNAL_*` string literal the plugin may emit is registered
-- in `gateway/error-codes.json` (= `/usr/local/apisix/conf/error-codes.json`
-- inside the container).
--
-- Rationale (see todolist.md §9.2 point 5 / docs/development/gateway.md §5.1):
--   * `gateway/error-codes.json` is the single source of truth for
--     infrastructure-prefix error codes; backend.md §6.3.1 is a rendered
--     view and frontend/src/shared/types/infra.ts mirrors the set.
--   * The CI gate (`scripts/check-contracts.py`) is the primary defense
--     against drift — this module is the secondary, in-process defense:
--     if an operator rebuilds the image with a Lua source change that
--     references an unregistered errorCode AND bypasses CI, the plugin
--     loader still errors out at worker init rather than silently shipping
--     the drifted code into production.
--   * Hard failure model: `error(msg)` inside plugin init triggers
--     APISIX's plugin-loader failure path. Since edge plugins protect the
--     browser boundary, a loader failure fails requests closed — which is
--     exactly what we want when the contract boundary has drifted.
--
-- Non-goals:
--   * This module does not discover errorCode literals from the plugin
--     source (too fragile across Lua AST forms). Each plugin explicitly
--     lists the literals it may emit in a `KNOWN_ERROR_CODES` table and
--     passes that table to `assert_registered()`. That same list is the
--     ground truth `scripts/check-contracts.py` also cross-checks against
--     `rg`-scanned literals — a two-sided assertion.
--   * This module does not reload the JSON at runtime. Rebuild the image
--     after editing `gateway/error-codes.json`.

local cjson = require("cjson.safe")

local _M = {}

-- Path inside the container. `GATEWAY_ERROR_CODES_JSON` is only honoured as
-- an override for unit tests running outside the APISIX image; production
-- ignores it.
local REGISTRY_PATH = os.getenv("GATEWAY_ERROR_CODES_JSON")
    or "/usr/local/apisix/conf/error-codes.json"

local cached_codes

local function load_registry()
    if cached_codes then
        return cached_codes
    end
    local f, open_err = io.open(REGISTRY_PATH, "r")
    if not f then
        error(string.format(
            "gateway error-code registry missing at %s: %s. "
            .. "Dockerfile must COPY gateway/error-codes.json into /usr/local/apisix/conf/.",
            REGISTRY_PATH, open_err or "unknown error"))
    end
    local body = f:read("*a")
    f:close()

    local decoded, err = cjson.decode(body or "")
    if not decoded then
        error(string.format(
            "gateway error-code registry %s failed to parse: %s",
            REGISTRY_PATH, tostring(err)))
    end
    if type(decoded.codes) ~= "table" then
        error(string.format(
            "gateway error-code registry %s is missing top-level `codes` object",
            REGISTRY_PATH))
    end
    cached_codes = decoded.codes
    return cached_codes
end

-- `plugin_name` is embedded in the panic message so operators can tell which
-- plugin tripped the assertion when APISIX logs a stack trace at boot.
-- `names` is a flat array of SCREAMING_SNAKE_CASE strings.
function _M.assert_registered(plugin_name, names)
    local codes = load_registry()
    for _, name in ipairs(names) do
        if not codes[name] then
            error(string.format(
                "%s: errorCode %q is emitted by this plugin but not registered "
                .. "in %s. Add it to gateway/error-codes.json and rebuild.",
                plugin_name, name, REGISTRY_PATH))
        end
    end
end

-- Exposed for unit tests / gateway/tests/spec/*.lua only.
_M._private = {
    reset_cache = function() cached_codes = nil end,
    registry_path = function() return REGISTRY_PATH end,
}

return _M
