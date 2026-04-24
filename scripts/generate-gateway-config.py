#!/usr/bin/env python3
"""Render downstream gateway configuration from ``config/services.yaml``.

Task 1 (architecture-tasks.md) introduces ``config/services.yaml`` as
the single source of truth for every backend service exposed under
``/api/v1/*``. Today four files used to be hand-edited whenever a new
backend service appeared:

    * ``gateway/apisix.yaml.template`` — per-service route + upstream
    * ``config/ory/oathkeeper/rules.yml`` — per-service Oathkeeper rule
    * ``docker-compose.yml``             — service block (container image)
    * the service's own FastAPI router prefix

Only the last two are unavoidable — the container image is the service,
and the FastAPI router carries the business logic. The other two are
mechanical renderings of facts already stated in the registry. This
script emits them.

Current scope
-------------

* **Oathkeeper rules** (``config/ory/oathkeeper/rules.yml``) are
  rendered *in full* from the registry. Every entry with
  ``auth_mode: cookie_session`` produces a standard Kratos session
  rule; ``auth_mode: public`` produces a ``noop`` authenticator rule;
  the reserved ``api_key`` / ``jwt_bearer`` slots raise
  ``NotImplementedError`` (§Task 5).

* **APISIX routing** currently funnels all of ``/api/v1/*`` to
  Oathkeeper through a single ``protected-api`` route, so per-service
  APISIX routes are intentionally NOT emitted today. Task 7 is the
  trigger for splitting the APISIX side by ``timeout_class``; this
  script is the seam that split will hook into. Until then the
  APISIX template is validated for consistency (upstream host/port
  declared in the registry must at least *appear* in the template's
  oathkeeper upstream) but not regenerated.

Modes
-----

``--check``  (default in CI)
    Render outputs in memory and exit non-zero iff the on-disk file
    does not byte-match. Prints a unified diff so the operator can
    either re-run with ``--write`` or fix the registry.

``--write``
    Render outputs to disk. Use after editing
    ``config/services.yaml``.

Exit codes: 0 = clean, 1 = drift / schema violation, 2 = usage error.
"""
from __future__ import annotations

import argparse
import difflib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    print("error: PyYAML is required (pip install pyyaml)", file=sys.stderr)
    sys.exit(2)


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "config" / "services.yaml"
OATHKEEPER_RULES_PATH = REPO_ROOT / "config" / "ory" / "oathkeeper" / "rules.yml"
APISIX_TEMPLATE_PATH = REPO_ROOT / "gateway" / "apisix.yaml.template"


# ---------------------------------------------------------------------------
# Registry model
# ---------------------------------------------------------------------------


# HTTP method sets per auth_mode.
#
# We keep these declared here (not in services.yaml) because they are
# properties of the *gateway shape* — what an edge is willing to accept
# for a given authenticator chain — not of the individual service.
# Services that want to narrow methods do so in their FastAPI router;
# the edge stays permissive over the CRUD + OPTIONS superset.
_AUTHED_METHODS: tuple[str, ...] = ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
_PUBLIC_METHODS: tuple[str, ...] = ("GET", "HEAD", "OPTIONS")

# Reserved auth_mode values that exist in the schema but have no
# generator implementation yet. Encountering one is a wiring error,
# not a user error — services.yaml passed JSON-Schema validation, so
# the contract slot exists; what's missing is the render branch.
_UNIMPLEMENTED_AUTH_MODES: frozenset[str] = frozenset({"api_key", "jwt_bearer"})

# ---------------------------------------------------------------------------
# timeout_class → APISIX route profile (architecture-tasks §Task 7)
# ---------------------------------------------------------------------------
#
# Historically a single `protected-api` route owned all of /api/v1/* and
# was forced to carry the loosest timeout the loudest SSE endpoint
# needed (900s read_timeout, request buffering off). That coupling is
# finding #4: tuning the SSE idle window silently extended the REST 504
# bound to 15 minutes.
#
# The fix: each `timeout_class` in config/services.yaml maps to a
# distinct APISIX timeout/buffering profile. Non-`standard` classes
# produce a per-service route whose URI is more specific than the
# `/api/v1/*` fallback and whose priority sits exactly
# `_APISIX_CLASS_PRIORITY_MARGIN` above it (gateway.md §6.2:
# "deeper prefix priority >= shallower + 10"). Standard-class entries
# fall through to the `protected-api` fallback with the tight REST
# read_timeout.
#
# This dataclass is declared HERE (next to its consumer, the APISIX
# template verifier) so that adding a new class, tightening its
# read_timeout, or flipping a plugin is a single source-controlled
# edit — no per-route YAML duplication, no check-contracts.py mirror
# literal. scripts/check-contracts.py imports these constants via
# importlib (same seam `oathkeeper-rules-match-services-yaml` already
# uses) and asserts the APISIX template obeys them.
#
# Numeric rationale (all seconds):
#   * `connect=5` + `send=60` are uniform across classes; they cover
#     only the TCP handshake and request-send window, which no traffic
#     shape legitimately exceeds. Tuning them per-class would add
#     knobs no endpoint today needs.
#   * `standard.read=30` restores the snappy REST 504 bound that the
#     pre-split template accidentally widened to 900s.
#   * `long_poll.read=300` matches the current long-poll budget used
#     nowhere today but reserved so the schema enum isn't a lie (a
#     future long-poll endpoint only has to flip `timeout_class`,
#     never re-touch the gateway template).
#   * `sse.read=1800` is the contracted upper bound enforced by
#     check-contracts.py `sse-routes-explicit-timeout-and-buffering`
#     (gateway.md §5.3.4 session-invalidation collapse-window rule).
#   * `request_buffering=False` is attached ONLY to `sse` — Nginx's
#     request buffering defeats the token-by-token streaming shape
#     that `text/event-stream` responses rely on. Standard REST
#     keeps the default (`on`), which is both safer (bounds in-flight
#     body size) and faster for small JSON payloads.
@dataclass(frozen=True)
class TimeoutClassProfile:
    """APISIX route shape implied by a registry entry's ``timeout_class``.

    ``request_buffering`` is tri-state: ``True`` / ``False`` pin the
    ``proxy-control.request_buffering`` knob; ``None`` means the route
    MUST NOT declare the ``proxy-control`` plugin at all (the APISIX
    default is on, and a silent extra plugin block would be drift
    worth catching).
    """

    connect_timeout_s: int
    send_timeout_s: int
    read_timeout_s: int
    request_buffering: bool | None


_APISIX_TIMEOUT_CLASS_PROFILES: dict[str, TimeoutClassProfile] = {
    "standard": TimeoutClassProfile(
        connect_timeout_s=5,
        send_timeout_s=60,
        read_timeout_s=30,
        request_buffering=None,
    ),
    "long_poll": TimeoutClassProfile(
        connect_timeout_s=5,
        send_timeout_s=60,
        read_timeout_s=300,
        request_buffering=None,
    ),
    "sse": TimeoutClassProfile(
        connect_timeout_s=5,
        send_timeout_s=60,
        read_timeout_s=1800,
        request_buffering=False,
    ),
}

# Priority of `protected-api` in gateway/apisix.yaml.template — the
# /api/v1/* fallback route every `standard`-class entry transits
# through. Declared here, not as a magic number, because per-class
# routes derive their priority off of it.
_APISIX_FALLBACK_ROUTE_PRIORITY: int = 800

# Margin from gateway.md §6.2: "deeper prefix priority >= shallower
# priority + 10". Re-stated here rather than imported to keep the
# generator a self-contained SSOT for everything related to the
# timeout_class split.
_APISIX_CLASS_PRIORITY_MARGIN: int = 10

# The single fallback route name. `standard`-class services produce
# no per-service APISIX route — they inherit this one.
_APISIX_FALLBACK_ROUTE_ID: str = "protected-api"


def timeout_class_expected_route_id(entry: "ServiceEntry") -> str | None:
    """Return the APISIX route id a registry entry implies, or None.

    Returns ``None`` for `standard`-class entries: those do NOT get a
    per-service route — they transit through `protected-api`. Any
    other class produces a deterministic ``<name>-<class>`` route id
    (``assistant-analysis-sse``, etc.) so a greppable route id tells
    the reader both the owning service and the timeout shape applied
    at the edge.
    """
    if entry.timeout_class == "standard":
        return None
    if entry.timeout_class not in _APISIX_TIMEOUT_CLASS_PROFILES:
        # Shouldn't happen — services.schema.yaml already enums the
        # allowed values — but keep a loud guard so a schema-broadening
        # change without a matching profile surfaces here, not as
        # silent "no route emitted".
        raise ValueError(
            f"services.yaml entry {entry.name!r}: timeout_class "
            f"{entry.timeout_class!r} has no profile in "
            f"_APISIX_TIMEOUT_CLASS_PROFILES"
        )
    return f"{entry.name}-{entry.timeout_class}"


def timeout_class_expected_route_uri(entry: "ServiceEntry") -> str:
    """Return the APISIX route URI for a non-standard class entry.

    The per-class APISIX route covers every path under the service's
    ``path_prefix`` — Oathkeeper's per-service rules still dispatch by
    exact prefix downstream, so the gateway-side URI can (and must)
    be the full subtree ``<path_prefix>*``.
    """
    return f"{entry.path_prefix}*"


# Terminal deny-all rule (architecture-tasks §Task 2).
#
# Rationale: Oathkeeper's access-rule engine is allow-list shaped —
# when no rule matches, a request is forwarded with NO X-Auth-* headers
# injected, and a backend that (correctly) trusts those headers then
# sees an anonymous request as if it were a "pre-auth" stage rather
# than rejecting it. That is exactly the "forget a rule = silent auth
# bypass" failure mode finding #1 calls out.
#
# The fix is a lowest-priority rule that matches EVERY path under the
# protected edge (`/api/v1/<.*>`) and uses Oathkeeper's built-in
# `unauthorized` authenticator, which unconditionally returns 401.
# Oathkeeper evaluates rules in the order they appear in the
# repository file (per Ory docs: "the first access rule that matches
# is used"), so emitting this rule LAST makes it a true fallback —
# any earlier, more specific service rule still wins.
#
# Design notes:
#   * Scope is deliberately narrowed to `/api/v1/<.*>` rather than
#     `.*`. Oathkeeper only sees traffic APISIX explicitly routes to
#     the `oathkeeper-proxy` upstream (today: `/api/v1/*`), so a
#     broader match would never fire — keeping the scope tight makes
#     the intent self-documenting and prevents future APISIX changes
#     from silently stretching the deny-all to paths that deserve a
#     different policy (e.g. public probes).
#   * `upstream.url` is required by Oathkeeper's rule schema even for
#     `unauthorized` rules, but the authenticator rejects the request
#     before any upstream dispatch happens. We point it at
#     `127.0.0.1:1` (TCP port 1 / tcpmux, RFC-reserved and never bound
#     inside the compose network) so that a hypothetical future bug
#     that let the request through the authenticator would fail loudly
#     on connect rather than silently leak to a real backend.
#   * `mutators: [noop]` — no subject was resolved (the authenticator
#     rejected the request), so there is nothing for the `header`
#     mutator to template into X-Auth-* headers. `noop` is the
#     explicit statement of that fact.
#   * The `id` is stable and referenced by
#     `scripts/check-contracts.py :: oathkeeper-rules-have-terminal-deny`
#     as the invariant that "the last rule is the deny-all" holds.
_OATHKEEPER_DENY_ALL_RULE_ID: str = "deny-all-api-v1"
_OATHKEEPER_DENY_ALL_UPSTREAM: str = "http://127.0.0.1:1"
_OATHKEEPER_DENY_ALL_MATCH_URL: str = "http://<.*>/api/v1/<.*>"
_OATHKEEPER_DENY_ALL_METHODS: tuple[str, ...] = (
    "GET",
    "HEAD",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
    "OPTIONS",
)


@dataclass(frozen=True)
class ServiceEntry:
    name: str
    path_prefix: str
    upstream_host: str
    upstream_port: int
    auth_mode: str
    timeout_class: str

    @classmethod
    def from_mapping(cls, raw: dict) -> "ServiceEntry":
        missing = [
            k
            for k in (
                "name",
                "path_prefix",
                "upstream_host",
                "upstream_port",
                "auth_mode",
                "timeout_class",
            )
            if k not in raw
        ]
        if missing:
            raise ValueError(
                f"services.yaml entry missing required keys: {missing} "
                f"(got {sorted(raw.keys())})"
            )
        return cls(
            name=str(raw["name"]),
            path_prefix=str(raw["path_prefix"]),
            upstream_host=str(raw["upstream_host"]),
            upstream_port=int(raw["upstream_port"]),
            auth_mode=str(raw["auth_mode"]),
            timeout_class=str(raw["timeout_class"]),
        )


def load_registry(path: Path = REGISTRY_PATH) -> list[ServiceEntry]:
    """Parse + validate ``services.yaml`` and return its entries.

    JSON-Schema validation lives in ``scripts/check-contracts.py`` —
    this function does the minimum structural parsing plus the
    uniqueness invariants (duplicate name / duplicate prefix) that
    JSON-Schema cannot express in a single rule.
    """
    if not path.is_file():
        raise FileNotFoundError(f"registry not found: {path}")
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw_services = doc.get("services")
    if not isinstance(raw_services, list) or not raw_services:
        raise ValueError(
            f"{path.relative_to(REPO_ROOT)}: expected a non-empty "
            f"`services:` list"
        )
    entries = [ServiceEntry.from_mapping(item) for item in raw_services]

    seen_names: dict[str, int] = {}
    seen_prefixes: dict[str, int] = {}
    for idx, entry in enumerate(entries):
        if entry.name in seen_names:
            raise ValueError(
                f"services.yaml: duplicate `name: {entry.name}` "
                f"(entries #{seen_names[entry.name]} and #{idx})"
            )
        if entry.path_prefix in seen_prefixes:
            raise ValueError(
                f"services.yaml: duplicate `path_prefix: {entry.path_prefix}` "
                f"(entries #{seen_prefixes[entry.path_prefix]} and #{idx})"
            )
        seen_names[entry.name] = idx
        seen_prefixes[entry.path_prefix] = idx
    return entries


# ---------------------------------------------------------------------------
# Oathkeeper rules renderer
# ---------------------------------------------------------------------------


_OATHKEEPER_HEADER = """\
# DO NOT EDIT — generated from config/services.yaml by
# scripts/generate-gateway-config.py. Run the generator with --write
# after editing the registry. scripts/check-contracts.py asserts this
# file is a byte-identical re-render of the registry and will fail CI
# on drift.
#
# Rule shape follows Oathkeeper access-rule schema (Ory Oathkeeper
# v26.x); each entry below corresponds to exactly one row in
# config/services.yaml.
"""


def _oathkeeper_methods_for(entry: ServiceEntry) -> tuple[str, ...]:
    if entry.auth_mode == "cookie_session":
        return _AUTHED_METHODS
    if entry.auth_mode == "public":
        return _PUBLIC_METHODS
    if entry.auth_mode in _UNIMPLEMENTED_AUTH_MODES:
        raise NotImplementedError(
            f"services.yaml entry {entry.name!r}: auth_mode "
            f"{entry.auth_mode!r} is a reserved contract slot "
            f"(§Task 5); no generator branch implemented yet"
        )
    raise ValueError(
        f"services.yaml entry {entry.name!r}: unknown auth_mode "
        f"{entry.auth_mode!r}"
    )


def _oathkeeper_authenticators_for(entry: ServiceEntry) -> list[dict]:
    if entry.auth_mode == "cookie_session":
        return [{"handler": "cookie_session"}]
    if entry.auth_mode == "public":
        return [{"handler": "noop"}]
    # Unreachable — _oathkeeper_methods_for would have raised first;
    # we keep the guard here so a future caller order change doesn't
    # silently emit an empty authenticator list.
    raise AssertionError(  # pragma: no cover
        f"unreachable: auth_mode {entry.auth_mode!r} passed methods "
        f"lookup but not authenticator lookup"
    )


def _oathkeeper_mutators_for(entry: ServiceEntry) -> list[dict]:
    # `public` services MUST NOT have the X-Auth-* header mutator
    # applied — without a Kratos session there is no subject to inject,
    # and a forged header on the request would propagate unchanged if
    # we chained `header` after `noop`. `cookie_session` is the only
    # live mode that participates in the X-Auth-* contract (§backend.md
    # header-contract §2.3).
    #
    # architecture-tasks §Task 8: cookie_session ALSO carries the
    # `id_token` mutator immediately after `header`. Oathkeeper signs a
    # short-TTL JWT over the same session claims and injects it as
    # `Authorization: Bearer <jwt>`. The backend's
    # `app.oathkeeper_jwt.verify_bearer_jwt` dependency verifies that
    # JWT against the JWKS endpoint and cross-checks its claims with
    # the X-Auth-* triple, so any sidecar that learns the X-Auth-*
    # header values still cannot forge a valid request without
    # Oathkeeper's signing key. Order matters: `header` must run
    # FIRST so the JWT payload is templated against the same
    # {{ .Subject / .Extra }} values as the headers — keeping the two
    # mutator outputs derived from a single session snapshot is the
    # whole point of the cross-check.
    if entry.auth_mode == "cookie_session":
        return [{"handler": "header"}, {"handler": "id_token"}]
    if entry.auth_mode == "public":
        return [{"handler": "noop"}]
    raise AssertionError(  # pragma: no cover
        f"unreachable: auth_mode {entry.auth_mode!r}"
    )


def render_oathkeeper_rules(entries: Iterable[ServiceEntry]) -> str:
    """Return the full text of ``rules.yml`` for the given registry."""
    rule_dicts: list[dict] = []
    for entry in entries:
        rule_dicts.append(
            {
                "id": entry.name,
                "upstream": {
                    "url": f"http://{entry.upstream_host}:{entry.upstream_port}",
                },
                "match": {
                    # Oathkeeper's regexp matching strategy (see
                    # config/ory/oathkeeper/oathkeeper.yml) requires
                    # the `<.*>` tail on both scheme+host and path.
                    "url": f"http://<.*>{entry.path_prefix}<.*>",
                    "methods": list(_oathkeeper_methods_for(entry)),
                },
                "authenticators": _oathkeeper_authenticators_for(entry),
                "authorizer": {"handler": "allow"},
                "mutators": _oathkeeper_mutators_for(entry),
                "errors": [{"handler": "json"}],
            }
        )

    # Terminal deny-all (architecture-tasks §Task 2). MUST be emitted
    # LAST — Oathkeeper walks rules in file order and the first match
    # wins, so placing the catch-all after every service rule makes it
    # a true fallback rather than shadowing the explicit allow-list.
    rule_dicts.append(
        {
            "id": _OATHKEEPER_DENY_ALL_RULE_ID,
            "upstream": {"url": _OATHKEEPER_DENY_ALL_UPSTREAM},
            "match": {
                "url": _OATHKEEPER_DENY_ALL_MATCH_URL,
                "methods": list(_OATHKEEPER_DENY_ALL_METHODS),
            },
            "authenticators": [{"handler": "unauthorized"}],
            "authorizer": {"handler": "allow"},
            "mutators": [{"handler": "noop"}],
            "errors": [{"handler": "json"}],
        }
    )

    # Emit as a YAML sequence of mappings with stable ordering,
    # blank-line separated for readability (matches the hand-written
    # shape that predates the generator).
    body_chunks: list[str] = []
    for rule in rule_dicts:
        # sort_keys=False so field order follows the dict literal
        # above — reviewers read `id` first, then `upstream`, etc.,
        # exactly like the pre-generator rules.yml.
        chunk = yaml.safe_dump(
            [rule],
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=True,
        )
        body_chunks.append(chunk)
    body = "\n".join(body_chunks)
    return _OATHKEEPER_HEADER + "\n" + body


# ---------------------------------------------------------------------------
# APISIX template consistency check
# ---------------------------------------------------------------------------

# Today APISIX funnels every /api/v1/* request to the Oathkeeper
# proxy through a single upstream (the per-service split waits on
# Task 7). We don't regenerate the APISIX template in this PR, but
# we DO assert that the single oathkeeper upstream host/port declared
# in the template agrees with what the registry says for services
# that target it — otherwise the registry would be lying.


def _apisix_oathkeeper_nodes(template_text: str) -> list[str]:
    """Return the list of ``"host:port"`` nodes under upstream id ``oathkeeper-proxy``.

    We deliberately parse the template as YAML (APISIX Standalone
    format is valid YAML except for the ``${VAR}`` placeholders in
    string scalars — those parse fine). This avoids fragile regex.
    """
    doc = yaml.safe_load(template_text) or {}
    upstreams = doc.get("upstreams", [])
    for up in upstreams:
        if not isinstance(up, dict):
            continue
        if up.get("id") == "oathkeeper-proxy":
            nodes = up.get("nodes", {}) or {}
            return list(nodes.keys())
    return []


def _apisix_routes_by_id(template_text: str) -> dict[str, dict]:
    """Return every top-level APISIX route keyed by its declared ``id``.

    Routes without an ``id`` key are skipped — they cannot be
    unambiguously referenced from the registry-derived verifier and
    a production route without an id is a template authoring bug the
    `protected-api-goes-through-oathkeeper` check already polices.
    """
    doc = yaml.safe_load(template_text) or {}
    out: dict[str, dict] = {}
    for route in doc.get("routes", []) or []:
        if not isinstance(route, dict):
            continue
        rid = route.get("id")
        if isinstance(rid, str) and rid:
            out[rid] = route
    return out


# Plugins every /api/v1/* route MUST carry. Per-route in APISIX, so
# a new per-class route forgetting `gateway-csrf` would re-open the
# CSRF surface, and one forgetting `proxy-rewrite: headers.remove`
# would re-open X-Auth-* forgery (finding #2). Declared once here so
# `verify_apisix_alignment` can assert every timeout_class route
# mirrors the fallback's mandatory plugin set — the generator is the
# single place that re-states this invariant.
_APISIX_API_V1_REQUIRED_PLUGINS: tuple[str, ...] = (
    "gateway-csrf",
    "proxy-rewrite",
)


def _verify_api_v1_route_shape(
    *,
    route_id: str,
    route: dict,
    profile: TimeoutClassProfile,
    expected_uri: str,
    expected_priority: int,
) -> list[str]:
    """Assert ``route`` matches ``profile`` + /api/v1 plugin invariants.

    Returns a list of failure messages (empty == clean). Kept as a
    pure function so both the fallback (`protected-api`) and every
    per-class route can be checked against their respective profiles
    through the same code path.
    """
    failures: list[str] = []

    uri = route.get("uri")
    if uri != expected_uri:
        failures.append(
            f"route {route_id!r}: uri must be {expected_uri!r}, got {uri!r}"
        )

    priority = route.get("priority")
    if priority != expected_priority:
        failures.append(
            f"route {route_id!r}: priority must be {expected_priority} "
            f"(gateway.md §6.2 `_APISIX_CLASS_PRIORITY_MARGIN` above "
            f"`protected-api`'s {_APISIX_FALLBACK_ROUTE_PRIORITY}), "
            f"got {priority!r}"
        )

    timeout = route.get("timeout") or {}
    for knob, expected in (
        ("connect", profile.connect_timeout_s),
        ("send", profile.send_timeout_s),
        ("read", profile.read_timeout_s),
    ):
        actual = timeout.get(knob)
        if actual != expected:
            failures.append(
                f"route {route_id!r}: timeout.{knob} must be "
                f"{expected}s per the `{_class_name_for_profile(profile)}` "
                f"timeout_class profile, got {actual!r}"
            )

    plugins = route.get("plugins") or {}
    for required in _APISIX_API_V1_REQUIRED_PLUGINS:
        if required not in plugins:
            failures.append(
                f"route {route_id!r}: missing required plugin "
                f"{required!r} — every /api/v1/* route MUST declare "
                f"gateway-csrf and proxy-rewrite to preserve the "
                f"CSRF + X-Auth-* strip invariants that `protected-api` "
                f"established (findings #2 and #3)"
            )

    # `proxy-control` is TRI-STATE per the profile: absent, on, or off.
    # Wrong state = silently different body-buffering behavior for
    # what should be uniformly-tuned traffic class.
    has_pc = "proxy-control" in plugins
    if profile.request_buffering is None:
        if has_pc:
            failures.append(
                f"route {route_id!r}: `proxy-control` plugin must NOT "
                f"be declared for timeout_class "
                f"{_class_name_for_profile(profile)!r} — its profile "
                f"inherits APISIX's default (request_buffering=on)"
            )
    else:
        if not has_pc:
            failures.append(
                f"route {route_id!r}: missing required `proxy-control` "
                f"plugin — timeout_class "
                f"{_class_name_for_profile(profile)!r} needs "
                f"request_buffering={str(profile.request_buffering).lower()}"
            )
        else:
            actual = plugins["proxy-control"].get("request_buffering")
            if actual is not profile.request_buffering:
                failures.append(
                    f"route {route_id!r}: "
                    f"proxy-control.request_buffering must be "
                    f"{profile.request_buffering} per the "
                    f"{_class_name_for_profile(profile)!r} profile, "
                    f"got {actual!r}"
                )

    upstream_id = route.get("upstream_id")
    if upstream_id != "oathkeeper-proxy":
        failures.append(
            f"route {route_id!r}: upstream_id must be "
            f"'oathkeeper-proxy' (every /api/v1/* route funnels "
            f"through Oathkeeper regardless of timeout_class), "
            f"got {upstream_id!r}"
        )

    return failures


def _class_name_for_profile(profile: TimeoutClassProfile) -> str:
    """Reverse-lookup the class name for a profile object.

    Error messages are much more actionable when they name the class
    (`'sse'`) rather than spelling out the profile's numeric tuple.
    """
    for name, p in _APISIX_TIMEOUT_CLASS_PROFILES.items():
        if p is profile:
            return name
    return "<unknown>"  # pragma: no cover — dict is closed-enum today


def verify_apisix_alignment(
    entries: Iterable[ServiceEntry],
    template_text: str,
) -> list[str]:
    """Return a list of alignment failures (empty == clean).

    Asserts the APISIX template agrees with the registry on three
    axes:

    1. Every cookie_session entry transits through the
       ``oathkeeper-proxy`` upstream declared in the template.
    2. ``protected-api`` (the /api/v1/* fallback route carrying every
       ``standard``-class service) honors the `standard` timeout
       profile and the /api/v1 plugin invariants.
    3. Every non-`standard` registry entry has a per-service APISIX
       route whose id/uri/priority/timeout/plugins match the
       corresponding ``TimeoutClassProfile`` exactly.

    The third axis is what Task 7 introduced — before the split, a
    single route had to carry SSE's 1800s read_timeout for every
    REST call (finding #4). Checking it inside the generator (as
    opposed to only in check-contracts.py) means `--check` fails the
    moment a new non-standard entry is added without a matching
    template edit.
    """
    failures: list[str] = []
    entries = list(entries)

    # --- Axis 1: oathkeeper-proxy upstream exists ---------------------
    apisix_nodes = set(_apisix_oathkeeper_nodes(template_text))
    if not apisix_nodes and any(e.auth_mode == "cookie_session" for e in entries):
        failures.append(
            "gateway/apisix.yaml.template: `upstreams` has no "
            "`oathkeeper-proxy` entry; every cookie_session "
            "service in services.yaml relies on it"
        )

    routes_by_id = _apisix_routes_by_id(template_text)

    # --- Axis 2: `protected-api` fallback honors `standard` profile ----
    fallback = routes_by_id.get(_APISIX_FALLBACK_ROUTE_ID)
    if fallback is None:
        # Only surface this if any `standard` entry actually relies on
        # the fallback — in an all-SSE registry (hypothetical future)
        # the fallback could legitimately be absent.
        if any(e.timeout_class == "standard" for e in entries):
            failures.append(
                f"gateway/apisix.yaml.template: route "
                f"{_APISIX_FALLBACK_ROUTE_ID!r} missing; required as "
                f"the /api/v1/* fallback for every `standard`-class "
                f"entry in services.yaml"
            )
    else:
        failures.extend(
            _verify_api_v1_route_shape(
                route_id=_APISIX_FALLBACK_ROUTE_ID,
                route=fallback,
                profile=_APISIX_TIMEOUT_CLASS_PROFILES["standard"],
                expected_uri="/api/v1/*",
                expected_priority=_APISIX_FALLBACK_ROUTE_PRIORITY,
            )
        )

    # --- Axis 3: per-class routes mirror non-standard entries ---------
    expected_priority = (
        _APISIX_FALLBACK_ROUTE_PRIORITY + _APISIX_CLASS_PRIORITY_MARGIN
    )
    for entry in entries:
        expected_id = timeout_class_expected_route_id(entry)
        if expected_id is None:
            # standard-class: covered by axis 2.
            continue
        route = routes_by_id.get(expected_id)
        if route is None:
            failures.append(
                f"services.yaml entry {entry.name!r} declares "
                f"timeout_class={entry.timeout_class!r} but "
                f"gateway/apisix.yaml.template has no route with "
                f"id={expected_id!r}; add the per-class route so "
                f"{entry.path_prefix}* gets the tuned profile "
                f"instead of falling through to the tight "
                f"standard-REST `{_APISIX_FALLBACK_ROUTE_ID}`"
            )
            continue
        failures.extend(
            _verify_api_v1_route_shape(
                route_id=expected_id,
                route=route,
                profile=_APISIX_TIMEOUT_CLASS_PROFILES[entry.timeout_class],
                expected_uri=timeout_class_expected_route_uri(entry),
                expected_priority=expected_priority,
            )
        )

    return failures


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _write_if_changed(path: Path, content: str) -> bool:
    if path.is_file() and path.read_text(encoding="utf-8") == content:
        return False
    path.write_text(content, encoding="utf-8")
    return True


def _diff(current: str, rendered: str, path: Path) -> str:
    rel = path.relative_to(REPO_ROOT)
    return "".join(
        difflib.unified_diff(
            current.splitlines(keepends=True),
            rendered.splitlines(keepends=True),
            fromfile=f"{rel} (on disk)",
            tofile=f"{rel} (rendered)",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="fail iff on-disk rendered files differ from the registry "
        "(default behavior when no flag is given)",
    )
    mode.add_argument(
        "--write",
        action="store_true",
        help="write rendered files to disk",
    )
    args = parser.parse_args(argv)

    try:
        entries = load_registry()
    except (FileNotFoundError, ValueError, NotImplementedError) as exc:
        print(f"registry error: {exc}", file=sys.stderr)
        return 1

    try:
        rendered_rules = render_oathkeeper_rules(entries)
    except (ValueError, NotImplementedError) as exc:
        print(f"render error: {exc}", file=sys.stderr)
        return 1

    template_text = (
        APISIX_TEMPLATE_PATH.read_text(encoding="utf-8")
        if APISIX_TEMPLATE_PATH.is_file()
        else ""
    )
    alignment_failures = verify_apisix_alignment(entries, template_text)
    if alignment_failures:
        for msg in alignment_failures:
            print(f"apisix alignment: {msg}", file=sys.stderr)
        return 1

    # Default to --check when neither flag given (CI-friendly).
    write_mode = args.write

    if write_mode:
        changed = _write_if_changed(OATHKEEPER_RULES_PATH, rendered_rules)
        rel = OATHKEEPER_RULES_PATH.relative_to(REPO_ROOT)
        print(f"{rel}: {'updated' if changed else 'unchanged'}")
        return 0

    # --check / default
    on_disk = (
        OATHKEEPER_RULES_PATH.read_text(encoding="utf-8")
        if OATHKEEPER_RULES_PATH.is_file()
        else ""
    )
    if on_disk == rendered_rules:
        print(
            f"{OATHKEEPER_RULES_PATH.relative_to(REPO_ROOT)}: in sync "
            f"with registry ({len(entries)} service(s))"
        )
        return 0

    print(
        f"{OATHKEEPER_RULES_PATH.relative_to(REPO_ROOT)}: drift vs. "
        f"config/services.yaml — run scripts/generate-gateway-config.py "
        f"--write",
        file=sys.stderr,
    )
    sys.stderr.write(_diff(on_disk, rendered_rules, OATHKEEPER_RULES_PATH))
    return 1


if __name__ == "__main__":
    sys.exit(main())
