"""
Interface-level authentication tests for the Backends API (/api/v1/analysis/backends).

Per ``backend.md §3.3`` + ``§6.3.1``, assistant-service never does token
validation itself — identity arrives via the gateway-injected ``X-Auth-*``
headers. Missing / malformed headers therefore produce
``500 + details.errorCode="GATEWAY_IDENTITY_MISSING"`` (category ``INTERNAL``),
not 401/403.
"""

import pytest

from tests.conftest import (
    auth_header,
    make_access_token,
    make_expired_token,
    make_refresh_token,
)

pytestmark = pytest.mark.asyncio


GATEWAY_MISSING_STATUS = 500
GATEWAY_MISSING_ERROR_CODE = "GATEWAY_IDENTITY_MISSING"
GATEWAY_MISSING_CATEGORY = "INTERNAL"


def _assert_gateway_identity_missing(resp) -> None:
    assert resp.status_code == GATEWAY_MISSING_STATUS
    body = resp.json()
    assert body["code"] == GATEWAY_MISSING_STATUS
    assert body["details"]["errorCode"] == GATEWAY_MISSING_ERROR_CODE
    assert body["details"]["category"] == GATEWAY_MISSING_CATEGORY


# ---------------------------------------------------------------------------
# GET /api/v1/analysis/backends — List backends
# ---------------------------------------------------------------------------


class TestListBackendsAuth:
    """Auth tests for GET /api/v1/analysis/backends."""

    async def test_rejects_missing_identity(self, async_client):
        resp = await async_client.get("/api/v1/analysis/backends")
        _assert_gateway_identity_missing(resp)

    async def test_rejects_invalid_identity(self, async_client):
        resp = await async_client.get(
            "/api/v1/analysis/backends",
            headers=auth_header("invalid-identity-payload"),
        )
        _assert_gateway_identity_missing(resp)

    async def test_rejects_expired_identity(self, async_client):
        token = make_expired_token()
        resp = await async_client.get(
            "/api/v1/analysis/backends",
            headers=auth_header(token),
        )
        _assert_gateway_identity_missing(resp)

    async def test_rejects_refresh_shaped_identity(self, async_client):
        token = make_refresh_token()
        resp = await async_client.get(
            "/api/v1/analysis/backends",
            headers=auth_header(token),
        )
        _assert_gateway_identity_missing(resp)

    async def test_rejects_wrong_issuer_identity(self, async_client):
        token = make_access_token(issuer="evil-issuer")
        resp = await async_client.get(
            "/api/v1/analysis/backends",
            headers=auth_header(token),
        )
        _assert_gateway_identity_missing(resp)

    async def test_accepts_valid_token(self, async_client):
        token = make_access_token()
        resp = await async_client.get(
            "/api/v1/analysis/backends",
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200
        assert isinstance(body["data"], list)
        # Should contain our mock backend
        assert len(body["data"]) >= 1
        assert body["data"][0]["backend_id"] == "mock-backend"

    async def test_error_response_contains_request_id(self, async_client):
        resp = await async_client.get("/api/v1/analysis/backends")
        body = resp.json()
        assert "requestId" in body


# ---------------------------------------------------------------------------
# GET /api/v1/analysis/backends/{backend_id}/schemas — List schemas
# ---------------------------------------------------------------------------


class TestListSchemasAuth:
    """Auth tests for GET /api/v1/analysis/backends/{backend_id}/schemas."""

    async def test_rejects_missing_identity(self, async_client):
        resp = await async_client.get("/api/v1/analysis/backends/mock-backend/schemas")
        _assert_gateway_identity_missing(resp)

    async def test_accepts_valid_token(self, async_client):
        token = make_access_token()
        resp = await async_client.get(
            "/api/v1/analysis/backends/mock-backend/schemas",
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200
        assert "schemas" in body["data"]
        assert "test_schema" in body["data"]["schemas"]


# ---------------------------------------------------------------------------
# GET /api/v1/analysis/backends/{backend_id}/schemas/{schema}/tables — List tables
# ---------------------------------------------------------------------------


class TestListTablesAuth:
    """Auth tests for GET /api/v1/analysis/backends/{backend_id}/schemas/{schema}/tables."""

    async def test_rejects_missing_identity(self, async_client):
        resp = await async_client.get("/api/v1/analysis/backends/mock-backend/schemas/test_schema/tables")
        _assert_gateway_identity_missing(resp)

    async def test_accepts_valid_token(self, async_client):
        token = make_access_token()
        resp = await async_client.get(
            "/api/v1/analysis/backends/mock-backend/schemas/test_schema/tables",
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200
        assert "tables" in body["data"]
        assert len(body["data"]["tables"]) >= 1


# ---------------------------------------------------------------------------
# GET /api/v1/analysis/backends/{backend_id}/schemas/{schema}/tables/{table}/columns
# ---------------------------------------------------------------------------


class TestListColumnsAuth:
    """Auth tests for columns endpoint."""

    async def test_rejects_missing_identity(self, async_client):
        resp = await async_client.get(
            "/api/v1/analysis/backends/mock-backend/schemas/test_schema/tables/test_table/columns"
        )
        _assert_gateway_identity_missing(resp)

    async def test_accepts_valid_token(self, async_client):
        token = make_access_token()
        resp = await async_client.get(
            "/api/v1/analysis/backends/mock-backend/schemas/test_schema/tables/test_table/columns",
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200
        assert "columns" in body["data"]
        assert len(body["data"]["columns"]) >= 1
