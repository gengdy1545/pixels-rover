"""Gateway identity extraction.

Requests reach this service only through the APISIX gateway, which is the
sole issuer of the ``X-Auth-*`` identity headers (see ``backend.md §3.1 / §3.3``).
Missing or malformed headers here therefore indicate an access-plane fault
(bypassed gateway, mis-wired route), not a user-facing auth error — hence
``500 + details.errorCode="GATEWAY_IDENTITY_MISSING"`` rather than 401/403,
mirroring ``auth-service``'s ``IdentityHeaderValidationFilter``.
"""

from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from app.error_codes import GATEWAY_IDENTITY_MISSING, ErrorCategory

USER_ID_HEADER = "X-Auth-User-Id"
USER_EMAIL_HEADER = "X-Auth-User-Email"
SESSION_ID_HEADER = "X-Auth-Session-Id"


@dataclass
class AuthenticatedUser:
    user_id: int
    email: str
    session_id: str | None = None


def _gateway_identity_missing() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={
            "message": "Gateway identity headers missing or malformed.",
            "errorCode": GATEWAY_IDENTITY_MISSING,
            "category": ErrorCategory.INTERNAL.value,
        },
    )


def get_current_user(request: Request) -> AuthenticatedUser:
    user_id_raw = request.headers.get(USER_ID_HEADER)
    email = request.headers.get(USER_EMAIL_HEADER)
    session_id = request.headers.get(SESSION_ID_HEADER)

    if not user_id_raw or not email or not email.strip():
        raise _gateway_identity_missing()

    try:
        user_id = int(user_id_raw)
    except (TypeError, ValueError) as exc:
        raise _gateway_identity_missing() from exc

    return AuthenticatedUser(user_id=user_id, email=email, session_id=session_id or None)
