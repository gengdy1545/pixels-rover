"""
Tests for Backends API — listing backends, schemas, tables, and columns.
"""

import pytest
from httpx import AsyncClient

from tests.conftest import auth_header, make_access_token


@pytest.mark.asyncio
async def test_list_backends(async_client: AsyncClient):
    """GET /api/v1/analysis/backends should return the registered mock backend."""
    token = make_access_token()
    resp = await async_client.get("/api/v1/analysis/backends", headers=auth_header(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    backends = body["data"]
    assert isinstance(backends, list)
    assert len(backends) == 1
    assert backends[0]["backend_id"] == "mock-backend"
    assert backends[0]["backend_type"] == "mock"
    assert "execute_query" in backends[0]["capabilities"]


@pytest.mark.asyncio
async def test_list_schemas(async_client: AsyncClient):
    """GET /api/v1/analysis/backends/{id}/schemas should return schemas from the mock backend."""
    token = make_access_token()
    resp = await async_client.get(
        "/api/v1/analysis/backends/mock-backend/schemas", headers=auth_header(token)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    assert "test_schema" in body["data"]["schemas"]


@pytest.mark.asyncio
async def test_list_tables(async_client: AsyncClient):
    """GET /api/v1/analysis/backends/{id}/schemas/{schema}/tables should return tables."""
    token = make_access_token()
    resp = await async_client.get(
        "/api/v1/analysis/backends/mock-backend/schemas/test_schema/tables",
        headers=auth_header(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    tables = body["data"]["tables"]
    assert isinstance(tables, list)
    assert len(tables) == 1
    assert tables[0]["name"] == "test_table"
    assert tables[0]["schema_name"] == "test_schema"


@pytest.mark.asyncio
async def test_list_columns(async_client: AsyncClient):
    """GET /api/v1/analysis/backends/{id}/schemas/{schema}/tables/{table}/columns should return columns."""
    token = make_access_token()
    resp = await async_client.get(
        "/api/v1/analysis/backends/mock-backend/schemas/test_schema/tables/test_table/columns",
        headers=auth_header(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    columns = body["data"]["columns"]
    assert isinstance(columns, list)
    assert len(columns) == 3
    col_names = [c["name"] for c in columns]
    assert "id" in col_names
    assert "name" in col_names
    assert "value" in col_names


@pytest.mark.asyncio
async def test_list_backends_without_auth(async_client: AsyncClient):
    """GET /api/v1/analysis/backends without gateway identity must surface GATEWAY_IDENTITY_MISSING."""
    resp = await async_client.get("/api/v1/analysis/backends")
    assert resp.status_code == 500
    body = resp.json()
    assert body["details"]["errorCode"] == "GATEWAY_IDENTITY_MISSING"
    assert body["details"]["category"] == "INTERNAL"
