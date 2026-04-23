"""
Gateway identity contract tests.

These tests replace the old cross-service token checks. The new contract is
that Oathkeeper projects identity into X-Auth-* headers, while the
assistant-service only consumes those headers.
"""

import pytest

from tests.conftest import gateway_identity_headers

pytestmark = pytest.mark.asyncio


class TestGatewayIdentityContract:
    async def test_accepts_minimal_gateway_identity_headers(self, async_client):
        resp = await async_client.get(
            "/api/v1/analysis/backends",
            headers=gateway_identity_headers(user_id="kratos-identity-42", email="alice@pixelsdb.io", session_id="sess-42"),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200

    async def test_rejects_missing_gateway_email(self, async_client):
        resp = await async_client.get(
            "/api/v1/analysis/backends",
            headers={"X-Auth-User-Id": "42"},
        )
        assert resp.status_code == 500
        body = resp.json()
        assert body["code"] == 500
        assert body["details"]["errorCode"] == "GATEWAY_IDENTITY_MISSING"
        assert body["details"]["category"] == "INTERNAL"

    async def test_accepts_opaque_gateway_user_id(self, async_client):
        resp = await async_client.get(
            "/api/v1/analysis/backends",
            headers={
                "X-Auth-User-Id": "not-a-number",
                "X-Auth-User-Email": "alice@pixelsdb.io",
            },
        )
        assert resp.status_code == 200

    async def test_accepts_identity_without_session_id(self, async_client):
        resp = await async_client.get(
            "/api/v1/semantic/metrics",
            headers=gateway_identity_headers(user_id=7, email="alice@pixelsdb.io", session_id=None),
        )
        assert resp.status_code == 200
