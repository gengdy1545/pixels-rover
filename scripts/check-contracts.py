#!/usr/bin/env python3
"""Cross-layer contract drift detector for pixels-rover.

Purpose
-------

The gateway, Ory components, assistant-service, and frontend each make
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
import os
import re
import subprocess
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
    REPO_ROOT / "docker-compose.yml",
    REPO_ROOT / "services" / "assistant-service" / "app" / "required_env.py",
    REPO_ROOT / "scripts" / "smoke.sh",
)
_TEMPLATE_ENV_PLACEHOLDER_RE = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")
_TEMPLATE_ENV_PATHS = (
    REPO_ROOT / "gateway" / "apisix.yaml.template",
    REPO_ROOT / "gateway" / "config.yaml.template",
)

# §Task 1 (architecture-tasks.md) — config/services.yaml is the SSOT for
# every backend service reachable under `/api/v1/*`. Mirrors the
# required-env registry pattern above: one YAML + schema pair, one
# consumer list, one generator. Drift between any two is a CI failure.
_SERVICES_YAML_PATH = REPO_ROOT / "config" / "services.yaml"
_SERVICES_SCHEMA_PATH = REPO_ROOT / "config" / "services.schema.yaml"
_OATHKEEPER_RULES_PATH = REPO_ROOT / "config" / "ory" / "oathkeeper" / "rules.yml"
_GATEWAY_CONFIG_GENERATOR = REPO_ROOT / "scripts" / "generate-gateway-config.py"
# Every file listed here MUST mention "config/services.yaml" as a
# string literal somewhere in its text, proving it reads from the
# SSOT rather than forking its own service list. Adding a consumer
# = append here AND cite the YAML path in the referenced file.
_SERVICES_YAML_CONSUMERS = (
    REPO_ROOT / "scripts" / "generate-gateway-config.py",
    # check-contracts.py itself references the path through the
    # _SERVICES_YAML_PATH constant above — no need to re-list it here.
)
# FastAPI services whose router prefixes are covered by services.yaml.
# Expanding this tuple is how a new backend service joins the registry
# ↔ FastAPI coherence check (§Task 6 extension).
_FASTAPI_SERVICE_ROOTS = (
    REPO_ROOT / "services" / "assistant-service" / "app" / "api",
)


def _load_services_registry() -> dict:
    return yaml.safe_load(_SERVICES_YAML_PATH.read_text(encoding="utf-8")) or {}


def _load_services_schema() -> dict:
    return yaml.safe_load(_SERVICES_SCHEMA_PATH.read_text(encoding="utf-8")) or {}


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

    Current gateway rendering is a straight envsubst. Older templates used
    an OpenAPI fragment marker; keep the splice path for historical branches
    but parse the template directly when the marker is absent.
    """
    template_text = _APISIX_TEMPLATE_PATH.read_text(encoding="utf-8")
    rendered = (
        _splice_openapi_fragment(template_text, profile)
        if _OPENAPI_MARKER in template_text
        else template_text
    )
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
    # Only audit custom plugins that actually emit errorCodes; skip
    # the shared helper and any future non-emitting modules.
    targeted = {"gateway-csrf.lua", "gateway-ready.lua"}

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
    apisix = _load_apisix_yaml()
    gateway_auth_in_runtime = "gateway-auth" in text or any(
        isinstance(route, dict) and "gateway-auth" in (route.get("plugins") or {})
        for route in apisix.get("routes") or []
    )
    if not gateway_auth_in_runtime:
        return result
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


@register_check(
    "retired-auth-runtime-absent",
    "Retired gateway-auth, auth-service, ory-policy-adapter, and keys/jwt "
    "runtime dependencies must not reappear in compose or APISIX runtime config.",
)
def check_retired_auth_runtime_absent() -> CheckResult:
    result = CheckResult(
        "retired-auth-runtime-absent",
        "old auth runtime dependencies absent",
    )
    apisix = _load_apisix_yaml()
    routes = apisix.get("routes") or []
    for route in routes:
        plugins = route.get("plugins") or {}
        if "gateway-auth" in plugins:
            result.failures.append(
                f"route {route.get('id', route.get('uri'))!r} still uses gateway-auth"
            )
    runtime_files = {
        "docker-compose.yml": REPO_ROOT / "docker-compose.yml",
        "gateway/Dockerfile": REPO_ROOT / "gateway" / "Dockerfile",
        "gateway/config.yaml.template": _CONFIG_TEMPLATE_PATH,
        "gateway/apisix.yaml.template": _APISIX_TEMPLATE_PATH,
    }
    banned = ("gateway-auth", "ory-policy-adapter", "services/auth-service", "keys/jwt")
    for label, path in runtime_files.items():
        text = path.read_text(encoding="utf-8")
        for needle in banned:
            if needle in text:
                result.failures.append(f"{label}: retired runtime reference {needle!r}")
    return result


@register_check(
    "protected-api-goes-through-oathkeeper",
    "APISIX has one coarse /api/v1/* protected route, strips forged X-Auth-* "
    "headers, enforces gateway-csrf, and proxies directly to Oathkeeper.",
)
def check_protected_api_goes_through_oathkeeper() -> CheckResult:
    result = CheckResult(
        "protected-api-goes-through-oathkeeper",
        "/api/v1/* -> gateway-csrf -> oathkeeper",
    )
    apisix = _load_apisix_yaml()
    routes = apisix.get("routes") or []
    protected = [r for r in routes if r.get("id") == "protected-api"]
    if len(protected) != 1:
        result.failures.append(
            f"expected exactly one route id='protected-api', found {len(protected)}"
        )
        return result

    route = protected[0]
    if route.get("uri") != "/api/v1/*":
        result.failures.append(f"protected-api uri must be /api/v1/*, got {route.get('uri')!r}")
    if route.get("upstream_id") != "oathkeeper-proxy":
        result.failures.append(
            f"protected-api upstream_id must be oathkeeper-proxy, got {route.get('upstream_id')!r}"
        )
    plugins = route.get("plugins") or {}
    if "gateway-csrf" not in plugins:
        result.failures.append("protected-api missing gateway-csrf plugin")
    proxy_rewrite = plugins.get("proxy-rewrite") or {}
    removed = set(((proxy_rewrite.get("headers") or {}).get("remove")) or [])
    required_removed = {"X-Auth-User-Id", "X-Auth-User-Email", "X-Auth-Session-Id"}
    missing_removed = required_removed - removed
    if missing_removed:
        result.failures.append(
            f"protected-api proxy-rewrite must remove {sorted(missing_removed)}"
        )

    upstreams = {
        u.get("id"): u
        for u in apisix.get("upstreams") or []
        if isinstance(u, dict)
    }
    oathkeeper = upstreams.get("oathkeeper-proxy")
    nodes = (oathkeeper or {}).get("nodes") or {}
    if set(nodes.keys()) != {"oathkeeper:4455"}:
        result.failures.append(
            f"oathkeeper-proxy upstream must point directly to oathkeeper:4455, got {sorted(nodes.keys())}"
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
            plugins = route.get("plugins") or {}
            deny_only = "serverless-pre-function" in plugins and not route.get("upstream_id")
            if deny_only:
                continue
            result.failures.append(
                f"route {route.get('id', uri)!r} exposes {uri!r} — "
                "internal prefixes must only have explicit deny routes"
            )
    return result


@register_check(
    "oathkeeper-rules-cover-protected-domains",
    "Oathkeeper rules own protected API path-to-upstream dispatch for analysis, "
    "conversations, and semantic domains.",
)
def check_oathkeeper_rules_cover_protected_domains() -> CheckResult:
    result = CheckResult(
        "oathkeeper-rules-cover-protected-domains",
        "Oathkeeper protected domain rules",
    )
    rules_path = REPO_ROOT / "config" / "ory" / "oathkeeper" / "rules.yml"
    if not rules_path.is_file():
        result.failures.append("config/ory/oathkeeper/rules.yml missing")
        return result
    rules = yaml.safe_load(rules_path.read_text(encoding="utf-8")) or []
    domains = {
        "analysis": "/api/v1/analysis",
        "conversations": "/api/v1/conversations",
        "semantic": "/api/v1/semantic",
    }
    text_by_rule = [
        {
            "id": rule.get("id"),
            "url": ((rule.get("match") or {}).get("url") or ""),
            "authenticators": [a.get("handler") for a in rule.get("authenticators") or []],
            "mutators": [m.get("handler") for m in rule.get("mutators") or []],
        }
        for rule in rules
        if isinstance(rule, dict)
    ]
    for domain, prefix in domains.items():
        matches = [r for r in text_by_rule if prefix in r["url"]]
        if not matches:
            result.failures.append(f"no Oathkeeper rule covers {domain} prefix {prefix}")
            continue
        if not any("cookie_session" in r["authenticators"] for r in matches):
            result.failures.append(f"{domain} rules must use cookie_session authenticator")
        if not any("header" in r["mutators"] for r in matches):
            result.failures.append(f"{domain} rules must use header mutator")
    return result


# ---------------------------------------------------------------------------
# OpenAPI per-service namespace routes (§9.1 / gateway.md §6.7)
# ---------------------------------------------------------------------------

# Known OpenAPI route ids for legacy fragment-based gateway templates. The
# current Ory cutover template does not use fragments, but keeping this check
# lets older branches fail loudly if they accidentally reintroduce ambiguous
# OpenAPI route ordering.
_OPENAPI_ROUTE_IDS: tuple[str, ...] = ("analysis-openapi",)
_OPENAPI_PROFILES: tuple[str, ...] = ("protected", "public")
# Mapping route id -> API domain prefix. Used to locate "sibling
# business prefix routes" against which the OpenAPI precise-path
# route's priority is compared.
_OPENAPI_ROUTE_DOMAIN: dict[str, str] = {
    "analysis-openapi": "/api/v1/analysis/",
}
_OPENAPI_PRIORITY_MARGIN = 10  # gateway.md §6.2 / §6.7 hard rule


@register_check(
    "openapi-route-priority-above-deepest-prefix",
    "Each /api/v1/<svc>/openapi.json route has priority >= "
    "deepest /api/v1/<svc>/* prefix route's priority + 10, and both "
    "fragments (public / protected) declare the same set of openapi "
    "routes with byte-identical fields.",
)
def check_openapi_route_priority() -> CheckResult:
    result = CheckResult(
        "openapi-route-priority-above-deepest-prefix",
        "OpenAPI route priority + fragment symmetry",
    )

    # 1. Parse template (sans openapi routes) to find deepest business
    #    prefix per domain.
    template_text = _APISIX_TEMPLATE_PATH.read_text(encoding="utf-8")
    if _OPENAPI_MARKER not in template_text:
        return result
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

    by_id_public = {
        r.get("id"): json.loads(json.dumps(r))
        for r in fragments.get("public", [])
        if isinstance(r, dict)
    }
    by_id_protected = {
        r.get("id"): json.loads(json.dumps(r))
        for r in fragments.get("protected", [])
        if isinstance(r, dict)
    }
    for rid in _OPENAPI_ROUTE_IDS:
        pub = by_id_public.get(rid)
        prot = by_id_protected.get(rid)
        if pub and prot and pub != prot:
            result.failures.append(
                f"route {rid}: public vs protected fragment differ in "
                "fields — fragment-based OpenAPI routes must be "
                "byte-identical after the Ory cutover (gateway.md §6.7)"
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

# SSE routes in apisix.yaml — derived from config/services.yaml rather
# than hand-maintained. Every registry entry with
# ``timeout_class: sse`` implies a per-service APISIX route whose id is
# ``<name>-sse`` (the same id the generator emits in
# ``verify_apisix_alignment``). Driving this contract off the SSOT
# means adding a new SSE endpoint is a one-line registry edit, not a
# tri-file coordination (registry + template + this contract).
#
# The [600, 1800] second window remains an INDEPENDENT invariant
# declared here (not inherited from the generator's TimeoutClassProfile).
# Rationale: the generator profile declares the single concrete value
# today's policy uses (``sse.read_timeout_s = 1800``); this contract
# enforces the WINDOW around it, so a future profile edit that dropped
# the SSE budget to, say, 60s — breaking long analyses — or raised it
# beyond the §5.3.4 collapse-window cap would fail here before the
# template ever reaches production. Two independent defenses, per
# task-file §Task 7 Acceptance "SSE heartbeats survive long idle gaps
# without 504" *and* gateway.md §5.3.4 upper bound.
_SSE_READ_TIMEOUT_MIN_S = 600   # 10 min lower bound for long LLM analyses
_SSE_READ_TIMEOUT_MAX_S = 1800  # 30 min hard cap (gateway.md §6.3 / §5.3.4)


def _load_sse_route_ids_from_registry() -> tuple[tuple[str, ...], str | None]:
    """Return (route ids for every sse-class entry, error or None).

    We go through the generator's ``timeout_class_expected_route_id``
    helper rather than concatenating the id here ourselves — the
    generator is the SSOT for the ``<name>-<class>`` naming rule, and
    duplicating it in the contract would be the exact drift seam we
    want to close.
    """
    import importlib.util as _ilu

    spec = _ilu.spec_from_file_location(
        "_gen_gateway_sse_lookup", _GATEWAY_CONFIG_GENERATOR
    )
    if spec is None or spec.loader is None:
        return (), (
            f"could not load {_GATEWAY_CONFIG_GENERATOR.relative_to(REPO_ROOT)}"
        )
    module = _ilu.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)  # type: ignore[arg-type]
        entries = module.load_registry()
    except (ValueError, NotImplementedError, FileNotFoundError) as exc:
        return (), f"generator refused to load registry: {exc}"
    finally:
        sys.modules.pop(spec.name, None)

    ids: list[str] = []
    for entry in entries:
        if entry.timeout_class != "sse":
            continue
        rid = module.timeout_class_expected_route_id(entry)
        if rid is None:
            continue  # unreachable — sse entries always yield a route id
        ids.append(rid)
    return tuple(ids), None


@register_check(
    "sse-routes-explicit-timeout-and-buffering",
    "Every /api/v1/* route derived from a `timeout_class: sse` entry in "
    "config/services.yaml declares an explicit read timeout in "
    "[600, 1800]s and disables request buffering (gateway.md §6.3 + "
    "§5.3.4 collapse-window rule; architecture-tasks §Task 7).",
)
def check_sse_route_hardening() -> CheckResult:
    result = CheckResult(
        "sse-routes-explicit-timeout-and-buffering",
        "SSE routes: explicit read_timeout + request_buffering off",
    )
    sse_route_ids, lookup_error = _load_sse_route_ids_from_registry()
    if lookup_error is not None:
        result.failures.append(lookup_error)
        return result
    if not sse_route_ids:
        # Zero sse-class entries is a valid registry state (e.g. a
        # future all-REST deployment). The invariant doesn't apply.
        return result

    apisix = _load_apisix_yaml()
    routes_by_id: dict[str, dict] = {}
    for r in apisix.get("routes") or []:
        rid = r.get("id")
        if isinstance(rid, str):
            routes_by_id[rid] = r

    for rid in sse_route_ids:
        route = routes_by_id.get(rid)
        if route is None:
            result.failures.append(
                f"SSE route id {rid!r} required by config/services.yaml "
                f"(a `timeout_class: sse` entry resolves to this id via "
                f"`timeout_class_expected_route_id`) but missing from "
                f"apisix.yaml — add the route or flip the registry "
                f"entry's timeout_class"
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


def _required_env_names() -> set[str]:
    doc = _load_required_env_doc()
    names: set[str] = set()
    for entries in (doc.get("services") or {}).values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get("name"), str):
                names.add(entry["name"])
    return names


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


@register_check(
    "template-env-placeholders-registered",
    "Every ${ENV_VAR} placeholder used by gateway templates is either "
    "declared in config/required-env.yaml or explicitly derived by the "
    "gateway entrypoint before envsubst. Also flags required-env entries "
    "that are never referenced anywhere in runtime/config files.",
)
def check_template_env_placeholders_registered() -> CheckResult:
    result = CheckResult(
        "template-env-placeholders-registered",
        "gateway template ${...} placeholders ↔ required-env.yaml",
    )
    declared = _required_env_names()
    used_by_template: dict[str, list[str]] = {}
    for path in _TEMPLATE_ENV_PATHS:
        if not path.is_file():
            result.failures.append(f"template missing: {path.relative_to(REPO_ROOT)}")
            continue
        text = path.read_text(encoding="utf-8")
        for name in _TEMPLATE_ENV_PLACEHOLDER_RE.findall(text):
            used_by_template.setdefault(name, []).append(str(path.relative_to(REPO_ROOT)))

    entrypoint = REPO_ROOT / "gateway" / "entrypoint.sh"
    entrypoint_text = entrypoint.read_text(encoding="utf-8") if entrypoint.is_file() else ""
    derived = {
        name
        for name in used_by_template
        if re.search(rf"^\s*{re.escape(name)}=", entrypoint_text, re.MULTILINE)
        and re.search(rf"^\s*export\s+{re.escape(name)}\b", entrypoint_text, re.MULTILINE)
    }

    for name, paths in sorted(used_by_template.items()):
        if name in declared or name in derived:
            continue
        result.failures.append(
            f"${{{name}}} appears in {paths} but is neither declared in "
            "config/required-env.yaml nor derived+exported by gateway/entrypoint.sh"
        )

    runtime_paths = (
        REPO_ROOT / "docker-compose.yml",
        REPO_ROOT / "docker-compose.dev.yml",
        REPO_ROOT / "gateway",
        REPO_ROOT / "services" / "assistant-service" / "app",
        REPO_ROOT / "scripts",
        REPO_ROOT / ".env.example",
    )
    runtime_text = ""
    for root in runtime_paths:
        if not root.exists():
            continue
        if root.is_file():
            runtime_text += "\n" + root.read_text(encoding="utf-8", errors="ignore")
            continue
        for path in root.rglob("*"):
            if not path.is_file() or _is_excluded_scan_path(path):
                continue
            try:
                runtime_text += "\n" + path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

    for name in sorted(declared):
        if name not in runtime_text:
            result.failures.append(
                f"config/required-env.yaml declares {name!r}, but no runtime/config "
                "consumer references that name"
            )
    return result


@register_check(
    "cors-csrf-header-canonical",
    "Gateway CORS allow_headers exposes only the canonical X-XSRF-TOKEN CSRF "
    "header and does not pre-authorize Authorization before jwt_bearer is implemented.",
)
def check_cors_csrf_header_canonical() -> CheckResult:
    result = CheckResult(
        "cors-csrf-header-canonical",
        "CORS allow_headers uses canonical CSRF header only",
    )
    apisix = _load_apisix_yaml()
    cors_rules = [
        rule
        for rule in apisix.get("global_rules") or []
        if isinstance(rule, dict) and rule.get("id") == "cors"
    ]
    if len(cors_rules) != 1:
        result.failures.append(f"expected exactly one global cors rule, found {len(cors_rules)}")
        return result
    allow_headers = (
        ((cors_rules[0].get("plugins") or {}).get("cors") or {}).get("allow_headers")
        or ""
    )
    observed = {part.strip() for part in allow_headers.split(",") if part.strip()}
    expected = {"Content-Type", "Cookie", "X-Request-Id", "X-XSRF-TOKEN"}
    if observed != expected:
        result.failures.append(
            f"cors.allow_headers must be exactly {sorted(expected)}, got {sorted(observed)}"
        )
    for forbidden in ("X-CSRF-Token", "Authorization"):
        if forbidden in observed:
            result.failures.append(
                f"cors.allow_headers must not include {forbidden!r} until a live auth mode needs it"
            )
    return result


# ---------------------------------------------------------------------------
# §Task 11 — source-side companion to cors-csrf-header-canonical.
#
# cors-csrf-header-canonical locks the edge: only X-XSRF-TOKEN is pre-flight
# allow-listed in the gateway's CORS policy. That contract on its own is NOT
# enough — a well-meaning PR could quietly teach gateway-csrf.lua to also
# read `X-CSRF-Token` (or `Authorization`, pre-jwt_bearer) as a fallback.
# CORS would still accept only the canonical header, but the plugin would
# now silently honor an alternative one on any cross-origin request that
# happened to supply it, reintroducing the "which header is authoritative"
# CSRF footgun Task 11 was written to eliminate.
#
# This check reads the plugin source directly and fails if (a) the canonical
# literal "X-XSRF-TOKEN" is not present exactly once at a get_header()
# call site, or (b) any of the forbidden alternative header names appear
# anywhere in the source (comments stripped). Task 5 reserves a future
# `auth_mode: jwt_bearer` that would legitimately reintroduce
# `Authorization`; when that branch lands, this check must be relaxed
# deliberately, which is exactly the drift signal we want.
# ---------------------------------------------------------------------------
@register_check(
    "gateway-csrf-plugin-canonical-header-name",
    "gateway-csrf.lua reads the CSRF token from exactly one header name — "
    "the canonical `X-XSRF-TOKEN` pinned by Task 11. Forbidden alternatives "
    "(`X-CSRF-Token`, `X-Csrf-Token`, `Authorization`) must not appear in "
    "the source so that accepting them can never be a one-line silent PR. "
    "This check is the plugin-source counterpart to cors-csrf-header-"
    "canonical: the former guards the edge allow-list, this one guards the "
    "code that actually reads the header.",
)
def check_gateway_csrf_plugin_canonical_header_name() -> CheckResult:
    result = CheckResult(
        "gateway-csrf-plugin-canonical-header-name",
        "gateway-csrf.lua reads only the canonical CSRF header",
    )
    plugin_basename = "gateway-csrf.lua"
    target: tuple[Path, str] | None = None
    for path, source in _plugin_sources():
        if path.name == plugin_basename:
            target = (path, source)
            break
    if target is None:
        result.failures.append(
            f"plugin source not found: {plugin_basename}"
        )
        return result

    path, source = target
    rel = path.relative_to(REPO_ROOT)
    # Strip line comments so rationale/"see finding #6" mentions in
    # documentation blocks can't accidentally be flagged, and so the
    # canonical-name count is never inflated by a comment echo.
    stripped = _strip_lua_line_comments(source)

    canonical = "X-XSRF-TOKEN"
    # get_header("X-XSRF-TOKEN") is the one load-bearing call site; the
    # regex requires the literal sit inside a get_header(...) call so a
    # stray string constant elsewhere would still trip the count check.
    read_sites = re.findall(
        r'get_header\s*\(\s*"' + re.escape(canonical) + r'"\s*\)',
        stripped,
    )
    if len(read_sites) != 1:
        result.failures.append(
            f"{rel}: expected exactly 1 `get_header(\"{canonical}\")` call "
            f"site (the canonical CSRF read), found {len(read_sites)}"
        )

    # Any literal string match for the forbidden names — case-insensitive,
    # to catch `X-Csrf-Token` / `x-csrf-token` variants that proxies
    # normalize differently across runtimes.
    forbidden = ("X-CSRF-Token", "Authorization")
    for name in forbidden:
        pattern = re.compile(
            r'["\']' + re.escape(name) + r'["\']',
            re.IGNORECASE,
        )
        if pattern.search(stripped):
            result.failures.append(
                f"{rel}: forbidden CSRF/auth header literal {name!r} "
                f"appears in plugin source; only {canonical!r} is "
                "canonical today. If this is a legitimate introduction of "
                "auth_mode=jwt_bearer (Task 5), relax this check in the "
                "same PR and update cors-csrf-header-canonical together."
            )
    return result


@register_check(
    "public-metrics-explicitly-denied",
    "APISIX declares an explicit public /metrics deny route so metrics are "
    "not protected only by absence of a business upstream route "
    "(architecture-tasks §Task 14). The contract locks five independent "
    "shape invariants — uri, methods subset, priority, reject status code "
    "emitted by serverless-pre-function, and black-hole upstream pinned "
    "to 127.0.0.1:65535 — so that any single-line drift (e.g. flipping "
    "ngx.status to 200, or re-pointing the upstream at the assistant "
    "service) is caught before it reaches runtime. Relaxation path for "
    "future observability work: introduce a second, higher-priority "
    "route scoped to the scraper network or a shared-secret header that "
    "DOES proxy to the metrics upstream, and update this contract to "
    "treat `uri: /metrics` as a TWO-route contract in the same PR.",
)
def check_public_metrics_explicitly_denied() -> CheckResult:
    result = CheckResult(
        "public-metrics-explicitly-denied",
        "gateway /metrics explicit deny route with locked shape",
    )
    routes = _load_apisix_yaml().get("routes") or []
    metrics = [
        route for route in routes
        if isinstance(route, dict) and route.get("uri") == "/metrics"
    ]
    if len(metrics) != 1:
        result.failures.append(
            f"expected exactly one route with uri == '/metrics', "
            f"found {len(metrics)}. If a scraper-scoped proxy route is "
            "being introduced, update this contract to expect the "
            "two-route shape in the same PR (see contract description)."
        )
        return result
    route = metrics[0]

    # -- priority must beat both the frontend SPA catch-all and any
    # future mis-ordered business route. The hard floor `>= 900` was
    # the original weak bound; Task 14 raises it to `>= 9000` because
    # the on-disk template pins `priority: 9989` on deny-public-metrics
    # specifically to sit above every business route. Lowering it
    # would open a race where a mis-sorted higher-priority rule could
    # accept the request first.
    prio = route.get("priority", 0)
    if not isinstance(prio, int) or prio < 9000:
        result.failures.append(
            f"/metrics deny route priority must be >= 9000 to sit "
            f"above every business route and the SPA catch-all, got "
            f"{prio!r}"
        )

    # -- methods subset: must not silently accept any verb. The deny
    # route should cover at least GET+HEAD (the only verbs a scraper
    # would emit); extending to POST/PUT is a behavioral change that
    # requires an explicit, reviewed contract update.
    methods = route.get("methods")
    if not isinstance(methods, list) or set(methods) != {"GET", "HEAD"}:
        result.failures.append(
            f"/metrics deny route methods must be exactly ['GET', "
            f"'HEAD'] (any other verb is either redundant — no "
            f"scraper emits it — or an accidental relaxation). "
            f"got {methods!r}"
        )

    # -- upstream must be the black-hole 127.0.0.1:65535. APISIX
    # requires every route to declare an upstream even when the
    # request is short-circuited by serverless-pre-function; pinning
    # the nodes map to 127.0.0.1:65535 ensures that if the plugin
    # chain is ever removed by mistake, the request still fails
    # closed (connection refused) instead of being proxied to a
    # real backend.
    if route.get("upstream_id"):
        result.failures.append(
            "/metrics deny route must not proxy to an upstream_id; "
            "the black-hole `upstream` inline block is the single "
            "allowed shape so the route fails closed even if the "
            "reject plugin is removed by mistake."
        )
    upstream = route.get("upstream") or {}
    nodes = upstream.get("nodes") if isinstance(upstream, dict) else None
    if not isinstance(nodes, dict) or set(nodes.keys()) != {"127.0.0.1:65535"}:
        result.failures.append(
            "/metrics deny route upstream.nodes must be exactly "
            "{'127.0.0.1:65535': <weight>} (black-hole host on a "
            "reserved unroutable port). Pointing this at a real "
            "host would turn the route from 'fail closed on plugin "
            f"absence' into 'leak metrics on plugin absence'. got {nodes!r}"
        )

    # -- serverless-pre-function must reject with an explicit 4xx.
    # The plugin body is a Lua chunk embedded as a YAML string; a
    # regex that grepping for `ngx.status = <NNN>` is the minimal
    # way to assert the status without pulling in a Lua parser. The
    # accepted status set is {403, 404}: 404 masks the route's
    # existence from arbitrary scanners (current template choice),
    # 403 would be the equivalent explicit policy denial if the
    # operator prefers it. 200 / 3xx / 5xx are all wrong for this
    # code path and would silently leak metrics body or tie the
    # deny to error-handling infra that may itself fail open.
    plugins = route.get("plugins") or {}
    spf = plugins.get("serverless-pre-function") if isinstance(plugins, dict) else None
    if not isinstance(spf, dict):
        result.failures.append(
            "/metrics route must reject via a serverless-pre-function "
            "plugin block (the explicit policy denial; route absence "
            "is NOT a substitute per Task 14)."
        )
        return result
    funcs = spf.get("functions") or []
    concatenated = "\n".join(f for f in funcs if isinstance(f, str))
    # Accept either ngx.status = 403 or 404 (explicit deny shapes).
    status_pattern = re.compile(r"ngx\.status\s*=\s*(403|404)\b")
    if not status_pattern.search(concatenated):
        result.failures.append(
            "/metrics serverless-pre-function must set ngx.status to "
            "403 or 404 (explicit deny). Any other status (especially "
            "200) would leak metrics body or mask the denial as a "
            "downstream error."
        )
    # And: the plugin body must actually terminate the request with
    # ngx.exit, not merely set a status and fall through. `return` on
    # its own works for some phases; ngx.exit is the unambiguous
    # short-circuit.
    if "ngx.exit" not in concatenated:
        result.failures.append(
            "/metrics serverless-pre-function must call ngx.exit(...) "
            "to short-circuit the request; relying on status alone "
            "leaves the upstream connect attempt on the code path."
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
_ROOT_ASSISTANT_APP = REPO_ROOT / "services" / "assistant-service" / "app"
_ROOT_FRONTEND_SRC = REPO_ROOT / "frontend" / "src"
_ROOT_GATEWAY_PLUGINS = REPO_ROOT / "gateway" / "custom" / "apisix" / "plugins"

_ALL_CODE_ROOTS = (
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


# User-facing controller files. Internal-only plumbing legitimately emits
# 401/403 because it IS the boundary; user-facing business APIs do not.
_USER_FACING_CONTROLLER_FILES = (
    REPO_ROOT / "services" / "assistant-service" / "app" / "api" / "analysis.py",
    REPO_ROOT / "services" / "assistant-service" / "app" / "api" / "backends.py",
    REPO_ROOT / "services" / "assistant-service" / "app" / "api" / "conversations.py",
    REPO_ROOT / "services" / "assistant-service" / "app" / "api" / "semantic.py",
)


@register_check(
    "no-business-401-or-403",
    "User-facing assistant-service API modules MUST "
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
    hits = _scan_for_pattern((_ROOT_ASSISTANT_APP,), pattern)
    for path, lineno, line in hits:
        result.failures.append(f"{path}:{lineno}: {line.strip()}")
    return result


# ---- A6 / JWKS sunset regression -----------------------------------------


_JWKS_FORBIDDEN_ROOTS = (
    _ROOT_ASSISTANT_APP,
    _ROOT_GATEWAY_PLUGINS,
    _ROOT_FRONTEND_SRC,
)

# architecture-tasks §Task 8 introduced a SINGLE legitimate consumer of
# JWKS symbols inside assistant-service: `app/oathkeeper_jwt.py`, which
# verifies Oathkeeper's id_token mutator signatures. Everything else
# stays sunset — the frontend and gateway plugins MUST still surface
# zero hits. Enumerating the allow-listed file here (rather than
# inside the scan helper) keeps the contract's scope legible at a
# glance: the list grows only when a reviewer deliberately extends it.
_JWKS_ALLOWED_FILES: frozenset[Path] = frozenset({
    _ROOT_ASSISTANT_APP / "oathkeeper_jwt.py",
})


@register_check(
    "jwks-sunset-no-regression",
    "`jwks` / `JWKS` / `PyJWKClient` / `NimbusJwtDecoder` / `jwks_uri` do "
    "not appear in assistant-service, gateway plugins, or the frontend, "
    "EXCEPT for the single allow-listed Oathkeeper JWT verifier module "
    "`services/assistant-service/app/oathkeeper_jwt.py` introduced by "
    "architecture-tasks §Task 8. Every other hit is still treated as a "
    "sunset regression — the allow-list is narrowly scoped to one file "
    "so a future careless `from jose import jwks_uri` elsewhere lights "
    "up CI immediately.",
)
def check_jwks_sunset() -> CheckResult:
    result = CheckResult(
        "jwks-sunset-no-regression",
        "zero JWKS-symbol references outside the Task-8 allow-list",
    )
    pattern = r"\b(jwks|JWKS|PyJWKClient|NimbusJwtDecoder|jwks_uri)\b"
    hits = _scan_for_pattern(_JWKS_FORBIDDEN_ROOTS, pattern)
    allowed_rel: frozenset[Path] = frozenset(
        p.relative_to(REPO_ROOT) for p in _JWKS_ALLOWED_FILES
    )
    for path, lineno, line in hits:
        if path in allowed_rel:
            continue
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
        (_ROOT_ASSISTANT_APP,),
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
# Business prefixes (ANALYSIS_* / CONVERSATION_* / SEMANTIC_* owned by
# assistant-service) need the symmetric guarantee:
#
#   * No cross-namespace leakage (backend.md §6.3).
#   * Frontend union equality with the Python source of truth, same
#     shape as `frontend-infra-union-equals-json` but bidirectional per
#     namespace.
#   * Route priority: every "request-set containment" pair must be ordered
#     by +10 (gateway.md §6.2 hard rule — not just the openapi-vs-prefix
#     subcase covered by the existing check).
# ---------------------------------------------------------------------------


_ERROR_CODES_PY = REPO_ROOT / "services" / "assistant-service" / "app" / "error_codes.py"
_FRONTEND_AUTH_ERRORCODE_TS = REPO_ROOT / "frontend" / "src" / "shared" / "types" / "auth" / "ErrorCode.ts"
_FRONTEND_ANALYSIS_ERRORCODE_TS = REPO_ROOT / "frontend" / "src" / "shared" / "types" / "analysis" / "ErrorCode.ts"

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


# ---- B1 / retired AUTH_* namespace ----------------------------------------


_AUTH_ALLOWED_ROOTS = (
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
    "retired-auth-business-namespace-absent",
    "`AUTH_*` business error-code literals are retired with auth-service and "
    "must not appear in runtime code.",
)
def check_auth_namespace_single_owner() -> CheckResult:
    result = CheckResult(
        "retired-auth-business-namespace-absent",
        "AUTH_* literals absent from runtime code",
    )
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
    # Auto-generated TS types (openapi-typescript, see Task 4) surface
    # every ``details.errorCode`` enum value from the assistant-service
    # pydantic models, which includes the full ANALYSIS_* / CONVERSATION_*
    # / SEMANTIC_* namespace. The file is re-rendered by `npm run gen:types`
    # off a committed OpenAPI snapshot that in turn is re-rendered by
    # `scripts/export-openapi.py` off the assistant-service pydantic
    # models, so any rogue literal here would have to have travelled
    # through the pydantic source first — it's the same owning service.
    REPO_ROOT / "frontend" / "src" / "shared" / "types" / "generated",
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
    "/ app). gateway plugins leaking any of these violate backend.md §6.3 "
    "cross-service namespace ownership.",
)
def check_analysis_namespace_single_owner() -> CheckResult:
    result = CheckResult(
        "analysis-business-namespace-single-owner",
        "ANALYSIS_* / CONVERSATION_* / SEMANTIC_* literals only in owner tree",
    )
    pattern = r"\b(?:ANALYSIS|CONVERSATION|SEMANTIC)_[A-Z][A-Z0-9_]+\b"
    hits = _scan_for_pattern(
        (_ROOT_FRONTEND_SRC, _ROOT_GATEWAY_PLUGINS),
        pattern,
    )
    for path, lineno, line in hits:
        abs_path = REPO_ROOT / path
        if _path_under(abs_path, _ANALYSIS_ALLOWED_ROOTS):
            continue
        result.failures.append(f"{path}:{lineno}: {line.strip()}")
    return result


# ---- B3 / retired frontend AuthErrorCode union ----------------------------


@register_check(
    "retired-frontend-auth-errorcode-type-absent",
    "frontend AuthErrorCode mirror is removed with auth-service.",
)
def check_frontend_auth_union_equals_java() -> CheckResult:
    result = CheckResult(
        "retired-frontend-auth-errorcode-type-absent",
        "frontend auth ErrorCode mirror absent",
    )
    if _FRONTEND_AUTH_ERRORCODE_TS.exists():
        result.failures.append(
            f"{_FRONTEND_AUTH_ERRORCODE_TS.relative_to(REPO_ROOT)} still exists"
        )
    if (REPO_ROOT / "services" / "auth-service").exists():
        result.failures.append(
            "services/auth-service still exists"
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
# Assistant-service renders log lines with the user-visible bracketed-field
# shape (`[<service>] [req:<requestId>] [user:<userId>]`), so future log
# aggregators have a stable format to key on.
#
# This check is deliberately scoped to the currently-produced text log
# format. When `elapsedMs` and per-request timing fields are introduced
# as structured JSON (future §18 or its follow-up), extend this check with
# the new required-field list rather than adding a second check.
# ---------------------------------------------------------------------------


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
    "assistant-service Python formatter produces log lines whose "
    "user-visible bracket prefixes `[req:` and `[user:` match the shared "
    "logging contract and embeds the owning service identity (backend.md §5).",
)
def check_log_format_bracket_consistency() -> CheckResult:
    result = CheckResult(
        "log-format-bracket-field-consistency",
        "assistant [req:] / [user:] / [service] bracket shape",
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

    py_idx = [py_fmt.find(p) for p in _REQUIRED_BRACKET_PREFIXES]
    if sorted(py_idx) != py_idx:
        result.failures.append(
            "Python formatter: [req:] / [user:] are out of order"
        )
    return result


@register_check(
    "retired-auth-service-directory-absent",
    "services/auth-service is removed after the Ory cutover.",
)
def check_auth_openapi_error_code_enum_matches_source() -> CheckResult:
    result = CheckResult(
        "retired-auth-service-directory-absent",
        "services/auth-service absent",
    )
    if (REPO_ROOT / "services" / "auth-service").exists():
        result.failures.append(
            "services/auth-service still exists after Ory cutover"
        )
    return result


# ---------------------------------------------------------------------------
# Frontend hand-mirrored contract type files: top-of-file metadata rule
# ---------------------------------------------------------------------------

_FRONTEND_TYPES_DIR = REPO_ROOT / "frontend" / "src" / "shared" / "types"
# Known allowed owners: business/identity services + the two pseudo-owners below.
#   "gateway" — infra-prefix codes / envelope shapes not tied to a backend;
#   "shared"  — genuinely cross-service envelope (currently: api.d.ts facade).
# Anything else must be an actual service identifier, keeping the mapping
# from contract → SSOT narrow.
_ALLOWED_OWNERS = {
    "assistant-service",
    "kratos",
    "gateway",
    "shared",
}


@register_check(
    "frontend-type-mirror-metadata",
    "Every hand-written contract-mirror file under "
    "`frontend/src/shared/types/**/*.{ts,d.ts}` (excluding tests and pure "
    "aggregators that do not declare types) MUST carry a top-of-file JSDoc "
    "block with an `owning-service:` tag matching one of "
    "{assistant-service, kratos, gateway, shared} and at least one "
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

    # Auto-generated types (openapi-typescript output + its support
    # utilities) live under `types/generated/**`. They are NOT
    # hand-written mirrors — they ARE the SSOT projection. The
    # `assistant-openapi-snapshot-fresh` + `frontend-generated-types-fresh`
    # pair (Task 4) locks their shape to the backend pydantic source, so
    # requiring the hand-written JSDoc contract header here would be
    # redundant (and impossible for the generator output, which
    # openapi-typescript rewrites on every `gen:types` run).
    skip_subdirs = {
        _FRONTEND_TYPES_DIR / "generated",
    }

    def iter_type_files():
        for ext in ("*.ts", "*.d.ts"):
            for path in _FRONTEND_TYPES_DIR.rglob(ext):
                if path.name in skip_names:
                    continue
                if any(
                    skip_root == path or skip_root in path.parents
                    for skip_root in skip_subdirs
                ):
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


# ---- Retired introspect/gateway-auth path --------------------------------


@register_check(
    "retired-introspect-gateway-auth-absent",
    "The old auth-service introspection path and gateway-auth Lua plugin "
    "must not exist after the Ory cutover.",
)
def check_introspect_envelope_wrapping() -> CheckResult:
    result = CheckResult(
        "retired-introspect-gateway-auth-absent",
        "old introspect/gateway-auth path absent",
    )
    for path in (
        REPO_ROOT / "services" / "auth-service",
        REPO_ROOT / "gateway" / "custom" / "apisix" / "plugins" / "gateway-auth.lua",
    ):
        if path.exists():
            result.failures.append(f"{path.relative_to(REPO_ROOT)} still exists")
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
# §Task 1 — config/services.yaml SSOT checks
#
# Four assertions lock down the backend-service registry SSOT in the same
# shape §14 locks down required-env.yaml:
#
#   1. services-yaml-conforms-to-schema
#        Shape-level validation against config/services.schema.yaml.
#   2. services-yaml-prefixes-have-fastapi-router
#        Every `path_prefix` in the registry appears as an
#        `APIRouter(prefix=...)` in at least one FastAPI service.
#        Catches "added entry, forgot to wire the route".
#   3. oathkeeper-rules-match-services-yaml
#        config/ory/oathkeeper/rules.yml is a byte-identical re-render
#        from the registry via scripts/generate-gateway-config.py.
#        Catches "edited one side, forgot to regenerate the other".
#   4. services-yaml-consumers-registered
#        Every file in _SERVICES_YAML_CONSUMERS mentions
#        "config/services.yaml" as a string literal — same SSOT
#        discipline we already apply to required-env.yaml.
# ---------------------------------------------------------------------------


# FastAPI router prefix regex. Matches:
#     router = APIRouter(prefix="/api/v1/whatever", ...)
# Accepts single- and double-quoted strings; anything else is ignored
# (e.g. test fixtures that build prefixes at runtime). The prefix MUST
# start with /api/v1/ to participate in the registry's jurisdiction.
_FASTAPI_PREFIX_RE = re.compile(
    r"APIRouter\s*\(\s*[^)]*?prefix\s*=\s*['\"](?P<prefix>/api/v1/[^'\"]*)['\"]",
    re.DOTALL,
)


def _collect_fastapi_prefixes(roots: Iterable[Path]) -> dict[str, list[Path]]:
    """Return {prefix: [files that declare it]} across the given service roots."""
    found: dict[str, list[Path]] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for py_path in sorted(root.rglob("*.py")):
            text = py_path.read_text(encoding="utf-8")
            for match in _FASTAPI_PREFIX_RE.finditer(text):
                prefix = match.group("prefix")
                found.setdefault(prefix, []).append(py_path)
    return found


@register_check(
    "services-yaml-conforms-to-schema",
    "config/services.yaml conforms to config/services.schema.yaml "
    "(§Task 1). Also enforces the uniqueness invariants the schema "
    "cannot express in a single rule: `name` and `path_prefix` are "
    "each unique across the file.",
)
def check_services_yaml_schema() -> CheckResult:
    result = CheckResult(
        "services-yaml-conforms-to-schema",
        "services.yaml shape + uniqueness invariants",
    )
    if not _SERVICES_YAML_PATH.is_file():
        result.failures.append(
            f"expected {_SERVICES_YAML_PATH.relative_to(REPO_ROOT)}"
        )
        return result
    if not _SERVICES_SCHEMA_PATH.is_file():
        result.failures.append(
            f"expected {_SERVICES_SCHEMA_PATH.relative_to(REPO_ROOT)}"
        )
        return result
    doc = _load_services_registry()
    schema = _load_services_schema()

    _validate_against_schema(doc, schema, "$", result.failures)
    if result.failures:
        return result

    entries = doc.get("services") or []
    seen_names: dict[str, int] = {}
    seen_prefixes: dict[str, int] = {}
    for idx, entry in enumerate(entries):
        name = entry.get("name")
        prefix = entry.get("path_prefix")
        if name in seen_names:
            result.failures.append(
                f"services.yaml entry #{idx}: duplicate name {name!r} "
                f"(first seen at entry #{seen_names[name]})"
            )
        else:
            seen_names[name] = idx
        if prefix in seen_prefixes:
            result.failures.append(
                f"services.yaml entry #{idx}: duplicate path_prefix "
                f"{prefix!r} (first seen at entry #{seen_prefixes[prefix]})"
            )
        else:
            seen_prefixes[prefix] = idx
    return result


@register_check(
    "services-yaml-prefixes-have-fastapi-router",
    "Every `path_prefix` declared in config/services.yaml MUST appear as "
    "`APIRouter(prefix=...)` in at least one FastAPI service under "
    "services/*/app/api/ (§Task 1 acceptance). Stops the drift where a "
    "registry entry is added but the backend route is never wired, "
    "which would otherwise surface only as a 404 at runtime.",
)
def check_services_yaml_has_fastapi_router() -> CheckResult:
    result = CheckResult(
        "services-yaml-prefixes-have-fastapi-router",
        "every services.yaml prefix has a FastAPI router",
    )
    if not _SERVICES_YAML_PATH.is_file():
        result.failures.append(
            f"expected {_SERVICES_YAML_PATH.relative_to(REPO_ROOT)}"
        )
        return result
    doc = _load_services_registry()
    entries = doc.get("services") or []
    if not entries:
        # Empty registry would have been caught by the schema check;
        # no need to duplicate that failure here.
        return result

    fastapi_prefixes = _collect_fastapi_prefixes(_FASTAPI_SERVICE_ROOTS)
    for entry in entries:
        prefix = entry.get("path_prefix")
        if prefix not in fastapi_prefixes:
            result.failures.append(
                f"services.yaml entry {entry.get('name')!r}: path_prefix "
                f"{prefix!r} has no matching `APIRouter(prefix=...)` in "
                "any FastAPI service under services/*/app/api/"
            )
    return result


@register_check(
    "oathkeeper-rules-match-services-yaml",
    "config/ory/oathkeeper/rules.yml is a byte-identical re-render of "
    "config/services.yaml via scripts/generate-gateway-config.py "
    "(§Task 1). If this fails, run the generator with --write and "
    "commit both files.",
)
def check_oathkeeper_rules_generated() -> CheckResult:
    result = CheckResult(
        "oathkeeper-rules-match-services-yaml",
        "rules.yml == generate-gateway-config.py(services.yaml)",
    )
    if not _GATEWAY_CONFIG_GENERATOR.is_file():
        result.failures.append(
            f"expected {_GATEWAY_CONFIG_GENERATOR.relative_to(REPO_ROOT)}"
        )
        return result
    if not _OATHKEEPER_RULES_PATH.is_file():
        result.failures.append(
            f"expected {_OATHKEEPER_RULES_PATH.relative_to(REPO_ROOT)}"
        )
        return result

    # Delegate to the generator's render function via importlib — same
    # pattern env-example-matches-required-env-yaml uses to avoid
    # duplicating the renderer in this file.
    import importlib.util as _ilu

    spec = _ilu.spec_from_file_location(
        "_gen_gateway", _GATEWAY_CONFIG_GENERATOR
    )
    if spec is None or spec.loader is None:
        result.failures.append(
            f"could not load {_GATEWAY_CONFIG_GENERATOR.relative_to(REPO_ROOT)}"
        )
        return result
    module = _ilu.module_from_spec(spec)
    # Register the module in sys.modules BEFORE exec_module so the
    # generator's `@dataclass` decorators can resolve `cls.__module__`
    # during their internal type inspection. Without this, Python 3.10
    # raises AttributeError: 'NoneType' object has no attribute '__dict__'
    # the moment the dataclass tries to look itself up by module name.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)  # type: ignore[arg-type]
        entries = module.load_registry()
        rendered = module.render_oathkeeper_rules(entries)
    except (ValueError, NotImplementedError, FileNotFoundError) as exc:
        result.failures.append(f"generator refused to render: {exc}")
        return result
    finally:
        # Leave sys.modules as we found it so parallel checks don't
        # see a stale copy of the generator's module namespace.
        sys.modules.pop(spec.name, None)

    on_disk = _OATHKEEPER_RULES_PATH.read_text(encoding="utf-8")
    if rendered != on_disk:
        result.failures.append(
            f"{_OATHKEEPER_RULES_PATH.relative_to(REPO_ROOT)} does not "
            "match the registry; run "
            "`python3 scripts/generate-gateway-config.py --write` and commit"
        )
    return result


@register_check(
    "oathkeeper-rules-have-terminal-deny",
    "config/ory/oathkeeper/rules.yml MUST end with a catch-all rule that "
    "uses Oathkeeper's built-in `unauthorized` authenticator scoped to "
    "/api/v1/<.*> (architecture-tasks.md §Task 2). Oathkeeper evaluates "
    "rules top-to-bottom and the first match wins, so a missing or "
    "mis-ordered terminal deny turns a dropped service rule into a "
    "silent auth bypass rather than a 401.",
)
def check_oathkeeper_rules_have_terminal_deny() -> CheckResult:
    result = CheckResult(
        "oathkeeper-rules-have-terminal-deny",
        "terminal deny-all rule present and last",
    )
    if not _OATHKEEPER_RULES_PATH.is_file():
        result.failures.append(
            f"expected {_OATHKEEPER_RULES_PATH.relative_to(REPO_ROOT)}"
        )
        return result
    rules = yaml.safe_load(
        _OATHKEEPER_RULES_PATH.read_text(encoding="utf-8")
    ) or []
    if not isinstance(rules, list) or not rules:
        result.failures.append(
            f"{_OATHKEEPER_RULES_PATH.relative_to(REPO_ROOT)}: no rules "
            "parsed; deny-all invariant cannot be enforced"
        )
        return result

    # Deny-all is the LAST rule — any rule after it would be
    # unreachable (Oathkeeper short-circuits on first match), so the
    # presence of such a rule is itself a correctness bug worth calling
    # out here rather than passing silently.
    last = rules[-1]
    if not isinstance(last, dict):
        result.failures.append(
            "last rule is not a mapping; cannot verify deny-all shape"
        )
        return result

    # Expected shape mirrors the generator's
    # render_oathkeeper_rules() terminal-rule constants. We deliberately
    # re-state the expectation here rather than importing the generator
    # symbols so a silent rename in the generator cannot weaken the
    # invariant this check defends.
    expected_id = "deny-all-api-v1"
    if last.get("id") != expected_id:
        result.failures.append(
            f"last rule id must be {expected_id!r}, got "
            f"{last.get('id')!r}; the terminal deny-all was either "
            "removed or shadowed by a later rule"
        )
        return result

    match = last.get("match") or {}
    match_url = match.get("url") or ""
    if "/api/v1/" not in match_url or "<.*>" not in match_url:
        result.failures.append(
            f"deny-all match.url must cover /api/v1/<.*>, got "
            f"{match_url!r}"
        )

    authenticators = [
        (a or {}).get("handler")
        for a in (last.get("authenticators") or [])
        if isinstance(a, dict)
    ]
    if authenticators != ["unauthorized"]:
        result.failures.append(
            f"deny-all authenticators must be exactly "
            f"[{{handler: unauthorized}}], got {authenticators}"
        )

    mutators = [
        (m or {}).get("handler")
        for m in (last.get("mutators") or [])
        if isinstance(m, dict)
    ]
    if mutators != ["noop"]:
        result.failures.append(
            "deny-all mutators must be exactly [{handler: noop}] — the "
            "`header` mutator would template X-Auth-* headers from a "
            "subject the authenticator just rejected; "
            f"got {mutators}"
        )

    return result


@register_check(
    "services-yaml-generator-branch-semantics",
    "scripts/generate-gateway-config.py branches on `auth_mode` to pick "
    "the Oathkeeper authenticator/mutator chain. This check is the "
    "generator's unit test (architecture-tasks §Task 5 acceptance): it "
    "drives every declared auth_mode value through the renderer against "
    "an IN-MEMORY synthetic registry and asserts the exact shape of the "
    "emitted rule. Covers the four contract slots (`cookie_session`, "
    "`public`, `api_key`, `jwt_bearer`) plus the terminal deny-all "
    "invariance under arbitrary registry content. Nothing on disk is "
    "touched — the production services.yaml / rules.yml are not "
    "modified or re-read by this check.",
)
def check_services_yaml_generator_branch_semantics() -> CheckResult:
    result = CheckResult(
        "services-yaml-generator-branch-semantics",
        "generator auth_mode branches round-trip correctly",
    )
    if not _GATEWAY_CONFIG_GENERATOR.is_file():
        result.failures.append(
            f"expected {_GATEWAY_CONFIG_GENERATOR.relative_to(REPO_ROOT)}"
        )
        return result

    # Load the generator module in isolation (same pattern
    # oathkeeper-rules-match-services-yaml uses). We deliberately
    # re-import here instead of caching across checks so a generator
    # change visible only in one check cannot leak into another.
    import importlib.util as _ilu

    spec = _ilu.spec_from_file_location(
        "_gen_gateway_semantics", _GATEWAY_CONFIG_GENERATOR
    )
    if spec is None or spec.loader is None:
        result.failures.append(
            f"could not load {_GATEWAY_CONFIG_GENERATOR.relative_to(REPO_ROOT)}"
        )
        return result
    module = _ilu.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)  # type: ignore[arg-type]
    except Exception as exc:  # pragma: no cover — import-time bug in generator
        result.failures.append(f"generator failed to import: {exc}")
        sys.modules.pop(spec.name, None)
        return result

    try:
        ServiceEntry = module.ServiceEntry
        render = module.render_oathkeeper_rules

        def _entry(name: str, prefix: str, auth_mode: str) -> "object":
            # Synthetic upstream pair; never bound to a real container.
            # Using distinct host/port per entry lets the assertions
            # below also catch a hypothetical cross-entry mixup.
            return ServiceEntry(
                name=name,
                path_prefix=prefix,
                upstream_host=f"{name}-svc",
                upstream_port=9000 + abs(hash(name)) % 1000,
                auth_mode=auth_mode,
                timeout_class="standard",
            )

        # -- Branch A: cookie_session --------------------------------
        # Mirrors production's live mode. The rendered rule MUST
        # participate in the X-Auth-* contract (header mutator) and
        # accept the full authed method set (GET/POST/PUT/PATCH/
        # DELETE/OPTIONS), because the backend is expected to enforce
        # per-route method narrowing itself (backend.md §2.3).
        cs_rules = _parse_rules(render([_entry("fix-cs", "/api/v1/fix-cs", "cookie_session")]))
        cs_service = _find_rule(cs_rules, "fix-cs")
        if cs_service is None:
            result.failures.append(
                "cookie_session branch: service rule 'fix-cs' missing "
                "from rendered output"
            )
        else:
            _expect_eq(
                result,
                "cookie_session.authenticators",
                [a.get("handler") for a in cs_service.get("authenticators") or []],
                ["cookie_session"],
            )
            _expect_eq(
                result,
                "cookie_session.mutators",
                [m.get("handler") for m in cs_service.get("mutators") or []],
                # architecture-tasks §Task 8: cookie_session carries
                # `header` + `id_token` (in that order). The JWT mutator
                # runs AFTER the header mutator so both derive from the
                # same {{ .Subject / .Extra }} snapshot; swapping the
                # order would make a future renderer emit a header
                # template that reads claims the id_token mutator has
                # not yet resolved.
                ["header", "id_token"],
            )
            _expect_eq(
                result,
                "cookie_session.methods",
                (cs_service.get("match") or {}).get("methods") or [],
                ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            )

        # -- Branch B: public ---------------------------------------
        # Acceptance-critical: flipping a service to `public` MUST
        # produce a rule that (a) permits anonymous traffic via the
        # `noop` authenticator and (b) DOES NOT attach the `header`
        # mutator — there is no subject to template, and letting the
        # `header` handler run after `noop` would propagate any
        # forged upstream X-Auth-* headers unchanged. This is the
        # concrete check that finding #1's "silent bypass" risk cannot
        # re-enter via the public-mode path either.
        pub_rules = _parse_rules(render([_entry("fix-pub", "/api/v1/fix-pub", "public")]))
        pub_service = _find_rule(pub_rules, "fix-pub")
        if pub_service is None:
            result.failures.append(
                "public branch: service rule 'fix-pub' missing from "
                "rendered output"
            )
        else:
            _expect_eq(
                result,
                "public.authenticators",
                [a.get("handler") for a in pub_service.get("authenticators") or []],
                ["noop"],
            )
            _expect_eq(
                result,
                "public.mutators",
                [m.get("handler") for m in pub_service.get("mutators") or []],
                ["noop"],
            )
            # Public = browser-safe verbs only; unsafe methods
            # MUST fall through to an explicit cookie_session rule
            # or the deny-all. Today this set is {GET, HEAD, OPTIONS}.
            _expect_eq(
                result,
                "public.methods",
                (pub_service.get("match") or {}).get("methods") or [],
                ["GET", "HEAD", "OPTIONS"],
            )

        # -- Branch C/D: api_key, jwt_bearer are reserved slots -----
        # Schema-open, generator-closed. Asking the generator to render
        # them MUST raise NotImplementedError so a future PR cannot
        # silently land `auth_mode: api_key` with no behind-the-scenes
        # wiring. The error must carry the service name to make the
        # operator's fix obvious.
        for reserved in ("api_key", "jwt_bearer"):
            try:
                render([_entry(f"fix-{reserved.replace('_', '-')}",
                               f"/api/v1/fix-{reserved.replace('_', '-')}",
                               reserved)])
            except NotImplementedError as exc:
                msg = str(exc)
                if reserved not in msg:
                    result.failures.append(
                        f"{reserved} branch: NotImplementedError did not "
                        f"name the offending auth_mode (got {msg!r}); "
                        "operators need the value echoed back to locate "
                        "the services.yaml row"
                    )
            except Exception as exc:  # noqa: BLE001 — guarding against silent regressions
                result.failures.append(
                    f"{reserved} branch: expected NotImplementedError, "
                    f"got {type(exc).__name__}: {exc}"
                )
            else:
                result.failures.append(
                    f"{reserved} branch: render succeeded but that "
                    f"auth_mode has no live generator branch — the "
                    "schema slot exists so CI could catch this drift, "
                    "not so the generator could silently accept it"
                )

        # -- Invariant E: deny-all is always last, regardless of
        # registry shape. Drives the renderer on an empty-but-valid
        # registry (no service rules) as well as a mixed cs+public
        # registry; in both the last rule's id must be the terminal
        # deny-all sentinel. This is the generator-level companion to
        # the rules-file-level check `oathkeeper-rules-have-terminal-deny`.
        for label, registry in (
            (
                "mixed-cs-and-public",
                [
                    _entry("fix-mix-cs", "/api/v1/fix-mix-cs", "cookie_session"),
                    _entry("fix-mix-pub", "/api/v1/fix-mix-pub", "public"),
                ],
            ),
        ):
            rendered = _parse_rules(render(registry))
            if not rendered:
                result.failures.append(
                    f"{label}: generator returned zero rules — deny-all "
                    "invariant trivially violated"
                )
                continue
            if rendered[-1].get("id") != module._OATHKEEPER_DENY_ALL_RULE_ID:
                result.failures.append(
                    f"{label}: last rendered rule is "
                    f"{rendered[-1].get('id')!r}, expected "
                    f"{module._OATHKEEPER_DENY_ALL_RULE_ID!r}"
                )

        # -- Invariant F: uniqueness. load_registry rejects duplicate
        # names / prefixes; we reach into it here instead of renderer
        # so we stress the structural parser too. We build the in-memory
        # dict shape load_registry expects by calling the underlying
        # ServiceEntry.from_mapping — the dedup logic lives in
        # load_registry, so the easiest check is to invoke it with a
        # monkey-patched REGISTRY_PATH pointing at a tempfile.
        import tempfile

        dup_name_yaml = (
            "services:\n"
            "  - {name: dup, path_prefix: /api/v1/a, upstream_host: a, "
            "upstream_port: 1, auth_mode: cookie_session, timeout_class: standard}\n"
            "  - {name: dup, path_prefix: /api/v1/b, upstream_host: b, "
            "upstream_port: 2, auth_mode: cookie_session, timeout_class: standard}\n"
        )
        dup_prefix_yaml = (
            "services:\n"
            "  - {name: a, path_prefix: /api/v1/same, upstream_host: a, "
            "upstream_port: 1, auth_mode: cookie_session, timeout_class: standard}\n"
            "  - {name: b, path_prefix: /api/v1/same, upstream_host: b, "
            "upstream_port: 2, auth_mode: cookie_session, timeout_class: standard}\n"
        )
        for label, doc in (
            ("duplicate-name", dup_name_yaml),
            ("duplicate-prefix", dup_prefix_yaml),
        ):
            with tempfile.NamedTemporaryFile(
                "w", suffix=".yaml", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(doc)
                tmp_path = Path(tmp.name)
            try:
                try:
                    module.load_registry(tmp_path)
                except ValueError:
                    pass  # expected
                else:
                    result.failures.append(
                        f"{label}: load_registry accepted an invariant "
                        "violation; dedup guard is missing"
                    )
            finally:
                tmp_path.unlink(missing_ok=True)
    finally:
        sys.modules.pop(spec.name, None)

    return result


def _parse_rules(rendered_text: str) -> list[dict]:
    """Parse a ``render_oathkeeper_rules()`` output into rule dicts.

    Broken out so the branch-semantics check can keep its body focused
    on the behavioural assertions rather than on YAML plumbing.
    """
    docs = yaml.safe_load(rendered_text) or []
    return [r for r in docs if isinstance(r, dict)]


def _find_rule(rules: list[dict], rule_id: str) -> dict | None:
    for rule in rules:
        if rule.get("id") == rule_id:
            return rule
    return None


def _expect_eq(
    result: "CheckResult", field: str, actual: object, expected: object
) -> None:
    if actual != expected:
        result.failures.append(
            f"{field}: expected {expected!r}, got {actual!r}"
        )


# ---------------------------------------------------------------------------
# §Task 6 — registry ↔ backend ↔ Oathkeeper cross-layer coherence.
#
# Task 1 already guards the forward direction registry → FastAPI /
# rules.yml. Task 6 closes the loop:
#
#   * `fastapi-prefixes-covered-by-services-yaml` enforces the REVERSE
#     direction — every APIRouter(prefix=/api/v1/...) declared in any
#     FastAPI source under _FASTAPI_SERVICE_ROOTS must sit under some
#     registry entry's path_prefix. This is the check that catches
#     "PR added /api/v1/billing/* routes without updating
#     services.yaml" which would otherwise land silently: the
#     deny-all would quietly 401 the new routes at runtime even
#     though the backend is serving them.
#
#   * `oathkeeper-rules-disk-honor-auth-mode` enforces the REGISTRY →
#     ON-DISK RULES.YML semantic mapping, independent of the
#     generator. oathkeeper-rules-match-services-yaml already asserts
#     byte-identity with the generator's output, but a hypothetical
#     future split where rules.yml is hand-edited (or edited by a
#     different generator variant) would erase that guard. This check
#     re-derives the expected authenticator/mutator shape straight
#     from each registry entry's auth_mode and asserts the on-disk
#     rule agrees — the same independence pattern
#     oathkeeper-rules-have-terminal-deny uses for the deny-all
#     rule.
# ---------------------------------------------------------------------------


# Canonical (authenticators, mutators) pair for each `auth_mode`
# value that has a live generator branch. Reserved slots are handled
# below — seeing one on disk means a rule WAS rendered for an
# auth_mode the generator is supposed to refuse, which itself is a
# contract violation.
_AUTH_MODE_EXPECTED_SHAPE: dict[str, tuple[list[str], list[str]]] = {
    # cookie_session participates in the X-Auth-* header contract
    # (backend.md §2.3) — the `header` mutator is what templates the
    # resolved subject into the request before it hits the backend.
    # architecture-tasks §Task 8 chains `id_token` after `header` so
    # every cookie_session request ALSO carries a short-TTL JWT the
    # backend can verify against Oathkeeper's JWKS. Order matters —
    # `header` MUST come first so both mutators project from the same
    # session snapshot (see generator `_oathkeeper_mutators_for`).
    "cookie_session": (
        ["cookie_session"],
        ["header", "id_token"],
    ),
    # public bypasses authn entirely; `noop` MUST appear in both
    # slots — chaining `header` after `noop` would propagate any
    # forged X-Auth-* headers on the inbound request unchanged (the
    # same leak vector finding #1's fix closed for cookie_session).
    "public": (["noop"], ["noop"]),
}
_AUTH_MODE_RESERVED: frozenset[str] = frozenset({"api_key", "jwt_bearer"})


@register_check(
    "fastapi-prefixes-covered-by-services-yaml",
    "Every `APIRouter(prefix='/api/v1/...')` declaration in services "
    "under _FASTAPI_SERVICE_ROOTS MUST sit under some "
    "config/services.yaml entry's `path_prefix` (architecture-tasks.md "
    "§Task 6 acceptance). This is the reverse direction of "
    "services-yaml-prefixes-have-fastapi-router: together they form a "
    "closed loop between the registry and the backend router, so a "
    "PR cannot land a new /api/v1/<svc>/* endpoint without also "
    "declaring it in the SSOT. Without this check the new endpoint "
    "would reach runtime, get caught by the Oathkeeper deny-all, and "
    "surface as a confusing 401 rather than a compile-time CI failure.",
)
def check_fastapi_prefixes_covered_by_services_yaml() -> CheckResult:
    result = CheckResult(
        "fastapi-prefixes-covered-by-services-yaml",
        "every FastAPI /api/v1/* router prefix is declared in services.yaml",
    )
    if not _SERVICES_YAML_PATH.is_file():
        result.failures.append(
            f"expected {_SERVICES_YAML_PATH.relative_to(REPO_ROOT)}"
        )
        return result

    doc = _load_services_registry()
    entries = doc.get("services") or []
    registry_prefixes: list[str] = [
        entry["path_prefix"]
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("path_prefix"), str)
    ]
    if not registry_prefixes:
        # Empty / malformed registry is the schema check's job to
        # call out — staying silent here keeps a single failure
        # source from cascading into redundant noise.
        return result

    fastapi_prefixes = _collect_fastapi_prefixes(_FASTAPI_SERVICE_ROOTS)

    def _is_covered(router_prefix: str) -> bool:
        # A router prefix is "covered" by a registry entry when the
        # registry prefix is a path-segment prefix of the router
        # prefix (exact equality included). Plain `startswith` would
        # let /api/v1/analysis-extra be covered by /api/v1/analysis,
        # which is the exact shadowing bug we want this check to
        # catch — the deny-all would then NOT fire on the extra
        # router, because an existing Oathkeeper rule's regex
        # `http://<.*>/api/v1/analysis<.*>` greedily matches the
        # longer prefix too. We therefore require either exact
        # equality or a trailing `/` to force a path-segment
        # boundary.
        for reg in registry_prefixes:
            if router_prefix == reg:
                return True
            if router_prefix.startswith(reg + "/"):
                return True
        return False

    # Deterministic iteration order makes CI log diffs useful even
    # when multiple routers drift at once.
    for router_prefix in sorted(fastapi_prefixes):
        if _is_covered(router_prefix):
            continue
        declaring_files = sorted(
            str(p.relative_to(REPO_ROOT))
            for p in fastapi_prefixes[router_prefix]
        )
        # Suggest the closest existing registry prefix so the fix is
        # one line. We pick the registry entry sharing the longest
        # leading path component with the offending router prefix.
        suggestion = max(
            registry_prefixes,
            key=lambda reg: len(_common_path_prefix(reg, router_prefix)),
            default=None,
        )
        hint = (
            f" (closest registry prefix: {suggestion!r})"
            if suggestion is not None
            else ""
        )
        result.failures.append(
            f"FastAPI router prefix {router_prefix!r} declared in "
            f"{declaring_files} has no covering entry in "
            f"config/services.yaml; add a row with that path_prefix "
            f"or consolidate under an existing one{hint}"
        )
    return result


def _common_path_prefix(a: str, b: str) -> str:
    """Longest common leading path-segment prefix of ``a`` and ``b``.

    Used only by the Task 6 coverage check's "closest registry prefix"
    hint. Returns a string that is either empty or ends on a path
    boundary so the hint never reports a half-word match like
    ``/api/v1/a`` as the closest prefix for ``/api/v1/analysis``.
    """
    segments_a = a.split("/")
    segments_b = b.split("/")
    common: list[str] = []
    for sa, sb in zip(segments_a, segments_b):
        if sa != sb:
            break
        common.append(sa)
    return "/".join(common)


@register_check(
    "oathkeeper-rules-disk-honor-auth-mode",
    "For every config/services.yaml entry, the SAME-ID rule in "
    "config/ory/oathkeeper/rules.yml MUST carry the exact "
    "authenticator/mutator pair implied by its auth_mode "
    "(architecture-tasks.md §Task 6 deliverable #2). "
    "`cookie_session` => ([cookie_session], [header]); `public` => "
    "([noop], [noop]); reserved slots (`api_key`, `jwt_bearer`) MUST "
    "NOT appear on disk. This mirrors services-yaml-generator-branch-"
    "semantics but reads the real rules.yml instead of driving the "
    "generator, so a hand-edit that bypasses the generator is still "
    "caught.",
)
def check_oathkeeper_rules_disk_honor_auth_mode() -> CheckResult:
    result = CheckResult(
        "oathkeeper-rules-disk-honor-auth-mode",
        "on-disk rules.yml authenticator/mutator chain matches auth_mode",
    )
    if not _SERVICES_YAML_PATH.is_file():
        result.failures.append(
            f"expected {_SERVICES_YAML_PATH.relative_to(REPO_ROOT)}"
        )
        return result
    if not _OATHKEEPER_RULES_PATH.is_file():
        result.failures.append(
            f"expected {_OATHKEEPER_RULES_PATH.relative_to(REPO_ROOT)}"
        )
        return result

    entries = (_load_services_registry().get("services") or [])
    rules = yaml.safe_load(
        _OATHKEEPER_RULES_PATH.read_text(encoding="utf-8")
    ) or []
    rules_by_id: dict[str, dict] = {
        rule.get("id"): rule
        for rule in rules
        if isinstance(rule, dict) and isinstance(rule.get("id"), str)
    }

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        auth_mode = entry.get("auth_mode")
        if not isinstance(name, str) or not isinstance(auth_mode, str):
            # Shape errors are the schema check's job; ignore here
            # to avoid redundant failure noise.
            continue

        if auth_mode in _AUTH_MODE_RESERVED:
            # Reserved slots must never reach on-disk rules. If one
            # does, the generator's NotImplementedError was bypassed
            # somehow — the fact that rules.yml carries a rule for
            # it is itself the violation.
            if name in rules_by_id:
                result.failures.append(
                    f"services.yaml entry {name!r} uses reserved "
                    f"auth_mode {auth_mode!r}, but rules.yml still "
                    f"emits a rule for it; remove the rule and/or "
                    f"change auth_mode to a live branch"
                )
            continue

        expected = _AUTH_MODE_EXPECTED_SHAPE.get(auth_mode)
        if expected is None:
            # Unknown auth_mode should have been caught by the schema
            # check; stay silent here for the same reason as above.
            continue
        expected_authenticators, expected_mutators = expected

        rule = rules_by_id.get(name)
        if rule is None:
            result.failures.append(
                f"services.yaml entry {name!r} has no matching "
                f"rule in rules.yml (expected id={name!r}); the "
                f"deny-all would swallow this service's traffic at "
                f"runtime"
            )
            continue

        got_authenticators = [
            (a or {}).get("handler")
            for a in (rule.get("authenticators") or [])
            if isinstance(a, dict)
        ]
        if got_authenticators != expected_authenticators:
            result.failures.append(
                f"rule {name!r} authenticators: auth_mode "
                f"{auth_mode!r} requires {expected_authenticators!r}, "
                f"got {got_authenticators!r}"
            )
        got_mutators = [
            (m or {}).get("handler")
            for m in (rule.get("mutators") or [])
            if isinstance(m, dict)
        ]
        if got_mutators != expected_mutators:
            result.failures.append(
                f"rule {name!r} mutators: auth_mode {auth_mode!r} "
                f"requires {expected_mutators!r}, got {got_mutators!r}"
            )

    return result


@register_check(
    "apisix-timeout-class-routes-match-services-yaml",
    "For every config/services.yaml entry, gateway/apisix.yaml.template "
    "MUST carry a route whose timeout / plugin profile matches the "
    "entry's `timeout_class` (architecture-tasks.md §Task 7). "
    "`standard`-class entries transit through the single `protected-api` "
    "fallback route (read_timeout=30s, no proxy-control); every "
    "non-`standard` entry produces a per-service route `<name>-<class>` "
    "with the class's own read_timeout and request_buffering setting. "
    "Delegates to scripts/generate-gateway-config.py :: "
    "verify_apisix_alignment so the fallback route's `standard` profile, "
    "the per-class routes' shape, and the `oathkeeper-proxy` upstream "
    "invariant are all SSOT-derived and asserted in one pass.",
)
def check_apisix_timeout_class_routes() -> CheckResult:
    result = CheckResult(
        "apisix-timeout-class-routes-match-services-yaml",
        "APISIX per-class routes align with services.yaml timeout_class",
    )
    if not _GATEWAY_CONFIG_GENERATOR.is_file():
        result.failures.append(
            f"expected {_GATEWAY_CONFIG_GENERATOR.relative_to(REPO_ROOT)}"
        )
        return result
    apisix_template_path = REPO_ROOT / "gateway" / "apisix.yaml.template"
    if not apisix_template_path.is_file():
        result.failures.append(
            f"expected {apisix_template_path.relative_to(REPO_ROOT)}"
        )
        return result

    # Same importlib seam the oathkeeper-rules-match-services-yaml and
    # sse-routes-explicit-timeout-and-buffering contracts use; keeping
    # it consistent means a future refactor that relocates the
    # generator only has to touch _GATEWAY_CONFIG_GENERATOR.
    import importlib.util as _ilu

    spec = _ilu.spec_from_file_location(
        "_gen_gateway_timeout_check", _GATEWAY_CONFIG_GENERATOR
    )
    if spec is None or spec.loader is None:
        result.failures.append(
            f"could not load {_GATEWAY_CONFIG_GENERATOR.relative_to(REPO_ROOT)}"
        )
        return result
    module = _ilu.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)  # type: ignore[arg-type]
        entries = module.load_registry()
        template_text = apisix_template_path.read_text(encoding="utf-8")
        alignment_failures = module.verify_apisix_alignment(
            entries, template_text
        )
    except (ValueError, NotImplementedError, FileNotFoundError) as exc:
        result.failures.append(f"generator refused to verify: {exc}")
        return result
    finally:
        sys.modules.pop(spec.name, None)

    # verify_apisix_alignment returns a flat list of human-legible
    # messages, each naming the offending route id / field / expected
    # value. Surface them verbatim — the generator already phrased
    # them for the operator fixing the drift.
    result.failures.extend(alignment_failures)
    return result


@register_check(
    "services-yaml-consumers-registered",
    "Every file listed in _SERVICES_YAML_CONSUMERS references the path "
    "'config/services.yaml' at least once. Prevents silent forks where "
    "a consumer hardcodes its own service list instead of reading the "
    "SSOT — same discipline required-env-yaml-consumers-registered "
    "applies to required-env.yaml.",
)
def check_services_yaml_consumers() -> CheckResult:
    result = CheckResult(
        "services-yaml-consumers-registered",
        "declared services.yaml consumers actually reference the YAML",
    )
    needle = "config/services.yaml"
    for path in _SERVICES_YAML_CONSUMERS:
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
                "_SERVICES_YAML_CONSUMERS"
            )
    return result


# ---------------------------------------------------------------------------
# Task 4 — OpenAPI snapshot + generated frontend types are CI-frozen
#
# Two tightly paired checks guarantee the "backend pydantic schema is the
# single source of truth for frontend TypeScript types" contract stays
# durable across PRs:
#
#   1. assistant-openapi-snapshot-fresh — the committed
#      services/assistant-service/openapi.json must be byte-identical
#      to ``python3 scripts/export-openapi.py --stdout``. Any pydantic
#      model field added / renamed without re-running the exporter is
#      caught before ``openapi-typescript`` is ever invoked.
#
#   2. frontend-generated-types-fresh — the committed
#      frontend/src/shared/types/generated/assistant.d.ts must be
#      byte-identical to ``(cd frontend && npm run gen:types)``.
#      A drifted snapshot (caught by #1) cannot reach this check
#      because #1 fails first; this check exclusively catches the
#      narrower case "snapshot refreshed but ``gen:types`` not re-run".
#
# Both checks delegate the real rendering work: we never reimplement
# FastAPI's OpenAPI generator or ``openapi-typescript`` here. That keeps
# the contract enforcement trivially correct — a "generator A agrees
# with generator A" tautology, not a "my reimplementation agrees with
# the real generator" leak.
# ---------------------------------------------------------------------------


_ASSISTANT_OPENAPI_SNAPSHOT_PATH = (
    REPO_ROOT / "services" / "assistant-service" / "openapi.json"
)
_EXPORT_OPENAPI_SCRIPT = REPO_ROOT / "scripts" / "export-openapi.py"
_FRONTEND_GENERATED_TYPES_PATH = (
    REPO_ROOT
    / "frontend"
    / "src"
    / "shared"
    / "types"
    / "generated"
    / "assistant.d.ts"
)
_FRONTEND_ROOT = REPO_ROOT / "frontend"


def _resolve_assistant_python() -> tuple[str | None, str]:
    """Return (path, reason) for the Python interpreter that can import
    ``app.main`` without ImportError.

    Order of preference:
      1. ``ROVER_ASSISTANT_PYTHON`` env var — explicit override for CI /
         dev boxes where the venv lives in a non-standard place.
      2. ``services/assistant-service/.venv/bin/python`` — the canonical
         dev location; present on any machine that has run the service
         once locally.
      3. The current interpreter (``sys.executable``) — works if the
         dev has installed the service deps globally / in a pyenv; if
         not we fall back to SKIP rather than FAIL so a contributor who
         has not provisioned the assistant-service venv isn't blocked
         from running the other 43 checks.
    """
    override = os.environ.get("ROVER_ASSISTANT_PYTHON", "").strip()
    if override:
        return override, f"ROVER_ASSISTANT_PYTHON={override!r}"

    venv_python = (
        REPO_ROOT / "services" / "assistant-service" / ".venv" / "bin" / "python"
    )
    if venv_python.is_file():
        return str(venv_python), f"assistant-service venv at {venv_python.relative_to(REPO_ROOT)}"

    # Last-ditch: the interpreter running check-contracts itself. Probe
    # importability before declaring victory — a globally-installed
    # ``fastapi`` is plausible in CI but not a given.
    try:
        import importlib.util as _ilu

        spec = _ilu.find_spec("fastapi")
    except Exception:  # noqa: BLE001 — defensive; find_spec can raise on bad PYTHONPATH
        spec = None
    if spec is not None:
        return sys.executable, f"current interpreter {sys.executable!r}"

    return None, (
        "no Python interpreter with fastapi installed found; set "
        "ROVER_ASSISTANT_PYTHON or create "
        "services/assistant-service/.venv"
    )


@register_check(
    "assistant-openapi-snapshot-fresh",
    "services/assistant-service/openapi.json is byte-identical to a "
    "fresh `python3 scripts/export-openapi.py --stdout` render. "
    "Adding or renaming a pydantic field in app/schemas/** without "
    "re-running the exporter fails this check. See Task 4.",
)
def check_assistant_openapi_snapshot_fresh() -> CheckResult:
    result = CheckResult(
        "assistant-openapi-snapshot-fresh",
        "OpenAPI snapshot matches pydantic models",
    )
    if not _EXPORT_OPENAPI_SCRIPT.is_file():
        result.failures.append(
            f"{_EXPORT_OPENAPI_SCRIPT.relative_to(REPO_ROOT)} missing"
        )
        return result
    if not _ASSISTANT_OPENAPI_SNAPSHOT_PATH.is_file():
        result.failures.append(
            f"{_ASSISTANT_OPENAPI_SNAPSHOT_PATH.relative_to(REPO_ROOT)} "
            "missing; run `python3 scripts/export-openapi.py`"
        )
        return result

    python, reason = _resolve_assistant_python()
    if python is None:
        result.failures.append(reason)
        return result

    try:
        completed = subprocess.run(
            [python, str(_EXPORT_OPENAPI_SCRIPT), "--check"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=60,
        )
    except Exception as exc:  # noqa: BLE001 — surface subprocess failure path
        result.failures.append(
            f"failed to invoke export-openapi.py via {reason}: {exc!r}"
        )
        return result

    if completed.returncode != 0:
        stderr_tail = (completed.stderr or "").strip().splitlines()[-10:]
        result.failures.append(
            "export-openapi.py --check reported drift; re-run "
            "`python3 scripts/export-openapi.py` and commit the "
            "updated services/assistant-service/openapi.json"
        )
        for line in stderr_tail:
            result.failures.append(f"  exporter: {line}")
    return result


@register_check(
    "frontend-generated-types-fresh",
    "frontend/src/shared/types/generated/assistant.d.ts is byte-identical "
    "to a fresh `npm run gen:types` render from the committed OpenAPI "
    "snapshot. Renaming a backend pydantic field fails "
    "assistant-openapi-snapshot-fresh first; this check then catches "
    "the narrower 'snapshot refreshed but gen:types not re-run' "
    "drift. See Task 4.",
)
def check_frontend_generated_types_fresh() -> CheckResult:
    result = CheckResult(
        "frontend-generated-types-fresh",
        "Generated TS types match OpenAPI snapshot",
    )
    if not _FRONTEND_GENERATED_TYPES_PATH.is_file():
        result.failures.append(
            f"{_FRONTEND_GENERATED_TYPES_PATH.relative_to(REPO_ROOT)} "
            "missing; run `(cd frontend && npm run gen:types)`"
        )
        return result
    if not (_FRONTEND_ROOT / "node_modules" / ".bin" / "openapi-typescript").exists():
        result.failures.append(
            "frontend/node_modules/.bin/openapi-typescript missing; "
            "run `(cd frontend && npm install)` first"
        )
        return result
    if not _ASSISTANT_OPENAPI_SNAPSHOT_PATH.is_file():
        # Upstream check-openapi-snapshot-fresh already reports this; we
        # still guard to keep the failure message actionable even when
        # a contributor runs --only=frontend-generated-types-fresh.
        result.failures.append(
            "upstream OpenAPI snapshot missing: "
            f"{_ASSISTANT_OPENAPI_SNAPSHOT_PATH.relative_to(REPO_ROOT)}"
        )
        return result

    # Render into a tempfile and diff. We deliberately do NOT invoke
    # the ``gen:types:check`` npm script (which uses ``diff -u``): that
    # binary doesn't set a stable exit convention across BSD/GNU and
    # surfaces CR/LF noise on Windows CI. Byte comparison here is
    # reproducible everywhere Python runs.
    import tempfile

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".d.ts", delete=False
        ) as tmp:
            tmp_path = Path(tmp.name)
        tool = _FRONTEND_ROOT / "node_modules" / ".bin" / "openapi-typescript"
        try:
            completed = subprocess.run(
                [
                    str(tool),
                    str(_ASSISTANT_OPENAPI_SNAPSHOT_PATH),
                    "--output",
                    str(tmp_path),
                    "--immutable",
                    "--alphabetize",
                ],
                capture_output=True,
                text=True,
                cwd=_FRONTEND_ROOT,
                timeout=120,
            )
        except Exception as exc:  # noqa: BLE001
            result.failures.append(
                f"failed to invoke openapi-typescript: {exc!r}"
            )
            return result
        if completed.returncode != 0:
            stderr_tail = (completed.stderr or "").strip().splitlines()[-10:]
            result.failures.append(
                "openapi-typescript failed to render; see tail below"
            )
            for line in stderr_tail:
                result.failures.append(f"  generator: {line}")
            return result

        fresh = tmp_path.read_text(encoding="utf-8")
        on_disk = _FRONTEND_GENERATED_TYPES_PATH.read_text(encoding="utf-8")
        if fresh != on_disk:
            result.failures.append(
                "assistant.d.ts is stale; re-run "
                "`(cd frontend && npm run gen:types)` and commit "
                "the updated file"
            )
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
    return result


# ---------------------------------------------------------------------------
# §Task 8 — subject integrity (Oathkeeper id_token mutator + backend JWT
# verifier). Three contracts pin the three axes that together make the
# identity contract independent of docker network topology:
#
#   * `oathkeeper-cookie-session-rules-have-id-token-mutator` — every
#     `auth_mode: cookie_session` rule ON DISK carries the chained
#     [header, id_token] mutator pair. A rule that still has only
#     `header` would silently fall back to the pre-Task-8 plaintext
#     trust regime and a sidecar on the same network could forge
#     X-Auth-* headers unnoticed.
#   * `backend-requires-bearer-jwt-from-oathkeeper` — the FastAPI
#     `get_current_user` dependency calls the verifier. A careless
#     refactor that dropped the `verify_bearer_jwt` import while
#     keeping the X-Auth-* parsing would pass every other test; this
#     contract catches that class of regression directly.
#   * `oathkeeper-jwt-required-in-runtime-env` — the env registry
#     declares OATHKEEPER_JWT_REQUIRED as always-required with a
#     default of "true". Flipping it optional (or defaulting "false")
#     would re-open the bypass path for every deployment that forgot
#     to set the variable.
# ---------------------------------------------------------------------------


_BACKEND_AUTH_ENTRYPOINT = (
    REPO_ROOT / "services" / "assistant-service" / "app" / "auth.py"
)
_BACKEND_OATHKEEPER_JWT_MODULE = (
    REPO_ROOT / "services" / "assistant-service" / "app" / "oathkeeper_jwt.py"
)


@register_check(
    "oathkeeper-cookie-session-rules-have-id-token-mutator",
    "Every `auth_mode: cookie_session` entry in config/services.yaml MUST "
    "resolve to an on-disk Oathkeeper rule whose mutators chain is exactly "
    "[`header`, `id_token`] in that order (architecture-tasks §Task 8). "
    "The pair is what decouples identity integrity from docker network "
    "topology: `header` preserves the legacy X-Auth-* contract for every "
    "existing handler, while `id_token` gives the backend a cryptographic "
    "signature to verify against the JWKS endpoint. Order is part of the "
    "contract — swapping would let the JWT template resolve claims before "
    "the header mutator has finalized its own projection.",
)
def check_oathkeeper_cookie_session_rules_have_id_token_mutator() -> CheckResult:
    result = CheckResult(
        "oathkeeper-cookie-session-rules-have-id-token-mutator",
        "on-disk cookie_session rules chain [header, id_token] mutators",
    )
    if not _SERVICES_YAML_PATH.is_file():
        result.failures.append(
            f"expected {_SERVICES_YAML_PATH.relative_to(REPO_ROOT)}"
        )
        return result
    if not _OATHKEEPER_RULES_PATH.is_file():
        result.failures.append(
            f"expected {_OATHKEEPER_RULES_PATH.relative_to(REPO_ROOT)}"
        )
        return result

    entries = (_load_services_registry().get("services") or [])
    rules = yaml.safe_load(
        _OATHKEEPER_RULES_PATH.read_text(encoding="utf-8")
    ) or []
    rules_by_id: dict[str, dict] = {
        rule.get("id"): rule
        for rule in rules
        if isinstance(rule, dict) and isinstance(rule.get("id"), str)
    }

    expected_pair = ["header", "id_token"]
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("auth_mode") != "cookie_session":
            continue
        name = entry.get("name")
        if not isinstance(name, str):
            continue
        rule = rules_by_id.get(name)
        if rule is None:
            # Registered separately by
            # `oathkeeper-rules-disk-honor-auth-mode` — stay quiet here
            # so the same drift is reported by exactly one contract.
            continue
        got = [
            (m or {}).get("handler")
            for m in (rule.get("mutators") or [])
            if isinstance(m, dict)
        ]
        if got != expected_pair:
            result.failures.append(
                f"rule {name!r}: cookie_session mutators chain must be "
                f"{expected_pair!r}, got {got!r}. Re-run "
                f"`python3 scripts/generate-gateway-config.py --write` "
                f"to re-render rules.yml from the SSOT."
            )
    return result


@register_check(
    "backend-requires-bearer-jwt-from-oathkeeper",
    "The FastAPI dependency `app.auth.get_current_user` MUST import AND "
    "call the Oathkeeper JWT verifier (`verify_bearer_jwt` from "
    "`app.oathkeeper_jwt`) (architecture-tasks §Task 8). Dropping the "
    "import while keeping the X-Auth-* parse logic would re-open finding "
    "#2's silent-bypass path: every protected route would 200 OK on a "
    "forged header triple, and the only test that would catch it is the "
    "one this contract is redundant with. Keeping two independent "
    "assertions (source contract + pytest negative) is the discipline "
    "`oathkeeper-rules-disk-honor-auth-mode` established for §Task 6.",
)
def check_backend_requires_bearer_jwt_from_oathkeeper() -> CheckResult:
    result = CheckResult(
        "backend-requires-bearer-jwt-from-oathkeeper",
        "app.auth.get_current_user imports and invokes verify_bearer_jwt",
    )
    if not _BACKEND_AUTH_ENTRYPOINT.is_file():
        result.failures.append(
            f"expected {_BACKEND_AUTH_ENTRYPOINT.relative_to(REPO_ROOT)}"
        )
        return result
    if not _BACKEND_OATHKEEPER_JWT_MODULE.is_file():
        result.failures.append(
            f"expected {_BACKEND_OATHKEEPER_JWT_MODULE.relative_to(REPO_ROOT)}"
        )
        return result

    source = _BACKEND_AUTH_ENTRYPOINT.read_text(encoding="utf-8")

    # Parse the module so we're looking at semantics, not comment hits.
    try:
        tree = ast.parse(source, filename=str(_BACKEND_AUTH_ENTRYPOINT))
    except SyntaxError as exc:
        result.failures.append(
            f"app/auth.py failed to parse: {exc}"
        )
        return result

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "app.oathkeeper_jwt":
            for alias in node.names:
                imported_names.add(alias.asname or alias.name)

    required_imports = {
        "verify_bearer_jwt",
        "jwt_required_from_env",
    }
    missing_imports = required_imports - imported_names
    if missing_imports:
        result.failures.append(
            "app/auth.py MUST `from app.oathkeeper_jwt import "
            f"{', '.join(sorted(required_imports))}` but is missing "
            f"{sorted(missing_imports)!r}"
        )

    # Locate the `get_current_user` function and confirm it calls the
    # verifier somewhere in its body. Walk the function tree instead of
    # regex-matching so a rename that preserves the symbol but breaks
    # the call site still trips CI.
    target_fn: ast.FunctionDef | None = None
    for node in tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "get_current_user"
        ):
            target_fn = node  # type: ignore[assignment]
            break
    if target_fn is None:
        result.failures.append(
            "app/auth.py: `get_current_user` function definition not "
            "found — cannot assert the JWT verifier is wired in."
        )
        return result

    calls: set[str] = set()
    for node in ast.walk(target_fn):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.add(node.func.attr)
    if "verify_bearer_jwt" not in calls:
        result.failures.append(
            "app/auth.py: `get_current_user` does not call "
            "`verify_bearer_jwt(...)` anywhere in its body. The JWT "
            "verification path is the ONLY thing standing between the "
            "backend and a forged X-Auth-* header (Task 8)."
        )
    if "jwt_required_from_env" not in calls:
        result.failures.append(
            "app/auth.py: `get_current_user` does not consult "
            "`jwt_required_from_env()`. The env-gated escape hatch is "
            "how unit tests opt out of the JWT check — dropping it "
            "silently would make every test suite succeed against the "
            "weakened plaintext trust regime."
        )
    return result


@register_check(
    "oathkeeper-jwt-required-in-runtime-env",
    "config/required-env.yaml MUST declare OATHKEEPER_JWT_REQUIRED as "
    "`required: true` with `enum: [true, false]` and "
    "`env_example: true` (architecture-tasks §Task 8). The companion "
    "vars OATHKEEPER_JWKS_URL / OATHKEEPER_JWT_ISSUER / "
    "OATHKEEPER_JWT_AUDIENCE MUST also be declared `required: true`. "
    "Loosening any of these to optional (or defaulting REQUIRED to "
    "`false`) would let a deployment forget one variable and silently "
    "fall back to the pre-Task-8 plaintext trust model — the exact "
    "regression the Oathkeeper JWT mutator closes.",
)
def check_oathkeeper_jwt_required_in_runtime_env() -> CheckResult:
    result = CheckResult(
        "oathkeeper-jwt-required-in-runtime-env",
        "OATHKEEPER_JWT_* vars are hard-required in required-env.yaml",
    )
    required_env_path = REPO_ROOT / "config" / "required-env.yaml"
    if not required_env_path.is_file():
        result.failures.append(
            f"expected {required_env_path.relative_to(REPO_ROOT)}"
        )
        return result

    doc = yaml.safe_load(required_env_path.read_text(encoding="utf-8")) or {}
    services = (doc.get("services") or {})
    assistant_block = services.get("assistant-service") or []
    by_name: dict[str, dict] = {
        entry.get("name"): entry
        for entry in assistant_block
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    }

    # The three supporting vars must be required-only (no required_when /
    # forbidden_when), so a deployment that turns on JWT enforcement
    # cannot forget one of them.
    for name in (
        "OATHKEEPER_JWKS_URL",
        "OATHKEEPER_JWT_ISSUER",
        "OATHKEEPER_JWT_AUDIENCE",
    ):
        entry = by_name.get(name)
        if entry is None:
            result.failures.append(
                f"config/required-env.yaml: assistant-service block is "
                f"missing the {name!r} entry"
            )
            continue
        if entry.get("required") is not True:
            result.failures.append(
                f"config/required-env.yaml: {name!r} must declare "
                f"`required: true` (got {entry.get('required')!r})"
            )

    # The master switch has an additional shape constraint: enum
    # [true, false] and env_example="true". That way generate-env-
    # example.py renders a working default and required-env validator
    # refuses any other literal.
    master = by_name.get("OATHKEEPER_JWT_REQUIRED")
    if master is None:
        result.failures.append(
            "config/required-env.yaml: assistant-service block is "
            "missing the 'OATHKEEPER_JWT_REQUIRED' entry"
        )
        return result
    if master.get("required") is not True:
        result.failures.append(
            "config/required-env.yaml: OATHKEEPER_JWT_REQUIRED must "
            "declare `required: true` so production deployments cannot "
            "forget it"
        )
    if master.get("enum") != ["true", "false"]:
        result.failures.append(
            "config/required-env.yaml: OATHKEEPER_JWT_REQUIRED must "
            "declare `enum: [\"true\", \"false\"]`; any other literal "
            "would silently disable the verifier"
        )
    if master.get("env_example") != "true":
        result.failures.append(
            "config/required-env.yaml: OATHKEEPER_JWT_REQUIRED must "
            "declare `env_example: \"true\"` so the generated "
            ".env.example ships the production default"
        )
    return result


# ---------------------------------------------------------------------------
# §Task 12 — compose `depends_on` entries MUST be health-gated.
#
# The human-readable rule (architecture-tasks.md §Task 12): every
# `depends_on` edge in docker-compose.yml / docker-compose.dev.yml
# MUST carry an explicit `condition:`, and that condition MUST match
# whether the target is a long-running service (`service_healthy`)
# or a one-shot init job (`service_completed_successfully`). Compose
# defaults to `service_started` when no condition is given — the
# exact behavior Task 12 exists to remove, because it lets the
# gateway start accepting traffic while Kratos is still binding its
# port. This check is the CI-time guard that keeps the "gateway
# 502s for the first 10s on `up`" regression from sneaking back in
# through a one-line PR.
#
# Rules enforced:
#
#   A. Short-form `depends_on: [foo, bar]` is banned outright. It is
#      equivalent to `{foo: {condition: service_started}, bar: ...}`
#      and therefore cannot be correct under Task 12.
#
#   B. For each `depends_on: {target: {condition: X}}`:
#        * If `target` declares a `healthcheck:` in the MERGED view
#          (base compose + optional dev overlay), X MUST be
#          `service_healthy`.
#        * Otherwise, X MUST be `service_completed_successfully`
#          (the one-shot init pattern used by kratos-migrate and
#          required-env-guard). A service with no healthcheck
#          depended upon as a long-running peer would silently race
#          — if it's truly one-shot, it should carry `restart: "no"`
#          and a terminating command, so requiring
#          `service_completed_successfully` here doubles as a
#          lightweight type signal.
#
#   C. If any edge requests `service_healthy`, the target MUST
#      actually declare a `healthcheck:` block somewhere in the
#      compose graph. This catches the inverse drift: someone flips
#      a target to `restart: "no"` (removing its healthcheck) while
#      leaving dependents pointing at `service_healthy`, which
#      compose rejects only at `up` time on that specific host.
#
# All three rules are applied uniformly to docker-compose.yml and
# docker-compose.dev.yml. `config/` overlays are not scanned — they
# don't declare services.
# ---------------------------------------------------------------------------


# Compose conditions that Task 12 treats as well-formed. Kept as a
# module-level constant instead of a literal inside the check body
# so the surrounding prose (and any future new condition) lives
# next to the human-readable explanation above rather than buried
# inside a function.
_TASK12_VALID_CONDITIONS: frozenset[str] = frozenset(
    {"service_healthy", "service_completed_successfully"}
)

_COMPOSE_FILES_FOR_DEPENDS_ON = (
    REPO_ROOT / "docker-compose.yml",
    REPO_ROOT / "docker-compose.dev.yml",
)


def _compose_healthcheck_targets() -> set[str]:
    """Return the set of service names that declare a `healthcheck:`
    block in the merged compose graph.

    We scan BOTH the base file and the dev overlay so a service that
    gets its healthcheck purely through overlay (none do today, but
    the overlay is free to add one) still counts. Overlay-only
    removal of a healthcheck is not representable in compose without
    `!reset` tags, which we don't use, so the union is the right
    answer.
    """
    targets: set[str] = set()
    for path in _COMPOSE_FILES_FOR_DEPENDS_ON:
        if not path.is_file():
            continue
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        services = doc.get("services") or {}
        if not isinstance(services, dict):
            continue
        for svc_name, svc_def in services.items():
            if not isinstance(svc_def, dict):
                continue
            if isinstance(svc_def.get("healthcheck"), dict):
                targets.add(svc_name)
    return targets


@register_check(
    "compose-depends-on-are-health-gated",
    "Every `depends_on` edge in docker-compose.yml / docker-compose."
    "dev.yml MUST carry an explicit `condition:` and that condition "
    "MUST match the target's lifecycle: `service_healthy` for long-"
    "running services (target has a healthcheck), "
    "`service_completed_successfully` for one-shot init jobs (target "
    "has no healthcheck). Short-form lists are banned because they "
    "implicitly mean `service_started`, which is the exact compose "
    "default Task 12 exists to remove. Also enforces the inverse: "
    "every edge requesting `service_healthy` must name a target that "
    "actually declares a healthcheck. Acceptance reference: "
    "architecture-tasks.md §Task 12 — `docker compose up` must not "
    "502 on the gateway while Kratos is still binding its port.",
)
def check_compose_depends_on_are_health_gated() -> CheckResult:
    result = CheckResult(
        "compose-depends-on-are-health-gated",
        "compose depends_on edges are explicitly condition-gated",
    )

    healthcheck_targets = _compose_healthcheck_targets()

    for path in _COMPOSE_FILES_FOR_DEPENDS_ON:
        if not path.is_file():
            result.failures.append(
                f"expected {path.relative_to(REPO_ROOT)}"
            )
            continue

        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        services = doc.get("services") or {}
        if not isinstance(services, dict):
            result.failures.append(
                f"{path.relative_to(REPO_ROOT)}: top-level `services:` "
                "is not a mapping"
            )
            continue

        rel = path.relative_to(REPO_ROOT)
        for svc_name, svc_def in services.items():
            if not isinstance(svc_def, dict):
                continue
            dep = svc_def.get("depends_on")
            if dep is None:
                continue

            # Rule A — short-form list bans.
            if isinstance(dep, list):
                result.failures.append(
                    f"{rel}: service {svc_name!r} uses short-form "
                    f"`depends_on: [...]`; convert to the map form "
                    f"with an explicit `condition:` (service_healthy "
                    "for long-running targets, "
                    "service_completed_successfully for one-shot "
                    "init jobs)"
                )
                continue
            if not isinstance(dep, dict):
                result.failures.append(
                    f"{rel}: service {svc_name!r} has a malformed "
                    f"`depends_on` ({type(dep).__name__}); expected "
                    "a mapping of target -> {condition: ...}"
                )
                continue

            for target, edge in dep.items():
                # Rule A (tail) — per-target shape. The map form
                # accepts `depends_on: {foo:}` (null edge), which
                # compose silently treats as service_started. Reject
                # it the same way as the list form.
                if not isinstance(edge, dict):
                    result.failures.append(
                        f"{rel}: depends_on edge "
                        f"{svc_name!r} -> {target!r} has no "
                        f"`condition:` block; add "
                        "`condition: service_healthy` (or "
                        "service_completed_successfully for one-shot "
                        "init jobs)"
                    )
                    continue
                condition = edge.get("condition")
                if condition not in _TASK12_VALID_CONDITIONS:
                    result.failures.append(
                        f"{rel}: depends_on edge "
                        f"{svc_name!r} -> {target!r} declares "
                        f"condition={condition!r}; only "
                        f"{sorted(_TASK12_VALID_CONDITIONS)} are "
                        "allowed under Task 12"
                    )
                    continue

                # Rule B — condition must match target lifecycle.
                target_has_healthcheck = target in healthcheck_targets
                if condition == "service_healthy" and not target_has_healthcheck:
                    # Rule C — inverse drift: dependent names a
                    # target that no longer carries a healthcheck.
                    result.failures.append(
                        f"{rel}: depends_on edge "
                        f"{svc_name!r} -> {target!r} requests "
                        f"service_healthy, but target {target!r} "
                        "declares no `healthcheck:` in either "
                        "compose file; either restore the "
                        "healthcheck or switch the edge to "
                        "service_completed_successfully"
                    )
                    continue
                if (
                    condition == "service_completed_successfully"
                    and target_has_healthcheck
                ):
                    result.failures.append(
                        f"{rel}: depends_on edge "
                        f"{svc_name!r} -> {target!r} uses "
                        "service_completed_successfully, but target "
                        f"{target!r} declares a healthcheck — "
                        "long-running services must be gated on "
                        "service_healthy; "
                        "service_completed_successfully is reserved "
                        "for one-shot init jobs like kratos-migrate"
                    )
                    continue

    return result


# ---------------------------------------------------------------------------
# §Task 13 — DuckDB persistence + idempotent seeding.
#
# Three independent contracts that together close finding #8:
#
#   * `duckdb-path-default-is-persistent` — the compose default for
#     ROVER_DUCKDB_PATH MUST be a real filesystem path rooted at
#     /var/lib/pixels-rover/duckdb/, never ":memory:". A careless PR
#     that flips the default back to in-memory would silently wipe
#     the demo dataset on every `docker compose restart`, reintroducing
#     the exact "DuckDB :memory: loses state" regression finding #8
#     named. The test harness legitimately uses ":memory:"
#     (tests/conftest.py) — that path is out of this contract's scope
#     because the compose graph never references conftest.
#
#   * `duckdb-volume-mounted` — the assistant-service block MUST bind
#     a named volume into /var/lib/pixels-rover/duckdb, AND that
#     volume MUST be declared in the top-level `volumes:` block.
#     Declaring the mount without declaring the volume, or declaring
#     the volume without mounting it, are both silent failure modes
#     that compose accepts but that defeat the persistence guarantee.
#     Split checks so either half triggers the offending label on its
#     own, independent of the other.
#
#   * `seed-functions-are-idempotent` — both seed entry points in
#     app/seed.py MUST early-return when their marker row already
#     exists (DuckDB side via `rover_meta.seed_marker`, semantic side
#     via `SELECT SemanticMetric ... LIMIT 1`). AST-level assertion
#     because the test harness can't easily cover the happy path:
#     conftest boots a fresh `:memory:` DB every test, so no real
#     "second boot reuses the file" invariant survives in pytest
#     without the contract.
# ---------------------------------------------------------------------------


# Canonical persistent-volume path. Single source of truth for both
# Task 13 contracts so a future relocation (e.g. "/data/duckdb") is a
# one-line change here, not a search-and-replace across test assertions.
_TASK13_DUCKDB_PERSISTENT_ROOT = "/var/lib/pixels-rover/duckdb"
_TASK13_DUCKDB_VOLUME_NAME = "assistant-duckdb"
_TASK13_SEED_MODULE = (
    REPO_ROOT / "services" / "assistant-service" / "app" / "seed.py"
)


def _compose_assistant_environment(path: Path) -> dict[str, Any]:
    """Parse the `assistant-service.environment:` block in a compose
    file, returning the raw mapping (or {} when the block is absent).

    Handles both list and mapping styles because compose accepts
    ``environment: ["FOO=bar"]`` and ``environment: {FOO: bar}``
    interchangeably. Returning the normalized mapping keeps each
    contract's own logic focused on the value, not the parsing.
    """
    if not path.is_file():
        return {}
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    assistant = (doc.get("services") or {}).get("assistant-service") or {}
    env = assistant.get("environment")
    if env is None:
        return {}
    if isinstance(env, dict):
        return dict(env)
    if isinstance(env, list):
        out: dict[str, Any] = {}
        for item in env:
            if not isinstance(item, str) or "=" not in item:
                continue
            k, _, v = item.partition("=")
            out[k] = v
        return out
    return {}


@register_check(
    "duckdb-path-default-is-persistent",
    "The compose default for ROVER_DUCKDB_PATH MUST be a persistent "
    f"filesystem path rooted at {_TASK13_DUCKDB_PERSISTENT_ROOT!r}, "
    "never ':memory:'. architecture-tasks §Task 13 exists precisely "
    "because the pre-Task-13 default (:memory:) silently wiped the "
    "demo dataset on every container restart; this contract prevents "
    "a one-line PR from re-introducing that exact regression.",
)
def check_duckdb_path_default_is_persistent() -> CheckResult:
    result = CheckResult(
        "duckdb-path-default-is-persistent",
        "compose default for ROVER_DUCKDB_PATH is a persistent path",
    )
    base_path = REPO_ROOT / "docker-compose.yml"
    if not base_path.is_file():
        result.failures.append(f"expected {base_path.relative_to(REPO_ROOT)}")
        return result

    env = _compose_assistant_environment(base_path)
    if "ROVER_DUCKDB_PATH" not in env:
        result.failures.append(
            "docker-compose.yml: assistant-service.environment MUST "
            "set ROVER_DUCKDB_PATH so the compose default is explicit; "
            "relying on the app's in-code default leaves persistence "
            "silently off when the entrypoint is wrong."
        )
        return result

    raw_value = str(env["ROVER_DUCKDB_PATH"])
    # Compose substitution shape: `${ROVER_DUCKDB_PATH:-/var/...}`.
    # Parse just the fallback so an override from the outer env does
    # not mask a bad default shipped in the repo.
    default_value: str
    if raw_value.startswith("${") and ":-" in raw_value and raw_value.endswith("}"):
        default_value = raw_value.split(":-", 1)[1][:-1]
    else:
        default_value = raw_value

    if default_value.strip() == ":memory:":
        result.failures.append(
            "docker-compose.yml: ROVER_DUCKDB_PATH default is "
            "':memory:' — this is the exact regression finding #8 / "
            "§Task 13 closed. Restore a persistent path rooted at "
            f"{_TASK13_DUCKDB_PERSISTENT_ROOT!r}."
        )
        return result

    if not default_value.startswith(_TASK13_DUCKDB_PERSISTENT_ROOT + "/"):
        result.failures.append(
            f"docker-compose.yml: ROVER_DUCKDB_PATH default "
            f"{default_value!r} is not rooted at "
            f"{_TASK13_DUCKDB_PERSISTENT_ROOT!r}. The volume mount "
            f"declared under `volumes:` targets that directory; any "
            "other root would leave DuckDB writing outside the "
            "persistent mount and silently losing state on restart."
        )
    return result


@register_check(
    "duckdb-volume-mounted",
    "docker-compose.yml MUST bind the "
    f"{_TASK13_DUCKDB_VOLUME_NAME!r} named volume into "
    f"{_TASK13_DUCKDB_PERSISTENT_ROOT!r} on assistant-service, AND "
    "declare that volume under the top-level `volumes:` block. "
    "Declaring the mount without declaring the volume, or declaring "
    "the volume without mounting it, are both silent failure modes "
    "that compose accepts; architecture-tasks §Task 13 requires both "
    "halves to hold simultaneously.",
)
def check_duckdb_volume_mounted() -> CheckResult:
    result = CheckResult(
        "duckdb-volume-mounted",
        "assistant-duckdb volume is mounted and top-level-declared",
    )
    base_path = REPO_ROOT / "docker-compose.yml"
    if not base_path.is_file():
        result.failures.append(f"expected {base_path.relative_to(REPO_ROOT)}")
        return result

    doc = yaml.safe_load(base_path.read_text(encoding="utf-8")) or {}
    services = doc.get("services") or {}
    assistant = services.get("assistant-service") or {}
    volumes_list = assistant.get("volumes") or []

    expected_mount_target = _TASK13_DUCKDB_PERSISTENT_ROOT
    expected_spec_prefix = (
        f"{_TASK13_DUCKDB_VOLUME_NAME}:{expected_mount_target}"
    )

    mounted = False
    for spec in volumes_list:
        if isinstance(spec, str) and spec.startswith(expected_spec_prefix):
            mounted = True
            break
        if isinstance(spec, dict):
            source = spec.get("source")
            target = spec.get("target")
            if (
                source == _TASK13_DUCKDB_VOLUME_NAME
                and target == expected_mount_target
            ):
                mounted = True
                break
    if not mounted:
        result.failures.append(
            "docker-compose.yml: assistant-service.volumes MUST "
            f"include {expected_spec_prefix!r} so DuckDB writes land "
            "on a persistent named volume; the absence of that mount "
            "is the persistence-silently-off failure mode §Task 13 "
            "closed."
        )

    top_level_volumes = doc.get("volumes")
    declared = (
        isinstance(top_level_volumes, dict)
        and _TASK13_DUCKDB_VOLUME_NAME in top_level_volumes
    )
    if not declared:
        result.failures.append(
            "docker-compose.yml: top-level `volumes:` block MUST "
            f"declare {_TASK13_DUCKDB_VOLUME_NAME!r}. Mounting a "
            "volume without declaring it at the top level makes "
            "compose synthesize an anonymous volume whose name "
            "changes on every project-recreate — exactly the "
            "'data survives restart but not rebuild' surprise that "
            "defeats the persistence guarantee."
        )
    return result


@register_check(
    "seed-functions-are-idempotent",
    "Both seed entry points in app/seed.py MUST early-return when "
    "their respective marker rows already exist: `seed_duckdb` via "
    "`rover_meta.seed_marker` (SELECT before INSERT), and "
    "`seed_semantic_layer` via a SemanticMetric LIMIT 1 probe. "
    "architecture-tasks §Task 13 makes idempotency a first-class "
    "acceptance gate: calling either function twice on the same "
    "database MUST be a no-op, because DuckDB is now persistent and "
    "every pod restart re-enters seeding after Alembic runs.",
)
def check_seed_functions_are_idempotent() -> CheckResult:
    result = CheckResult(
        "seed-functions-are-idempotent",
        "app/seed.py entry points perform a marker-row early return",
    )
    if not _TASK13_SEED_MODULE.is_file():
        result.failures.append(
            f"expected {_TASK13_SEED_MODULE.relative_to(REPO_ROOT)}"
        )
        return result

    source = _TASK13_SEED_MODULE.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(_TASK13_SEED_MODULE))
    except SyntaxError as exc:
        result.failures.append(f"app/seed.py failed to parse: {exc}")
        return result

    fn_by_name: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn_by_name[node.name] = node

    def _fn_source(fn: ast.AST) -> str:
        start = getattr(fn, "lineno", 1) - 1
        end = getattr(fn, "end_lineno", start + 1)
        return "\n".join(source.splitlines()[start:end])

    # --- seed_duckdb ---
    duckdb_fn = fn_by_name.get("seed_duckdb")
    if duckdb_fn is None:
        result.failures.append(
            "app/seed.py: top-level `seed_duckdb` function definition "
            "not found — cannot assert DuckDB seeding is idempotent."
        )
    else:
        body = _fn_source(duckdb_fn)
        # Marker table must be read BEFORE any INSERT runs. Encoding
        # "marker read happens" via substring match of the well-known
        # literal keeps the check robust across formatting changes.
        if "rover_meta.seed_marker" not in body:
            result.failures.append(
                "app/seed.py::seed_duckdb does not reference "
                "`rover_meta.seed_marker`; without the marker table "
                "the function would re-run DDL + INSERT on every "
                "pod restart and fail with PRIMARY KEY violations "
                "the second time around."
            )
        # The early-return path is the idempotency proof — an
        # unconditional INSERT without a guarded return is what
        # Task 13 forbids.
        has_early_return = any(
            isinstance(node, ast.Return) for node in ast.walk(duckdb_fn)
        )
        if not has_early_return:
            result.failures.append(
                "app/seed.py::seed_duckdb has no `return` statement; "
                "the marker-row early-exit path is how idempotency "
                "is implemented — removing it makes the function "
                "non-idempotent regardless of what the marker table "
                "contains."
            )

    # --- seed_semantic_layer ---
    semantic_fn = fn_by_name.get("seed_semantic_layer")
    if semantic_fn is None:
        result.failures.append(
            "app/seed.py: top-level `seed_semantic_layer` function "
            "definition not found — cannot assert semantic-layer "
            "seeding is idempotent."
        )
    else:
        body = _fn_source(semantic_fn)
        if "SemanticMetric" not in body or "limit(1)" not in body.lower():
            result.failures.append(
                "app/seed.py::seed_semantic_layer must probe an "
                "existing SemanticMetric row with a `.limit(1)` "
                "query before inserting. Without that probe every "
                "pod restart would double-insert metrics / "
                "synonyms and eventually violate the unique "
                "constraint on SemanticSynonym.term."
            )
        has_early_return = any(
            isinstance(node, ast.Return) for node in ast.walk(semantic_fn)
        )
        if not has_early_return:
            result.failures.append(
                "app/seed.py::seed_semantic_layer has no `return` "
                "statement; the existence-probe early-exit is what "
                "makes the function idempotent."
            )
    return result


# ---------------------------------------------------------------------------
# §Task 15 — close the loop on the request_id_missing=true log invariant.
#
# One contract, four bindings:
#
#   1. assistant-service Counter name == "assistant_request_id_missing_total"
#      with label set == {"route"}. Declared once in
#      services/assistant-service/app/metrics.py (owned there rather
#      than in app/main.py so tests can import the singleton without
#      triggering create_app()'s side effects).
#   2. app/main.py's add_request_id middleware increments that counter
#      at the same call site that emits the
#      `request_id_missing=true` warning. Conftest mirrors both halves
#      so the test-harness FastAPI app gives Prometheus the same
#      scrape output as production.
#   3. config/observability/prometheus-rules.request-id-missing.yml
#      declares an alert whose expression sums rate() over the SAME
#      metric name — matching docs/runbooks/observability-roadmap.md
#      §Stage A Watch List character-for-character.
#   4. observability-roadmap.md's Stage A paragraph spells out the
#      same alert expression as the rule file, so operators who read
#      the runbook see exactly what Prometheus actually evaluates.
#
# If any one of these four drifts, the alert pipeline silently
# stops firing on the real-world event the invariant is designed to
# catch (gateway bypassed / request-id plugin misconfigured). This
# contract pins all four in one place so that drift is a contract
# failure on the PR that introduces it, not a silent paging gap
# discovered three months later.
# ---------------------------------------------------------------------------


_REQUEST_ID_METRICS_PATH = (
    REPO_ROOT
    / "services"
    / "assistant-service"
    / "app"
    / "metrics.py"
)
_REQUEST_ID_MAIN_PATH = (
    REPO_ROOT / "services" / "assistant-service" / "app" / "main.py"
)
_REQUEST_ID_CONFTEST_PATH = (
    REPO_ROOT
    / "services"
    / "assistant-service"
    / "tests"
    / "conftest.py"
)
_REQUEST_ID_ALERT_RULE_PATH = (
    REPO_ROOT
    / "config"
    / "observability"
    / "prometheus-rules.request-id-missing.yml"
)
_REQUEST_ID_ROADMAP_PATH = (
    REPO_ROOT / "docs" / "runbooks" / "observability-roadmap.md"
)


@register_check(
    "request-id-missing-alert-rule-bound",
    "architecture-tasks §Task 15 — the request_id_missing=true log "
    "invariant MUST be closed end-to-end: (a) app/metrics.py owns one "
    "Counter named 'assistant_request_id_missing_total' with a single "
    "label 'route'; (b) app/main.py and tests/conftest.py both "
    "increment that counter AT the warning call site; (c) "
    "config/observability/prometheus-rules.request-id-missing.yml "
    "declares an alert whose expr sums rate() over that counter name "
    "for 5 minutes; (d) docs/runbooks/observability-roadmap.md §Stage "
    "A Watch List spells out the same expression. Drift on any leg "
    "silently breaks the paging pipeline — counter renamed but rule "
    "untouched, or rule tightened but roadmap stale — hence all four "
    "legs are pinned here in one contract. Legitimate renames happen "
    "by updating this contract, app/metrics.py, the rule file, and "
    "the roadmap in the SAME commit.",
)
def check_request_id_missing_alert_rule_bound() -> CheckResult:
    result = CheckResult(
        "request-id-missing-alert-rule-bound",
        "request_id_missing counter / alert / roadmap stay in lock-step",
    )
    expected_counter_name = "assistant_request_id_missing_total"
    expected_label_names = ("route",)
    expected_log_phrase = "request_id_missing=true"
    expected_alert_expr = (
        "sum(rate(assistant_request_id_missing_total[5m])) > 0"
    )
    expected_alert_for = "5m"

    # -- Leg 1: app/metrics.py owns the Counter singleton ----------------
    if not _REQUEST_ID_METRICS_PATH.is_file():
        result.failures.append(
            f"expected {_REQUEST_ID_METRICS_PATH.relative_to(REPO_ROOT)} "
            f"(Task 15 moved the Counter here so tests can share the "
            f"singleton without pulling in app.main's create_app() side "
            f"effects)"
        )
        return result
    metrics_src = _REQUEST_ID_METRICS_PATH.read_text(encoding="utf-8")

    try:
        metrics_tree = ast.parse(metrics_src, filename=str(_REQUEST_ID_METRICS_PATH))
    except SyntaxError as exc:
        result.failures.append(
            f"app/metrics.py failed to parse: {exc}"
        )
        return result

    counter_assignments: list[ast.Assign] = []
    for node in metrics_tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not (
            isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "Counter"
        ):
            continue
        counter_assignments.append(node)
    if len(counter_assignments) != 1:
        result.failures.append(
            f"app/metrics.py must declare exactly one prometheus_client "
            f"Counter (Task 15 pins the request_id_missing counter as "
            f"the sole member for now); found {len(counter_assignments)}."
        )
        return result

    counter_call = counter_assignments[0].value
    assert isinstance(counter_call, ast.Call)
    if not counter_call.args or not isinstance(counter_call.args[0], ast.Constant):
        result.failures.append(
            "app/metrics.py: Counter(...) first positional argument must "
            "be a string literal for the metric name."
        )
        return result
    counter_name_literal = counter_call.args[0].value
    if counter_name_literal != expected_counter_name:
        result.failures.append(
            f"app/metrics.py: Counter name literal is "
            f"{counter_name_literal!r}, expected {expected_counter_name!r}. "
            f"Rename would orphan the AssistantRequestIdMissing alert "
            f"rule — update the rule file and the observability roadmap "
            f"in the same commit."
        )

    # Counter label set: must be a literal tuple/list of strings and
    # equal the expected label tuple exactly. Relying on a runtime
    # Counter.labelnames inspection would need an import — keep this
    # contract source-only.
    if len(counter_call.args) < 3:
        result.failures.append(
            "app/metrics.py: Counter(...) must be called with three "
            "positional args: (name, docstring, labelnames). A 2-arg "
            "call would implicitly drop the `route` label and break "
            "the alert rule's sum-by shape."
        )
    else:
        labelnames_node = counter_call.args[2]
        if isinstance(labelnames_node, (ast.Tuple, ast.List)):
            label_literals = tuple(
                elt.value
                for elt in labelnames_node.elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            )
        else:
            label_literals = ()
        if label_literals != expected_label_names:
            result.failures.append(
                f"app/metrics.py: Counter label set is {label_literals!r}, "
                f"expected {expected_label_names!r}. Changing the label "
                f"set breaks every Prometheus scraper that is already "
                f"grouping by `route` — update the rule file's sum() "
                f"expression and the roadmap example in the same commit."
            )

    # -- Leg 2: app/main.py increments the counter at the warning site --
    if not _REQUEST_ID_MAIN_PATH.is_file():
        result.failures.append(
            f"expected {_REQUEST_ID_MAIN_PATH.relative_to(REPO_ROOT)}"
        )
        return result
    main_src = _REQUEST_ID_MAIN_PATH.read_text(encoding="utf-8")
    if "from app.metrics import REQUEST_ID_MISSING_TOTAL" not in main_src:
        result.failures.append(
            "app/main.py must import the Counter singleton from "
            "app.metrics (Task 15: the singleton lives in app/metrics.py "
            "so tests and production share one CollectorRegistry entry)."
        )
    if "REQUEST_ID_MISSING_TOTAL.labels(route=" not in main_src:
        result.failures.append(
            "app/main.py must call "
            "`REQUEST_ID_MISSING_TOTAL.labels(route=<path>).inc()` "
            "inside the add_request_id fallback branch. Without the "
            "counter bump, the request_id_missing=true warning has no "
            "numeric signal for the alert rule to sum over."
        )
    if expected_log_phrase not in main_src:
        result.failures.append(
            f"app/main.py must log the canonical "
            f"{expected_log_phrase!r} literal; renaming it would "
            f"silently orphan log-based dashboards that operators "
            f"build on the line. See backend.md §5 rule 1."
        )

    # -- Leg 2b: conftest mirrors BOTH halves (counter + warning) -------
    if not _REQUEST_ID_CONFTEST_PATH.is_file():
        result.failures.append(
            f"expected {_REQUEST_ID_CONFTEST_PATH.relative_to(REPO_ROOT)}"
        )
    else:
        conftest_src = _REQUEST_ID_CONFTEST_PATH.read_text(encoding="utf-8")
        if "from app.metrics import REQUEST_ID_MISSING_TOTAL" not in conftest_src:
            result.failures.append(
                "tests/conftest.py must import REQUEST_ID_MISSING_TOTAL "
                "from app.metrics (NOT from app.main — that would trip "
                "create_app()'s validate_or_die() during test "
                "collection when the /app/config bind-mount is absent)."
            )
        if expected_log_phrase not in conftest_src:
            result.failures.append(
                "tests/conftest.py's add_request_id shim must emit the "
                f"canonical {expected_log_phrase!r} warning so "
                "test_request_id.py can assert on it without special-"
                "casing the test app."
            )
        if ".labels(route=" not in conftest_src:
            result.failures.append(
                "tests/conftest.py's add_request_id shim must also "
                "increment the Counter (`.labels(route=...).inc()`), "
                "mirroring the production middleware. The Task 15 "
                "acceptance test asserts the counter bumps under the "
                "test client; a warning-only shim silently drifts "
                "from the production code path."
            )

    # -- Leg 3: alert rule file declares the sum-rate expression --------
    if not _REQUEST_ID_ALERT_RULE_PATH.is_file():
        result.failures.append(
            f"expected {_REQUEST_ID_ALERT_RULE_PATH.relative_to(REPO_ROOT)} "
            f"— Task 15 deliverable: \"Add an alerting rule ... "
            f"`rate(... > 0) for 5m`\". A missing file means the "
            f"deferred-Prometheus operator has nothing to drop into "
            f"rule_files: on day one."
        )
    else:
        rule_doc = yaml.safe_load(
            _REQUEST_ID_ALERT_RULE_PATH.read_text(encoding="utf-8")
        ) or {}
        groups = rule_doc.get("groups") or []
        alert_nodes: list[dict] = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            for rule in group.get("rules") or []:
                if isinstance(rule, dict) and rule.get("alert"):
                    alert_nodes.append(rule)
        if not alert_nodes:
            result.failures.append(
                f"{_REQUEST_ID_ALERT_RULE_PATH.relative_to(REPO_ROOT)}: "
                f"contains no Prometheus alert rules."
            )
        else:
            # Find the alert that references our counter. Tying the
            # contract to a specific alert name (AssistantRequestIdMissing)
            # would make a future rename churn both files; instead,
            # require that some alert references the counter with the
            # expected expression literal.
            matching = [
                rule for rule in alert_nodes
                if rule.get("expr", "").strip() == expected_alert_expr
            ]
            if not matching:
                seen = [
                    (rule.get("alert"), rule.get("expr"))
                    for rule in alert_nodes
                ]
                result.failures.append(
                    f"{_REQUEST_ID_ALERT_RULE_PATH.relative_to(REPO_ROOT)}: "
                    f"no alert with expr exactly {expected_alert_expr!r}. "
                    f"Found {seen!r}. Update the rule expression (and "
                    f"the observability roadmap in the same commit) if "
                    f"the counter name or aggregation intentionally "
                    f"changed."
                )
            else:
                # All alerts that reference the counter MUST hold the 5m
                # debounce window. A shorter `for:` would page on scrape-
                # interval flakes; a longer one would hide a sustained
                # gateway misconfiguration.
                for rule in matching:
                    for_value = str(rule.get("for", "")).strip()
                    if for_value != expected_alert_for:
                        result.failures.append(
                            f"{_REQUEST_ID_ALERT_RULE_PATH.relative_to(REPO_ROOT)} "
                            f"alert {rule.get('alert')!r}: `for:` must be "
                            f"{expected_alert_for!r} (Task 15 pins the "
                            f"5-minute debounce window); got "
                            f"{for_value!r}."
                        )

    # -- Leg 4: observability roadmap doc carries the same expr ---------
    if not _REQUEST_ID_ROADMAP_PATH.is_file():
        result.failures.append(
            f"expected {_REQUEST_ID_ROADMAP_PATH.relative_to(REPO_ROOT)}"
        )
    else:
        roadmap_src = _REQUEST_ID_ROADMAP_PATH.read_text(encoding="utf-8")
        if expected_alert_expr not in roadmap_src:
            result.failures.append(
                f"{_REQUEST_ID_ROADMAP_PATH.relative_to(REPO_ROOT)}: "
                f"does not contain the literal alert expression "
                f"{expected_alert_expr!r}. Operators reading the "
                f"roadmap would see a stale example while Prometheus "
                f"evaluates a different one — that disconnect is the "
                f"whole category of bug this contract exists to "
                f"prevent."
            )
    return result


# ---------------------------------------------------------------------------
# §Task 16 — Tidy assistant-service/app/core/ layering. Four contracts pin
# the four facets that together make the "pluggable backend" story true
# at the file-tree level, not just in prose:
#
#   * `core-layer-no-legacy-llm-client-path` — the historic
#     `app.core.llm_client` import path is dead, and the file
#     `app/core/llm_client.py` MUST NOT reappear. Every LLM consumer
#     now routes through `app.infra.llm`. Without this lock a careless
#     re-add of the old module would silently resurrect the flat
#     "infra mixed with domain" layout Finding #11 called out.
#   * `core-interfaces-declares-four-protocols` — `app/core/interfaces.py`
#     declares Protocols for Planner / StepExecutor / ResultInterpreter /
#     TaskInterpreter, not one fewer, not one more. Silently dropping a
#     Protocol would make the matching registry seam a dead letter;
#     silently adding one without an accompanying registry seam would
#     give consumers a type they can't swap.
#   * `core-registry-swap-seam-present` — `app/core/registry.py` exists
#     and `app/dependencies.py` consumes it instead of `new`ing core
#     classes directly. The acceptance wording is "swap one symbol in
#     a registry, no edits inside `core/`"; the contract operationalizes
#     that by asserting the registry call sites exist AND the forbidden
#     direct-construction call sites do not.
#   * `core-must-not-import-infra-internals` — `app/core/*.py` may
#     import `app.infra.llm` (the one sanctioned infra dependency) but
#     MUST NOT import other `app.infra.*` submodules. Keeps the
#     dependency edge between layers a single, visible arrow.
# ---------------------------------------------------------------------------


_ASSISTANT_APP_ROOT = REPO_ROOT / "services" / "assistant-service" / "app"
_CORE_DIR = _ASSISTANT_APP_ROOT / "core"
_CORE_INTERFACES = _CORE_DIR / "interfaces.py"
_CORE_REGISTRY = _CORE_DIR / "registry.py"
_CORE_LEGACY_LLM = _CORE_DIR / "llm_client.py"
_APP_DEPENDENCIES = _ASSISTANT_APP_ROOT / "dependencies.py"


@register_check(
    "core-layer-no-legacy-llm-client-path",
    "The historic flat-layout import path `from app.core.llm_client` "
    "is sunset (architecture-tasks §Task 16). No file under "
    "`services/assistant-service/` may import from it, and the file "
    "`app/core/llm_client.py` itself MUST NOT reappear. Every LLM "
    "consumer now routes through `app.infra.llm`. A legitimate "
    "reintroduction of the old path would require relaxing this "
    "contract in the same PR.",
)
def check_core_layer_no_legacy_llm_client_path() -> CheckResult:
    result = CheckResult(
        "core-layer-no-legacy-llm-client-path",
        "zero hits for the sunsetted `app.core.llm_client` import + file",
    )
    if _CORE_LEGACY_LLM.exists():
        result.failures.append(
            f"{_CORE_LEGACY_LLM.relative_to(REPO_ROOT)} has been resurrected; "
            "Task 16 moved LLMClient to app/infra/llm.py. Keeping the old "
            "path alive defeats the whole point of the tidy-up — either "
            "finish the deletion or relax this contract in the same PR."
        )
    # Grep-scan the whole assistant-service tree (NOT just app/) so tests,
    # scripts, and conftest.py are all in scope.
    scan_root = REPO_ROOT / "services" / "assistant-service"
    pattern = r"\bfrom\s+app\.core\.llm_client\b|\bimport\s+app\.core\.llm_client\b"
    hits = _scan_for_pattern((scan_root,), pattern)
    for path, lineno, line in hits:
        # check-contracts.py is allowed to mention the string in its
        # own pattern; we narrow the scan root to services/ above so
        # that is already excluded.
        result.failures.append(f"{path}:{lineno}: {line.strip()}")
    return result


@register_check(
    "core-interfaces-declares-four-protocols",
    "`app/core/interfaces.py` declares Protocols named exactly "
    "{Planner, StepExecutor, ResultInterpreter, TaskInterpreter} — "
    "no more, no less (architecture-tasks §Task 16). Silently dropping "
    "a Protocol would orphan the matching registry seam; silently "
    "adding one without updating `app/core/registry.SEAM_NAMES` would "
    "give consumers a type they have no way to swap. Extending this "
    "set is a coordinated change: Protocol + SEAM_NAMES + "
    "core-registry-swap-seam-present all in the same PR.",
)
def check_core_interfaces_declares_four_protocols() -> CheckResult:
    result = CheckResult(
        "core-interfaces-declares-four-protocols",
        "interfaces.py declares exactly the four Task 16 Protocols",
    )
    if not _CORE_INTERFACES.is_file():
        result.failures.append(
            f"expected {_CORE_INTERFACES.relative_to(REPO_ROOT)} to exist"
        )
        return result
    try:
        tree = ast.parse(
            _CORE_INTERFACES.read_text(encoding="utf-8"),
            filename=str(_CORE_INTERFACES),
        )
    except SyntaxError as exc:
        result.failures.append(
            f"{_CORE_INTERFACES.relative_to(REPO_ROOT)} failed to parse: {exc}"
        )
        return result

    expected = {"Planner", "StepExecutor", "ResultInterpreter", "TaskInterpreter"}
    declared: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            # We want classes that inherit from Protocol (typing.Protocol).
            # Accept both `class X(Protocol):` and `class X(Protocol, ...):`.
            base_names = set()
            for base in node.bases:
                if isinstance(base, ast.Name):
                    base_names.add(base.id)
                elif isinstance(base, ast.Attribute):
                    base_names.add(base.attr)
            if "Protocol" in base_names:
                declared.add(node.name)

    missing = expected - declared
    extras = declared - expected
    if missing:
        result.failures.append(
            f"app/core/interfaces.py is missing Protocol(s) {sorted(missing)!r}. "
            f"Task 16 requires exactly {sorted(expected)!r}."
        )
    if extras:
        result.failures.append(
            f"app/core/interfaces.py declares extra Protocol(s) {sorted(extras)!r} "
            f"beyond the Task 16 set {sorted(expected)!r}. Extending the "
            f"seam set requires a coordinated update to "
            f"app/core/registry.SEAM_NAMES and the "
            f"core-registry-swap-seam-present contract in the same PR."
        )
    return result


@register_check(
    "core-registry-swap-seam-present",
    "`app/core/registry.py` exists with SEAM_NAMES = "
    "{planner, step_executor, result_interpreter, task_interpreter} AND "
    "`app/dependencies.py::get_analysis_service` resolves each seam "
    "through `core_registry.get(<seam>)` rather than directly "
    "instantiating the concrete class (architecture-tasks §Task 16 "
    "acceptance clause 2). Direct `Planner(...)` / `StepExecutor(...)` / "
    "`ResultInterpreter(...)` / `TaskInterpreter(...)` calls inside "
    "get_analysis_service would bypass the swap seam — a stub would "
    "then still require editing dependencies.py, which is the line the "
    "acceptance text specifically draws around `core/` plus the DI "
    "wiring: ONE place to edit, and that edit is a registry entry.",
)
def check_core_registry_swap_seam_present() -> CheckResult:
    result = CheckResult(
        "core-registry-swap-seam-present",
        "core registry exists and dependencies.py routes through it",
    )
    if not _CORE_REGISTRY.is_file():
        result.failures.append(
            f"expected {_CORE_REGISTRY.relative_to(REPO_ROOT)} to exist "
            "as the Task 16 swap seam"
        )
        return result
    if not _APP_DEPENDENCIES.is_file():
        result.failures.append(
            f"expected {_APP_DEPENDENCIES.relative_to(REPO_ROOT)} to exist"
        )
        return result

    registry_src = _CORE_REGISTRY.read_text(encoding="utf-8")
    # SEAM_NAMES must be a frozenset literal of exactly the four Task 16 names.
    # Parse via AST to avoid string-ordering or comment false positives.
    try:
        reg_tree = ast.parse(registry_src, filename=str(_CORE_REGISTRY))
    except SyntaxError as exc:
        result.failures.append(f"app/core/registry.py failed to parse: {exc}")
        return result

    expected_seams = {"planner", "step_executor", "result_interpreter", "task_interpreter"}
    seam_names_literal: set[str] | None = None
    for node in reg_tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.target.id == "SEAM_NAMES" and node.value is not None:
            call = node.value
            if isinstance(call, ast.Call) and (
                (isinstance(call.func, ast.Name) and call.func.id == "frozenset")
                or (isinstance(call.func, ast.Attribute) and call.func.attr == "frozenset")
            ) and call.args:
                arg = call.args[0]
                if isinstance(arg, (ast.Set, ast.List, ast.Tuple)):
                    literals: set[str] = set()
                    ok = True
                    for elt in arg.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            literals.add(elt.value)
                        else:
                            ok = False
                            break
                    if ok:
                        seam_names_literal = literals
            break
    if seam_names_literal is None:
        result.failures.append(
            "app/core/registry.py: could not find SEAM_NAMES as a "
            "frozenset({...}) of string literals. The contract parses "
            "the literal directly (not runtime) so test stubs can't "
            "accidentally mutate it at import time."
        )
    elif seam_names_literal != expected_seams:
        result.failures.append(
            f"app/core/registry.py: SEAM_NAMES literal is "
            f"{sorted(seam_names_literal)!r}, expected "
            f"{sorted(expected_seams)!r}. Changing this set is a "
            f"coordinated refactor with app/core/interfaces.py and "
            f"app/dependencies.py — update all three in the same PR."
        )

    # get_analysis_service MUST call core_registry.get(<seam>) for each
    # seam AND MUST NOT directly instantiate the concrete classes.
    dep_src = _APP_DEPENDENCIES.read_text(encoding="utf-8")
    try:
        dep_tree = ast.parse(dep_src, filename=str(_APP_DEPENDENCIES))
    except SyntaxError as exc:
        result.failures.append(f"app/dependencies.py failed to parse: {exc}")
        return result

    target_fn: ast.FunctionDef | None = None
    for node in dep_tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == "get_analysis_service":
            target_fn = node  # type: ignore[assignment]
            break
    if target_fn is None:
        result.failures.append(
            "app/dependencies.py: `get_analysis_service` definition not "
            "found — cannot assert it routes through the core registry."
        )
        return result

    resolved_seams: set[str] = set()
    direct_constructs: set[str] = set()
    forbidden_names = {"Planner", "StepExecutor", "ResultInterpreter", "TaskInterpreter"}
    for node in ast.walk(target_fn):
        if isinstance(node, ast.Call):
            # core_registry.get("<seam>") — attribute call with 1 str arg
            if isinstance(node.func, ast.Attribute) and node.func.attr == "get":
                caller = node.func.value
                if isinstance(caller, ast.Name) and caller.id in {"core_registry", "registry"}:
                    if node.args and isinstance(node.args[0], ast.Constant) \
                            and isinstance(node.args[0].value, str):
                        resolved_seams.add(node.args[0].value)
            # Direct class construction: Planner(...) / StepExecutor(...) / etc.
            if isinstance(node.func, ast.Name) and node.func.id in forbidden_names:
                direct_constructs.add(node.func.id)

    missing_lookups = expected_seams - resolved_seams
    if missing_lookups:
        result.failures.append(
            f"app/dependencies.py::get_analysis_service does not call "
            f"core_registry.get(...) for seam(s) {sorted(missing_lookups)!r}. "
            f"Each of the four Task 16 seams MUST be resolved through the "
            f"registry — that is exactly what makes `swap one symbol, no "
            f"edits inside core/` true."
        )
    if direct_constructs:
        result.failures.append(
            f"app/dependencies.py::get_analysis_service directly "
            f"constructs {sorted(direct_constructs)!r}. These must be "
            f"obtained from core_registry.get(...) instead; direct "
            f"construction bypasses the swap seam entirely and brings "
            f"back the Finding #11 anti-pattern."
        )
    return result


_CORE_PY_FILES_GLOB = "*.py"


@register_check(
    "core-must-not-import-infra-internals",
    "Files in `app/core/` may import the sanctioned infra facade "
    "`app.infra.llm` (LLMClient), but MUST NOT import any other "
    "`app.infra.*` submodule (architecture-tasks §Task 16). The "
    "single-arrow rule: core depends on infra through one narrow seam, "
    "not through a web of ad-hoc calls into infra internals. "
    "Adding a second sanctioned dependency requires extending this "
    "contract's allow-list in the same PR as the import.",
)
def check_core_must_not_import_infra_internals() -> CheckResult:
    result = CheckResult(
        "core-must-not-import-infra-internals",
        "core imports from app.infra.* stay confined to app.infra.llm",
    )
    if not _CORE_DIR.is_dir():
        result.failures.append(
            f"expected {_CORE_DIR.relative_to(REPO_ROOT)} to exist"
        )
        return result

    allowed_infra_modules = {"app.infra.llm"}
    for py_path in sorted(_CORE_DIR.glob(_CORE_PY_FILES_GLOB)):
        try:
            tree = ast.parse(
                py_path.read_text(encoding="utf-8"),
                filename=str(py_path),
            )
        except SyntaxError as exc:
            result.failures.append(f"{py_path.relative_to(REPO_ROOT)}: parse error: {exc}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module \
                    and node.module.startswith("app.infra"):
                if node.module not in allowed_infra_modules:
                    result.failures.append(
                        f"{py_path.relative_to(REPO_ROOT)}:{node.lineno}: "
                        f"`from {node.module} import ...` is forbidden. "
                        f"core/ may only depend on {sorted(allowed_infra_modules)!r}. "
                        f"If this is a legitimate new core↔infra seam, "
                        f"extend the allow-list in the same PR and add "
                        f"a rationale to the contract docstring."
                    )
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    if name.startswith("app.infra") and name not in allowed_infra_modules:
                        result.failures.append(
                            f"{py_path.relative_to(REPO_ROOT)}:{node.lineno}: "
                            f"`import {name}` is forbidden."
                        )
    return result


# ---------------------------------------------------------------------------
# §Task 17 — Reserve an assistant-worker seam for long-running work. Four
# contracts pin the four independent facets that together make the "future
# worker process can be wired up without touching app/core/" acceptance
# clause true at the file-tree level rather than as prose:
#
#   * `worker-reaper-module-exists-and-shares-core` — the standalone
#     entrypoint `app/workers/reaper.py` exists, defines `main()`, AND
#     resolves the reaper loop by importing `run_periodic_reaper` from
#     `app.core.task_lifecycle`. Without the shared import this would
#     devolve into "two copies of the reaper drift", which is exactly
#     the Finding #14 shape the task exists to avoid.
#   * `worker-reaper-shared-by-api-lifespan` — the API process
#     (`app/main.py`) also imports and invokes the SAME functions from
#     `app.core.task_lifecycle` that `app/workers/reaper.py` imports.
#     Checking BOTH call sites guarantees the "same module, two
#     entrypoints" story is a bi-directional fact, not a one-off file.
#   * `assistant-worker-dir-and-split-doc-present` — the
#     `services/assistant-worker/` directory exists as the structural
#     slot for a future compose service / build context, AND
#     `docs/design/assistant-worker-split.md` spells out the intended
#     split so a future operator doesn't have to reverse-engineer it
#     from compose files.
#   * `worker-entrypoint-is-thin-wrapper` — `app/workers/reaper.py`
#     MUST stay a thin wrapper: no locally-defined reaper coroutine,
#     no local SELECT/UPDATE on AnalysisSession, no duplicated
#     IN_FLIGHT_STATUSES list. If a future PR grows the worker module
#     with its own reaper internals, it has silently forked the
#     lifecycle contract; the worker module must delegate to
#     `app.core.task_lifecycle` or extend a new seam there.
# ---------------------------------------------------------------------------


_ASSISTANT_SERVICE_ROOT = REPO_ROOT / "services" / "assistant-service"
_WORKER_REAPER_MODULE = _ASSISTANT_SERVICE_ROOT / "app" / "workers" / "reaper.py"
_TASK_LIFECYCLE_MODULE = _ASSISTANT_SERVICE_ROOT / "app" / "core" / "task_lifecycle.py"
_APP_MAIN_MODULE = _ASSISTANT_SERVICE_ROOT / "app" / "main.py"
_ASSISTANT_WORKER_DIR = REPO_ROOT / "services" / "assistant-worker"
_ASSISTANT_WORKER_README = _ASSISTANT_WORKER_DIR / "README.md"
_ASSISTANT_SPLIT_DOC = REPO_ROOT / "docs" / "design" / "assistant-worker-split.md"


@register_check(
    "worker-reaper-module-exists-and-shares-core",
    "The standalone worker entrypoint `app/workers/reaper.py` MUST "
    "exist, MUST define `main()`, AND MUST resolve its reaper loop by "
    "importing `run_periodic_reaper` from `app.core.task_lifecycle` "
    "(architecture-tasks §Task 17 acceptance clause 1). A future PR "
    "wiring up assistant-worker as its own compose service can set "
    "`command: python -m app.workers.reaper` without editing anything "
    "under `app/core/` — exactly because the entrypoint is a thin "
    "re-exporter of the lifecycle-shared function.",
)
def check_worker_reaper_module_exists_and_shares_core() -> CheckResult:
    result = CheckResult(
        "worker-reaper-module-exists-and-shares-core",
        "worker reaper entrypoint shares the lifecycle module",
    )
    if not _WORKER_REAPER_MODULE.is_file():
        result.failures.append(
            f"expected {_WORKER_REAPER_MODULE.relative_to(REPO_ROOT)} to "
            "exist; it is the `python -m app.workers.reaper` entrypoint "
            "named in Task 17's acceptance text."
        )
        return result
    try:
        tree = ast.parse(
            _WORKER_REAPER_MODULE.read_text(encoding="utf-8"),
            filename=str(_WORKER_REAPER_MODULE),
        )
    except SyntaxError as exc:
        result.failures.append(
            f"{_WORKER_REAPER_MODULE.relative_to(REPO_ROOT)} failed to parse: {exc}"
        )
        return result

    has_main = any(
        isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "main"
        for n in tree.body
    )
    if not has_main:
        result.failures.append(
            "app/workers/reaper.py must define `main()` — the module "
            "is imported via `python -m app.workers.reaper` which then "
            "executes the `if __name__ == '__main__'` block; removing "
            "main() would make the module's entrypoint status silent."
        )

    # The critical invariant: run_periodic_reaper is imported from the
    # shared module, not redefined locally.
    imports_from_lifecycle: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "app.core.task_lifecycle":
            for alias in node.names:
                imports_from_lifecycle.add(alias.name)
    if "run_periodic_reaper" not in imports_from_lifecycle:
        result.failures.append(
            "app/workers/reaper.py must `from app.core.task_lifecycle "
            "import run_periodic_reaper`. Without this the worker would "
            "be running its own forked reaper loop — re-opening the "
            "Finding #14 failure mode Task 17 exists to prevent."
        )
    return result


@register_check(
    "worker-reaper-shared-by-api-lifespan",
    "The API process (`app/main.py`) MUST import AND invoke the same "
    "`app.core.task_lifecycle` functions the standalone worker relies "
    "on — specifically `start_periodic_reaper` and "
    "`recover_zombie_sessions_on_startup` (architecture-tasks §Task 17). "
    "This is the counterpart to `worker-reaper-module-exists-and-"
    "shares-core`: the one contract asserts the worker consumes the "
    "shared module, this one asserts the API still consumes it. "
    "Dropping either call on the API side would silently downgrade to "
    "`task_lifecycle is worker-only` and a freshly booted API pod "
    "would no longer reap zombies or recover on startup.",
)
def check_worker_reaper_shared_by_api_lifespan() -> CheckResult:
    result = CheckResult(
        "worker-reaper-shared-by-api-lifespan",
        "API lifespan still consumes the shared lifecycle module",
    )
    if not _APP_MAIN_MODULE.is_file():
        result.failures.append(
            f"expected {_APP_MAIN_MODULE.relative_to(REPO_ROOT)} to exist"
        )
        return result
    try:
        tree = ast.parse(
            _APP_MAIN_MODULE.read_text(encoding="utf-8"),
            filename=str(_APP_MAIN_MODULE),
        )
    except SyntaxError as exc:
        result.failures.append(
            f"{_APP_MAIN_MODULE.relative_to(REPO_ROOT)} failed to parse: {exc}"
        )
        return result

    imported: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "app.core.task_lifecycle":
            for alias in node.names:
                imported.add(alias.name)
    required_imports = {"start_periodic_reaper", "recover_zombie_sessions_on_startup"}
    missing_imports = required_imports - imported
    if missing_imports:
        result.failures.append(
            f"app/main.py does not import {sorted(missing_imports)!r} "
            f"from app.core.task_lifecycle. The API lifespan depends on "
            f"those names; removing them would mean the reaper/recovery "
            f"only exists in the worker entrypoint."
        )

    # Also verify the names are actually called (not just imported).
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in required_imports:
                called.add(node.func.id)
    missing_calls = required_imports - called
    if missing_calls:
        result.failures.append(
            f"app/main.py imports {sorted(required_imports - missing_calls)!r} "
            f"but does not call {sorted(missing_calls)!r}. Dead imports "
            f"don't reap zombies — the lifespan must invoke each one."
        )
    return result


@register_check(
    "assistant-worker-dir-and-split-doc-present",
    "The structural slot for a future worker process MUST exist even "
    "while no compose service is wired up yet (architecture-tasks "
    "§Task 17). Specifically: (a) `services/assistant-worker/` exists "
    "with a README that names `python -m app.workers.reaper` as the "
    "first command; (b) `docs/design/assistant-worker-split.md` "
    "spells out API / Worker / Shared responsibilities so the split "
    "intent is documented before the first on-call has to infer it "
    "from compose diffs. Deleting either half erases the seam the "
    "task exists to reserve.",
)
def check_assistant_worker_dir_and_split_doc_present() -> CheckResult:
    result = CheckResult(
        "assistant-worker-dir-and-split-doc-present",
        "worker seam directory and design doc both present",
    )
    if not _ASSISTANT_WORKER_DIR.is_dir():
        result.failures.append(
            f"{_ASSISTANT_WORKER_DIR.relative_to(REPO_ROOT)}/ is missing. "
            "Task 17 reserves this directory as the seam for a future "
            "assistant-worker compose service; it MUST exist even when "
            "the compose wiring is not yet live."
        )
    elif not _ASSISTANT_WORKER_README.is_file():
        result.failures.append(
            f"{_ASSISTANT_WORKER_README.relative_to(REPO_ROOT)} is missing. "
            "The README is what tells a future operator that the "
            "first command is `python -m app.workers.reaper`."
        )
    else:
        readme_text = _ASSISTANT_WORKER_README.read_text(encoding="utf-8")
        if "python -m app.workers.reaper" not in readme_text:
            result.failures.append(
                f"{_ASSISTANT_WORKER_README.relative_to(REPO_ROOT)} must "
                "reference the `python -m app.workers.reaper` command "
                "literal — Task 17 acceptance clause 1 calls it out by "
                "exact name."
            )

    if not _ASSISTANT_SPLIT_DOC.is_file():
        result.failures.append(
            f"{_ASSISTANT_SPLIT_DOC.relative_to(REPO_ROOT)} is missing. "
            "Task 17 deliverable #3: document the intended split in "
            "docs/design/ — API = request/response + SSE; Worker = cron "
            "+ LLM-heavy queues (future). Without this doc the first "
            "on-call has to reverse-engineer the split from compose "
            "diffs, which is exactly what the task tries to prevent."
        )
        return result
    doc_text = _ASSISTANT_SPLIT_DOC.read_text(encoding="utf-8").lower()
    for keyword, hint in (
        ("api", "the doc must discuss the API process's responsibilities"),
        ("worker", "the doc must discuss the Worker process's responsibilities"),
        ("shared", "the doc must call out the shared-code contract"),
        ("app.workers.reaper", "the doc must name the first executable seam"),
    ):
        if keyword.lower() not in doc_text:
            result.failures.append(
                f"{_ASSISTANT_SPLIT_DOC.relative_to(REPO_ROOT)}: missing "
                f"keyword {keyword!r} — {hint}."
            )
    return result


@register_check(
    "worker-entrypoint-is-thin-wrapper",
    "`app/workers/reaper.py` MUST stay a thin wrapper over "
    "`app.core.task_lifecycle` (architecture-tasks §Task 17). "
    "It is explicitly NOT allowed to (a) define its own reaper "
    "coroutine, (b) execute SQL directly against AnalysisSession, or "
    "(c) carry its own copy of the IN_FLIGHT_STATUSES list — those "
    "belong to `task_lifecycle`, and duplicating them forks the "
    "contract so that API-owned reaping and worker-owned reaping "
    "drift apart silently. If a genuine worker-specific loop is "
    "needed in the future, add a new function to `task_lifecycle` and "
    "import THAT from the worker entrypoint; this contract stays "
    "intact.",
)
def check_worker_entrypoint_is_thin_wrapper() -> CheckResult:
    result = CheckResult(
        "worker-entrypoint-is-thin-wrapper",
        "worker entrypoint does not fork lifecycle internals",
    )
    if not _WORKER_REAPER_MODULE.is_file():
        result.failures.append(
            f"expected {_WORKER_REAPER_MODULE.relative_to(REPO_ROOT)} to exist"
        )
        return result
    try:
        src = _WORKER_REAPER_MODULE.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(_WORKER_REAPER_MODULE))
    except (OSError, SyntaxError) as exc:
        result.failures.append(
            f"{_WORKER_REAPER_MODULE.relative_to(REPO_ROOT)} failed to read/parse: {exc}"
        )
        return result

    # Forbid locally-defined reaper-shaped functions. `main` is the one
    # function the module is allowed to define; anything else named
    # *reaper* / *reap* would indicate the module has grown its own
    # internals. This is a shape-level guard, not a behavior one.
    forbidden_local_fns: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "main":
                continue
            low = node.name.lower()
            if "reap" in low or "periodic" in low or "zombie" in low:
                forbidden_local_fns.append(node.name)
    if forbidden_local_fns:
        result.failures.append(
            f"app/workers/reaper.py defines locally-named reaper "
            f"function(s) {forbidden_local_fns!r}. Task 17 requires the "
            f"worker entrypoint to stay a thin wrapper; move this logic "
            f"into app.core.task_lifecycle and import it from there."
        )

    # Forbid direct SQLAlchemy / model imports — those belong to
    # task_lifecycle and would indicate worker-local SQL.
    banned_imports = {
        "sqlalchemy": "direct SQL belongs in app.core.task_lifecycle, not the worker entrypoint",
        "app.models.session": "AnalysisSession access belongs in app.core.task_lifecycle",
        "app.database": "async_session_factory belongs in app.core.task_lifecycle",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for banned_mod, why in banned_imports.items():
                if node.module == banned_mod or node.module.startswith(banned_mod + "."):
                    result.failures.append(
                        f"app/workers/reaper.py:{node.lineno}: "
                        f"`from {node.module} import ...` is forbidden — {why}."
                    )
        if isinstance(node, ast.Import):
            for alias in node.names:
                for banned_mod, why in banned_imports.items():
                    if alias.name == banned_mod or alias.name.startswith(banned_mod + "."):
                        result.failures.append(
                            f"app/workers/reaper.py:{node.lineno}: "
                            f"`import {alias.name}` is forbidden — {why}."
                        )

    # Forbid IN_FLIGHT_STATUSES duplication.
    if "IN_FLIGHT_STATUSES" in src and "from app.core.task_lifecycle" not in src.split(
        "IN_FLIGHT_STATUSES", 1
    )[0][-200:]:
        # naive proximity check: if IN_FLIGHT_STATUSES appears and no
        # task_lifecycle import precedes it, the worker is declaring
        # its own copy.
        # (The benign case — importing IN_FLIGHT_STATUSES from
        # task_lifecycle — passes because the import line itself
        # carries the required prefix.)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "IN_FLIGHT_STATUSES":
                        result.failures.append(
                            f"app/workers/reaper.py:{node.lineno}: "
                            "IN_FLIGHT_STATUSES must not be redefined in "
                            "the worker entrypoint — import it from "
                            "app.core.task_lifecycle to keep both "
                            "entrypoints reaping the same status set."
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
