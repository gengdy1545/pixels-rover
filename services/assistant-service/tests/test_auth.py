"""Unit tests for :mod:`app.auth` identity extraction.

Per ``backend.md §3.3`` + ``§6.3.1``, missing gateway identity
headers must surface as ``500 + details.errorCode="GATEWAY_IDENTITY_MISSING"``
(category ``INTERNAL``) — **not** 401/403 — because the gateway is the sole
issuer of these headers and their absence indicates an access-plane fault.
"""

import unittest
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from app.auth import get_current_user
from app.config import get_settings
from app.error_codes import GATEWAY_IDENTITY_MISSING, ErrorCategory


def make_request(headers: dict[str, str]) -> Request:
    raw_headers = [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()]
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/analysis/backends",
        "headers": raw_headers,
    }
    return Request(scope)


class AuthTestCase(unittest.IsolatedAsyncioTestCase):
    def _assert_gateway_missing(self, exc: HTTPException) -> None:
        self.assertEqual(exc.status_code, 500)
        self.assertEqual(exc.detail["errorCode"], GATEWAY_IDENTITY_MISSING)
        self.assertEqual(exc.detail["category"], ErrorCategory.INTERNAL.value)

    async def test_requires_gateway_identity_headers(self):
        with self.assertRaises(HTTPException) as context:
            await get_current_user(make_request({}))

        self._assert_gateway_missing(context.exception)

    async def test_accepts_valid_gateway_headers(self):
        current_user = await get_current_user(
            make_request(
                {
                    "X-Auth-User-Id": "kratos-identity-7",
                    "X-Auth-User-Email": "alice@example.com",
                    "X-Auth-Session-Id": "session-7",
                }
            )
        )

        self.assertEqual(current_user.user_id, "kratos-identity-7")
        self.assertEqual(current_user.email, "alice@example.com")
        self.assertEqual(current_user.session_id, "session-7")

    async def test_accepts_opaque_user_id(self):
        current_user = await get_current_user(
            make_request(
                {
                    "X-Auth-User-Id": "not-a-number",
                    "X-Auth-User-Email": "alice@example.com",
                    "X-Auth-Session-Id": "session-7",
                }
            )
        )

        self.assertEqual(current_user.user_id, "not-a-number")

    async def test_rejects_blank_email(self):
        with self.assertRaises(HTTPException) as context:
            await get_current_user(
                make_request(
                    {
                        "X-Auth-User-Id": "kratos-identity-7",
                        "X-Auth-User-Email": "   ",
                    }
                )
            )

        self._assert_gateway_missing(context.exception)

    async def test_rejects_forged_headers_without_bearer_when_verification_enabled(self):
        # architecture-tasks §Task 8: with the Oathkeeper JWT verifier
        # enabled, a request that carries plausible X-Auth-* headers but
        # NO Bearer token must be rejected with 401
        # GATEWAY_SUBJECT_UNVERIFIED — regardless of whether the header
        # triple itself parses cleanly. This is the unit-level counterpart
        # to the tests/test_oathkeeper_jwt.py negative suite and to the
        # smoke.sh direct-curl stage.
        get_settings.cache_clear()
        with patch.dict("os.environ", {"OATHKEEPER_JWT_REQUIRED": "true"}):
            with self.assertRaises(HTTPException) as context:
                await get_current_user(
                    make_request(
                        {
                            "X-Auth-User-Id": "kratos-identity-7",
                            "X-Auth-User-Email": "alice@example.com",
                            "X-Auth-Session-Id": "session-7",
                        }
                    )
                )
        get_settings.cache_clear()
        self.assertEqual(context.exception.status_code, 401)
        self.assertEqual(
            context.exception.detail["errorCode"],
            "GATEWAY_SUBJECT_UNVERIFIED",
        )


if __name__ == "__main__":
    unittest.main()
