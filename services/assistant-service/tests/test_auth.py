"""Unit tests for :mod:`app.auth` identity extraction.

Per ``backend.md §3.3`` + ``§6.3.1``, missing / malformed gateway identity
headers must surface as ``500 + details.errorCode="GATEWAY_IDENTITY_MISSING"``
(category ``INTERNAL``) — **not** 401/403 — because the gateway is the sole
issuer of these headers and their absence indicates an access-plane fault.
"""

import unittest

from fastapi import HTTPException
from starlette.requests import Request

from app.auth import get_current_user
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


class AuthTestCase(unittest.TestCase):
    def _assert_gateway_missing(self, exc: HTTPException) -> None:
        self.assertEqual(exc.status_code, 500)
        self.assertEqual(exc.detail["errorCode"], GATEWAY_IDENTITY_MISSING)
        self.assertEqual(exc.detail["category"], ErrorCategory.INTERNAL.value)

    def test_requires_gateway_identity_headers(self):
        with self.assertRaises(HTTPException) as context:
            get_current_user(make_request({}))

        self._assert_gateway_missing(context.exception)

    def test_accepts_valid_gateway_headers(self):
        current_user = get_current_user(
            make_request(
                {
                    "X-Auth-User-Id": "7",
                    "X-Auth-User-Email": "alice@example.com",
                    "X-Auth-Session-Id": "session-7",
                }
            )
        )

        self.assertEqual(current_user.user_id, 7)
        self.assertEqual(current_user.email, "alice@example.com")
        self.assertEqual(current_user.session_id, "session-7")

    def test_rejects_non_numeric_user_id(self):
        with self.assertRaises(HTTPException) as context:
            get_current_user(
                make_request(
                    {
                        "X-Auth-User-Id": "not-a-number",
                        "X-Auth-User-Email": "alice@example.com",
                    }
                )
            )

        self._assert_gateway_missing(context.exception)

    def test_rejects_blank_email(self):
        with self.assertRaises(HTTPException) as context:
            get_current_user(
                make_request(
                    {
                        "X-Auth-User-Id": "7",
                        "X-Auth-User-Email": "   ",
                    }
                )
            )

        self._assert_gateway_missing(context.exception)


if __name__ == "__main__":
    unittest.main()
