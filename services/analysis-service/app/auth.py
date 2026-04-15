import base64
import binascii
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import Settings, get_settings
from app.error_codes import (
    AUTHENTICATION_REQUIRED,
    AUTHENTICATION_REQUIRED_NAME,
    INVALID_TOKEN,
    INVALID_TOKEN_NAME,
    INVALID_TOKEN_TYPE,
    INVALID_TOKEN_TYPE_NAME,
)

ACCESS_TOKEN_COOKIE = "access_token"

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class AuthenticatedUser:
    user_id: int
    email: str
    token_type: str


def _resolve_jwt_key(secret: str) -> bytes:
    try:
        return base64.b64decode(secret, validate=True)
    except (binascii.Error, ValueError):
        return secret.encode("utf-8")


def _resolve_verification_key(settings: Settings, token: str) -> tuple[Any, str]:
    header = jwt.get_unverified_header(token)
    algorithm = header.get("alg", settings.jwt_algorithm)

    if algorithm == "RS256":
        kid = header.get("kid")
        public_key = settings.get_jwt_public_keys().get(kid)
        if not public_key:
            raise JWTError("Unknown or missing key id")
        return public_key, algorithm

    if algorithm == "HS256":
        return _resolve_jwt_key(settings.jwt_secret), algorithm

    raise JWTError("Unsupported JWT algorithm")


def _extract_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
) -> str | None:
    """Extract access token from Authorization header first, then fall back to Cookie."""
    # 1. Authorization: Bearer <token>
    if credentials is not None and credentials.scheme.lower() == "bearer":
        return credentials.credentials

    # 2. HttpOnly Cookie (set by Java Auth Service)
    return request.cookies.get(ACCESS_TOKEN_COOKIE)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> AuthenticatedUser:
    token = _extract_token(request, credentials)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "message": "Missing bearer token",
                "code": AUTHENTICATION_REQUIRED,
                "errorCode": AUTHENTICATION_REQUIRED_NAME,
            },
        )

    try:
        verification_key, algorithm = _resolve_verification_key(settings, token)
        payload = jwt.decode(
            token,
            verification_key,
            algorithms=[algorithm],
            issuer=settings.jwt_issuer,
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "message": "Invalid or expired token",
                "code": INVALID_TOKEN,
                "errorCode": INVALID_TOKEN_NAME,
            },
        ) from exc

    token_type = payload.get("type")
    email = payload.get("sub")
    user_id = payload.get("uid")

    if token_type != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "message": "Invalid token type",
                "code": INVALID_TOKEN_TYPE,
                "errorCode": INVALID_TOKEN_TYPE_NAME,
            },
        )
    if not email or user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "message": "Invalid token payload",
                "code": INVALID_TOKEN,
                "errorCode": INVALID_TOKEN_NAME,
            },
        )

    return AuthenticatedUser(user_id=int(user_id), email=email, token_type=token_type)
