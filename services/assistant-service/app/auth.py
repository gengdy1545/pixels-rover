"""Gateway identity extraction.

Requests reach this service only through the APISIX gateway, which is the
sole issuer of the ``X-Auth-*`` identity headers (see ``backend.md §3.1 / §3.3``).
Missing or malformed headers here therefore indicate an access-plane fault
(bypassed gateway, mis-wired route), not a user-facing auth error — hence
``500 + details.errorCode="GATEWAY_IDENTITY_MISSING"`` rather than 401/403,
The user id is an opaque Kratos identity id and must not be parsed as an
integer by business services.

Architecture-tasks §Task 8 strengthens this contract: on top of the
plaintext X-Auth-* triple, every protected request MUST also carry a
Bearer JWT signed by Oathkeeper's ``id_token`` mutator. When
``OATHKEEPER_JWT_REQUIRED=true`` (every non-test runtime), this module
first verifies the Bearer token via :mod:`app.oathkeeper_jwt`, then
cross-checks the verified claims against the X-Auth-* headers before
returning the :class:`AuthenticatedUser`. Verification failure is 401
``GATEWAY_SUBJECT_UNVERIFIED``; claims/header mismatch is 401
``GATEWAY_SUBJECT_MISMATCH``. The legacy 500 ``GATEWAY_IDENTITY_MISSING``
path survives because "gateway forgot to inject headers" still maps to
"gateway mis-wired", not to "caller unauthenticated".
"""

from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from app.error_codes import GATEWAY_IDENTITY_MISSING, ErrorCategory
from app.oathkeeper_jwt import (
    ensure_claims_match_headers,
    jwt_required_from_env,
    verify_bearer_jwt,
)

USER_ID_HEADER = "X-Auth-User-Id"
USER_EMAIL_HEADER = "X-Auth-User-Email"
SESSION_ID_HEADER = "X-Auth-Session-Id"


@dataclass
class AuthenticatedUser:
    user_id: str
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


async def get_current_user(request: Request) -> AuthenticatedUser:
    # §Task 8 verifier runs FIRST when enabled. Running it before the
    # header-triple parse ensures that a request carrying forged
    # X-Auth-* headers but no Bearer token is rejected with 401
    # SUBJECT_UNVERIFIED — not 500 IDENTITY_MISSING, which would be
    # misleading (the headers ARE present, they're just untrustworthy)
    # and not 200 OK, which was the pre-Task-8 failure mode this whole
    # layer exists to close. See .notes/task-8-subject-integrity.md.
    verified_claims = None
    if jwt_required_from_env():
        verified_claims = verify_bearer_jwt(request)

    user_id_raw = request.headers.get(USER_ID_HEADER)
    email = request.headers.get(USER_EMAIL_HEADER)
    session_id = request.headers.get(SESSION_ID_HEADER)

    if not user_id_raw or not email or not email.strip():
        raise _gateway_identity_missing()

    user_id = user_id_raw.strip()
    if not user_id:
        raise _gateway_identity_missing()

    normalized_email = email.strip()
    normalized_session_id = session_id.strip() if session_id else None
    if normalized_session_id == "":
        normalized_session_id = None

    if verified_claims is not None:
        # Claims/header cross-check. Raises 401 SUBJECT_MISMATCH on
        # any disagreement — see app.oathkeeper_jwt for the exact
        # rules (sub is strict equality; email is strict when both
        # sides declare a value; sid is equality-when-both-present).
        ensure_claims_match_headers(
            verified_claims,
            header_user_id=user_id,
            header_email=normalized_email,
            header_session_id=normalized_session_id,
        )

    return AuthenticatedUser(
        user_id=user_id,
        email=normalized_email,
        session_id=normalized_session_id,
    )
