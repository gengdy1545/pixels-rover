"""Unified API response envelope aligned with ``backend.md §6.0``.

Contract:

- Top-level ``code`` strictly equals the HTTP status code; no 5-digit business codes.
- Success responses carry ``data`` only; failure responses carry ``details`` only.
- Failure responses **must** carry both ``details.errorCode`` (SCREAMING_SNAKE_CASE
  business/infra identifier) and ``details.category`` (:class:`ErrorCategory`).
  The only exception is the §6.5 safety-net for wholly-unknown unhandled exceptions.
- ``apiVersion`` is intentionally absent — API versioning is carried by the URL
  prefix ``/api/v1/``.
"""

from typing import Any, Mapping

from app.error_codes import ErrorCategory
from app.request_id import get_request_id


def api_success(data: Any = None, message: str = "success") -> dict[str, Any]:
    """Build a success response envelope."""
    return {
        "code": 200,
        "message": message,
        "data": data,
        "requestId": get_request_id(),
    }


def api_error(
    http_status: int,
    message: str,
    error_code: str,
    category: ErrorCategory,
    extras: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a failure response envelope with mandatory ``errorCode`` + ``category``.

    This is the only path for typed failures. ``http_status`` must equal the
    HTTP status on the outgoing response (``code`` mirrors it). ``extras``
    may supply additional ``details`` keys (e.g. ``hint``, ``field``), but
    may not override ``errorCode`` / ``category``.
    """
    if not error_code:
        raise ValueError("error_code is required on failure responses")
    if not isinstance(category, ErrorCategory):
        raise TypeError("category must be an ErrorCategory enum value")

    details: dict[str, Any] = {
        "errorCode": error_code,
        "category": category.value,
    }
    if extras:
        for key, value in extras.items():
            if key in ("errorCode", "category"):
                continue
            details[key] = value

    return {
        "code": http_status,
        "message": message,
        "details": details,
        "requestId": get_request_id(),
    }


def api_unknown_error(http_status: int, message: str) -> dict[str, Any]:
    """Build the §6.5 safety-net envelope for wholly-unknown unhandled exceptions.

    This is the **only** path that may emit a failure response without ``details``.
    All other failure call sites must use :func:`api_error`. The accompanying
    log entry must be at ``level=error`` so the incident remains investigable.
    """
    return {
        "code": http_status,
        "message": message,
        "requestId": get_request_id(),
    }
