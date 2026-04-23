"""
Interface-level authentication tests for the Analysis API (/api/v1/analysis).

Per ``backend.md §3.3`` + ``§6.3.1``, missing / malformed gateway identity
headers surface as ``500 + details.errorCode="GATEWAY_IDENTITY_MISSING"``
(category ``INTERNAL``), not 401/403. Business 404 on nonexistent sessions
uses ``ANALYSIS_SESSION_NOT_FOUND`` (category ``USER_INPUT``).
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


GATEWAY_MISSING_STATUS = 500
GATEWAY_MISSING_ERROR_CODE = "GATEWAY_IDENTITY_MISSING"


def _assert_gateway_identity_missing(resp) -> None:
    assert resp.status_code == GATEWAY_MISSING_STATUS
    body = resp.json()
    assert body["code"] == GATEWAY_MISSING_STATUS
    assert body["details"]["errorCode"] == GATEWAY_MISSING_ERROR_CODE
    assert body["details"]["category"] == "INTERNAL"


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

    async def test_rejects_missing_identity(self, async_client):
        resp = await async_client.post(
            "/api/v1/analysis",
            json={"question": "What is the total revenue?", "threadId": "missing-thread"},
        )
        _assert_gateway_identity_missing(resp)

    async def test_rejects_invalid_identity(self, async_client):
        resp = await async_client.post(
            "/api/v1/analysis",
            json={"question": "What is the total revenue?", "threadId": "missing-thread"},
            headers=auth_header("not-a-valid-jwt"),
        )
        _assert_gateway_identity_missing(resp)

    async def test_rejects_expired_identity(self, async_client):
        token = make_expired_token()
        resp = await async_client.post(
            "/api/v1/analysis",
            json={"question": "What is the total revenue?", "threadId": "missing-thread"},
            headers=auth_header(token),
        )
        _assert_gateway_identity_missing(resp)

    async def test_rejects_refresh_shaped_identity(self, async_client):
        token = make_refresh_token()
        resp = await async_client.post(
            "/api/v1/analysis",
            json={"question": "What is the total revenue?", "threadId": "missing-thread"},
            headers=auth_header(token),
        )
        _assert_gateway_identity_missing(resp)

    async def test_rejects_wrong_issuer_identity(self, async_client):
        token = make_access_token(issuer="some-other-service")
        resp = await async_client.post(
            "/api/v1/analysis",
            json={"question": "What is the total revenue?", "threadId": "missing-thread"},
            headers=auth_header(token),
        )
        _assert_gateway_identity_missing(resp)

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

    async def test_service_does_not_write_request_id_response_header(self, async_client):
        """Contract (gateway.md §7.5 / §7.6 + backend.md §5): the gateway is
        the sole writer of the outbound X-Request-Id header via a global
        response-rewrite plugin. Business services MUST NOT write the header
        themselves; the inbound id only flows into logs and into the body
        envelope's ``requestId`` field.

        /api/v1/analysis returns a streaming SSE response here, so this test
        only exercises the response-header invariant. Body-side propagation
        on JSON responses is covered by TestRequestIdPropagation in
        test_e2e_auth_flow.py.
        """
        custom_id = "test-req-12345"
        token = make_access_token()
        thread_id = await create_thread(async_client, token)
        resp = await async_client.post(
            "/api/v1/analysis",
            json={"question": "What is the total revenue?", "threadId": thread_id},
            headers={**auth_header(token), "X-Request-Id": custom_id},
        )
        assert resp.headers.get("X-Request-Id") is None


# ---------------------------------------------------------------------------
# GET /api/v1/analysis/{session_id} — Get analysis result
# ---------------------------------------------------------------------------


class TestGetAnalysisResultAuth:
    """Auth tests for GET /api/v1/analysis/{session_id}."""

    async def test_rejects_missing_identity(self, async_client):
        resp = await async_client.get("/api/v1/analysis/some-session-id")
        _assert_gateway_identity_missing(resp)

    async def test_rejects_invalid_identity(self, async_client):
        resp = await async_client.get(
            "/api/v1/analysis/some-session-id",
            headers=auth_header("garbage-token"),
        )
        _assert_gateway_identity_missing(resp)

    async def test_returns_404_for_nonexistent_session(self, async_client):
        """Authenticated user requesting a non-existent session gets 404 with ANALYSIS_SESSION_NOT_FOUND."""
        token = make_access_token(user_id=1)
        resp = await async_client.get(
            "/api/v1/analysis/nonexistent-session-id",
            headers=auth_header(token),
        )
        assert resp.status_code == 404
        body = resp.json()
        assert body["code"] == 404
        assert body["details"]["errorCode"] == "ANALYSIS_SESSION_NOT_FOUND"
        assert body["details"]["category"] == "USER_INPUT"

    async def test_session_ownership_isolation(self, async_client):
        """User A must not be able to read User B's session."""
        token_user_100 = make_access_token(user_id=100, email="user100@example.com")
        token_user_200 = make_access_token(user_id=200, email="user200@example.com")
        thread_id = await create_thread(async_client, token_user_100)

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
        assert resp.status_code == 404
