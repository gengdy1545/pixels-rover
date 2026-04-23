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

CI integration: this script is expected to run as a PR gate next to
``scripts/smoke.sh``. Either failure blocks merge.

Hard rule: an assertion here that **cannot** be expressed as a reproducible
grep / AST walk / YAML parse does not belong here — move it to
``scripts/smoke.sh`` instead, which has access to a live
``docker compose up`` environment.
"""
from __future__ import annotations

import argparse
import ast
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
_APISIX_TEMPLATE_PATH = REPO_ROOT / "gateway" / "apisix.yaml.template"
_OPENAPI_FRAGMENT_DIR = REPO_ROOT / "gateway" / "fragments"
_OPENAPI_MARKER = "#__OPENAPI_ROUTES__"
_CONFIG_TEMPLATE_PATH = REPO_ROOT / "gateway" / "config.yaml.template"
_INFRA_TS_PATH = REPO_ROOT / "frontend" / "src" / "shared" / "types" / "infra.ts"
_PLUGIN_DIR = REPO_ROOT / "gateway" / "custom" / "apisix" / "plugins"
_REQUIRED_ENV_YAML_PATH = REPO_ROOT / "config" / "required-env.yaml"
_REQUIRED_ENV_SCHEMA_PATH = REPO_ROOT / "config" / "required-env.schema.yaml"
_ENV_EXAMPLE_PATH = REPO_ROOT / ".env.example"
# §14 consumer registry: every module / script listed here MUST
# reference the path "config/required-env.yaml" (as a string literal)
# so a grep enforces the "SSOT has exactly N known consumers" rule.
# Adding a new consumer = append here AND cite the YAML path in the
# referenced file. Removing a consumer = remove from both.
_REQUIRED_ENV_CONSUMERS = (
    REPO_ROOT / "scripts" / "generate-env-example.py",
    REPO_ROOT / "gateway" / "validate-required-env.py",
    REPO_ROOT
    / "services" / "auth-service" / "src" / "main" / "java"
    / "io" / "pixelsdb" / "pixels" / "rover" / "bootstrap"
    / "RequiredEnvValidator.java",
    REPO_ROOT / "services" / "assistant-service" / "app" / "required_env.py",
    REPO_ROOT / "scripts" / "smoke.sh",
)


def _load_error_codes() -> dict:
    return json.loads(_ERROR_CODES_PATH.read_text(encoding="utf-8"))


def _splice_openapi_fragment(template_text: str, profile: str) -> str:
    """Splice the named OpenAPI fragment into the apisix template.

    Mirrors the splice logic in ``gateway/entrypoint.sh`` so contract
    checks see a realistic post-render route table. The marker line
    MUST appear exactly once; caller-visible errors are surfaced as
    ValueError so checks can report a precise failure message.
    """
    fragment_path = _OPENAPI_FRAGMENT_DIR / f"openapi-{profile}.yaml"
    if not fragment_path.is_file():
        raise ValueError(f"OpenAPI fragment missing: {fragment_path}")
    fragment_text = fragment_path.read_text(encoding="utf-8")

    lines = template_text.splitlines(keepends=True)
    marker_hits = [i for i, line in enumerate(lines) if line.strip() == _OPENAPI_MARKER]
    if not marker_hits:
        raise ValueError(
            f"{_OPENAPI_MARKER} marker not found in {_APISIX_TEMPLATE_PATH}"
        )
    if len(marker_hits) > 1:
        raise ValueError(
            f"{_OPENAPI_MARKER} marker appears {len(marker_hits)} times "
            f"in {_APISIX_TEMPLATE_PATH} (must be exactly 1)"
        )
    idx = marker_hits[0]
    return "".join(lines[:idx]) + fragment_text + "".join(lines[idx + 1 :])


def _load_apisix_yaml(profile: str = "protected") -> dict:
    """Return the apisix route table as it would exist at runtime.

    Mirrors entrypoint.sh: reads ``apisix.yaml.template`` and splices
    the requested OpenAPI fragment (default = protected, the PROD
    baseline) into place. Returns the parsed YAML dict.
    """
    template_text = _APISIX_TEMPLATE_PATH.read_text(encoding="utf-8")
    rendered = _splice_openapi_fragment(template_text, profile)
    return yaml.safe_load(rendered) or {}


def _load_openapi_fragment(profile: str) -> list[dict]:
    """Return the list of route dicts declared in an OpenAPI fragment."""
    fragment_path = _OPENAPI_FRAGMENT_DIR / f"openapi-{profile}.yaml"
    fragment_text = fragment_path.read_text(encoding="utf-8")
    # The fragment is a YAML snippet expected to be spliced UNDER an
    # existing `routes:` list; at the top-level of a standalone parse
    # it reads as a bare sequence, which PyYAML returns as a list.
    parsed = yaml.safe_load(fragment_text)
    if not isinstance(parsed, list):
        raise ValueError(
            f"{fragment_path} did not parse as a YAML sequence of routes; "
            f"got {type(parsed).__name__}"
        )
    return parsed


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
    "introspect_total_budget_ms (gateway.md §5.3).",
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
# OpenAPI per-service namespace routes (§9.1 / gateway.md §6.7)
# ---------------------------------------------------------------------------

# Known OpenAPI route ids. Each must appear in BOTH fragments with
# byte-identical config except for gateway-auth.require_auth.
_OPENAPI_ROUTE_IDS: tuple[str, ...] = ("auth-openapi", "analysis-openapi")
_OPENAPI_PROFILES: tuple[str, ...] = ("protected", "public")
# Mapping route id -> API domain prefix. Used to locate "sibling
# business prefix routes" against which the OpenAPI precise-path
# route's priority is compared.
_OPENAPI_ROUTE_DOMAIN: dict[str, str] = {
    "auth-openapi": "/api/v1/auth/",
    "analysis-openapi": "/api/v1/analysis/",
}
_OPENAPI_PRIORITY_MARGIN = 10  # gateway.md §6.2 / §6.7 hard rule


@register_check(
    "openapi-route-priority-above-deepest-prefix",
    "Each /api/v1/<svc>/openapi.json route has priority >= "
    "deepest /api/v1/<svc>/* prefix route's priority + 10, and both "
    "fragments (public / protected) declare the same set of openapi "
    "routes with byte-identical fields except for require_auth.",
)
def check_openapi_route_priority() -> CheckResult:
    result = CheckResult(
        "openapi-route-priority-above-deepest-prefix",
        "OpenAPI route priority + fragment symmetry",
    )

    # 1. Parse template (sans openapi routes) to find deepest business
    #    prefix per domain.
    template_text = _APISIX_TEMPLATE_PATH.read_text(encoding="utf-8")
    try:
        # Splicing with an empty-fragment stand-in would need another
        # scaffold; easier to splice protected and then strip openapi
        # routes out before computing the per-domain prefix bases.
        template_only = yaml.safe_load(
            _splice_openapi_fragment(template_text, "protected")
        ) or {}
    except ValueError as exc:
        result.failures.append(str(exc))
        return result

    template_routes = [
        r
        for r in (template_only.get("routes") or [])
        if isinstance(r, dict) and r.get("id") not in _OPENAPI_ROUTE_IDS
    ]

    deepest_prefix_priority: dict[str, int] = {}
    for rid, domain in _OPENAPI_ROUTE_DOMAIN.items():
        max_prio = -1
        for r in template_routes:
            uri = r.get("uri") or ""
            prio = r.get("priority")
            if not isinstance(prio, int):
                continue
            # Match any route that lives under <domain> (including
            # prefix routes like `/api/v1/auth/*` and precise routes
            # like `/api/v1/auth/login`). Excludes the openapi route
            # itself via the _OPENAPI_ROUTE_IDS filter above.
            if uri.startswith(domain) or uri == domain.rstrip("/"):
                if prio > max_prio:
                    max_prio = prio
        if max_prio < 0:
            # Domain has no sibling routes — still require the openapi
            # priority to be declared, but there's nothing to compare
            # against. Skip the +10 check and leave a note.
            continue
        deepest_prefix_priority[rid] = max_prio

    # 2. For each fragment, verify openapi route set + priority.
    fragments: dict[str, list[dict]] = {}
    for profile in _OPENAPI_PROFILES:
        try:
            fragments[profile] = _load_openapi_fragment(profile)
        except (FileNotFoundError, ValueError) as exc:
            result.failures.append(f"fragment {profile}: {exc}")
            return result

    for profile, routes in fragments.items():
        ids_in_fragment = {
            r.get("id") for r in routes if isinstance(r, dict)
        }
        missing = set(_OPENAPI_ROUTE_IDS) - ids_in_fragment
        extra = ids_in_fragment - set(_OPENAPI_ROUTE_IDS)
        if missing:
            result.failures.append(
                f"fragment {profile}: missing openapi routes {sorted(missing)}"
            )
        if extra:
            result.failures.append(
                f"fragment {profile}: fragment declares unknown openapi "
                f"routes {sorted(extra)}; register them in _OPENAPI_ROUTE_IDS "
                "or remove from the fragment"
            )

        for route in routes:
            if not isinstance(route, dict):
                continue
            rid = route.get("id")
            if rid not in _OPENAPI_ROUTE_IDS:
                continue
            uri = route.get("uri") or ""
            if not uri.endswith("/openapi.json"):
                result.failures.append(
                    f"fragment {profile} route {rid}: uri {uri!r} must end "
                    "with /openapi.json (precise path, not a prefix)"
                )
            if uri.rstrip("/") == "/openapi.json":
                result.failures.append(
                    f"fragment {profile} route {rid}: bare /openapi.json "
                    "exposure is forbidden by gateway.md §6.7; use "
                    "/api/v1/<svc>/openapi.json"
                )

            prio = route.get("priority")
            if not isinstance(prio, int):
                result.failures.append(
                    f"fragment {profile} route {rid}: priority must be an "
                    f"integer, got {prio!r}"
                )
                continue
            floor = deepest_prefix_priority.get(rid)
            if floor is not None and prio < floor + _OPENAPI_PRIORITY_MARGIN:
                result.failures.append(
                    f"fragment {profile} route {rid}: priority={prio} < "
                    f"deepest /api/v1/<svc>/ prefix priority ({floor}) + "
                    f"{_OPENAPI_PRIORITY_MARGIN}; gateway.md §6.2 / §6.7 "
                    "require openapi precise paths to beat their domain's "
                    "deepest prefix route by at least the margin to avoid "
                    "being shadowed"
                )

            # proxy-rewrite must rewrite upstream path to /openapi.json.
            plugins = route.get("plugins") or {}
            proxy_rewrite = plugins.get("proxy-rewrite")
            if not isinstance(proxy_rewrite, dict):
                result.failures.append(
                    f"fragment {profile} route {rid}: missing proxy-rewrite "
                    "plugin; gateway must strip the /api/v1/<svc>/ prefix so "
                    "upstream receives /openapi.json (backend.md §9)"
                )
            elif proxy_rewrite.get("uri") != "/openapi.json":
                result.failures.append(
                    f"fragment {profile} route {rid}: proxy-rewrite.uri must "
                    f"be '/openapi.json', got {proxy_rewrite.get('uri')!r}"
                )

    # 3. Cross-fragment symmetry: public / protected must differ ONLY
    #    in gateway-auth.require_auth.
    def _strip_require_auth(route: dict) -> dict:
        clone = json.loads(json.dumps(route))
        ga = (clone.get("plugins") or {}).get("gateway-auth")
        if isinstance(ga, dict):
            ga.pop("require_auth", None)
        return clone

    by_id_public = {
        r.get("id"): _strip_require_auth(r)
        for r in fragments.get("public", [])
        if isinstance(r, dict)
    }
    by_id_protected = {
        r.get("id"): _strip_require_auth(r)
        for r in fragments.get("protected", [])
        if isinstance(r, dict)
    }
    for rid in _OPENAPI_ROUTE_IDS:
        pub = by_id_public.get(rid)
        prot = by_id_protected.get(rid)
        if pub and prot and pub != prot:
            result.failures.append(
                f"route {rid}: public vs protected fragment differ in "
                "fields other than gateway-auth.require_auth — the two "
                "fragments must be byte-identical except for that one "
                "boolean (gateway.md §6.7)"
            )

    # 4. Require the opposite require_auth values actually differ.
    for rid in _OPENAPI_ROUTE_IDS:
        pub_r = next(
            (r for r in fragments.get("public", []) if isinstance(r, dict) and r.get("id") == rid),
            None,
        )
        prot_r = next(
            (r for r in fragments.get("protected", []) if isinstance(r, dict) and r.get("id") == rid),
            None,
        )
        if not pub_r or not prot_r:
            continue
        pub_req = ((pub_r.get("plugins") or {}).get("gateway-auth") or {}).get("require_auth")
        prot_req = ((prot_r.get("plugins") or {}).get("gateway-auth") or {}).get("require_auth")
        if pub_req is not False:
            result.failures.append(
                f"route {rid} in public fragment: require_auth must be "
                f"exactly False, got {pub_req!r}"
            )
        if prot_req is not True:
            result.failures.append(
                f"route {rid} in protected fragment: require_auth must be "
                f"exactly True, got {prot_req!r}"
            )

    return result


@register_check(
    "no-bare-openapi-json-route",
    "apisix.yaml.template and both openapi fragments declare zero "
    "routes with uri == /openapi.json (gateway.md §6.7 bans bare "
    "exposure; use /api/v1/<svc>/openapi.json instead).",
)
def check_no_bare_openapi_route() -> CheckResult:
    result = CheckResult(
        "no-bare-openapi-json-route",
        "Bare /openapi.json never exposed",
    )
    # Scan the raw text of template + both fragments; YAML parsing
    # is unnecessary here, and grep-style catches copy-paste slips
    # in comments too (false positives on comments are acceptable
    # since the rule is "not even as a draft").
    paths_to_scan = [_APISIX_TEMPLATE_PATH] + [
        _OPENAPI_FRAGMENT_DIR / f"openapi-{p}.yaml" for p in _OPENAPI_PROFILES
    ]
    # Match `uri: /openapi.json` (with any amount of whitespace); the
    # pattern deliberately anchors to the `uri:` key to ignore any
    # internal proxy-rewrite `uri: /openapi.json` which IS permitted.
    # Specifically: top-level route `uri:` lines are indented with 4
    # spaces; plugin-nested `uri:` lines are indented with 8+ spaces.
    bare_route_uri = re.compile(r"^\s{2,4}uri:\s*/openapi\.json\s*$", re.MULTILINE)
    for path in paths_to_scan:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if bare_route_uri.search(text):
            result.failures.append(
                f"{path.relative_to(REPO_ROOT)}: found a route with "
                "`uri: /openapi.json` at route-level indentation; bare "
                "exposure is forbidden — use a namespaced URI like "
                "/api/v1/<svc>/openapi.json and move /openapi.json to "
                "proxy-rewrite only"
            )
    return result


# ---------------------------------------------------------------------------
# SSE route hardening (A1)
# ---------------------------------------------------------------------------

# Known SSE route ids in apisix.yaml. Each entry MUST satisfy the contract
# documented in gateway/apisix.yaml above the route declaration AND in
# gateway.md §6.3 / §5.3.4:
#
#   * timeout.read in [_SSE_READ_TIMEOUT_MIN_S, _SSE_READ_TIMEOUT_MAX_S]
#     — 10 min lower bound to keep long-running LLM analyses alive;
#       30 min upper bound because the read_timeout doubles as the
#       in-flight session-invalidation collapse window (§5.3.4).
#   * proxy-control plugin with request_buffering: false.
#
# Adding a new SSE route: append the route id here AND mirror the
# template in apisix.yaml. The check below will fail loudly if either
# half drifts.
_SSE_ROUTE_IDS: tuple[str, ...] = ("analysis-submit",)
_SSE_READ_TIMEOUT_MIN_S = 600   # 10 min
_SSE_READ_TIMEOUT_MAX_S = 1800  # 30 min hard cap (gateway.md §6.3)


@register_check(
    "sse-routes-explicit-timeout-and-buffering",
    "Each known SSE route in apisix.yaml declares an explicit read "
    "timeout in [600, 1800]s and disables request buffering "
    "(gateway.md §6.3 + §5.3.4 collapse-window rule).",
)
def check_sse_route_hardening() -> CheckResult:
    result = CheckResult(
        "sse-routes-explicit-timeout-and-buffering",
        "SSE routes: explicit read_timeout + request_buffering off",
    )
    apisix = _load_apisix_yaml()
    routes_by_id: dict[str, dict] = {}
    for r in apisix.get("routes") or []:
        rid = r.get("id")
        if isinstance(rid, str):
            routes_by_id[rid] = r

    for rid in _SSE_ROUTE_IDS:
        route = routes_by_id.get(rid)
        if route is None:
            result.failures.append(
                f"SSE route id {rid!r} listed in _SSE_ROUTE_IDS but missing "
                "from apisix.yaml — either restore the route or remove the "
                "registry entry"
            )
            continue

        timeout = route.get("timeout")
        if not isinstance(timeout, dict) or "read" not in timeout:
            result.failures.append(
                f"route {rid}: missing explicit `timeout.read` — SSE routes "
                "must NOT inherit the default 30s; declare an upper bound "
                "in [600, 1800] seconds (gateway.md §6.3)"
            )
        else:
            read = timeout.get("read")
            if not isinstance(read, int):
                result.failures.append(
                    f"route {rid}: timeout.read must be an integer (seconds), "
                    f"got {read!r}"
                )
            elif not (_SSE_READ_TIMEOUT_MIN_S <= read <= _SSE_READ_TIMEOUT_MAX_S):
                result.failures.append(
                    f"route {rid}: timeout.read = {read}s outside allowed "
                    f"window [{_SSE_READ_TIMEOUT_MIN_S}, "
                    f"{_SSE_READ_TIMEOUT_MAX_S}]s — "
                    "below the lower bound truncates legitimate long "
                    "analyses; above the upper bound enlarges the §5.3.4 "
                    "session-invalidation collapse window beyond policy"
                )

        plugins = route.get("plugins") or {}
        proxy_control = plugins.get("proxy-control")
        if not isinstance(proxy_control, dict):
            result.failures.append(
                f"route {rid}: missing `proxy-control` plugin — SSE routes "
                "must declare `proxy-control: { request_buffering: false }` "
                "to disable nginx request buffering"
            )
        elif proxy_control.get("request_buffering") is not False:
            result.failures.append(
                f"route {rid}: proxy-control.request_buffering must be "
                f"explicitly `false`, got {proxy_control.get('request_buffering')!r}"
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
# §14 required-env.yaml SSOT checks
# ---------------------------------------------------------------------------


def _load_required_env_doc() -> dict:
    return yaml.safe_load(_REQUIRED_ENV_YAML_PATH.read_text(encoding="utf-8")) or {}


def _load_required_env_schema() -> dict:
    return yaml.safe_load(_REQUIRED_ENV_SCHEMA_PATH.read_text(encoding="utf-8")) or {}


def _validate_against_schema(
    instance: object, schema: dict, path: str, failures: list[str]
) -> None:
    """Recursive subset of JSON-Schema draft-07 sufficient for this DSL.

    Supports: type, required, additionalProperties, patternProperties,
    items, enum, minLength, minimum, pattern. Anything fancier belongs in
    a real schema library, but this DSL is tiny by design.
    """
    stype = schema.get("type")
    if stype == "object":
        if not isinstance(instance, dict):
            failures.append(f"{path}: expected object, got {type(instance).__name__}")
            return
        for req in schema.get("required", []):
            if req not in instance:
                failures.append(f"{path}: missing required key {req!r}")
        props = schema.get("properties") or {}
        additional = schema.get("additionalProperties", True)
        for key, val in instance.items():
            if key in props:
                _validate_against_schema(val, props[key], f"{path}.{key}", failures)
            elif additional is False:
                failures.append(f"{path}: unexpected key {key!r}")
            elif isinstance(additional, dict):
                _validate_against_schema(val, additional, f"{path}.{key}", failures)
    elif stype == "array":
        if not isinstance(instance, list):
            failures.append(f"{path}: expected array, got {type(instance).__name__}")
            return
        item_schema = schema.get("items")
        if item_schema is not None:
            for i, item in enumerate(instance):
                _validate_against_schema(item, item_schema, f"{path}[{i}]", failures)
    elif stype == "string":
        if not isinstance(instance, str):
            failures.append(f"{path}: expected string, got {type(instance).__name__}")
            return
        if "minLength" in schema and len(instance) < schema["minLength"]:
            failures.append(
                f"{path}: string shorter than minLength={schema['minLength']}"
            )
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            failures.append(
                f"{path}: value {instance!r} does not match pattern {schema['pattern']!r}"
            )
        enum = schema.get("enum")
        if enum is not None and instance not in enum:
            failures.append(f"{path}: value {instance!r} not in enum {enum}")
    elif stype == "integer":
        if not isinstance(instance, int) or isinstance(instance, bool):
            failures.append(f"{path}: expected integer, got {type(instance).__name__}")
            return
        if "minimum" in schema and instance < schema["minimum"]:
            failures.append(
                f"{path}: integer {instance} below minimum {schema['minimum']}"
            )
    elif stype == "boolean":
        if not isinstance(instance, bool):
            failures.append(f"{path}: expected boolean, got {type(instance).__name__}")


@register_check(
    "required-env-yaml-conforms-to-schema",
    "config/required-env.yaml conforms to config/required-env.schema.yaml "
    "AND satisfies the cross-entry rules (exactly one of required / "
    "required_when, forbidden_when only where required_when is set, etc.) "
    "from §14 / backend.md §13.1.",
)
def check_required_env_schema() -> CheckResult:
    result = CheckResult(
        "required-env-yaml-conforms-to-schema",
        "required-env.yaml shape + DSL invariants",
    )
    doc = _load_required_env_doc()
    schema = _load_required_env_schema()

    _validate_against_schema(doc, schema, "$", result.failures)
    if result.failures:
        # Surface-level schema errors mask deeper logic errors; stop early.
        return result

    services = doc.get("services") or {}
    for svc_name, entries in services.items():
        seen: set[str] = set()
        for entry in entries:
            name = entry["name"]
            if name in seen:
                result.failures.append(
                    f"{svc_name}: duplicate var name {name!r}"
                )
            seen.add(name)

            has_required = "required" in entry and entry["required"] is True
            has_required_when = "required_when" in entry
            if has_required and has_required_when:
                result.failures.append(
                    f"{svc_name}.{name}: entry carries BOTH `required: true` "
                    "AND `required_when`; pick exactly one"
                )
            if not has_required and not has_required_when:
                result.failures.append(
                    f"{svc_name}.{name}: entry is neither `required: true` "
                    "nor `required_when: OTHER=value`; pure-optional vars "
                    "do not belong in required-env.yaml"
                )
            if "forbidden_when" in entry and not has_required_when:
                result.failures.append(
                    f"{svc_name}.{name}: `forbidden_when` without "
                    "`required_when` is meaningless; encode the mutual "
                    "exclusion by pairing the two"
                )
            # Forward reference check: required_when / forbidden_when must
            # name a variable declared EARLIER in the same service block.
            for clause_key in ("required_when", "forbidden_when"):
                clause = entry.get(clause_key)
                if not clause:
                    continue
                other_name = clause.split("=", 1)[0]
                if other_name not in seen:
                    result.failures.append(
                        f"{svc_name}.{name}.{clause_key} references "
                        f"{other_name!r} which is not declared earlier in "
                        "services." + svc_name + " — declaration order MUST "
                        "be dependency order"
                    )
            # Schema forbids explicit "" in forbidden_values (empty is
            # handled by the required / required_when gate). Catch drift.
            for bad in entry.get("forbidden_values", []):
                if bad == "":
                    result.failures.append(
                        f"{svc_name}.{name}: forbidden_values contains the "
                        "empty string explicitly — empty is implicit; remove it"
                    )
    return result


@register_check(
    "env-example-matches-required-env-yaml",
    ".env.example is a byte-identical re-render of config/required-env.yaml "
    "via scripts/generate-env-example.py (§14). If this fails, run the "
    "generator and commit both files.",
)
def check_env_example_fresh() -> CheckResult:
    result = CheckResult(
        "env-example-matches-required-env-yaml",
        ".env.example up-to-date",
    )
    # Delegate to the generator's --check mode to avoid duplicating the
    # renderer here. Import via importlib so check-contracts stays a
    # single-file drop-in.
    import importlib.util as _ilu

    spec = _ilu.spec_from_file_location(
        "_gen_env", REPO_ROOT / "scripts" / "generate-env-example.py"
    )
    if spec is None or spec.loader is None:
        result.failures.append("could not load scripts/generate-env-example.py")
        return result
    module = _ilu.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[arg-type]

    doc = _load_required_env_doc()
    rendered = module.render(doc)
    existing = (
        _ENV_EXAMPLE_PATH.read_text(encoding="utf-8")
        if _ENV_EXAMPLE_PATH.exists()
        else ""
    )
    if rendered != existing:
        result.failures.append(
            ".env.example does not match required-env.yaml; "
            "run `python3 scripts/generate-env-example.py` and commit"
        )
    return result


@register_check(
    "required-env-yaml-consumers-registered",
    "Every file listed in _REQUIRED_ENV_CONSUMERS references the path "
    "'config/required-env.yaml' at least once. Prevents silent forks where "
    "a consumer hardcodes its own list instead of reading the SSOT.",
)
def check_required_env_consumers() -> CheckResult:
    result = CheckResult(
        "required-env-yaml-consumers-registered",
        "5 declared SSOT consumers actually reference the YAML",
    )
    needle = "config/required-env.yaml"
    for path in _REQUIRED_ENV_CONSUMERS:
        if not path.exists():
            result.failures.append(
                f"consumer file missing: {path.relative_to(REPO_ROOT)}"
            )
            continue
        text = path.read_text(encoding="utf-8")
        if needle not in text:
            result.failures.append(
                f"{path.relative_to(REPO_ROOT)} does not reference "
                f"{needle!r}; either read the SSOT or remove from "
                "_REQUIRED_ENV_CONSUMERS"
            )
    return result


# ---------------------------------------------------------------------------
# §15.2 Batch A — zero-occurrence grep scans for historical regressions.
#
# Each of these assertions codifies an "we have REMOVED this pattern from the
# codebase; if it comes back, it's a silent contract drift" rule. The scans
# are structured against code directories only; docs/markdown mentions and
# test-side "this must be absent" assertions are allowed, otherwise the check
# would fight its own documentation.
#
# Scan helpers are shared between checks and are kept small on purpose — the
# complexity budget for these checks is "a newcomer can add one more pattern
# in five minutes without reading a parser".
# ---------------------------------------------------------------------------


# Source file extensions we consider "code" for §15.2 scans.
_SOURCE_EXTS = {".java", ".py", ".ts", ".tsx", ".js", ".jsx", ".lua"}

# Path fragments that indicate generated / vendored / test-local content that
# does NOT represent production code paths. Absolute-string substring match;
# keep these tight — a fragment that's too broad hides real violations.
_SCAN_EXCLUDE_FRAGMENTS = (
    "/__pycache__/",
    "/.git/",
    "/target/",                 # Maven build output
    "/build/",                  # Gradle / frontend build output
    "/node_modules/",
    "/dist/",
    "/.pytest_cache/",
    "/.mypy_cache/",
    "/coverage/",
    "/.venv/",
    "/venv/",
    # Test locations — each assertion is about production contract shape, so
    # test fixtures (which often exercise the forbidden pattern on purpose
    # to prove it stays rejected) are out of scope.
    "/src/test/",               # Maven convention
    "/services/assistant-service/tests/",
    "/services/assistant-service/app/tests/",
    "/gateway/tests/",
    "/frontend/src/test/",
    "/frontend/tests/",
    "/__tests__/",
)

_TEST_NAME_SUFFIXES = (
    ".test.ts", ".test.tsx", ".test.js", ".test.jsx",
    ".spec.ts", ".spec.tsx", ".spec.js",
    "_test.py", "_spec.py",
)


def _is_excluded_scan_path(path: Path) -> bool:
    s = "/" + str(path.relative_to(REPO_ROOT)).replace("\\", "/") + "/"
    for frag in _SCAN_EXCLUDE_FRAGMENTS:
        if frag in s:
            return True
    if any(path.name.endswith(suf) for suf in _TEST_NAME_SUFFIXES):
        return True
    return False


def _iter_source_files(roots: Iterable[Path]) -> Iterable[Path]:
    """Recursively yield code-like files under the given roots, skipping
    generated / vendored / test content per ``_SCAN_EXCLUDE_FRAGMENTS``.
    """
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            if root.suffix in _SOURCE_EXTS and not _is_excluded_scan_path(root):
                yield root
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix not in _SOURCE_EXTS:
                continue
            if _is_excluded_scan_path(p):
                continue
            yield p


def _python_docstring_line_set(path: Path, text: str) -> set[int]:
    """Return the set of 1-indexed line numbers covered by module / class /
    function docstrings in ``text``. Used to strip docstring mentions from
    grep-style scans so we don't fight our own "this was removed" comments.
    On parse failure returns an empty set (so the scan falls back to a
    strictly raw-text grep rather than silently missing all hits).
    """
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return set()
    skip: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        head = body[0]
        if not isinstance(head, ast.Expr):
            continue
        val = head.value
        if not isinstance(val, ast.Constant) or not isinstance(val.value, str):
            continue
        start = val.lineno
        end = getattr(val, "end_lineno", start)
        for ln in range(start, end + 1):
            skip.add(ln)
    return skip


def _strip_line_comments(path: Path, text: str) -> list[tuple[int, str]]:
    """Return (lineno, code_portion_of_line) for every source line, with
    comments stripped:

    * Python: blanks lines starting with ``#``; drops lines inside module /
      class / function docstrings (via AST).
    * Java / TS / JS / Lua: removes ``/* ... */`` blocks (best-effort
      line-by-line state machine); removes Java-style ``//`` tail comments
      and Lua ``-- ...`` tails; drops lines whose non-whitespace prefix is
      ``*`` (Javadoc continuation), ``//`` or ``--``.

    This is intentionally a line-level approximation; it treats string
    literals that contain ``//`` / ``/*`` as comments. For the §15.2
    regression patterns (SCREAMING_SNAKE_CASE identifiers, explicit
    HTTP-status keywords, header-name literals) that false-positive shape
    does not fire.
    """
    ext = path.suffix
    lines = text.splitlines()
    out: list[tuple[int, str]] = []

    if ext == ".py":
        doc_lines = _python_docstring_line_set(path, text)
        for i, line in enumerate(lines, start=1):
            if i in doc_lines:
                continue
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            out.append((i, line))
        return out

    if ext in {".java", ".ts", ".tsx", ".js", ".jsx"}:
        in_block = False
        for i, line in enumerate(lines, start=1):
            start_in_block = in_block
            # Strip /* ... */ blocks that this line touches.
            rebuilt: list[str] = []
            j = 0
            while j < len(line):
                if not in_block:
                    k = line.find("/*", j)
                    if k < 0:
                        rebuilt.append(line[j:])
                        break
                    rebuilt.append(line[j:k])
                    in_block = True
                    j = k + 2
                else:
                    k = line.find("*/", j)
                    if k < 0:
                        break
                    in_block = False
                    j = k + 2
            code = "".join(rebuilt)
            # Strip // tail, but skip the `://` URL shape (e.g. http://, s3://,
            # file://) which is NOT a line comment.
            k = 0
            while True:
                k = code.find("//", k)
                if k < 0:
                    break
                if k > 0 and code[k - 1] == ":":
                    k += 2  # skip past this `://`, resume looking
                    continue
                code = code[:k]
                break
            stripped_raw = line.lstrip()
            if start_in_block and not code.strip():
                # Pure continuation of a block comment.
                continue
            if stripped_raw.startswith("*") or stripped_raw.startswith("//"):
                continue
            out.append((i, code))
        return out

    if ext == ".lua":
        in_block = False
        for i, line in enumerate(lines, start=1):
            start_in_block = in_block
            rebuilt: list[str] = []
            j = 0
            while j < len(line):
                if not in_block:
                    k = line.find("--[[", j)
                    if k < 0:
                        rebuilt.append(line[j:])
                        break
                    rebuilt.append(line[j:k])
                    in_block = True
                    j = k + 4
                else:
                    k = line.find("]]", j)
                    if k < 0:
                        break
                    in_block = False
                    j = k + 2
            code = "".join(rebuilt)
            k = code.find("--")
            if k >= 0:
                code = code[:k]
            stripped_raw = line.lstrip()
            if start_in_block and not code.strip():
                continue
            if stripped_raw.startswith("--"):
                continue
            out.append((i, code))
        return out

    # Fallback: no comment awareness.
    return [(i + 1, line) for i, line in enumerate(lines)]


def _scan_for_pattern(
    roots: Iterable[Path],
    pattern: str,
    *,
    flags: int = 0,
) -> list[tuple[Path, int, str]]:
    """Return (path, lineno, matched_line) for every regex hit under
    ``roots`` **after** stripping comments / docstrings via
    ``_strip_line_comments``. Paths reported are relative to REPO_ROOT.
    """
    rx = re.compile(pattern, flags)
    hits: list[tuple[Path, int, str]] = []
    for f in _iter_source_files(roots):
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, code in _strip_line_comments(f, text):
            if rx.search(code):
                hits.append((f.relative_to(REPO_ROOT), lineno, code.rstrip()))
    return hits


# Named scan roots — keep the list here so individual checks compose cleanly.
_ROOT_AUTH_MAIN = REPO_ROOT / "services" / "auth-service" / "src" / "main"
_ROOT_ASSISTANT_APP = REPO_ROOT / "services" / "assistant-service" / "app"
_ROOT_FRONTEND_SRC = REPO_ROOT / "frontend" / "src"
_ROOT_GATEWAY_PLUGINS = REPO_ROOT / "gateway" / "custom" / "apisix" / "plugins"

_ALL_CODE_ROOTS = (
    _ROOT_AUTH_MAIN,
    _ROOT_ASSISTANT_APP,
    _ROOT_FRONTEND_SRC,
    _ROOT_GATEWAY_PLUGINS,
)


# ---- A1 / apiVersion ------------------------------------------------------


@register_check(
    "no-api-version-field",
    "`apiVersion` is not emitted as a response-envelope field anywhere in "
    "production source (backend.md §6.0 — version is carried by /api/v1/ "
    "URL prefix, never by the body).",
)
def check_no_api_version_field() -> CheckResult:
    result = CheckResult(
        "no-api-version-field",
        "zero apiVersion field occurrences in code",
    )
    # Field-assignment shapes only. Comment mentions are already filtered by
    # _strip_line_comments; tests that assert ABSENCE live in excluded dirs.
    pattern = r"""(["']apiVersion["']\s*:|[.\s]apiVersion\s*=)"""
    hits = _scan_for_pattern(_ALL_CODE_ROOTS, pattern)
    for path, lineno, line in hits:
        result.failures.append(f"{path}:{lineno}: {line.strip()}")
    return result


# ---- A2 / fromCode reverse-lookup ----------------------------------------


@register_check(
    "no-error-code-reverse-lookup",
    "`ErrorCodeName.fromCode(...)` / `resolve_error_code_name(...)` reverse "
    "lookups are permanently retired (backend.md §6.3). Keeping them would "
    "tempt callers to fill numeric codes again and re-open the drift source.",
)
def check_no_error_code_reverse_lookup() -> CheckResult:
    result = CheckResult(
        "no-error-code-reverse-lookup",
        "zero fromCode / resolve_error_code_name call sites",
    )
    pattern = r"\b(fromCode|resolve_error_code_name)\s*\("
    hits = _scan_for_pattern(_ALL_CODE_ROOTS, pattern)
    for path, lineno, line in hits:
        result.failures.append(f"{path}:{lineno}: {line.strip()}")
    return result


# ---- A3 / 5-digit business codes -----------------------------------------


@register_check(
    "no-5-digit-business-codes",
    "No 5-digit numeric 'business code' literals (e.g. 40100 / 40102 / "
    "50001) appear in response constructors or constants (backend.md §6.3). "
    "Business granularity is carried by the SCREAMING_SNAKE_CASE "
    "`details.errorCode`; the top-level `code` is the HTTP status number.",
)
def check_no_5_digit_codes() -> CheckResult:
    result = CheckResult(
        "no-5-digit-business-codes",
        "zero 5-digit numeric code literals in code context",
    )
    # Targeted: the literal appears as the right-hand side of a code /
    # errorCode / statusCode / status_code assignment, or as the first
    # positional arg to a ResponseEntity.status / ApiResponse.error /
    # HTTPException call. Raw 5-digit tokens (prices, seed data, etc.) in
    # other contexts are not false-positived by this shape.
    pattern = (
        r"""(?x)
        (?:
            \b (?: code | errorCode | status[_]?[Cc]ode ) \s* [=:(]\s*
          |
            ["'] (?: code | errorCode | status[_]?[Cc]ode ) ["'] \s* : \s*
          |
            \b (?: ResponseEntity\.status | ApiResponse\.error | HTTPException )
              \s* \(\s* (?: status_code\s*=\s*)?
        )
        [45][0-9]{4}
        \b
        """
    )
    hits = _scan_for_pattern(_ALL_CODE_ROOTS, pattern)
    for path, lineno, line in hits:
        result.failures.append(f"{path}:{lineno}: {line.strip()}")
    return result


# ---- A4 / no business 401 or 403 (user-facing controllers only) ----------


# User-facing controller files. Internal-only plumbing (InternalAuthFilter,
# JsonAuthenticationFailHandler wired to /api/internal/*, introspect service
# layer) legitimately emits 401/403 because it IS the boundary. The §17.B
# sweep covers those paths by hand.
_USER_FACING_CONTROLLER_FILES = (
    REPO_ROOT / "services" / "auth-service" / "src" / "main" / "java"
    / "io" / "pixelsdb" / "pixels" / "rover" / "controller" / "AuthController.java",
    REPO_ROOT / "services" / "auth-service" / "src" / "main" / "java"
    / "io" / "pixelsdb" / "pixels" / "rover" / "controller" / "HealthController.java",
    REPO_ROOT / "services" / "assistant-service" / "app" / "api" / "analysis.py",
    REPO_ROOT / "services" / "assistant-service" / "app" / "api" / "backends.py",
    REPO_ROOT / "services" / "assistant-service" / "app" / "api" / "conversations.py",
    REPO_ROOT / "services" / "assistant-service" / "app" / "api" / "semantic.py",
)


@register_check(
    "no-business-401-or-403",
    "User-facing controllers (auth-service/.../controller/*.java excluding "
    "Internal*, assistant-service/app/api/*.py excluding internal.py) MUST "
    "NOT emit HTTP 401 / 403. Those are gateway-level statuses per "
    "backend.md §6.3; business errors use 4xx / 500 + a SCREAMING_SNAKE_CASE "
    "errorCode. Internal / introspect plumbing is allow-listed.",
)
def check_no_business_401_403() -> CheckResult:
    result = CheckResult(
        "no-business-401-or-403",
        "no 401 / 403 in user-facing controllers",
    )
    pattern = (
        r"\b(UNAUTHORIZED|FORBIDDEN)\b"
        r"|HTTPException\s*\(\s*(?:status_code\s*=\s*)?40[13]\b"
        r"|status_code\s*=\s*40[13]\b"
        r"|\.status\s*\(\s*40[13]\b"
    )
    hits = _scan_for_pattern(_USER_FACING_CONTROLLER_FILES, pattern)
    for path, lineno, line in hits:
        result.failures.append(f"{path}:{lineno}: {line.strip()}")
    return result


# ---- A5 / X-Request-Id single writer --------------------------------------


@register_check(
    "x-request-id-single-writer",
    "No production service code actively writes an X-Request-Id RESPONSE "
    "header. The gateway's global `response-rewrite` plugin is the single "
    "writer (gateway.md §7.6); service code only CONSUMES the inbound "
    "header as a log correlation field.",
)
def check_x_request_id_single_writer() -> CheckResult:
    result = CheckResult(
        "x-request-id-single-writer",
        "zero active X-Request-Id response-header writes in service code",
    )
    pattern = (
        r"""(?x)
        (?:
          setHeader \s* \(\s* ["']X-Request-Id["']
        | \.set \s* \(\s* ["']X-Request-Id["']
        | headers \s* \[ \s* ["']X-Request-Id["'] \s* \] \s* =
        | headers\.set \s* \(\s* ["']X-Request-Id["']
        | response\.headers \s* \[ \s* ["']X-Request-Id["'] \s* \] \s* =
        )
        """
    )
    # Scan the two service code trees. Gateway writes it intentionally.
    hits = _scan_for_pattern(
        (_ROOT_AUTH_MAIN, _ROOT_ASSISTANT_APP),
        pattern,
    )
    for path, lineno, line in hits:
        result.failures.append(f"{path}:{lineno}: {line.strip()}")
    return result


# ---- A6 / JWKS sunset regression -----------------------------------------


# Allowed callers of JWKS symbols. Auth-service is the ONLY place that may
# mention these (the multi-public-key rotation internals still carry kid /
# pubkey bookkeeping even with the external JWKS endpoint retired).
_JWKS_FORBIDDEN_ROOTS = (
    _ROOT_ASSISTANT_APP,
    _ROOT_GATEWAY_PLUGINS,
    _ROOT_FRONTEND_SRC,
)


@register_check(
    "jwks-sunset-no-regression",
    "`jwks` / `JWKS` / `PyJWKClient` / `NimbusJwtDecoder` / `jwks_uri` do "
    "not appear in assistant-service, gateway plugins, or the frontend "
    "(docs/design/jwt-rotation.md §6.B). Auth-service retains the symbols "
    "for key-rotation internals — see §6.B sunset review mechanism for the "
    "conditions under which this check itself is reviewed.",
)
def check_jwks_sunset() -> CheckResult:
    result = CheckResult(
        "jwks-sunset-no-regression",
        "zero JWKS-symbol references outside auth-service / docs",
    )
    pattern = r"\b(jwks|JWKS|PyJWKClient|NimbusJwtDecoder|jwks_uri)\b"
    hits = _scan_for_pattern(_JWKS_FORBIDDEN_ROOTS, pattern)
    for path, lineno, line in hits:
        result.failures.append(f"{path}:{lineno}: {line.strip()}")
    return result


# ---- A7 / B6 horizontal call boundary -----------------------------------


@register_check(
    "no-horizontal-service-calls",
    "Business service code MUST NOT contain URL literals of the form "
    "`http://<service>:<port>/api/v1/...` (backend.md §2, B6). The only "
    "allowed cross-service horizontal shape is `/gateway/internal/*` via "
    "the gateway, and even that shape must be registered in the §2 "
    "whitelist.",
)
def check_no_horizontal_service_calls() -> CheckResult:
    result = CheckResult(
        "no-horizontal-service-calls",
        "zero http://<svc>/api/v1/... literals in service code",
    )
    # Matches http[s]://<hostish>[:port]/api/v1/... where <hostish> does not
    # contain a slash. Guards against both hostname and IP literals.
    pattern = r"""https?://[A-Za-z0-9_.-]+(?::\d+)?/api/v1/"""
    hits = _scan_for_pattern(
        (_ROOT_AUTH_MAIN, _ROOT_ASSISTANT_APP),
        pattern,
    )
    for path, lineno, line in hits:
        result.failures.append(f"{path}:{lineno}: {line.strip()}")
    return result


# ---------------------------------------------------------------------------
# §15.2 Batch B — business error-code namespace ownership + priority ordering.
#
# The infra-code checks upstream (lua-literals-registered / frontend-infra-
# union-equals-json) prove that GATEWAY_* / INTERNAL_* stay in lockstep.
# Business prefixes (AUTH_* owned by auth-service, ANALYSIS_* / CONVERSATION_*
# / SEMANTIC_* owned by assistant-service) need the symmetric guarantee:
#
#   * No cross-namespace leakage (backend.md §6.3): auth-service source must
#     NOT mention ANALYSIS_* / CONVERSATION_* / SEMANTIC_*, and the converse.
#   * Frontend union equality with the Java / Python source of truth, same
#     shape as `frontend-infra-union-equals-json` but bidirectional per
#     namespace.
#   * Route priority: every "request-set containment" pair must be ordered
#     by +10 (gateway.md §6.2 hard rule — not just the openapi-vs-prefix
#     subcase covered by the existing check).
# ---------------------------------------------------------------------------


_ERROR_CODE_NAME_JAVA = (
    REPO_ROOT / "services" / "auth-service" / "src" / "main" / "java"
    / "io" / "pixelsdb" / "pixels" / "rover" / "config" / "common" / "ErrorCodeName.java"
)
_ERROR_CODES_PY = REPO_ROOT / "services" / "assistant-service" / "app" / "error_codes.py"
_FRONTEND_AUTH_ERRORCODE_TS = REPO_ROOT / "frontend" / "src" / "shared" / "types" / "auth" / "ErrorCode.ts"
_FRONTEND_ANALYSIS_ERRORCODE_TS = REPO_ROOT / "frontend" / "src" / "shared" / "types" / "analysis" / "ErrorCode.ts"

_BUSINESS_PREFIX_AUTH = ("AUTH_",)
_BUSINESS_PREFIX_ANALYSIS = ("ANALYSIS_", "CONVERSATION_", "SEMANTIC_")


def _extract_java_string_constants(path: Path, prefix_match: tuple[str, ...]) -> dict[str, str]:
    """Return {constant_name: string_value} for top-level Java declarations of
    shape ``public static final String NAME = "VALUE";`` where NAME starts
    with one of the given prefixes.
    """
    text = path.read_text(encoding="utf-8")
    rx = re.compile(
        r"""public\s+static\s+final\s+String\s+([A-Z][A-Z0-9_]*)\s*=\s*"([^"]+)"\s*;""",
        re.MULTILINE,
    )
    out: dict[str, str] = {}
    for m in rx.finditer(text):
        name, value = m.group(1), m.group(2)
        if any(name.startswith(p) for p in prefix_match):
            out[name] = value
    return out


def _extract_python_string_constants(path: Path, prefix_match: tuple[str, ...]) -> dict[str, str]:
    """Return {constant_name: string_value} for top-level Python assignments
    of shape ``NAME = "VALUE"`` where NAME starts with one of the given
    prefixes. Uses AST so we pick up only real module-level assignments.
    """
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    out: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        name = node.targets[0].id
        if not any(name.startswith(p) for p in prefix_match):
            continue
        if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
            continue
        out[name] = node.value.value
    return out


def _extract_ts_union_literals(path: Path, type_name: str) -> set[str]:
    """Return the set of quoted string literals used as union members of the
    given TypeScript type alias. Expects a shape like::

        export type FooErrorCode =
          | 'FOO_A'
          | 'FOO_B';
    """
    text = path.read_text(encoding="utf-8")
    rx = re.compile(
        rf"""(?ms)^\s*export\s+type\s+{re.escape(type_name)}\s*=\s*(.+?);""",
    )
    m = rx.search(text)
    if not m:
        return set()
    body = m.group(1)
    return set(re.findall(r"""['"]([A-Z][A-Z0-9_]+)['"]""", body))


# ---- B1 / AUTH_* namespace single owner ----------------------------------


_AUTH_ALLOWED_ROOTS = (
    REPO_ROOT / "services" / "auth-service",
    REPO_ROOT / "frontend" / "src" / "shared" / "types" / "auth",
    # Frontend consumer-side dispatch is a legitimate use of the literals
    # per backend.md §6.3.2 step-1 (precise errorCode branching). The TS
    # compiler narrows `case 'AUTH_FOO':` against the `AuthErrorCode` union
    # and rejects typos at compile time, so these subtrees don't need the
    # belt-and-suspenders string-literal gate — `frontend-auth-union-
    # equals-java-source` already locks in the union/source alignment.
    REPO_ROOT / "frontend" / "src" / "features",
    REPO_ROOT / "frontend" / "src" / "pages",
    REPO_ROOT / "frontend" / "src" / "app",
)


def _path_under(path: Path, roots: Iterable[Path]) -> bool:
    for root in roots:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


@register_check(
    "auth-business-namespace-single-owner",
    "`AUTH_*` business error-code literals only appear inside auth-service "
    "source, the frontend auth type mirror, or frontend consumer subtrees "
    "(features / pages / app). assistant-service and gateway plugins leaking "
    "any `AUTH_*` literal violate backend.md §6.3 cross-service namespace "
    "ownership.",
)
def check_auth_namespace_single_owner() -> CheckResult:
    result = CheckResult(
        "auth-business-namespace-single-owner",
        "AUTH_* literals only in auth-service + frontend auth types",
    )
    # \b guards the left edge; `INTERNAL_AUTH_FAILED` does NOT match because
    # the `_` before `A` is a word char (no \b boundary).
    pattern = r"\bAUTH_[A-Z][A-Z0-9_]+\b"
    hits = _scan_for_pattern(
        (_ROOT_ASSISTANT_APP, _ROOT_FRONTEND_SRC, _ROOT_GATEWAY_PLUGINS),
        pattern,
    )
    for path, lineno, line in hits:
        abs_path = REPO_ROOT / path
        if _path_under(abs_path, _AUTH_ALLOWED_ROOTS):
            continue
        result.failures.append(f"{path}:{lineno}: {line.strip()}")
    return result


# ---- B2 / ANALYSIS_* / CONVERSATION_* / SEMANTIC_* namespace owner ------


_ANALYSIS_ALLOWED_ROOTS = (
    REPO_ROOT / "services" / "assistant-service",
    REPO_ROOT / "frontend" / "src" / "shared" / "types" / "analysis",
    # Frontend consumer-side dispatch is a legitimate use of the literals
    # per backend.md §6.3.2 step-1 (precise errorCode branching). The TS
    # compiler narrows `case 'ANALYSIS_FOO':` against the `AnalysisErrorCode`
    # union and rejects typos at compile time, so these subtrees don't need
    # the belt-and-suspenders string-literal gate — `frontend-analysis-
    # union-equals-python-source` already locks in the union/source
    # alignment.
    REPO_ROOT / "frontend" / "src" / "features",
    REPO_ROOT / "frontend" / "src" / "pages",
    REPO_ROOT / "frontend" / "src" / "app",
)


@register_check(
    "analysis-business-namespace-single-owner",
    "`ANALYSIS_*` / `CONVERSATION_*` / `SEMANTIC_*` business error-code "
    "literals only appear inside assistant-service source, the frontend "
    "analysis type mirror, or frontend consumer subtrees (features / pages "
    "/ app). auth-service and gateway plugins leaking any of these violate "
    "backend.md §6.3 cross-service namespace ownership.",
)
def check_analysis_namespace_single_owner() -> CheckResult:
    result = CheckResult(
        "analysis-business-namespace-single-owner",
        "ANALYSIS_* / CONVERSATION_* / SEMANTIC_* literals only in owner tree",
    )
    pattern = r"\b(?:ANALYSIS|CONVERSATION|SEMANTIC)_[A-Z][A-Z0-9_]+\b"
    hits = _scan_for_pattern(
        (_ROOT_AUTH_MAIN, _ROOT_FRONTEND_SRC, _ROOT_GATEWAY_PLUGINS),
        pattern,
    )
    for path, lineno, line in hits:
        abs_path = REPO_ROOT / path
        if _path_under(abs_path, _ANALYSIS_ALLOWED_ROOTS):
            continue
        result.failures.append(f"{path}:{lineno}: {line.strip()}")
    return result


# ---- B3 / frontend AuthErrorCode union == Java AUTH_* constants ----------


@register_check(
    "frontend-auth-union-equals-java-source",
    "frontend/src/shared/types/auth/ErrorCode.ts `AuthErrorCode` union "
    "equals the set of AUTH_* public-static-final constants in "
    "services/auth-service/.../config/common/ErrorCodeName.java "
    "(bidirectional). Adding a code on one side without the other is drift.",
)
def check_frontend_auth_union_equals_java() -> CheckResult:
    result = CheckResult(
        "frontend-auth-union-equals-java-source",
        "AuthErrorCode union ≡ AUTH_* Java constants",
    )
    java_constants = _extract_java_string_constants(
        _ERROR_CODE_NAME_JAVA, _BUSINESS_PREFIX_AUTH
    )
    # Confirm each LHS == RHS (self-referencing pattern) — divergence here
    # would mean a name/value mismatch bug upstream.
    for name, value in java_constants.items():
        if name != value:
            result.failures.append(
                f"ErrorCodeName.{name} constant value is {value!r}, "
                f"must self-reference its own name"
            )
    java_names = set(java_constants.keys())

    union_names = _extract_ts_union_literals(
        _FRONTEND_AUTH_ERRORCODE_TS, "AuthErrorCode"
    )
    if not union_names:
        result.failures.append(
            f"could not parse `AuthErrorCode` union in "
            f"{_FRONTEND_AUTH_ERRORCODE_TS.relative_to(REPO_ROOT)}"
        )
        return result

    missing_in_union = sorted(java_names - union_names)
    extra_in_union = sorted(union_names - java_names)
    for n in missing_in_union:
        result.failures.append(
            f"ErrorCodeName.java declares {n!r} but AuthErrorCode union is missing it"
        )
    for n in extra_in_union:
        result.failures.append(
            f"AuthErrorCode union has {n!r} but ErrorCodeName.java doesn't declare it"
        )
    return result


# ---- B4 / frontend AnalysisErrorCode union == Python constants ----------


@register_check(
    "frontend-analysis-union-equals-python-source",
    "frontend/src/shared/types/analysis/ErrorCode.ts `AnalysisErrorCode` "
    "union equals the set of ANALYSIS_* / CONVERSATION_* / SEMANTIC_* "
    "string constants in services/assistant-service/app/error_codes.py "
    "(bidirectional). Adding a code on one side without the other is drift.",
)
def check_frontend_analysis_union_equals_python() -> CheckResult:
    result = CheckResult(
        "frontend-analysis-union-equals-python-source",
        "AnalysisErrorCode union ≡ business-prefix Python constants",
    )
    py_constants = _extract_python_string_constants(
        _ERROR_CODES_PY, _BUSINESS_PREFIX_ANALYSIS
    )
    for name, value in py_constants.items():
        if name != value:
            result.failures.append(
                f"error_codes.py {name} constant value is {value!r}, "
                f"must self-reference its own name"
            )
    py_names = set(py_constants.keys())

    union_names = _extract_ts_union_literals(
        _FRONTEND_ANALYSIS_ERRORCODE_TS, "AnalysisErrorCode"
    )
    if not union_names:
        result.failures.append(
            f"could not parse `AnalysisErrorCode` union in "
            f"{_FRONTEND_ANALYSIS_ERRORCODE_TS.relative_to(REPO_ROOT)}"
        )
        return result

    missing_in_union = sorted(py_names - union_names)
    extra_in_union = sorted(union_names - py_names)
    for n in missing_in_union:
        result.failures.append(
            f"error_codes.py declares {n!r} but AnalysisErrorCode union is missing it"
        )
    for n in extra_in_union:
        result.failures.append(
            f"AnalysisErrorCode union has {n!r} but error_codes.py doesn't declare it"
        )
    return result


# ---- B5 / generalised deep-prefix priority +10 rule ----------------------


def _route_request_set_contained(inner_uri: str, outer_uri: str) -> bool:
    """True iff every HTTP URI matching ``inner_uri`` also matches
    ``outer_uri`` per APISIX route semantics (precise path vs `*`-suffixed
    prefix). Equal URIs return True as a trivial case — caller should
    skip pair comparisons where inner == outer.
    """
    if outer_uri == inner_uri:
        return True
    if outer_uri.endswith("/*"):
        outer_prefix = outer_uri[:-1]  # keep trailing '/'
        if inner_uri.endswith("/*"):
            inner_prefix = inner_uri[:-1]
            return inner_prefix.startswith(outer_prefix)
        return inner_uri.startswith(outer_prefix)
    # outer is a precise path: only equality counts (handled above)
    return False


_PREFIX_PRIORITY_MARGIN = 10


@register_check(
    "route-prefix-priority-ordered",
    "For every pair of apisix.yaml routes where one URI's request set is "
    "strictly contained in another's, the deeper route's `priority` >= the "
    "shallower's priority + 10 (gateway.md §6.2 hard rule). Equality is "
    "explicitly forbidden — match order under equal priority is an APISIX "
    "implementation detail and not a stable contract.",
)
def check_route_prefix_priority_ordered() -> CheckResult:
    result = CheckResult(
        "route-prefix-priority-ordered",
        "deep prefix ≥ shallow prefix + 10",
    )
    try:
        apisix = _load_apisix_yaml("protected")
    except ValueError as exc:
        result.failures.append(str(exc))
        return result
    routes = apisix.get("routes") or []
    named: list[tuple[str, int]] = []
    for r in routes:
        if not isinstance(r, dict):
            continue
        uri = r.get("uri")
        prio = r.get("priority")
        if not isinstance(uri, str) or not isinstance(prio, int):
            result.failures.append(
                f"route id={r.get('id')!r} missing uri or integer priority "
                f"(uri={uri!r}, priority={prio!r})"
            )
            continue
        named.append((uri, prio))

    for i, (uri_a, prio_a) in enumerate(named):
        for j, (uri_b, prio_b) in enumerate(named):
            if i == j:
                continue
            if uri_a == uri_b:
                result.failures.append(
                    f"duplicate URI in apisix.yaml: {uri_a!r} appears twice"
                )
                continue
            # Determine prefix relationship. `inner` contained in `outer`.
            if _route_request_set_contained(uri_a, uri_b):
                # A is inner (deep), B is outer (shallow)
                inner_uri, inner_prio = uri_a, prio_a
                outer_uri, outer_prio = uri_b, prio_b
            else:
                continue
            if inner_prio < outer_prio + _PREFIX_PRIORITY_MARGIN:
                result.failures.append(
                    f"{inner_uri!r} (priority={inner_prio}) is a deeper "
                    f"prefix of {outer_uri!r} (priority={outer_prio}) but "
                    f"priority delta {inner_prio - outer_prio} < "
                    f"{_PREFIX_PRIORITY_MARGIN}; gateway.md §6.2 requires "
                    "the deeper route's priority to exceed the shallower's "
                    "by at least 10"
                )
    return result


# ---------------------------------------------------------------------------
# §15.2 Batch C — structured log field-name consistency across layers.
#
# Both services render log lines with the same user-visible bracketed-field
# shape (`[<service>] [req:<requestId>] [user:<userId>]`), so log aggregators
# can grep a single request across auth-service and assistant-service. The
# underlying MDC / ContextVar naming is intentionally language-idiomatic
# (`requestId` in Java MDC, `request_id` in Python ContextVar), but the
# OUTPUT field prefixes must match byte-for-byte; otherwise grep / aggregation
# rules fork silently.
#
# This check is deliberately scoped to the currently-produced text log
# format. When `elapsedMs` and per-request timing fields are introduced
# as structured JSON (future §18 or its follow-up), extend this check with
# the new required-field list rather than adding a second check.
# ---------------------------------------------------------------------------


_AUTH_LOGBACK_PATH = REPO_ROOT / "services" / "auth-service" / "src" / "main" / "resources" / "logback-spring.xml"
_ASSISTANT_LOGGING_PY = REPO_ROOT / "services" / "assistant-service" / "app" / "logging_config.py"


# Required user-visible bracketed-field prefixes. Order matters for cross-
# layer grep: the tuple is the expected appearance order in both formatters.
_REQUIRED_BRACKET_PREFIXES = ("[req:", "[user:")


def _extract_logback_pattern(path: Path) -> str | None:
    text = path.read_text(encoding="utf-8")
    m = re.search(r"<pattern>([^<]+)</pattern>", text)
    return m.group(1) if m else None


def _extract_python_fmt_literal(path: Path) -> str | None:
    """Extract the `fmt=` keyword-argument string from the first
    ``UnifiedFormatter(...)`` call in the module. Walks the AST so we
    don't misread comments."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id.endswith("Formatter"):
            for kw in node.keywords:
                if kw.arg != "fmt":
                    continue
                # fmt can be a plain str, an f-string, or a BinOp concat.
                return _collapse_string_node(kw.value)
    return None


def _collapse_string_node(node: ast.AST) -> str | None:
    """Best-effort: resolve str / JoinedStr / BinOp-of-strs into a flat str."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                parts.append(v.value)
            else:
                # Interpolation — treat as a wildcard, we don't need the value.
                parts.append("")
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _collapse_string_node(node.left) or ""
        right = _collapse_string_node(node.right) or ""
        return left + right
    return None


@register_check(
    "log-format-bracket-field-consistency",
    "auth-service logback pattern and assistant-service Python formatter "
    "produce log lines whose user-visible bracket prefixes `[req:` and "
    "`[user:` match byte-for-byte, and each embeds the owning service "
    "identity (backend.md §5). Guards against silent divergence where one "
    "service emits `[reqId:` while the other emits `[req:`, breaking "
    "aggregated log grep.",
)
def check_log_format_bracket_consistency() -> CheckResult:
    result = CheckResult(
        "log-format-bracket-field-consistency",
        "shared [req:] / [user:] / [service] bracket shape",
    )

    # --- auth-service logback pattern ---
    logback_pattern = _extract_logback_pattern(_AUTH_LOGBACK_PATH)
    if not logback_pattern:
        result.failures.append(
            f"could not find a <pattern> element in "
            f"{_AUTH_LOGBACK_PATH.relative_to(REPO_ROOT)}"
        )
        return result
    # Must reference the ${SERVICE_NAME} property so the literal service
    # identity bracket is present in the final output.
    if "${SERVICE_NAME}" not in logback_pattern:
        result.failures.append(
            "logback pattern does not interpolate ${SERVICE_NAME} — "
            "log lines will be missing the service-identity bracket"
        )
    for prefix in _REQUIRED_BRACKET_PREFIXES:
        if prefix not in logback_pattern:
            result.failures.append(
                f"logback pattern missing required bracket prefix {prefix!r}; "
                f"got: {logback_pattern!r}"
            )

    # --- assistant-service Python formatter ---
    py_fmt = _extract_python_fmt_literal(_ASSISTANT_LOGGING_PY)
    if py_fmt is None:
        result.failures.append(
            f"could not extract `fmt=` string from "
            f"{_ASSISTANT_LOGGING_PY.relative_to(REPO_ROOT)}"
        )
        return result
    # Must reference a `%(service)s` interpolation for the service-identity
    # bracket (the formatter fills record.service per handler).
    if "%(service)s" not in py_fmt:
        result.failures.append(
            "Python formatter does not use %(service)s — log lines will be "
            "missing the service-identity bracket"
        )
    for prefix in _REQUIRED_BRACKET_PREFIXES:
        if prefix not in py_fmt:
            result.failures.append(
                f"Python formatter missing required bracket prefix "
                f"{prefix!r}; got: {py_fmt!r}"
            )

    # --- cross-layer prefix-order sanity ---
    # The prefixes must appear in the SAME ORDER in both formatters so grep
    # regexes that key off column position stay valid.
    def _indices(s: str) -> list[int]:
        return [s.find(p) for p in _REQUIRED_BRACKET_PREFIXES]

    java_idx = _indices(logback_pattern)
    py_idx = _indices(py_fmt)
    if sorted(java_idx) != java_idx:
        result.failures.append(
            "logback pattern: [req:] / [user:] are out of order"
        )
    if sorted(py_idx) != py_idx:
        result.failures.append(
            "Python formatter: [req:] / [user:] are out of order"
        )
    return result


# ---------------------------------------------------------------------------
# auth-service OpenAPI schema: `details.errorCode` enum covers every
# `ErrorCodeName` constant (§9.3 condition 8)
# ---------------------------------------------------------------------------

_AUTH_ERROR_CODE_NAME_PATH = (
    REPO_ROOT / "services" / "auth-service" / "src" / "main" / "java"
    / "io" / "pixelsdb" / "pixels" / "rover" / "config" / "common"
    / "ErrorCodeName.java"
)
_AUTH_API_ERROR_DETAILS_PATH = (
    REPO_ROOT / "services" / "auth-service" / "src" / "main" / "java"
    / "io" / "pixelsdb" / "pixels" / "rover" / "api" / "dto"
    / "ApiErrorDetails.java"
)


def _parse_error_code_name_constants(path: Path) -> set[str]:
    """Extract every ``public static final String <NAME> = "<VALUE>";`` from
    the auth-service ``ErrorCodeName.java`` file."""
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"public\s+static\s+final\s+String\s+(\w+)\s*=\s*\"([^\"]+)\"\s*;"
    )
    out: set[str] = set()
    for name, value in pattern.findall(text):
        if name != value:
            continue  # defensive — the contract demands name ≡ value
        out.add(value)
    return out


def _parse_error_details_allowable_values(path: Path) -> set[str]:
    """Extract the ``allowableValues = { ... }`` array declared on the
    ``errorCode`` field of ``ApiErrorDetails.java``."""
    text = path.read_text(encoding="utf-8")
    # Strip // line comments so commented-out strings aren't credited.
    uncommented = re.sub(r"//[^\n]*", "", text)
    m = re.search(
        r"allowableValues\s*=\s*\{([^}]*)\}",
        uncommented,
        re.DOTALL,
    )
    if not m:
        return set()
    body = m.group(1)
    return set(re.findall(r'"([^"]+)"', body))


@register_check(
    "auth-openapi-error-code-enum-matches-source",
    "auth-service's `ApiErrorDetails.errorCode` @Schema allowableValues "
    "array MUST be an exact permutation of the public-static-final string "
    "constants declared in `ErrorCodeName.java` (backend.md §6.3 + §9.3 "
    "condition 8). This is the static mirror of the spring PostConstruct "
    "drift guard in OpenApiErrorSchemaContract; running the check here lets "
    "PR review catch the skew before the context load fails on container "
    "start, and before any code path that ingests `/openapi.json` can hand "
    "out a stale enum.",
)
def check_auth_openapi_error_code_enum_matches_source() -> CheckResult:
    result = CheckResult(
        "auth-openapi-error-code-enum-matches-source",
        "auth ApiErrorDetails.errorCode ⇄ ErrorCodeName",
    )
    if not _AUTH_ERROR_CODE_NAME_PATH.is_file():
        result.failures.append(
            f"expected {_AUTH_ERROR_CODE_NAME_PATH.relative_to(REPO_ROOT)} is missing"
        )
        return result
    if not _AUTH_API_ERROR_DETAILS_PATH.is_file():
        result.failures.append(
            f"expected {_AUTH_API_ERROR_DETAILS_PATH.relative_to(REPO_ROOT)} is missing"
        )
        return result

    from_source = _parse_error_code_name_constants(_AUTH_ERROR_CODE_NAME_PATH)
    from_schema = _parse_error_details_allowable_values(
        _AUTH_API_ERROR_DETAILS_PATH
    )

    missing = from_source - from_schema
    extra = from_schema - from_source

    if missing:
        result.failures.append(
            f"ApiErrorDetails.errorCode allowableValues is missing "
            f"{sorted(missing)} — add them alongside the matching "
            f"ErrorCodeName constant"
        )
    if extra:
        result.failures.append(
            f"ApiErrorDetails.errorCode allowableValues has extra values "
            f"{sorted(extra)} that are not declared in ErrorCodeName — "
            f"remove them or add the matching Java constant"
        )

    # §9.3 condition 8 explicitly calls out AUTH_INVALID_TOKEN / _TYPE pair;
    # keep a belt-and-suspenders assertion so a lean-up collapse can't quietly
    # drop them even if both sides agree on the removal.
    for required in ("AUTH_INVALID_TOKEN", "AUTH_INVALID_TOKEN_TYPE"):
        if required not in from_schema:
            result.failures.append(
                f"ApiErrorDetails.errorCode allowableValues must include "
                f"{required!r} (explicit §9.3 condition 8 requirement)"
            )
    return result


# ---------------------------------------------------------------------------
# Frontend hand-mirrored contract type files: top-of-file metadata rule
# ---------------------------------------------------------------------------

_FRONTEND_TYPES_DIR = REPO_ROOT / "frontend" / "src" / "shared" / "types"
# Known allowed owners: business services + the two pseudo-owners below.
#   "gateway" — infra-prefix codes / envelope shapes not tied to a backend;
#   "shared"  — genuinely cross-service envelope (currently: api.d.ts facade).
# Anything else must be an actual service identifier, keeping the mapping
# from contract → SSOT narrow.
_ALLOWED_OWNERS = {
    "assistant-service",
    "auth-service",
    "gateway",
    "shared",
}


@register_check(
    "frontend-type-mirror-metadata",
    "Every hand-written contract-mirror file under "
    "`frontend/src/shared/types/**/*.{ts,d.ts}` (excluding tests and pure "
    "aggregators that do not declare types) MUST carry a top-of-file JSDoc "
    "block with an `owning-service:` tag matching one of "
    "{assistant-service, auth-service, gateway, shared} and at least one "
    "`source-of-truth` / `Source of truth` tag pointing at the OpenAPI schema "
    "name or SSOT file + symbol (frontend.md §4.6 hard rule). The `shared` "
    "owner is reserved for cross-service envelope definitions and aggregator "
    "facades — any other owner value fails because "
    "`owning-service: frontend` / `owning-service: rover` etc. would drop the "
    "link back to a concrete backend contract.",
)
def check_frontend_type_mirror_metadata() -> CheckResult:
    result = CheckResult(
        "frontend-type-mirror-metadata",
        "frontend type-mirror files: owning-service + source-of-truth metadata",
    )
    if not _FRONTEND_TYPES_DIR.is_dir():
        result.failures.append(
            f"expected dir {_FRONTEND_TYPES_DIR.relative_to(REPO_ROOT)} "
            f"is missing — did the frontend layout move?"
        )
        return result

    # Files whose shape is enforced elsewhere and that genuinely have no
    # contract surface (test utilities, query-key enums). These are not
    # mirror files — they're frontend-owned.
    skip_names = {
        "query-keys.ts",
        "query-keys.test.ts",
    }

    def iter_type_files():
        for ext in ("*.ts", "*.d.ts"):
            for path in _FRONTEND_TYPES_DIR.rglob(ext):
                if path.name in skip_names:
                    continue
                yield path

    owning_re = re.compile(r"owning-service\s*:\s*([\w\-]+)")
    sot_re = re.compile(r"(?:source-of-truth|Source of truth)\b", re.IGNORECASE)

    for path in sorted(iter_type_files()):
        rel = path.relative_to(REPO_ROOT)
        text = path.read_text(encoding="utf-8")
        # Only look at the first JSDoc block (top of file). Nested JSDoc on
        # interfaces should not count — the rule targets the file banner.
        m_block = re.match(r"\s*/\*\*[\s\S]*?\*/", text)
        if not m_block:
            result.failures.append(
                f"{rel}: missing top-of-file JSDoc block with "
                f"`owning-service:` and `source-of-truth:` tags"
            )
            continue
        block = m_block.group(0)

        m_owner = owning_re.search(block)
        if not m_owner:
            result.failures.append(
                f"{rel}: top-of-file JSDoc does not declare "
                f"`owning-service: <service>`"
            )
            continue
        owner = m_owner.group(1)
        if owner not in _ALLOWED_OWNERS:
            result.failures.append(
                f"{rel}: owning-service={owner!r} is not one of "
                f"{sorted(_ALLOWED_OWNERS)}"
            )
            continue

        if not sot_re.search(block):
            result.failures.append(
                f"{rel}: top-of-file JSDoc does not declare any "
                f"`source-of-truth` / `Source of truth` tag"
            )
            continue

    return result


# ---------------------------------------------------------------------------
# Frontend nginx.conf: index.html must opt out of caching
# ---------------------------------------------------------------------------

_FRONTEND_NGINX_PATH = REPO_ROOT / "frontend" / "nginx.conf"


@register_check(
    "frontend-index-html-no-store",
    "frontend/nginx.conf MUST declare `location = /index.html { ... "
    "add_header Cache-Control \"no-store\" always; ... }` (frontend.md §5 "
    "hard rule). Hashed asset bundles are `immutable`, but `index.html` is "
    "the single mutable entry point: a stale cached copy pins the user to "
    "asset hashes that no longer exist on disk after a deploy, producing a "
    "white screen / 404 on /assets/index-<old>.js until the cache expires.",
)
def check_frontend_index_html_no_store() -> CheckResult:
    result = CheckResult(
        "frontend-index-html-no-store",
        "frontend nginx.conf: /index.html Cache-Control: no-store",
    )
    if not _FRONTEND_NGINX_PATH.is_file():
        result.failures.append(
            f"expected frontend nginx config at "
            f"{_FRONTEND_NGINX_PATH.relative_to(REPO_ROOT)}; not found"
        )
        return result
    text = _FRONTEND_NGINX_PATH.read_text(encoding="utf-8")

    # Strip line comments so that an accidentally commented-out directive
    # isn't credited as compliance.
    uncommented = "\n".join(
        line.split("#", 1)[0] for line in text.splitlines()
    )

    index_block_re = re.compile(
        r"location\s*=\s*/index\.html\s*\{(?P<body>[^}]*)\}",
        re.DOTALL,
    )
    block = index_block_re.search(uncommented)
    if not block:
        result.failures.append(
            "no `location = /index.html { ... }` exact-match block found; "
            "without the exact match the regex asset block (`immutable`) "
            "would win for direct /index.html requests"
        )
        return result

    body = block.group("body")
    # Require the `no-store` directive AND the `always` modifier: without
    # `always`, nginx drops `add_header` on non-2xx/3xx responses (e.g. 404
    # from `try_files`), and the stale-index risk sneaks back in through the
    # error path.
    if 'Cache-Control "no-store"' not in body and "Cache-Control 'no-store'" not in body:
        result.failures.append(
            "`location = /index.html` block missing "
            '`add_header Cache-Control "no-store" always;`'
        )
    elif "always" not in body:
        result.failures.append(
            "`add_header Cache-Control \"no-store\"` found but without the "
            "`always` modifier — nginx will silently drop the header on "
            "non-2xx/3xx responses; add `always` to cover the full status "
            "range"
        )
    return result


# ---- Frontend X-Request-Id lifecycle (frontend.md §4.6) -------------------


_FRONTEND_REQUEST_ID_MODULE = (
    _ROOT_FRONTEND_SRC / "shared" / "storage" / "requestId.ts"
)
_FRONTEND_API_CLIENT = _ROOT_FRONTEND_SRC / "shared" / "api" / "client.ts"
_FRONTEND_API_SSE = _ROOT_FRONTEND_SRC / "shared" / "api" / "sse.ts"


@register_check(
    "frontend-request-id-storage-isolation",
    "frontend.md §4.6 request-id layering: the generator module "
    "`shared/storage/requestId.ts` stays free of axios / fetch / Request / "
    "Web storage. Any drift into those collapses layer boundaries and "
    "risks process-global id caches colliding across parallel requests.",
)
def check_frontend_request_id_storage_isolation() -> CheckResult:
    result = CheckResult(
        "frontend-request-id-storage-isolation",
        "requestId.ts imports neither axios/fetch/Request nor browser storage",
    )
    if not _FRONTEND_REQUEST_ID_MODULE.is_file():
        result.failures.append(
            f"expected frontend request-id module at "
            f"{_FRONTEND_REQUEST_ID_MODULE.relative_to(REPO_ROOT)}; not found"
        )
        return result
    text = _FRONTEND_REQUEST_ID_MODULE.read_text(encoding="utf-8")
    # Strip TS // line comments and /* ... */ block comments so our prose
    # about localStorage / axios inside JSDoc doesn't trip the guard.
    stripped = re.sub(r"/\*[\s\S]*?\*/", "", text)
    stripped = "\n".join(
        line.split("//", 1)[0] for line in stripped.splitlines()
    )
    forbidden = (
        ("import axios", "axios import"),
        ("from 'axios'", "axios import"),
        ('from "axios"', "axios import"),
        ("localStorage", "Web storage (localStorage)"),
        ("sessionStorage", "Web storage (sessionStorage)"),
        # fetch/Request/XMLHttpRequest as symbol uses (not as substrings in
        # words like ``RequestId``/``fetchRequest``). Use word boundaries.
    )
    for needle, label in forbidden:
        if needle in stripped:
            result.failures.append(
                f"{_FRONTEND_REQUEST_ID_MODULE.relative_to(REPO_ROOT)}: "
                f"forbidden reference to {label} ({needle!r}); the "
                "generator module must stay pure"
            )
    # Word-boundary checks for symbol-level escapes.
    symbol_patterns = (
        (r"\bfetch\s*\(", "fetch() call"),
        (r"\bnew\s+Request\s*\(", "new Request() construction"),
        (r"\bXMLHttpRequest\b", "XMLHttpRequest reference"),
    )
    for pattern, label in symbol_patterns:
        if re.search(pattern, stripped):
            result.failures.append(
                f"{_FRONTEND_REQUEST_ID_MODULE.relative_to(REPO_ROOT)}: "
                f"forbidden {label}; binding id to the wire is "
                "`shared/api/`'s job"
            )
    return result


@register_check(
    "frontend-request-id-consumers-via-ensure",
    "frontend.md §4.6: axios client and SSE client go through "
    "`ensureRequestId` so the 401-retry / SSE reconnect paths reuse the "
    "same X-Request-Id. They must never call `createRequestId` or "
    "`crypto.randomUUID` directly — that's the drift that silently "
    "regenerates ids on retry.",
)
def check_frontend_request_id_consumers_via_ensure() -> CheckResult:
    result = CheckResult(
        "frontend-request-id-consumers-via-ensure",
        "client.ts & sse.ts route X-Request-Id through ensureRequestId",
    )
    for path in (_FRONTEND_API_CLIENT, _FRONTEND_API_SSE):
        if not path.is_file():
            result.failures.append(
                f"expected frontend api module at "
                f"{path.relative_to(REPO_ROOT)}; not found"
            )
            continue
        text = path.read_text(encoding="utf-8")
        stripped = re.sub(r"/\*[\s\S]*?\*/", "", text)
        stripped = "\n".join(
            line.split("//", 1)[0] for line in stripped.splitlines()
        )
        rel = path.relative_to(REPO_ROOT)

        # Call-site guards: a direct crypto.randomUUID() or createRequestId()
        # bypasses the reuse wrapper. client.ts is a special case — it owns
        # the reuse semantics and legitimately calls ensureRequestId, not
        # createRequestId; sse.ts goes through buildCommonHeaders.
        if re.search(r"\bcrypto\s*\.\s*randomUUID\s*\(", stripped):
            result.failures.append(
                f"{rel}: calls `crypto.randomUUID()` directly; route "
                "through ensureRequestId() in shared/storage/requestId.ts"
            )
        if re.search(r"\bcreateRequestId\s*\(", stripped):
            result.failures.append(
                f"{rel}: calls `createRequestId()` directly; use "
                "`ensureRequestId(existing)` so retries reuse the id"
            )

    # Positive assertion: ensureRequestId actually appears in the client.
    if _FRONTEND_API_CLIENT.is_file():
        client_text = _FRONTEND_API_CLIENT.read_text(encoding="utf-8")
        if "ensureRequestId" not in client_text:
            result.failures.append(
                f"{_FRONTEND_API_CLIENT.relative_to(REPO_ROOT)}: expected "
                "`ensureRequestId` to be used by the axios interceptor / "
                "buildCommonHeaders, but the symbol is absent"
            )
    return result


# ---- Introspect envelope wrapping (backend.md §8.6.1) ---------------------


_INTERNAL_AUTH_CONTROLLER = (
    REPO_ROOT / "services" / "auth-service" / "src" / "main" / "java"
    / "io" / "pixelsdb" / "pixels" / "rover" / "controller"
    / "InternalAuthController.java"
)
_GATEWAY_AUTH_LUA = (
    REPO_ROOT / "gateway" / "custom" / "apisix" / "plugins" / "gateway-auth.lua"
)


@register_check(
    "introspect-envelope-wrapping",
    "The `/api/internal/auth/introspect` endpoint MUST return "
    "`ApiResponse<AuthIntrospectionResponse>` (backend.md §8.6.1 — no "
    "RFC 7662 bare-schema exemption) and `gateway-auth.lua` MUST unwrap "
    "`decoded.data.active` / `.userId` / `.email` / `.sessionId`. A "
    "regression on either side silently breaks every introspect cache "
    "lookup at startup; this check freezes both sides against drift.",
)
def check_introspect_envelope_wrapping() -> CheckResult:
    result = CheckResult(
        "introspect-envelope-wrapping",
        "InternalAuthController + gateway-auth.lua agree on envelope shape",
    )
    if not _INTERNAL_AUTH_CONTROLLER.is_file():
        result.failures.append(
            f"missing {_INTERNAL_AUTH_CONTROLLER.relative_to(REPO_ROOT)}"
        )
    else:
        ctrl = _INTERNAL_AUTH_CONTROLLER.read_text(encoding="utf-8")
        # Strip comments so prose mentioning "AuthIntrospectionResponse"
        # in JavaDoc doesn't satisfy the return-type check below.
        code = re.sub(r"/\*[\s\S]*?\*/", "", ctrl)
        code = "\n".join(
            line.split("//", 1)[0] for line in code.splitlines()
        )
        # Positive: a @PostMapping handler declared on the class must
        # return ApiResponse<AuthIntrospectionResponse>.
        if not re.search(
            r"public\s+ApiResponse<\s*AuthIntrospectionResponse\s*>",
            code,
        ):
            result.failures.append(
                f"{_INTERNAL_AUTH_CONTROLLER.relative_to(REPO_ROOT)}: "
                "expected a `public ApiResponse<AuthIntrospectionResponse>` "
                "handler; the introspect endpoint MUST wrap in ApiResponse"
            )
        # Positive: the wrap call must be present.
        if "ApiResponse.success(" not in code:
            result.failures.append(
                f"{_INTERNAL_AUTH_CONTROLLER.relative_to(REPO_ROOT)}: "
                "expected `ApiResponse.success(...)` wrap; the handler is "
                "returning a bare DTO, which would make gateway-auth.lua "
                "unwrap `decoded.data` fail"
            )
        # Negative: no bare return of an AuthIntrospectionResponse variable.
        # This catches the specific regression where a refactor re-introduces
        # `return response;` at the end of the handler body.
        if re.search(
            r"public\s+AuthIntrospectionResponse\s+\w+\s*\(",
            code,
        ):
            result.failures.append(
                f"{_INTERNAL_AUTH_CONTROLLER.relative_to(REPO_ROOT)}: a "
                "handler method has return type AuthIntrospectionResponse; "
                "wrap it in ApiResponse<AuthIntrospectionResponse> per "
                "backend.md §8.6.1"
            )

    if not _GATEWAY_AUTH_LUA.is_file():
        result.failures.append(
            f"missing {_GATEWAY_AUTH_LUA.relative_to(REPO_ROOT)}"
        )
    else:
        lua = _GATEWAY_AUTH_LUA.read_text(encoding="utf-8")
        # Strip Lua `--` line comments so the `backend.md §8.6.1` anchor
        # comment doesn't satisfy the positive check below.
        lua_code = "\n".join(
            line.split("--", 1)[0] for line in lua.splitlines()
        )
        # Positive: must traverse `decoded.data.*`.
        if not re.search(r"\bdecoded\.data\b", lua_code):
            result.failures.append(
                f"{_GATEWAY_AUTH_LUA.relative_to(REPO_ROOT)}: expected "
                "traversal through `decoded.data.*`; gateway-auth.lua "
                "MUST unwrap the ApiResponse envelope one extra layer"
            )
        # Negative: no direct read of `decoded.active` (the pre-wrap shape).
        if re.search(r"\bdecoded\.active\b", lua_code):
            result.failures.append(
                f"{_GATEWAY_AUTH_LUA.relative_to(REPO_ROOT)}: found "
                "`decoded.active` — that's the pre-wrap bare-schema shape; "
                "read `decoded.data.active` instead per backend.md §8.6.1"
            )
    return result


# ---- Frontend retryable-infra codes mirror JSON ---------------------------


_FRONTEND_ERROR_POLICY = (
    _ROOT_FRONTEND_SRC / "shared" / "api" / "errorPolicy.ts"
)
_ERROR_CODES_JSON = REPO_ROOT / "gateway" / "error-codes.json"


@register_check(
    "frontend-retryable-infra-codes-match-json",
    "The hand-mirrored `RETRYABLE_INFRA_ERROR_CODES` set in "
    "`frontend/src/shared/api/errorPolicy.ts` MUST equal the set of "
    "infra-prefix (GATEWAY_* / INTERNAL_*) codes whose `retryable: true` "
    "is declared in `gateway/error-codes.json` (SSOT). Drift on either "
    "side — flipping the JSON's retryable flag without updating the "
    "frontend, or adding a new GATEWAY_* literal to the frontend set — "
    "silently changes whether user-facing `retry` buttons appear for that "
    "failure class. See backend.md §6.3.2 two-tier dispatch contract.",
)
def check_frontend_retryable_infra_codes_match_json() -> CheckResult:
    result = CheckResult(
        "frontend-retryable-infra-codes-match-json",
        "errorPolicy.ts retryable infra set == gateway/error-codes.json",
    )
    if not _FRONTEND_ERROR_POLICY.is_file():
        result.failures.append(
            f"expected {_FRONTEND_ERROR_POLICY.relative_to(REPO_ROOT)}"
        )
        return result
    if not _ERROR_CODES_JSON.is_file():
        result.failures.append(
            f"expected {_ERROR_CODES_JSON.relative_to(REPO_ROOT)}"
        )
        return result
    try:
        registry = json.loads(_ERROR_CODES_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        result.failures.append(f"error-codes.json parse error: {exc}")
        return result
    codes = registry.get("codes", {})
    expected = {
        name
        for name, meta in codes.items()
        if isinstance(meta, dict) and meta.get("retryable") is True
    }

    text = _FRONTEND_ERROR_POLICY.read_text(encoding="utf-8")
    block_re = re.compile(
        r"RETRYABLE_INFRA_ERROR_CODES\s*:\s*ReadonlySet<[^>]*>\s*="
        r"\s*new\s+Set<[^>]*>\(\s*\[(?P<body>[^\]]*)\]\s*\)",
        re.DOTALL,
    )
    match = block_re.search(text)
    if not match:
        result.failures.append(
            "could not locate `RETRYABLE_INFRA_ERROR_CODES` declaration; "
            "preserve the `new Set<ErrorCode>([...])` shape the contract "
            "check parses"
        )
        return result
    literal_re = re.compile(r"['\"]([A-Z_][A-Z0-9_]*)['\"]")
    observed = set(literal_re.findall(match.group("body")))

    missing_in_frontend = expected - observed
    extra_in_frontend = observed - expected
    if missing_in_frontend:
        result.failures.append(
            "gateway/error-codes.json marks these as retryable but "
            "frontend errorPolicy.ts omits them: "
            f"{sorted(missing_in_frontend)}"
        )
    if extra_in_frontend:
        result.failures.append(
            "frontend errorPolicy.ts marks these as retryable-infra but "
            "gateway/error-codes.json does NOT: "
            f"{sorted(extra_in_frontend)}"
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
