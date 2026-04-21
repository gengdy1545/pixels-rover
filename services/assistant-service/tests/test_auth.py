import unittest

from fastapi import HTTPException
from starlette.requests import Request

from app.auth import get_current_user
from app.error_codes import (
    AUTHENTICATION_REQUIRED,
    AUTHENTICATION_REQUIRED_NAME,
    INVALID_TOKEN,
    INVALID_TOKEN_NAME,
)


def make_request(headers: dict[str, str]) -> Request:
    raw_headers = [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()]
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/backends",
        "headers": raw_headers,
    }
    return Request(scope)


class AuthTestCase(unittest.TestCase):
    def test_requires_gateway_identity_headers(self):
        with self.assertRaises(HTTPException) as context:
            get_current_user(make_request({}))

        self.assertEqual(context.exception.status_code, 401)
        self.assertEqual(context.exception.detail["code"], AUTHENTICATION_REQUIRED)
        self.assertEqual(context.exception.detail["errorCode"], AUTHENTICATION_REQUIRED_NAME)

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

        self.assertEqual(context.exception.status_code, 401)
        self.assertEqual(context.exception.detail["code"], INVALID_TOKEN)
        self.assertEqual(context.exception.detail["errorCode"], INVALID_TOKEN_NAME)

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

        self.assertEqual(context.exception.status_code, 401)
        self.assertEqual(context.exception.detail["code"], INVALID_TOKEN)
        self.assertEqual(context.exception.detail["errorCode"], INVALID_TOKEN_NAME)


if __name__ == "__main__":
    unittest.main()
