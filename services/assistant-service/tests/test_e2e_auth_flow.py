"""
End-to-end auth flow tests for the gateway-header trust model.
"""

from unittest.mock import AsyncMock, patch

import pytest

from tests.conftest import gateway_identity_headers

pytestmark = pytest.mark.asyncio


async def create_thread(async_client, headers: dict[str, str]) -> str:
    resp = await async_client.post(
        "/api/v1/conversations",
        json={"backendId": "mock-backend", "schemaName": "test_schema", "title": "E2E Thread"},
        headers=headers,
    )
    assert resp.status_code == 200
    return resp.json()["data"]["threadId"]


class TestGatewayHeaderJourney:
    async def test_unauthenticated_user_blocked_everywhere(self, async_client):
        protected_endpoints = [
            ("GET", "/api/v1/analysis/backends"),
            ("GET", "/api/v1/conversations"),
            ("GET", "/api/v1/analysis/backends/mock-backend/schemas"),
            ("GET", "/api/v1/semantic/metrics"),
            ("POST", "/api/v1/analysis"),
            ("GET", "/api/v1/analysis/some-session"),
        ]

        for method, path in protected_endpoints:
            if method == "GET":
                resp = await async_client.get(path)
            else:
                resp = await async_client.post(path, json={"question": "test", "threadId": "missing-thread"})
            assert resp.status_code == 401

    async def test_authenticated_user_can_access_read_endpoints(self, async_client):
        headers = gateway_identity_headers(user_id=1, email="e2e-user@pixelsdb.io", session_id="sess-1")

        resp = await async_client.get("/api/v1/analysis/backends", headers=headers)
        assert resp.status_code == 200

        resp = await async_client.get("/api/v1/semantic/metrics", headers=headers)
        assert resp.status_code == 200

    async def test_discover_and_analyze_workflow(self, async_client):
        headers = gateway_identity_headers(user_id=10, email="analyst@pixelsdb.io", session_id="sess-10")
        thread_id = await create_thread(async_client, headers)

        resp = await async_client.get("/api/v1/analysis/backends", headers=headers)
        assert resp.status_code == 200
        backend_id = resp.json()["data"][0]["backend_id"]

        resp = await async_client.get(f"/api/v1/analysis/backends/{backend_id}/schemas", headers=headers)
        assert resp.status_code == 200

        with patch("app.api.analysis.get_analysis_service") as mock_get_svc:
            mock_svc = AsyncMock()

            async def fake_stream(**kwargs):
                yield {"event": "status_change", "data": '{"status":"received"}'}
                yield {"event": "analysis_done", "data": '{"status":"completed"}'}

            mock_svc.run_analysis_stream = fake_stream
            mock_get_svc.return_value = mock_svc

            resp = await async_client.post(
                "/api/v1/analysis",
                json={"question": "Show me data", "threadId": thread_id},
                headers=headers,
            )
            assert resp.status_code == 200


class TestRequestIdPropagation:
    async def test_request_id_in_success_response(self, async_client):
        resp = await async_client.get(
            "/api/v1/analysis/backends",
            headers={**gateway_identity_headers(user_id=1, email="a@b.com"), "X-Request-Id": "e2e-req-001"},
        )
        assert resp.status_code == 200
        assert resp.headers.get("X-Request-Id") == "e2e-req-001"
        assert resp.json()["requestId"] == "e2e-req-001"

    async def test_request_id_in_error_response(self, async_client):
        resp = await async_client.get(
            "/api/v1/analysis/backends",
            headers={"X-Request-Id": "e2e-req-err-001"},
        )
        assert resp.status_code == 401
        assert resp.headers.get("X-Request-Id") == "e2e-req-err-001"
        assert resp.json()["requestId"] == "e2e-req-err-001"
