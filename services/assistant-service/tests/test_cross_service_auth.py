"""
Gateway identity contract tests.

These tests replace the old JWT cross-service checks. The new contract is that
APISIX validates tokens and projects identity into X-Auth-* headers, while the
assistant-service only consumes those headers.
"""

import pytest

from tests.conftest import gateway_identity_headers

pytestmark = pytest.mark.asyncio


class TestGatewayIdentityContract:
    async def test_accepts_minimal_gateway_identity_headers(self, async_client):
        resp = await async_client.get(
            "/api/v1/backends",
            headers=gateway_identity_headers(user_id=42, email="alice@pixelsdb.io", session_id="sess-42"),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200

    async def test_rejects_missing_gateway_email(self, async_client):
        resp = await async_client.get(
            "/api/v1/backends",
            headers={"X-Auth-User-Id": "42"},
        )
        assert resp.status_code == 401
        body = resp.json()
        assert body["code"] == 40100
        assert body["errorCode"] == "AUTHENTICATION_REQUIRED"

    async def test_rejects_non_numeric_gateway_user_id(self, async_client):
        resp = await async_client.get(
            "/api/v1/backends",
            headers={
                "X-Auth-User-Id": "not-a-number",
                "X-Auth-User-Email": "alice@pixelsdb.io",
            },
        )
        assert resp.status_code == 401
        body = resp.json()
        assert body["code"] == 40102
        assert body["errorCode"] == "INVALID_TOKEN"

    async def test_accepts_identity_without_session_id(self, async_client):
        resp = await async_client.get(
            "/api/v1/semantic/metrics",
            headers=gateway_identity_headers(user_id=7, email="alice@pixelsdb.io", session_id=None),
        )
        assert resp.status_code == 200
