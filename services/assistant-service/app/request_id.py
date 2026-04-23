"""Per-request ``X-Request-Id`` handling.

The gateway is the single writer of the outbound ``X-Request-Id`` response
header (gateway.md §7.6); this service only **consumes** the inbound header
and threads it through logs / envelopes / downstream calls.

When the inbound header is missing (gateway misconfig / direct-probe),
``backend.md §5`` prescribes a three-rule fallback:

1.  Emit a single ``request_id_missing=true`` warning per request, carrying
    the triggering route so the incident is investigable.
2.  Use a ``missing-<8-char-rand>`` literal as the local ``requestId`` so the
    single-event log line can still be aggregated. The ``missing-`` prefix
    keeps the fallback value visually distinct from a real gateway-issued id.
3.  Do **not** write the fallback back onto the response header — polluting
    downstream request-id chains masks the underlying gateway fault.
"""

from __future__ import annotations

import secrets
from contextvars import ContextVar

REQUEST_ID_HEADER = "X-Request-Id"
FALLBACK_PREFIX = "missing-"
_FALLBACK_RAND_BYTES = 4  # 4 bytes → 8 hex chars per backend.md §5.

_request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


def set_request_id(request_id: str) -> None:
    _request_id_ctx.set(request_id)


def get_request_id() -> str | None:
    return _request_id_ctx.get()


def clear_request_id() -> None:
    _request_id_ctx.set(None)


def generate_fallback_request_id() -> str:
    """Return ``missing-<8 hex chars>`` per ``backend.md §5`` fallback rule."""
    return FALLBACK_PREFIX + secrets.token_hex(_FALLBACK_RAND_BYTES)


def resolve_request_id(inbound: str | None) -> tuple[str, bool]:
    """Resolve the per-request id and whether it was fall-back-generated.

    Returns ``(request_id, is_fallback)``. Callers are expected to emit a
    ``request_id_missing=true`` warning exactly once when ``is_fallback`` is
    ``True`` (see ``backend.md §5`` rule 1).
    """
    if inbound:
        return inbound, False
    return generate_fallback_request_id(), True


def ensure_request_id(inbound: str | None) -> str:
    """Backward-compatible helper; returns only the string form.

    Prefer :func:`resolve_request_id` in middleware / filter code so the
    "one warning per fallback" rule can be enforced; this thin shim exists
    for call sites that do not care about the signal (e.g. tests or tasks
    already inside a context).
    """
    request_id, _is_fallback = resolve_request_id(inbound)
    return request_id
