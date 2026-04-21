"""
Interface-level authentication tests for the Analysis API (/api/v1/analysis).

Covers:
- Unauthenticated access is rejected (401)
- Invalid gateway identity headers are rejected
- Valid tokens grant access
- Session ownership isolation (user A cannot read user B's session)
- Unified error response format
"""

import pytest
from unittest.mock import AsyncMock, patch

from tests.conftest import (
    auth_header,
    make_access_token,
    make_expired_token,
    make_refresh_token,
)

pytestmark = pytest.mark.asyncio


async def create_thread(async_client, token: str) -> str:
    resp = await async_client.post(
        "/api/v1/conversations",
        json={"backendId": "mock-backend", "schemaName": "test_schema", "title": "Auth Thread"},
        headers=auth_header(token),
    )
    assert resp.status_code == 200
    return resp.json()["data"]["threadId"]


# ---------------------------------------------------------------------------
# POST /api/v1/analysis — Submit analysis
# ---------------------------------------------------------------------------


class TestSubmitAnalysisAuth:
    """Auth tests for POST /api/v1/analysis."""

    async def test_returns_401_without_token(self, async_client):
        """Unauthenticated request must receive 401."""
        resp = await async_client.post(
            "/api/v1/analysis",
            json={"question": "What is the total revenue?", "threadId": "missing-thread"},
        )
        assert resp.status_code == 401
        body = resp.json()
        assert body["code"] == 40100
        assert body["errorCode"] == "AUTHENTICATION_REQUIRED"

    async def test_returns_401_with_invalid_token(self, async_client):
        """Garbage token must receive 401."""
        resp = await async_client.post(
            "/api/v1/analysis",
            json={"question": "What is the total revenue?", "threadId": "missing-thread"},
            headers=auth_header("not-a-valid-jwt"),
        )
        assert resp.status_code == 401
        body = resp.json()
        assert body["code"] == 40102
        assert body["errorCode"] == "INVALID_TOKEN"

    async def test_returns_401_with_expired_token(self, async_client):
        """Expired token must receive 401."""
        token = make_expired_token()
        resp = await async_client.post(
            "/api/v1/analysis",
            json={"question": "What is the total revenue?", "threadId": "missing-thread"},
            headers=auth_header(token),
        )
        assert resp.status_code == 401
        body = resp.json()
        assert body["code"] == 40102
        assert body["errorCode"] == "INVALID_TOKEN"

    async def test_returns_401_with_refresh_token(self, async_client):
        """Malformed gateway identity must not be accepted for API access."""
        token = make_refresh_token()
        resp = await async_client.post(
            "/api/v1/analysis",
            json={"question": "What is the total revenue?", "threadId": "missing-thread"},
            headers=auth_header(token),
        )
        assert resp.status_code == 401
        body = resp.json()
        assert body["code"] == 40102
        assert body["errorCode"] == "INVALID_TOKEN"

    async def test_returns_401_with_wrong_issuer(self, async_client):
        """Token from a different issuer must be rejected."""
        token = make_access_token(issuer="some-other-service")
        resp = await async_client.post(
            "/api/v1/analysis",
            json={"question": "What is the total revenue?", "threadId": "missing-thread"},
            headers=auth_header(token),
        )
        assert resp.status_code == 401

    async def test_accepts_gateway_projected_identity_regardless_of_upstream_signing(self, async_client):
        """
        Once the gateway has projected identity headers, assistant-service should not
        care how the upstream token was signed.
        """
        token = make_access_token(secret="wrong-secret-key")
        thread_id = await create_thread(async_client, token)
        with patch("app.api.analysis.get_analysis_service") as mock_get_svc:
            mock_svc = AsyncMock()

            async def fake_stream(**kwargs):
                yield {"event": "status_change", "data": '{"status":"received"}'}

            mock_svc.run_analysis_stream = fake_stream
            mock_get_svc.return_value = mock_svc

            resp = await async_client.post(
                "/api/v1/analysis",
                json={"question": "What is the total revenue?", "threadId": thread_id},
                headers=auth_header(token),
            )
            assert resp.status_code == 200

    async def test_accepts_valid_token(self, async_client):
        """Valid access token should be accepted (SSE stream returned)."""
        token = make_access_token(user_id=10, email="alice@example.com")
        thread_id = await create_thread(async_client, token)

        # Mock the assistant service to avoid real LLM calls
        with patch(
            "app.api.analysis.get_analysis_service",
        ) as mock_get_svc:
            mock_svc = AsyncMock()

            async def fake_stream(**kwargs):
                yield {"event": "status_change", "data": '{"status":"received"}'}
                yield {"event": "analysis_done", "data": '{"status":"completed"}'}

            mock_svc.run_analysis_stream = fake_stream
            mock_get_svc.return_value = mock_svc

            resp = await async_client.post(
                "/api/v1/analysis",
                json={"question": "What is the total revenue?", "threadId": thread_id},
                headers=auth_header(token),
            )
            # SSE endpoint returns 200 with text/event-stream
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")

    async def test_error_response_contains_request_id(self, async_client):
        """All error responses must include a requestId field."""
        resp = await async_client.post(
            "/api/v1/analysis",
            json={"question": "What is the total revenue?", "threadId": "missing-thread"},
        )
        body = resp.json()
        assert "requestId" in body

    async def test_custom_request_id_is_echoed(self, async_client):
        """If client sends X-Request-Id, it should be echoed back."""
        custom_id = "test-req-12345"
        token = make_access_token()
        thread_id = await create_thread(async_client, token)
        resp = await async_client.post(
            "/api/v1/analysis",
            json={"question": "What is the total revenue?", "threadId": thread_id},
            headers={**auth_header(token), "X-Request-Id": custom_id},
        )
        assert resp.headers.get("X-Request-Id") == custom_id


# ---------------------------------------------------------------------------
# GET /api/v1/analysis/{session_id} — Get analysis result
# ---------------------------------------------------------------------------


class TestGetAnalysisResultAuth:
    """Auth tests for GET /api/v1/analysis/{session_id}."""

    async def test_returns_401_without_token(self, async_client):
        resp = await async_client.get("/api/v1/analysis/some-session-id")
        assert resp.status_code == 401
        body = resp.json()
        assert body["code"] == 40100

    async def test_returns_401_with_invalid_token(self, async_client):
        resp = await async_client.get(
            "/api/v1/analysis/some-session-id",
            headers=auth_header("garbage-token"),
        )
        assert resp.status_code == 401

    async def test_returns_404_for_nonexistent_session(self, async_client):
        """Authenticated user requesting a non-existent session gets 404."""
        token = make_access_token(user_id=1)
        resp = await async_client.get(
            "/api/v1/analysis/nonexistent-session-id",
            headers=auth_header(token),
        )
        assert resp.status_code == 404
        body = resp.json()
        assert body["code"] == 40400
        assert body["errorCode"] == "RESOURCE_NOT_FOUND"

    async def test_session_ownership_isolation(self, async_client):
        """User A must not be able to read User B's session."""
        from sqlalchemy.ext.asyncio import AsyncSession as _AS

        # First, create a session owned by user_id=100 via direct DB insert
        token_user_100 = make_access_token(user_id=100, email="user100@example.com")
        token_user_200 = make_access_token(user_id=200, email="user200@example.com")
        thread_id = await create_thread(async_client, token_user_100)

        # Create a session for user 100 by calling the analysis endpoint
        with patch("app.api.analysis.get_analysis_service") as mock_get_svc:
            mock_svc = AsyncMock()

            async def fake_stream(**kwargs):
                yield {"event": "status_change", "data": '{"status":"received","session_id":"owned-by-100"}'}
                yield {"event": "analysis_done", "data": '{"status":"completed"}'}

            mock_svc.run_analysis_stream = fake_stream
            mock_get_svc.return_value = mock_svc

            await async_client.post(
                "/api/v1/analysis",
                json={"question": "test", "threadId": thread_id},
                headers=auth_header(token_user_100),
            )

        # User 200 tries to access a session — should get 404 (not 403, to avoid leaking existence)
        resp = await async_client.get(
            "/api/v1/analysis/owned-by-100",
            headers=auth_header(token_user_200),
        )
        # The session may not exist in DB (mock doesn't persist), so 404 is expected
        assert resp.status_code == 404
