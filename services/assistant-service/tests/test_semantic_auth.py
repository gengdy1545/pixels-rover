"""
Interface-level authentication tests for the Semantic API (/api/v1/semantic).

Per ``backend.md §3.3`` + ``§6.3.1``, missing / malformed gateway identity
headers surface as ``500 + details.errorCode="GATEWAY_IDENTITY_MISSING"``
(category ``INTERNAL``), not 401/403.
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


def _assert_gateway_identity_missing(resp) -> None:
    assert resp.status_code == GATEWAY_MISSING_STATUS
    body = resp.json()
    assert body["code"] == GATEWAY_MISSING_STATUS
    assert body["details"]["errorCode"] == GATEWAY_MISSING_ERROR_CODE
    assert body["details"]["category"] == "INTERNAL"


# ---------------------------------------------------------------------------
# GET /api/v1/semantic/metrics — List metrics
# ---------------------------------------------------------------------------


class TestListMetricsAuth:
    """Auth tests for GET /api/v1/semantic/metrics."""

    async def test_rejects_missing_identity(self, async_client):
        resp = await async_client.get("/api/v1/semantic/metrics")
        _assert_gateway_identity_missing(resp)

    async def test_rejects_invalid_identity(self, async_client):
        resp = await async_client.get(
            "/api/v1/semantic/metrics",
            headers=auth_header("bad-token"),
        )
        _assert_gateway_identity_missing(resp)

    async def test_rejects_expired_identity(self, async_client):
        token = make_expired_token()
        resp = await async_client.get(
            "/api/v1/semantic/metrics",
            headers=auth_header(token),
        )
        _assert_gateway_identity_missing(resp)

    async def test_rejects_refresh_shaped_identity(self, async_client):
        token = make_refresh_token()
        resp = await async_client.get(
            "/api/v1/semantic/metrics",
            headers=auth_header(token),
        )
        _assert_gateway_identity_missing(resp)

    async def test_accepts_valid_token(self, async_client):
        token = make_access_token()
        resp = await async_client.get(
            "/api/v1/semantic/metrics",
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200
        assert isinstance(body["data"], list)


# ---------------------------------------------------------------------------
# POST /api/v1/semantic/metrics — Create metric
# ---------------------------------------------------------------------------


class TestCreateMetricAuth:
    """Auth tests for POST /api/v1/semantic/metrics."""

    METRIC_PAYLOAD = {
        "name": "test_revenue",
        "display_name": "Test Revenue",
        "description": "Total revenue for testing",
        "calculation": "SUM(amount)",
        "source_table": "orders",
        "source_schema": "test_schema",
        "backend_id": "mock-backend",
        "data_type": "DOUBLE",
    }

    async def test_rejects_missing_identity(self, async_client):
        resp = await async_client.post(
            "/api/v1/semantic/metrics",
            json=self.METRIC_PAYLOAD,
        )
        _assert_gateway_identity_missing(resp)

    async def test_rejects_invalid_identity(self, async_client):
        resp = await async_client.post(
            "/api/v1/semantic/metrics",
            json=self.METRIC_PAYLOAD,
            headers=auth_header("invalid"),
        )
        _assert_gateway_identity_missing(resp)

    async def test_accepts_valid_token_and_creates_metric(self, async_client):
        token = make_access_token()
        resp = await async_client.post(
            "/api/v1/semantic/metrics",
            json=self.METRIC_PAYLOAD,
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200
        assert body["data"]["name"] == "test_revenue"


# ---------------------------------------------------------------------------
# GET /api/v1/semantic/dimensions — List dimensions
# ---------------------------------------------------------------------------


class TestListDimensionsAuth:
    """Auth tests for GET /api/v1/semantic/dimensions."""

    async def test_rejects_missing_identity(self, async_client):
        resp = await async_client.get("/api/v1/semantic/dimensions")
        _assert_gateway_identity_missing(resp)

    async def test_accepts_valid_token(self, async_client):
        token = make_access_token()
        resp = await async_client.get(
            "/api/v1/semantic/dimensions",
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200
        assert isinstance(body["data"], list)


# ---------------------------------------------------------------------------
# POST /api/v1/semantic/dimensions — Create dimension
# ---------------------------------------------------------------------------


class TestCreateDimensionAuth:
    """Auth tests for POST /api/v1/semantic/dimensions."""

    DIMENSION_PAYLOAD = {
        "name": "test_region",
        "display_name": "Test Region",
        "source_column": "region",
        "source_table": "customers",
        "source_schema": "test_schema",
        "backend_id": "mock-backend",
    }

    async def test_rejects_missing_identity(self, async_client):
        resp = await async_client.post(
            "/api/v1/semantic/dimensions",
            json=self.DIMENSION_PAYLOAD,
        )
        _assert_gateway_identity_missing(resp)

    async def test_accepts_valid_token_and_creates_dimension(self, async_client):
        token = make_access_token()
        resp = await async_client.post(
            "/api/v1/semantic/dimensions",
            json=self.DIMENSION_PAYLOAD,
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200
        assert body["data"]["name"] == "test_region"


# ---------------------------------------------------------------------------
# GET /api/v1/semantic/synonyms — List synonyms
# ---------------------------------------------------------------------------


class TestListSynonymsAuth:
    """Auth tests for GET /api/v1/semantic/synonyms."""

    async def test_rejects_missing_identity(self, async_client):
        resp = await async_client.get("/api/v1/semantic/synonyms")
        _assert_gateway_identity_missing(resp)

    async def test_accepts_valid_token(self, async_client):
        token = make_access_token()
        resp = await async_client.get(
            "/api/v1/semantic/synonyms",
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200
        assert isinstance(body["data"], list)


# ---------------------------------------------------------------------------
# POST /api/v1/semantic/synonyms — Create synonym
# ---------------------------------------------------------------------------


class TestCreateSynonymAuth:
    """Auth tests for POST /api/v1/semantic/synonyms."""

    SYNONYM_PAYLOAD = {
        "term": "revenue",
        "canonical_name": "total_revenue",
        "entity_type": "metric",
    }

    async def test_rejects_missing_identity(self, async_client):
        resp = await async_client.post(
            "/api/v1/semantic/synonyms",
            json=self.SYNONYM_PAYLOAD,
        )
        _assert_gateway_identity_missing(resp)

    async def test_accepts_valid_token_and_creates_synonym(self, async_client):
        token = make_access_token()
        resp = await async_client.post(
            "/api/v1/semantic/synonyms",
            json=self.SYNONYM_PAYLOAD,
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200
        assert body["data"]["term"] == "revenue"
