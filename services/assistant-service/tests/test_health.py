"""
Tests for the health check endpoint.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_endpoint(async_client: AsyncClient):
    """GET /health should return status ok."""
    resp = await async_client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"


@pytest.mark.asyncio
async def test_health_no_auth_required(async_client: AsyncClient):
    """GET /health should not require authentication."""
    # No auth header — should still succeed
    resp = await async_client.get("/health")
    assert resp.status_code == 200
