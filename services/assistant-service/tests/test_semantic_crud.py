"""
Tests for Semantic API CRUD operations (metrics, dimensions, synonyms).
"""

import pytest
from httpx import AsyncClient

from tests.conftest import auth_header, make_access_token


# ---------------------------------------------------------------------------
# Metrics CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_metric(async_client: AsyncClient):
    """POST /api/v1/semantic/metrics should create a new metric."""
    token = make_access_token()
    payload = {
        "name": "total_revenue",
        "display_name": "Total Revenue",
        "description": "Sum of all revenue",
        "calculation": "SUM(revenue)",
        "source_table": "test_table",
        "source_schema": "test_schema",
        "backend_id": "mock-backend",
        "data_type": "DOUBLE",
    }
    resp = await async_client.post(
        "/api/v1/semantic/metrics", json=payload, headers=auth_header(token)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    assert body["data"]["name"] == "total_revenue"
    assert "id" in body["data"]


@pytest.mark.asyncio
async def test_list_metrics_empty(async_client: AsyncClient):
    """GET /api/v1/semantic/metrics should return empty list initially."""
    token = make_access_token()
    resp = await async_client.get(
        "/api/v1/semantic/metrics", headers=auth_header(token)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    assert isinstance(body["data"], list)


@pytest.mark.asyncio
async def test_create_and_list_metrics(async_client: AsyncClient):
    """Creating a metric should make it appear in the list."""
    token = make_access_token()
    headers = auth_header(token)

    # Create
    payload = {
        "name": "avg_price",
        "calculation": "AVG(price)",
        "source_table": "test_table",
        "source_schema": "test_schema",
        "backend_id": "mock-backend",
    }
    create_resp = await async_client.post(
        "/api/v1/semantic/metrics", json=payload, headers=headers
    )
    assert create_resp.status_code == 200
    created_id = create_resp.json()["data"]["id"]

    # List
    list_resp = await async_client.get(
        "/api/v1/semantic/metrics", headers=headers
    )
    assert list_resp.status_code == 200
    metrics = list_resp.json()["data"]
    assert any(m["id"] == created_id for m in metrics)


# ---------------------------------------------------------------------------
# Dimensions CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_dimension(async_client: AsyncClient):
    """POST /api/v1/semantic/dimensions should create a new dimension."""
    token = make_access_token()
    payload = {
        "name": "region",
        "display_name": "Region",
        "source_column": "region_col",
        "source_table": "test_table",
        "source_schema": "test_schema",
        "backend_id": "mock-backend",
    }
    resp = await async_client.post(
        "/api/v1/semantic/dimensions", json=payload, headers=auth_header(token)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    assert body["data"]["name"] == "region"


@pytest.mark.asyncio
async def test_list_dimensions_empty(async_client: AsyncClient):
    """GET /api/v1/semantic/dimensions should return empty list initially."""
    token = make_access_token()
    resp = await async_client.get(
        "/api/v1/semantic/dimensions", headers=auth_header(token)
    )
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"], list)


@pytest.mark.asyncio
async def test_create_and_list_dimensions(async_client: AsyncClient):
    """Creating a dimension should make it appear in the list."""
    token = make_access_token()
    headers = auth_header(token)

    payload = {
        "name": "category",
        "source_column": "cat_col",
        "source_table": "test_table",
        "source_schema": "test_schema",
        "backend_id": "mock-backend",
    }
    create_resp = await async_client.post(
        "/api/v1/semantic/dimensions", json=payload, headers=headers
    )
    assert create_resp.status_code == 200
    created_id = create_resp.json()["data"]["id"]

    list_resp = await async_client.get(
        "/api/v1/semantic/dimensions", headers=headers
    )
    dims = list_resp.json()["data"]
    assert any(d["id"] == created_id for d in dims)


# ---------------------------------------------------------------------------
# Synonyms CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_synonym(async_client: AsyncClient):
    """POST /api/v1/semantic/synonyms should create a new synonym."""
    token = make_access_token()
    payload = {
        "term": "revenue",
        "canonical_name": "total_revenue",
        "entity_type": "metric",
    }
    resp = await async_client.post(
        "/api/v1/semantic/synonyms", json=payload, headers=auth_header(token)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    assert body["data"]["term"] == "revenue"


@pytest.mark.asyncio
async def test_list_synonyms_empty(async_client: AsyncClient):
    """GET /api/v1/semantic/synonyms should return empty list initially."""
    token = make_access_token()
    resp = await async_client.get(
        "/api/v1/semantic/synonyms", headers=auth_header(token)
    )
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"], list)


@pytest.mark.asyncio
async def test_create_and_list_synonyms(async_client: AsyncClient):
    """Creating a synonym should make it appear in the list."""
    token = make_access_token()
    headers = auth_header(token)

    payload = {
        "term": "sales",
        "canonical_name": "total_revenue",
        "entity_type": "metric",
    }
    create_resp = await async_client.post(
        "/api/v1/semantic/synonyms", json=payload, headers=headers
    )
    assert create_resp.status_code == 200
    created_id = create_resp.json()["data"]["id"]

    list_resp = await async_client.get(
        "/api/v1/semantic/synonyms", headers=headers
    )
    syns = list_resp.json()["data"]
    assert any(s["id"] == created_id for s in syns)
