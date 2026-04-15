"""
Interface-level authentication tests for the Backends API (/api/v1/backends).

Covers:
- All endpoints require authentication (router-level dependency)
- Invalid / expired / wrong-type tokens are rejected
- Valid tokens grant access to backend listing and metadata
- Unified error response format
"""

import pytest

from tests.conftest import (
    auth_header,
    make_access_token,
    make_expired_token,
    make_refresh_token,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# GET /api/v1/backends — List backends
# ---------------------------------------------------------------------------


class TestListBackendsAuth:
    """Auth tests for GET /api/v1/backends."""

    async def test_returns_401_without_token(self, async_client):
        resp = await async_client.get("/api/v1/backends")
        assert resp.status_code == 401
        body = resp.json()
        assert body["code"] == 40100
        assert body["errorCode"] == "AUTHENTICATION_REQUIRED"

    async def test_returns_401_with_invalid_token(self, async_client):
        resp = await async_client.get(
            "/api/v1/backends",
            headers=auth_header("invalid-jwt-token"),
        )
        assert resp.status_code == 401
        body = resp.json()
        assert body["code"] == 40102
        assert body["errorCode"] == "INVALID_TOKEN"

    async def test_returns_401_with_expired_token(self, async_client):
        token = make_expired_token()
        resp = await async_client.get(
            "/api/v1/backends",
            headers=auth_header(token),
        )
        assert resp.status_code == 401

    async def test_returns_401_with_refresh_token(self, async_client):
        token = make_refresh_token()
        resp = await async_client.get(
            "/api/v1/backends",
            headers=auth_header(token),
        )
        assert resp.status_code == 401
        body = resp.json()
        assert body["code"] == 40103
        assert body["errorCode"] == "INVALID_TOKEN_TYPE"

    async def test_returns_401_with_wrong_issuer(self, async_client):
        token = make_access_token(issuer="evil-issuer")
        resp = await async_client.get(
            "/api/v1/backends",
            headers=auth_header(token),
        )
        assert resp.status_code == 401

    async def test_accepts_valid_token(self, async_client):
        token = make_access_token()
        resp = await async_client.get(
            "/api/v1/backends",
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200
        assert isinstance(body["data"], list)
        # Should contain our mock backend
        assert len(body["data"]) >= 1
        assert body["data"][0]["backend_id"] == "mock-backend"

    async def test_accepts_token_via_cookie(self, async_client):
        token = make_access_token()
        resp = await async_client.get(
            "/api/v1/backends",
            cookies={"access_token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200

    async def test_error_response_contains_request_id(self, async_client):
        resp = await async_client.get("/api/v1/backends")
        body = resp.json()
        assert "requestId" in body


# ---------------------------------------------------------------------------
# GET /api/v1/backends/{backend_id}/schemas — List schemas
# ---------------------------------------------------------------------------


class TestListSchemasAuth:
    """Auth tests for GET /api/v1/backends/{backend_id}/schemas."""

    async def test_returns_401_without_token(self, async_client):
        resp = await async_client.get("/api/v1/backends/mock-backend/schemas")
        assert resp.status_code == 401

    async def test_accepts_valid_token(self, async_client):
        token = make_access_token()
        resp = await async_client.get(
            "/api/v1/backends/mock-backend/schemas",
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200
        assert "schemas" in body["data"]
        assert "test_schema" in body["data"]["schemas"]


# ---------------------------------------------------------------------------
# GET /api/v1/backends/{backend_id}/schemas/{schema}/tables — List tables
# ---------------------------------------------------------------------------


class TestListTablesAuth:
    """Auth tests for GET /api/v1/backends/{backend_id}/schemas/{schema}/tables."""

    async def test_returns_401_without_token(self, async_client):
        resp = await async_client.get("/api/v1/backends/mock-backend/schemas/test_schema/tables")
        assert resp.status_code == 401

    async def test_accepts_valid_token(self, async_client):
        token = make_access_token()
        resp = await async_client.get(
            "/api/v1/backends/mock-backend/schemas/test_schema/tables",
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200
        assert "tables" in body["data"]
        assert len(body["data"]["tables"]) >= 1


# ---------------------------------------------------------------------------
# GET /api/v1/backends/{backend_id}/schemas/{schema}/tables/{table}/columns
# ---------------------------------------------------------------------------


class TestListColumnsAuth:
    """Auth tests for columns endpoint."""

    async def test_returns_401_without_token(self, async_client):
        resp = await async_client.get(
            "/api/v1/backends/mock-backend/schemas/test_schema/tables/test_table/columns"
        )
        assert resp.status_code == 401

    async def test_accepts_valid_token(self, async_client):
        token = make_access_token()
        resp = await async_client.get(
            "/api/v1/backends/mock-backend/schemas/test_schema/tables/test_table/columns",
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200
        assert "columns" in body["data"]
        assert len(body["data"]["columns"]) >= 1
