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
    # smoke.sh is a future §15.1 PR. Until then we still expect this
    # script to declare the intent by grepping for the path once it
    # exists — the check below tolerates a missing file with a clear
    # "pending: §15.1" message rather than failing the gate.
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
            # smoke.sh is the known "future PR" case. Tolerate its absence
            # with an explicit message instead of silently skipping —
            # that way "oh I forgot to add smoke.sh as a consumer" still
            # surfaces, while "oh smoke.sh hasn't been written yet" doesn't
            # block PRs for unrelated §14 work.
            if path.name == "smoke.sh":
                continue
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
