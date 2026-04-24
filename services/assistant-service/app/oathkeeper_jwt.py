"""Oathkeeper ``id_token`` mutator verifier.

architecture-tasks §Task 8 — subject integrity.

The gateway's cookie_session access rules now emit TWO mutators in a row:

1. ``header`` projects the X-Auth-User-Id / X-Auth-User-Email /
   X-Auth-Session-Id triple (kept for backwards compatibility — every
   existing handler, test, and log line still reads from those
   headers).
2. ``id_token`` signs a short-TTL JWT carrying the same identity claims
   (``sub`` = Kratos identity id, ``email``, ``sid``) and injects it as
   ``Authorization: Bearer <jwt>``.

This module is the backend's half of the handshake: it verifies the
incoming Bearer JWT against Oathkeeper's JWKS, then cross-checks that
the verified claims agree with the X-Auth-* triple. Mismatch or
missing JWT raises ``HTTPException(401, GATEWAY_SUBJECT_UNVERIFIED |
GATEWAY_SUBJECT_MISMATCH)``.

This is the SINGLE module in ``services/assistant-service/app`` that is
allowed to reference ``jwks`` / ``jwks_uri`` / ``PyJWKClient`` symbols —
the ``jwks-sunset-no-regression`` contract check narrows its scope to
exclude this file explicitly. Any future consumer that wants to talk to
the JWKS endpoint MUST route through this module's verifier instead of
reopening the sunsetted abstraction elsewhere.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request, status
from jose import jwt
from jose.exceptions import JWTError

from app.error_codes import (
    ErrorCategory,
    GATEWAY_SUBJECT_MISMATCH,
    GATEWAY_SUBJECT_UNVERIFIED,
)

logger = logging.getLogger(__name__)

AUTHORIZATION_HEADER = "Authorization"
BEARER_PREFIX = "Bearer "

# Environment variable names — kept as module-level constants so
# check-contracts.py can grep-assert they stay in sync with
# config/required-env.yaml's assistant-service block.
ENV_JWKS_URL = "OATHKEEPER_JWKS_URL"
ENV_ISSUER = "OATHKEEPER_JWT_ISSUER"
ENV_AUDIENCE = "OATHKEEPER_JWT_AUDIENCE"
ENV_REQUIRED = "OATHKEEPER_JWT_REQUIRED"

# JWKS cache TTL (seconds). Short enough that a key rotation propagates
# quickly after the fetch succeeds; long enough that cookie_session's
# request rate does not hammer Oathkeeper's /.well-known endpoint.
# Oathkeeper's default id_token key rotation interval is 24h, so 5min
# is conservative on both axes.
_JWKS_CACHE_TTL_SECONDS = 300


def jwt_required_from_env() -> bool:
    """Return True if the Task 8 verifier is enabled for this process.

    The production default is ``true``; ``false`` is reserved for
    pytest / unit-test harnesses that bypass the JWT layer via
    ``ROVER_REQUIRED_ENV_SKIP=1``. There is deliberately no in-code
    default: a missing variable means "verifier disabled", which is
    safe because ``required-env.yaml`` declares this variable
    ``required: true`` — boot fails before we reach this function in
    any real runtime.
    """
    return os.environ.get(ENV_REQUIRED, "").strip().lower() == "true"


def _subject_unverified(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "message": message,
            "errorCode": GATEWAY_SUBJECT_UNVERIFIED,
            "category": ErrorCategory.AUTH.value,
        },
    )


def _subject_mismatch(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "message": message,
            "errorCode": GATEWAY_SUBJECT_MISMATCH,
            "category": ErrorCategory.AUTH.value,
        },
    )


@dataclass
class VerifiedClaims:
    """Minimal projection of a verified Oathkeeper id_token."""

    sub: str
    email: str
    sid: str | None


class _JwksCache:
    """Process-local, TTL-bounded JWKS cache.

    Shared across all requests in the uvicorn worker. Thread-safe (FastAPI
    runs coroutines on a single event loop, but the sync ``fetch`` path is
    still guarded because Starlette's ``BackgroundTasks`` and eventual
    gunicorn multi-worker deploys both cross the boundary).
    """

    def __init__(self, ttl_seconds: int = _JWKS_CACHE_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._fetched_at: float = 0.0
        self._jwks: dict[str, Any] | None = None
        self._source_url: str | None = None

    def get(self, url: str) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            fresh = (
                self._jwks is not None
                and self._source_url == url
                and (now - self._fetched_at) < self._ttl
            )
            if fresh:
                return self._jwks  # type: ignore[return-value]
        # Fetch outside the lock so one slow Oathkeeper does not serialize
        # every request in the worker.
        doc = _http_get_json(url)
        with self._lock:
            self._jwks = doc
            self._fetched_at = time.monotonic()
            self._source_url = url
        return doc

    def invalidate(self) -> None:
        with self._lock:
            self._jwks = None
            self._fetched_at = 0.0
            self._source_url = None


_jwks_cache = _JwksCache()


def _http_get_json(url: str) -> dict[str, Any]:
    """Blocking HTTP GET that returns a JSON document.

    Deliberately avoids adding httpx/aiohttp/requests as a dependency —
    the verifier is on the hot path of every protected request, and
    pulling in an async HTTP client would invite the "I'll await this
    inside get_current_user" refactor that would then require making
    the dependency itself async and cascading the change through every
    route's Depends() call. The JWKS endpoint is intra-cluster, the
    response is a few hundred bytes, and the cache soaks up >99% of
    the requests — stdlib urllib is the right cost/benefit trade.
    """
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            if resp.status != 200:
                raise RuntimeError(
                    f"JWKS endpoint {url} returned HTTP {resp.status}"
                )
            body = resp.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"JWKS endpoint {url} unreachable: {exc}") from exc

    try:
        doc = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"JWKS endpoint {url} returned non-JSON body") from exc

    if not isinstance(doc, dict) or "keys" not in doc:
        raise RuntimeError(
            f"JWKS endpoint {url} returned a body with no `keys` array"
        )
    return doc


def _extract_bearer_token(request: Request) -> str | None:
    header = request.headers.get(AUTHORIZATION_HEADER)
    if not header:
        return None
    if not header.startswith(BEARER_PREFIX):
        return None
    token = header[len(BEARER_PREFIX):].strip()
    return token or None


def verify_bearer_jwt(request: Request) -> VerifiedClaims:
    """Verify the Oathkeeper-issued Bearer JWT on the current request.

    Reads the four OATHKEEPER_JWT_* env variables at call time (not at
    import time) so the test harness can flip ``OATHKEEPER_JWT_REQUIRED``
    per-test without re-importing. Raises HTTPException on any failure
    path; returns a VerifiedClaims on success.
    """
    token = _extract_bearer_token(request)
    if not token:
        raise _subject_unverified(
            "Authorization Bearer token is missing; the gateway "
            "should have injected an Oathkeeper-signed JWT."
        )

    jwks_url = os.environ.get(ENV_JWKS_URL, "").strip()
    issuer = os.environ.get(ENV_ISSUER, "").strip()
    audience = os.environ.get(ENV_AUDIENCE, "").strip()
    if not jwks_url or not issuer or not audience:
        # required-env.yaml declares these required: true, so reaching
        # here means the operator set OATHKEEPER_JWT_REQUIRED=true but
        # forgot one of the supporting vars. Fail closed.
        raise _subject_unverified(
            "Oathkeeper JWT verifier misconfigured: one of "
            "OATHKEEPER_JWKS_URL / OATHKEEPER_JWT_ISSUER / "
            "OATHKEEPER_JWT_AUDIENCE is unset."
        )

    try:
        jwks_doc = _jwks_cache.get(jwks_url)
    except RuntimeError as exc:
        logger.error("JWKS fetch failed: %s", exc)
        raise _subject_unverified(
            "Unable to fetch Oathkeeper JWKS to verify the Bearer token."
        ) from exc

    # jose.jwt.decode understands either a JWKS dict or a single JWK
    # dict; handing it the whole JWKS doc lets it pick the key by kid.
    try:
        claims = jwt.decode(
            token,
            jwks_doc,
            algorithms=["RS256", "ES256"],
            audience=audience,
            issuer=issuer,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except JWTError as exc:
        # Do NOT log the token — it's capabilities. Log the class of
        # failure instead (``jose`` already formats the reason).
        logger.info("Oathkeeper JWT verification failed: %s", exc)
        raise _subject_unverified(
            f"Oathkeeper JWT verification failed: {exc}"
        ) from exc

    sub = str(claims.get("sub") or "").strip()
    if not sub:
        raise _subject_unverified(
            "Oathkeeper JWT has no `sub` claim after verification; "
            "token payload is malformed."
        )
    email = str(claims.get("email") or "").strip()
    sid_raw = claims.get("sid")
    sid = str(sid_raw).strip() if sid_raw else None

    return VerifiedClaims(sub=sub, email=email, sid=sid or None)


def ensure_claims_match_headers(
    claims: VerifiedClaims,
    *,
    header_user_id: str,
    header_email: str,
    header_session_id: str | None,
) -> None:
    """Cross-check that the X-Auth-* header triple matches the verified JWT.

    Mismatch ⇒ 401 GATEWAY_SUBJECT_MISMATCH. This is the leg that closes
    the forged-header vector when the JWT itself is genuine but the
    X-Auth-* headers were injected by a party other than Oathkeeper
    (§Task 8 threat model).
    """
    if claims.sub != header_user_id:
        raise _subject_mismatch(
            "X-Auth-User-Id does not match the verified JWT `sub` claim."
        )
    if claims.email and header_email and claims.email != header_email:
        raise _subject_mismatch(
            "X-Auth-User-Email does not match the verified JWT `email` claim."
        )
    # Session id is optional in both places — enforce equality only
    # when both sides declare a value, so a back-end call path that
    # genuinely has no session (e.g. machine-initiated background job
    # with a signed JWT but no browser session) is not spuriously 401'd.
    if claims.sid and header_session_id and claims.sid != header_session_id:
        raise _subject_mismatch(
            "X-Auth-Session-Id does not match the verified JWT `sid` claim."
        )
