"""Stable string error codes used as ``details.errorCode`` on failure responses.

Naming follows ``backend.md §6.3``:

- Business-domain prefix ``ANALYSIS_*`` for errors originating in this service
  (assistant / analysis / conversation / semantic).
- Infrastructure prefix ``GATEWAY_*`` / ``INTERNAL_*`` for access-plane faults
  (registered in ``backend.md §6.3.1``); these are intentionally written via
  call sites with known semantics (e.g. missing gateway identity headers),
  not inferred from HTTP status codes.

Numeric 5-digit "business codes" (``40000``, ``50000`` ...) have been retired
together with the ``resolve_error_code_name(code)`` reverse-lookup table; every
failure response now writes ``errorCode`` directly at the call site.
"""

from enum import Enum


class ErrorCategory(str, Enum):
    """Coarse failure categories used by ``details.category`` (``backend.md §6.0``).

    The frontend's fallback UX hook keys off these values when the precise
    ``errorCode`` is unrecognized — see ``backend.md §6.3.2``.
    """

    USER_INPUT = "USER_INPUT"
    AUTH = "AUTH"
    RATE_LIMIT = "RATE_LIMIT"
    UPSTREAM = "UPSTREAM"
    INTERNAL = "INTERNAL"


# ---- Infrastructure prefix (backend.md §6.3.1) ----
GATEWAY_IDENTITY_MISSING = "GATEWAY_IDENTITY_MISSING"
INTERNAL_AUTH_FAILED = "INTERNAL_AUTH_FAILED"

# ---- Business-domain prefix ANALYSIS_* (backend.md §6.3) ----

ANALYSIS_INVALID_ARGUMENT = "ANALYSIS_INVALID_ARGUMENT"
"""Generic input validation failure (shape, type, enum, range)."""

ANALYSIS_THREAD_NOT_FOUND = "ANALYSIS_THREAD_NOT_FOUND"
"""Conversation thread referenced by the request does not exist or is not owned by caller."""

ANALYSIS_THREAD_ARCHIVED = "ANALYSIS_THREAD_ARCHIVED"
"""Conversation thread exists but is archived; cannot accept new analysis runs."""

ANALYSIS_SESSION_NOT_FOUND = "ANALYSIS_SESSION_NOT_FOUND"
"""Analysis session does not exist or is not owned by caller."""

ANALYSIS_BACKEND_NOT_FOUND = "ANALYSIS_BACKEND_NOT_FOUND"
"""Requested analysis backend identifier is not registered."""

ANALYSIS_SCHEMA_UNAVAILABLE = "ANALYSIS_SCHEMA_UNAVAILABLE"
"""Schema is not available on the requested analysis backend."""

# ---- Degradation-mode UPSTREAM codes (backend.md §6.7) ----
#
# Each of these maps to ``HTTP 503 + category=UPSTREAM``. The frontend's
# fallback dispatcher (backend.md §6.3.2) keys off the prefix to decide
# whether the whole page degrades or only the affected feature — see the
# per-service failure contract table in backend.md §6.7.

ANALYSIS_DATABASE_UNAVAILABLE = "ANALYSIS_DATABASE_UNAVAILABLE"
"""``pixels_analysis`` database transiently unreachable (connection refused,
pool exhausted, query timeout). New analysis / write-conversation / semantic
CRUD paths fail uniformly; pure-read paths that happen to be served from
memory MAY survive but that is not a contract."""

ANALYSIS_UPSTREAM_UNAVAILABLE = "ANALYSIS_UPSTREAM_UNAVAILABLE"
"""External LLM API unavailable (network / quota / provider 5xx). Affects
the analysis route only — conversation-history browsing and semantic CRUD
keep working because they do not share the LLM downstream dependency."""

ANALYSIS_BACKEND_UNAVAILABLE = "ANALYSIS_BACKEND_UNAVAILABLE"
"""Specific analysis-backend data source (user-configured external DB / file
source) is unreachable. Only requests hitting that backend are affected; other
backends and non-analysis paths keep working. Do NOT widen this to "the
whole ``/api/v1/analysis/*`` domain is 5xx" — that violates the "粒度就低不就高"
rule in backend.md §6.7."""
