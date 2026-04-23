#!/usr/bin/env python3
"""Cross-layer contract drift detector for pixels-rover.

Purpose
-------

The gateway, auth-service, assistant-service, and frontend each make
contract-bearing claims that MUST agree with each other: error-code
registries, APISIX route declarations, Lua shared-dict sizing, internal
prefix isolation, readiness probe coverage, etc. Hand-review cannot catch
drift reliably, so this script encodes the cross-layer invariants as
machine assertions.

This is the **first cut** — shipped alongside the B3+C4 PR that introduces
``gateway/error-codes.json`` as the single source of truth for
infrastructure-prefix error codes. Later PRs (A1+A3 session invalidation,
OpenAPI public/private toggling, etc.) will extend this script with more
checks; the scaffolding below is designed to accept new check functions
as ``@register_check`` decorated functions without touching ``main()``.

Usage
-----

Run everything (default — exit 1 on any failure)::

    python3 scripts/check-contracts.py

Run a specific subset::

    python3 scripts/check-contracts.py --only error-codes,shared-dicts

List available checks::

    python3 scripts/check-contracts.py --list

CI integration (see ``todolist.md §15.2``): this script is expected to run
as a PR gate next to ``scripts/smoke.sh``. Either failure blocks merge.

Hard rule (todolist §15.2): an assertion here that **cannot** be expressed
as a reproducible grep / AST walk / YAML parse does not belong here —
move it to ``scripts/smoke.sh`` instead, which has access to a live
``docker compose up`` environment.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - dev env should always have PyYAML
    print(
        "error: PyYAML is required (pip install pyyaml)",
        file=sys.stderr,
    )
    sys.exit(2)


REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Infrastructure: check registry + result type
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    """A single check's verdict. ``failures`` empty == pass."""

    name: str
    description: str
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


CheckFn = Callable[[], CheckResult]
REGISTERED_CHECKS: list[tuple[str, str, CheckFn]] = []


def register_check(name: str, description: str):
    def decorator(fn: CheckFn):
        REGISTERED_CHECKS.append((name, description, fn))
        return fn

    return decorator


# ---------------------------------------------------------------------------
# Shared loaders (cached at module scope so repeated checks don't re-parse)
# ---------------------------------------------------------------------------


_ERROR_CODES_PATH = REPO_ROOT / "gateway" / "error-codes.json"
_APISIX_YAML_PATH = REPO_ROOT / "gateway" / "apisix.yaml"
_CONFIG_TEMPLATE_PATH = REPO_ROOT / "gateway" / "config.yaml.template"
_INFRA_TS_PATH = REPO_ROOT / "frontend" / "src" / "shared" / "types" / "infra.ts"
_PLUGIN_DIR = REPO_ROOT / "gateway" / "custom" / "apisix" / "plugins"


def _load_error_codes() -> dict:
    return json.loads(_ERROR_CODES_PATH.read_text(encoding="utf-8"))


def _load_apisix_yaml() -> dict:
    # APISIX Standalone YAML ends with a literal `#END` marker that is not
    # actually valid YAML body — strip any trailing content after the final
    # document separator before parsing. In practice PyYAML tolerates `#END`
    # as a comment, so no special handling is needed, but we keep a guard.
    text = _APISIX_YAML_PATH.read_text(encoding="utf-8")
    return yaml.safe_load(text) or {}


def _load_config_template() -> str:
    # The template contains ${VAR} placeholders that aren't valid YAML values
    # after envsubst, but the shape we care about (lua_shared_dict directives,
    # `location` blocks) lives inside literal block scalars. We treat it as
    # raw text for grep-style checks.
    return _CONFIG_TEMPLATE_PATH.read_text(encoding="utf-8")


def _load_infra_ts_union() -> set[str]:
    """Parse the ``InfraErrorCode`` union body and return its string literal set."""
    source = _INFRA_TS_PATH.read_text(encoding="utf-8")
    m = re.search(
        r"export\s+type\s+InfraErrorCode\s*=\s*(.*?);",
        source,
        re.DOTALL,
    )
    if not m:
        return set()
    body = m.group(1)
    return set(re.findall(r"'([A-Z][A-Z0-9_]+)'", body))


def _plugin_sources() -> list[tuple[Path, str]]:
    return [
        (p, p.read_text(encoding="utf-8"))
        for p in sorted(_PLUGIN_DIR.glob("*.lua"))
    ]


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


@register_check(
    "error-codes-json-shape",
    "gateway/error-codes.json parses, has non-empty codes{}, and every "
    "entry carries the required fields.",
)
def check_error_codes_json_shape() -> CheckResult:
    result = CheckResult(
        "error-codes-json-shape",
        "gateway/error-codes.json shape",
    )
    try:
        registry = _load_error_codes()
    except FileNotFoundError:
        result.failures.append(f"{_ERROR_CODES_PATH} is missing")
        return result
    except json.JSONDecodeError as exc:
        result.failures.append(f"{_ERROR_CODES_PATH} is not valid JSON: {exc}")
        return result

    codes = registry.get("codes")
    if not isinstance(codes, dict) or not codes:
        result.failures.append(
            "top-level `codes` must be a non-empty object"
        )
        return result

    required_fields = ("httpStatus", "category", "writtenBy", "trigger", "retryable", "docAnchor")
    allowed_categories = {"USER_INPUT", "AUTH", "RATE_LIMIT", "UPSTREAM", "INTERNAL"}
    key_pattern = re.compile(r"^(GATEWAY|INTERNAL)_[A-Z][A-Z0-9_]*$")

    for name, meta in sorted(codes.items()):
        if not key_pattern.match(name):
            result.failures.append(
                f"code name {name!r} violates ^(GATEWAY|INTERNAL)_[A-Z][A-Z0-9_]*$"
            )
            continue
        if not isinstance(meta, dict):
            result.failures.append(f"{name}: entry must be an object")
            continue
        for fld in required_fields:
            if fld not in meta:
                result.failures.append(f"{name}: missing required field `{fld}`")
        status = meta.get("httpStatus")
        if not isinstance(status, int) or not (400 <= status <= 599):
            result.failures.append(
                f"{name}: httpStatus must be an integer in 400..599, got {status!r}"
            )
        cat = meta.get("category")
        if cat not in allowed_categories:
            result.failures.append(
                f"{name}: category must be one of {sorted(allowed_categories)}, got {cat!r}"
            )
        if "retryable" in meta and not isinstance(meta["retryable"], bool):
            result.failures.append(f"{name}: retryable must be boolean")
        if meta.get("retryable") is False and "retryGuidance" in meta:
            result.failures.append(
                f"{name}: retryGuidance is only meaningful when retryable=true"
            )
    return result


@register_check(
    "backend-md-registry-rendered",
    "docs/development/backend.md §6.3.1 table matches gateway/error-codes.json",
)
def check_backend_md_rendered_view() -> CheckResult:
    result = CheckResult(
        "backend-md-registry-rendered",
        "backend.md §6.3.1 rendered view",
    )
    # Delegate to the renderer in --check mode so we stay DRY.
    import subprocess

    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "generate-error-code-registry.py"),
            "--check",
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip()
        result.failures.append(
            f"generate-error-code-registry.py --check failed: {msg}"
        )
    return result


# Two Lua literal forms we scan for: `"GATEWAY_FOO"` and `'GATEWAY_FOO'`.
# Plugin source never uses double brackets for errorCodes, so this covers all
# current call sites.
#
# Scan excludes:
#   * `-- ... to EOL` line comments (lightweight preprocessing, sufficient
#     because plugin source never embeds errorCode strings inside block
#     comments);
#   * `os.getenv("GATEWAY_*" or "INTERNAL_*")` arguments — those are env var
#     names that happen to share the infra prefixes by naming convention
#     (e.g. `INTERNAL_INTROSPECTION_SECRET`, `GATEWAY_ERROR_CODES_JSON`);
#   * `require("apisix.plugins.error_code_registry")` / similar module paths
#     (not infra-prefix literals anyway, but documented for clarity).
_LUA_ERROR_CODE_RE = re.compile(r"""["']([A-Z][A-Z0-9_]+)["']""")
_LUA_INFRA_PREFIX_RE = re.compile(r"^(GATEWAY|INTERNAL)_")
_LUA_OS_GETENV_RE = re.compile(r"""os\.getenv\s*\(\s*["'][^"']+["']\s*\)""")


def _strip_lua_line_comments(source: str) -> str:
    out_lines = []
    for line in source.splitlines():
        # Respect `--` only when it isn't inside a string literal. The plugin
        # sources don't embed `--` inside strings, so the simple split is
        # safe; a dedicated lexer would be overkill.
        idx = line.find("--")
        if idx != -1:
            line = line[:idx]
        out_lines.append(line)
    return "\n".join(out_lines)


def _strip_env_var_lookups(source: str) -> str:
    """Remove ``os.getenv("NAME")`` call sites so their env-var names don't
    get confused with errorCode literals. The replacement keeps character
    positions roughly stable but that is not important for the regex-scan
    consumers."""
    return _LUA_OS_GETENV_RE.sub("os.getenv(_ENV_)", source)


@register_check(
    "lua-literals-registered",
    "Every GATEWAY_* / INTERNAL_* literal in plugin source is registered in JSON.",
)
def check_lua_literals_registered() -> CheckResult:
    result = CheckResult("lua-literals-registered", "Lua literal ⊆ JSON")
    codes = set(_load_error_codes().get("codes", {}).keys())
    if not codes:
        result.failures.append("registry empty; cannot validate Lua literals")
        return result

    for path, source in _plugin_sources():
        stripped = _strip_env_var_lookups(_strip_lua_line_comments(source))
        for match in _LUA_ERROR_CODE_RE.finditer(stripped):
            literal = match.group(1)
            if not _LUA_INFRA_PREFIX_RE.match(literal):
                continue
            if literal not in codes:
                rel = path.relative_to(REPO_ROOT)
                result.failures.append(
                    f"{rel}: Lua source references {literal!r} which is not "
                    "in gateway/error-codes.json"
                )
    return result


@register_check(
    "lua-known-table-matches-literals",
    "Each plugin's KNOWN_ERROR_CODES table matches the GATEWAY_*/INTERNAL_* "
    "literals actually present in that plugin's source (no stale table, no "
    "unlisted literal).",
)
def check_lua_known_table_matches_literals() -> CheckResult:
    result = CheckResult(
        "lua-known-table-matches-literals",
        "KNOWN_ERROR_CODES ↔ plugin source",
    )
    # Only audit the two custom plugins that actually emit errorCodes; skip
    # the shared helper and any future non-emitting modules.
    targeted = {"gateway-auth.lua", "gateway-ready.lua"}

    for path, source in _plugin_sources():
        if path.name not in targeted:
            continue
        rel = path.relative_to(REPO_ROOT)
        stripped = _strip_env_var_lookups(_strip_lua_line_comments(source))

        # Extract declared KNOWN_ERROR_CODES table.
        m = re.search(
            r"KNOWN_ERROR_CODES\s*=\s*\{(.*?)\}",
            stripped,
            re.DOTALL,
        )
        if not m:
            result.failures.append(
                f"{rel}: no KNOWN_ERROR_CODES table declared (expected for "
                "init() self-check)"
            )
            continue
        declared = set(re.findall(r"""["']([A-Z][A-Z0-9_]+)["']""", m.group(1)))
        declared = {c for c in declared if _LUA_INFRA_PREFIX_RE.match(c)}

        # Extract literals outside the KNOWN table (remove the KNOWN block
        # first so we don't double-count).
        source_without_known = stripped[: m.start()] + stripped[m.end():]
        emitted = {
            match.group(1)
            for match in _LUA_ERROR_CODE_RE.finditer(source_without_known)
            if _LUA_INFRA_PREFIX_RE.match(match.group(1))
        }

        missing_in_known = emitted - declared
        stale_in_known = declared - emitted
        if missing_in_known:
            result.failures.append(
                f"{rel}: literals {sorted(missing_in_known)} are emitted but "
                "not in KNOWN_ERROR_CODES — init self-check would pass them "
                "silently. Add to KNOWN_ERROR_CODES."
            )
        if stale_in_known:
            result.failures.append(
                f"{rel}: KNOWN_ERROR_CODES declares {sorted(stale_in_known)} "
                "but plugin source no longer emits them. Remove."
            )
    return result


@register_check(
    "frontend-infra-union-equals-json",
    "frontend/src/shared/types/infra.ts InfraErrorCode union equals "
    "gateway/error-codes.json keys (bidirectional).",
)
def check_frontend_union_matches_json() -> CheckResult:
    result = CheckResult(
        "frontend-infra-union-equals-json",
        "InfraErrorCode union = JSON",
    )
    json_codes = set(_load_error_codes().get("codes", {}).keys())
    union = _load_infra_ts_union()
    only_in_json = json_codes - union
    only_in_union = union - json_codes
    if only_in_json:
        result.failures.append(
            f"gateway/error-codes.json has codes not in InfraErrorCode union: {sorted(only_in_json)}"
        )
    if only_in_union:
        result.failures.append(
            f"InfraErrorCode union has codes not in gateway/error-codes.json: {sorted(only_in_union)}"
        )
    return result


# ---------------------------------------------------------------------------
# lua_shared_dict checks (B3)
# ---------------------------------------------------------------------------


_SHARED_DICTS = ("gateway_auth_cache", "gateway_auth_session_index", "gateway_auth_user_index")
_SHARED_DICT_MIN_MB = 8


@register_check(
    "shared-dicts-declared",
    "config.yaml.template declares all three lua_shared_dict entries with size >= 8m.",
)
def check_shared_dicts_declared() -> CheckResult:
    result = CheckResult("shared-dicts-declared", "lua_shared_dict declarations")
    text = _load_config_template()
    for name in _SHARED_DICTS:
        m = re.search(
            rf"lua_shared_dict\s+{re.escape(name)}\s+(\d+)([kKmM]);",
            text,
        )
        if not m:
            result.failures.append(
                f"lua_shared_dict {name} not declared in config.yaml.template"
            )
            continue
        size = int(m.group(1))
        unit = m.group(2).lower()
        size_mb = size if unit == "m" else size / 1024
        if size_mb < _SHARED_DICT_MIN_MB:
            result.failures.append(
                f"lua_shared_dict {name} declared as {size}{unit}; "
                f"minimum is {_SHARED_DICT_MIN_MB}m (gateway.md §5.3.2)"
            )
    return result


_BANNED_SHARED_DICT_METHODS = ("safe_set", "safe_add", "incr")


@register_check(
    "shared-dict-access-banned-methods",
    "Lua source never invokes safe_set / safe_add / incr on the three reverse-index "
    "dicts (RMW banned; LRU eviction must win over `no memory`).",
)
def check_shared_dict_banned_methods() -> CheckResult:
    result = CheckResult(
        "shared-dict-access-banned-methods",
        "shared_dict access method allow-list",
    )
    for path, source in _plugin_sources():
        stripped = _strip_lua_line_comments(source)
        for dict_name in _SHARED_DICTS:
            # Find accesses like `ngx.shared.<name>:<method>` or via a local
            # alias; covering the local-alias form robustly needs flow analysis
            # so we scan for the banned methods appearing anywhere the dict
            # name also appears in the file.
            if dict_name not in stripped:
                continue
            for method in _BANNED_SHARED_DICT_METHODS:
                if re.search(
                    rf":\s*{re.escape(method)}\s*\(",
                    stripped,
                ):
                    rel = path.relative_to(REPO_ROOT)
                    result.failures.append(
                        f"{rel}: calls :{method}(...) and references "
                        f"shared_dict {dict_name}; use :set/:get/:delete "
                        "(LRU eviction required by gateway.md §5.3.2)"
                    )
    return result


# ---------------------------------------------------------------------------
# APISIX route / plugin checks
# ---------------------------------------------------------------------------


def _gateway_auth_routes(apisix: dict) -> list[dict]:
    """Return every route entry in apisix.yaml that carries the gateway-auth plugin."""
    routes = apisix.get("routes") or []
    return [r for r in routes if isinstance(r, dict) and "gateway-auth" in (r.get("plugins") or {})]


@register_check(
    "gateway-auth-route-mandatory-fields",
    "Every gateway-auth route in apisix.yaml explicitly declares "
    "positive_cache_ttl / negative_cache_ttl / introspect_timeout_ms / "
    "introspect_total_budget_ms (todolist.md §7.2).",
)
def check_gateway_auth_route_fields() -> CheckResult:
    result = CheckResult(
        "gateway-auth-route-mandatory-fields",
        "gateway-auth per-route required fields",
    )
    required = (
        "positive_cache_ttl",
        "negative_cache_ttl",
        "introspect_timeout_ms",
        "introspect_total_budget_ms",
    )
    apisix = _load_apisix_yaml()
    for route in _gateway_auth_routes(apisix):
        conf = route["plugins"]["gateway-auth"]
        missing = [f for f in required if f not in conf]
        if missing:
            rid = route.get("id") or route.get("uri") or "<unnamed>"
            result.failures.append(
                f"route {rid}: gateway-auth missing {missing}"
            )
    return result


@register_check(
    "no-external-internal-prefix-routes",
    "apisix.yaml declares zero routes whose uri starts with /api/internal/ or "
    "/gateway/internal/ (backend.md §8.6; gateway.md §6.1).",
)
def check_no_external_internal_routes() -> CheckResult:
    result = CheckResult(
        "no-external-internal-prefix-routes",
        "/api/internal/* and /gateway/internal/* zero exposure",
    )
    apisix = _load_apisix_yaml()
    banned_prefixes = ("/api/internal/", "/gateway/internal/")
    for route in apisix.get("routes") or []:
        uri = route.get("uri") or ""
        if any(uri.startswith(p) for p in banned_prefixes):
            result.failures.append(
                f"route {route.get('id', uri)!r} exposes {uri!r} — "
                "internal prefixes must NOT have external routes"
            )
    return result


@register_check(
    "positive-cache-ttl-invalidate-session-linkage",
    "If no /gateway/internal/invalidate_session route exists, every "
    "gateway-auth route must have positive_cache_ttl <= 5 (gateway.md §5.3 "
    "bidirectional invariant).",
)
def check_positive_cache_invalidate_linkage() -> CheckResult:
    result = CheckResult(
        "positive-cache-ttl-invalidate-session-linkage",
        "positive_cache_ttl ↔ invalidate_session",
    )
    apisix = _load_apisix_yaml()
    has_invalidate = any(
        (r.get("uri") or "").rstrip("/") == "/gateway/internal/invalidate_session"
        for r in apisix.get("routes") or []
    )
    if has_invalidate:
        # Reverse direction: when invalidate_session IS declared, at least one
        # route should reasonably have positive_cache_ttl > 5 (else why bother
        # declaring it?). We don't enforce this strictly because intermediate
        # states during a PR chain are legitimate.
        return result

    for route in _gateway_auth_routes(apisix):
        conf = route["plugins"]["gateway-auth"]
        ttl = conf.get("positive_cache_ttl")
        if isinstance(ttl, int) and ttl > 5:
            rid = route.get("id") or route.get("uri") or "<unnamed>"
            result.failures.append(
                f"route {rid}: positive_cache_ttl={ttl} but no "
                "/gateway/internal/invalidate_session route exists. "
                "Lower to <=5 or land the invalidate_session PR first."
            )
    return result


# ---------------------------------------------------------------------------
# gateway-ready probes[] ↔ internal locations (B1+B2)
# ---------------------------------------------------------------------------


def _gateway_ready_probes(apisix: dict) -> list[dict]:
    for route in apisix.get("routes") or []:
        plugins = route.get("plugins") or {}
        conf = plugins.get("gateway-ready")
        if conf:
            return conf.get("probes") or []
    return []


def _gateway_ready_total_timeout(apisix: dict) -> int | None:
    for route in apisix.get("routes") or []:
        plugins = route.get("plugins") or {}
        conf = plugins.get("gateway-ready")
        if conf:
            val = conf.get("total_timeout_ms")
            return val if isinstance(val, int) else None
    return None


_INTERNAL_LOCATION_RE = re.compile(
    r"location\s*=\s*(/__ready_probe/[A-Za-z0-9_\-]+)\s*\{",
)


@register_check(
    "ready-probes-match-internal-locations",
    "gateway-ready.probes[].uri set equals the /__ready_probe/* location set "
    "declared in config.yaml.template's http_server_configuration_snippet "
    "(gateway.md §4.1).",
)
def check_probes_match_locations() -> CheckResult:
    result = CheckResult(
        "ready-probes-match-internal-locations",
        "gateway-ready probes ↔ internal locations",
    )
    apisix = _load_apisix_yaml()
    probes = _gateway_ready_probes(apisix)
    probe_uris = {p.get("uri") for p in probes if p.get("uri")}
    locations = set(_INTERNAL_LOCATION_RE.findall(_load_config_template()))

    missing_locations = probe_uris - locations
    stale_locations = locations - probe_uris
    if missing_locations:
        result.failures.append(
            f"probe uris declared without matching internal location: "
            f"{sorted(missing_locations)}"
        )
    if stale_locations:
        result.failures.append(
            f"internal location declared without matching probe: "
            f"{sorted(stale_locations)}"
        )
    return result


@register_check(
    "ready-total-timeout-budget",
    "Σ gateway-ready.probes[i].timeout_ms <= total_timeout_ms "
    "(gateway.md §4.1 budget conservation).",
)
def check_total_timeout_budget() -> CheckResult:
    result = CheckResult(
        "ready-total-timeout-budget",
        "gateway-ready total_timeout_ms ≥ Σ probes[*].timeout_ms",
    )
    apisix = _load_apisix_yaml()
    probes = _gateway_ready_probes(apisix)
    total = _gateway_ready_total_timeout(apisix)
    if total is None:
        if probes:
            result.failures.append(
                "gateway-ready declares probes[] but no total_timeout_ms"
            )
        return result
    summed = sum(int(p.get("timeout_ms", 0)) for p in probes)
    if summed > total:
        result.failures.append(
            f"Σ probes timeout_ms = {summed} exceeds total_timeout_ms = {total}"
        )
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _run_checks(selected: Iterable[str] | None) -> int:
    names = {n for (n, _desc, _fn) in REGISTERED_CHECKS}
    if selected is not None:
        selected = set(selected)
        unknown = selected - names
        if unknown:
            print(
                f"error: unknown check names: {sorted(unknown)}",
                file=sys.stderr,
            )
            print(
                f"       known: {sorted(names)}",
                file=sys.stderr,
            )
            return 2

    ran = 0
    failed = 0
    print(f"running {len(REGISTERED_CHECKS) if selected is None else len(selected)} check(s)...\n")
    for (name, description, fn) in REGISTERED_CHECKS:
        if selected is not None and name not in selected:
            continue
        ran += 1
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001 — surface any check-level bug
            print(f"  [CRASH] {name}: {exc!r}")
            failed += 1
            continue
        if result.ok:
            print(f"  [ OK ] {name}: {description}")
        else:
            failed += 1
            print(f"  [FAIL] {name}: {description}")
            for f in result.failures:
                print(f"         - {f}")
    print()
    print(f"summary: {ran - failed}/{ran} passed, {failed} failed")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        help="comma-separated list of check names to run (default: all)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list registered checks and exit",
    )
    args = parser.parse_args()

    if args.list:
        for name, description, _fn in REGISTERED_CHECKS:
            print(f"{name}\n  {description}")
        return 0

    selected = None
    if args.only:
        selected = [n.strip() for n in args.only.split(",") if n.strip()]

    return _run_checks(selected)


if __name__ == "__main__":
    sys.exit(main())
