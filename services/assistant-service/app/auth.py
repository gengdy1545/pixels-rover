from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from app.error_codes import (
    AUTHENTICATION_REQUIRED,
    AUTHENTICATION_REQUIRED_NAME,
    INVALID_TOKEN,
    INVALID_TOKEN_NAME,
)

USER_ID_HEADER = "X-Auth-User-Id"
USER_EMAIL_HEADER = "X-Auth-User-Email"
SESSION_ID_HEADER = "X-Auth-Session-Id"


@dataclass
class AuthenticatedUser:
    user_id: int
    email: str
    session_id: str | None = None


def get_current_user(request: Request) -> AuthenticatedUser:
    user_id_raw = request.headers.get(USER_ID_HEADER)
    email = request.headers.get(USER_EMAIL_HEADER)
    session_id = request.headers.get(SESSION_ID_HEADER)

    if not user_id_raw or not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "message": "Missing gateway identity headers. Requests must pass through the gateway.",
                "code": AUTHENTICATION_REQUIRED,
                "errorCode": AUTHENTICATION_REQUIRED_NAME,
            },
        )

    try:
        user_id = int(user_id_raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "message": "Invalid gateway identity headers.",
                "code": INVALID_TOKEN,
                "errorCode": INVALID_TOKEN_NAME,
            },
        ) from exc

    if not email.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "message": "Invalid gateway identity headers.",
                "code": INVALID_TOKEN,
                "errorCode": INVALID_TOKEN_NAME,
            },
        )

    return AuthenticatedUser(user_id=user_id, email=email, session_id=session_id or None)
