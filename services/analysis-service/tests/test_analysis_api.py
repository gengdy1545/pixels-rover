"""
Tests for Analysis API — submit analysis and get result.
"""

import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch

from tests.conftest import auth_header, make_access_token


@pytest.mark.asyncio
async def test_submit_analysis_returns_sse_stream(async_client: AsyncClient):
    """POST /api/v1/analysis should return an SSE stream (text/event-stream)."""
    token = make_access_token()

    # Mock the analysis service to yield a simple event sequence
    async def mock_stream(**kwargs):
        yield {"event": "status_change", "data": '{"session_id": "sess-1", "status": "running"}'}
        yield {"event": "step", "data": '{"step": 1, "action": "thinking"}'}
        yield {"event": "status_change", "data": '{"session_id": "sess-1", "status": "completed"}'}

    with patch("app.api.analysis.get_analysis_service") as mock_dep:
        mock_service = AsyncMock()
        mock_service.run_analysis_stream = mock_stream
        mock_dep.return_value = mock_service

        # Override the dependency in the test app
        from app.dependencies import get_analysis_service
        async_client._transport.app.dependency_overrides[get_analysis_service] = lambda: mock_service

        resp = await async_client.post(
            "/api/v1/analysis",
            json={"question": "What is the total revenue?"},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        # Verify SSE events are present in the response body
        body = resp.text
        assert "event: status_change" in body
        assert "sess-1" in body


@pytest.mark.asyncio
async def test_submit_analysis_without_auth(async_client: AsyncClient):
    """POST /api/v1/analysis without auth should return 401."""
    resp = await async_client.post(
        "/api/v1/analysis",
        json={"question": "What is the total revenue?"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_submit_analysis_missing_question(async_client: AsyncClient):
    """POST /api/v1/analysis without question field should return 422."""
    token = make_access_token()
    resp = await async_client.post(
        "/api/v1/analysis",
        json={},
        headers=auth_header(token),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_analysis_result_not_found(async_client: AsyncClient):
    """GET /api/v1/analysis/{session_id} for non-existent session should return 404."""
    token = make_access_token()
    resp = await async_client.get(
        "/api/v1/analysis/non-existent-session",
        headers=auth_header(token),
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body["message"] == "Session not found"


@pytest.mark.asyncio
async def test_get_analysis_result_without_auth(async_client: AsyncClient):
    """GET /api/v1/analysis/{session_id} without auth should return 401."""
    resp = await async_client.get("/api/v1/analysis/some-session")
    assert resp.status_code == 401
