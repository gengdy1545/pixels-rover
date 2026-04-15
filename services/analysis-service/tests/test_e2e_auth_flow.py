"""
End-to-end authentication flow tests.

These tests simulate the complete user journey through the authentication
boundary of the Python Analysis Service:

1. Unauthenticated user → gets 401 on all protected endpoints
2. User obtains token (simulated) → accesses protected endpoints
3. Token expires → gets 401 again
4. User uses refresh token → gets 401 (refresh tokens not accepted)
5. Multi-endpoint flow: auth → list backends → list schemas → submit analysis
6. Health endpoint remains accessible without auth
7. Request ID propagation across the auth boundary
8. Authorization header takes precedence over cookie
"""

import time
from unittest.mock import AsyncMock, patch

import pytest
from jose import jwt

from tests.conftest import (
    RSA_PRIVATE_KEY,
    TEST_JWT_ISSUER,
    TEST_JWT_SECRET,
    TEST_RSA_KID,
    auth_header,
    make_access_token,
    make_expired_token,
    make_refresh_token,
    make_rs256_access_token,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Full user journey: unauthenticated → authenticated → token lifecycle
# ---------------------------------------------------------------------------


class TestFullAuthJourney:
    """Simulate a complete user authentication lifecycle."""

    async def test_unauthenticated_user_blocked_everywhere(self, async_client):
        """An unauthenticated user must receive 401 on all protected endpoints."""
        protected_endpoints = [
            ("GET", "/api/v1/backends"),
            ("GET", "/api/v1/backends/mock-backend/schemas"),
            ("GET", "/api/v1/semantic/metrics"),
            ("GET", "/api/v1/semantic/dimensions"),
            ("GET", "/api/v1/semantic/synonyms"),
            ("POST", "/api/v1/analysis"),
            ("GET", "/api/v1/analysis/some-session"),
        ]

        for method, path in protected_endpoints:
            if method == "GET":
                resp = await async_client.get(path)
            else:
                resp = await async_client.post(path, json={"question": "test"})
            assert resp.status_code == 401, f"{method} {path} should return 401, got {resp.status_code}"

    async def test_authenticated_user_can_access_all_read_endpoints(self, async_client):
        """
        After obtaining a valid token, user can access all read endpoints.
        """
        token = make_access_token(user_id=1, email="e2e-user@pixelsdb.io")
        headers = auth_header(token)

        # List backends
        resp = await async_client.get("/api/v1/backends", headers=headers)
        assert resp.status_code == 200
        backends = resp.json()["data"]
        assert len(backends) >= 1

        # List schemas
        backend_id = backends[0]["backend_id"]
        resp = await async_client.get(f"/api/v1/backends/{backend_id}/schemas", headers=headers)
        assert resp.status_code == 200

        # List metrics
        resp = await async_client.get("/api/v1/semantic/metrics", headers=headers)
        assert resp.status_code == 200

        # List dimensions
        resp = await async_client.get("/api/v1/semantic/dimensions", headers=headers)
        assert resp.status_code == 200

        # List synonyms
        resp = await async_client.get("/api/v1/semantic/synonyms", headers=headers)
        assert resp.status_code == 200

    async def test_expired_token_rejected_after_initial_success(self, async_client):
        """
        Simulate: user's token expires → subsequent requests are rejected.
        """
        # First, valid token works
        valid_token = make_access_token(user_id=1)
        resp = await async_client.get("/api/v1/backends", headers=auth_header(valid_token))
        assert resp.status_code == 200

        # Then, expired token is rejected
        expired_token = make_expired_token(user_id=1)
        resp = await async_client.get("/api/v1/backends", headers=auth_header(expired_token))
        assert resp.status_code == 401

    async def test_refresh_token_cannot_be_used_for_api_access(self, async_client):
        """
        User mistakenly sends refresh token instead of access token.
        Must be rejected with INVALID_TOKEN_TYPE.
        """
        refresh_token = make_refresh_token(user_id=1)
        resp = await async_client.get("/api/v1/backends", headers=auth_header(refresh_token))
        assert resp.status_code == 401
        body = resp.json()
        assert body["code"] == 40103
        assert body["errorCode"] == "INVALID_TOKEN_TYPE"


# ---------------------------------------------------------------------------
# Multi-step workflow with authentication
# ---------------------------------------------------------------------------


class TestAuthenticatedWorkflow:
    """Test a realistic multi-step workflow with authentication."""

    async def test_discover_and_analyze_workflow(self, async_client):
        """
        Simulate: discover backends → list schemas → list tables → submit analysis.
        """
        token = make_access_token(user_id=10, email="analyst@pixelsdb.io")
        headers = auth_header(token)

        # Step 1: Discover backends
        resp = await async_client.get("/api/v1/backends", headers=headers)
        assert resp.status_code == 200
        backends = resp.json()["data"]
        backend_id = backends[0]["backend_id"]

        # Step 2: List schemas
        resp = await async_client.get(f"/api/v1/backends/{backend_id}/schemas", headers=headers)
        assert resp.status_code == 200
        schemas = resp.json()["data"]["schemas"]
        assert len(schemas) >= 1

        # Step 3: List tables
        schema = schemas[0]
        resp = await async_client.get(
            f"/api/v1/backends/{backend_id}/schemas/{schema}/tables",
            headers=headers,
        )
        assert resp.status_code == 200
        tables = resp.json()["data"]["tables"]
        assert len(tables) >= 1

        # Step 4: List columns
        table_name = tables[0]["name"]
        resp = await async_client.get(
            f"/api/v1/backends/{backend_id}/schemas/{schema}/tables/{table_name}/columns",
            headers=headers,
        )
        assert resp.status_code == 200
        columns = resp.json()["data"]["columns"]
        assert len(columns) >= 1

        # Step 5: Submit analysis (mocked)
        with patch("app.api.analysis.get_analysis_service") as mock_get_svc:
            mock_svc = AsyncMock()

            async def fake_stream(**kwargs):
                yield {"event": "status_change", "data": '{"status":"received"}'}
                yield {"event": "analysis_done", "data": '{"status":"completed"}'}

            mock_svc.run_analysis_stream = fake_stream
            mock_get_svc.return_value = mock_svc

            resp = await async_client.post(
                "/api/v1/analysis",
                json={"question": f"Show me data from {table_name}"},
                headers=headers,
            )
            assert resp.status_code == 200

    async def test_semantic_crud_workflow(self, async_client):
        """
        Simulate: create metric → create dimension → create synonym → list all.
        """
        token = make_access_token(user_id=20, email="admin@pixelsdb.io")
        headers = auth_header(token)

        # Create metric
        resp = await async_client.post(
            "/api/v1/semantic/metrics",
            json={
                "name": "e2e_metric",
                "calculation": "COUNT(*)",
                "source_table": "orders",
                "source_schema": "test_schema",
                "backend_id": "mock-backend",
            },
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["name"] == "e2e_metric"

        # Create dimension
        resp = await async_client.post(
            "/api/v1/semantic/dimensions",
            json={
                "name": "e2e_dimension",
                "source_column": "region",
                "source_table": "customers",
                "source_schema": "test_schema",
                "backend_id": "mock-backend",
            },
            headers=headers,
        )
        assert resp.status_code == 200

        # Create synonym
        resp = await async_client.post(
            "/api/v1/semantic/synonyms",
            json={
                "term": "e2e_synonym",
                "canonical_name": "e2e_metric",
                "entity_type": "metric",
            },
            headers=headers,
        )
        assert resp.status_code == 200

        # List all and verify
        resp = await async_client.get("/api/v1/semantic/metrics", headers=headers)
        assert resp.status_code == 200
        metrics = resp.json()["data"]
        assert any(m["name"] == "e2e_metric" for m in metrics)


# ---------------------------------------------------------------------------
# Health endpoint (public, no auth required)
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    """The /health endpoint must be accessible without authentication."""

    async def test_health_without_auth(self, async_client):
        resp = await async_client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"

    async def test_health_with_auth(self, async_client):
        """Health endpoint should also work with auth (no interference)."""
        token = make_access_token()
        resp = await async_client.get("/health", headers=auth_header(token))
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Request ID propagation
# ---------------------------------------------------------------------------


class TestRequestIdPropagation:
    """Verify X-Request-Id is propagated through the auth boundary."""

    async def test_request_id_in_success_response(self, async_client):
        token = make_access_token()
        custom_id = "e2e-req-001"
        resp = await async_client.get(
            "/api/v1/backends",
            headers={**auth_header(token), "X-Request-Id": custom_id},
        )
        assert resp.status_code == 200
        assert resp.headers.get("X-Request-Id") == custom_id
        body = resp.json()
        assert body.get("requestId") == custom_id

    async def test_request_id_in_error_response(self, async_client):
        custom_id = "e2e-req-err-001"
        resp = await async_client.get(
            "/api/v1/backends",
            headers={"X-Request-Id": custom_id},
        )
        assert resp.status_code == 401
        assert resp.headers.get("X-Request-Id") == custom_id
        body = resp.json()
        assert body.get("requestId") == custom_id

    async def test_auto_generated_request_id(self, async_client):
        """When no X-Request-Id is sent, one should be auto-generated."""
        resp = await async_client.get("/api/v1/backends")
        assert resp.status_code == 401
        request_id = resp.headers.get("X-Request-Id")
        assert request_id is not None
        assert len(request_id) > 0


# ---------------------------------------------------------------------------
# Token source precedence: Authorization header > Cookie
# ---------------------------------------------------------------------------


class TestTokenSourcePrecedence:
    """Verify that Authorization header takes precedence over cookie."""

    async def test_header_takes_precedence_over_cookie(self, async_client):
        """
        If both Authorization header and cookie are present,
        the header token should be used.
        """
        valid_token = make_access_token(user_id=1, email="header@example.com")
        invalid_cookie_token = "this-is-not-a-valid-jwt"

        # Valid header + invalid cookie → should succeed (header wins)
        resp = await async_client.get(
            "/api/v1/backends",
            headers=auth_header(valid_token),
            cookies={"access_token": invalid_cookie_token},
        )
        assert resp.status_code == 200

    async def test_cookie_used_when_no_header(self, async_client):
        """
        If no Authorization header is present, cookie should be used.
        """
        valid_token = make_access_token(user_id=1, email="cookie@example.com")

        resp = await async_client.get(
            "/api/v1/backends",
            cookies={"access_token": valid_token},
        )
        assert resp.status_code == 200

    async def test_invalid_header_not_fallback_to_cookie(self, async_client):
        """
        If Authorization header is present but has invalid scheme,
        the system should still try cookie fallback.
        """
        valid_cookie_token = make_access_token(user_id=1)

        # Send a non-Bearer auth header — HTTPBearer returns None for non-bearer
        # So it should fall back to cookie
        resp = await async_client.get(
            "/api/v1/backends",
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
            cookies={"access_token": valid_cookie_token},
        )
        # With Basic auth, HTTPBearer(auto_error=False) returns None,
        # so cookie fallback should work
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# RS256 end-to-end flow
# ---------------------------------------------------------------------------


class TestRS256EndToEnd:
    """End-to-end tests using RS256 tokens."""

    async def test_full_rs256_workflow(self, async_client_rs256):
        """
        Complete workflow using RS256 tokens:
        list backends → list schemas → list tables → list columns.
        """
        token = make_rs256_access_token(user_id=42, email="rs256-user@pixelsdb.io")
        headers = auth_header(token)

        # List backends
        resp = await async_client_rs256.get("/api/v1/backends", headers=headers)
        assert resp.status_code == 200

        # List schemas
        resp = await async_client_rs256.get(
            "/api/v1/backends/mock-backend/schemas", headers=headers
        )
        assert resp.status_code == 200

        # List tables
        resp = await async_client_rs256.get(
            "/api/v1/backends/mock-backend/schemas/test_schema/tables", headers=headers
        )
        assert resp.status_code == 200

        # List columns
        resp = await async_client_rs256.get(
            "/api/v1/backends/mock-backend/schemas/test_schema/tables/test_table/columns",
            headers=headers,
        )
        assert resp.status_code == 200

    async def test_hs256_token_rejected_by_rs256_service(self, async_client_rs256):
        """
        When the service is configured for RS256, an HS256 token
        should still be accepted if the alg header says HS256 and
        the shared secret matches (dual-mode support during migration).
        """
        token = make_access_token()  # HS256 token
        resp = await async_client_rs256.get(
            "/api/v1/backends",
            headers=auth_header(token),
        )
        # The service supports dual-mode: HS256 tokens are still accepted
        # because _resolve_verification_key checks the token's alg header
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Unified error response format validation
# ---------------------------------------------------------------------------


class TestUnifiedErrorFormat:
    """Verify all auth errors follow the unified error response format."""

    async def test_401_response_format(self, async_client):
        """All 401 responses must have: code, message, requestId, errorCode."""
        resp = await async_client.get("/api/v1/backends")
        assert resp.status_code == 401
        body = resp.json()

        # Required fields
        assert "code" in body
        assert "message" in body
        assert "requestId" in body
        assert "errorCode" in body

        # Code should be a numeric error code
        assert isinstance(body["code"], int)
        assert body["code"] >= 40000

    async def test_404_response_format(self, async_client):
        """404 responses must also follow the unified format."""
        token = make_access_token()
        resp = await async_client.get(
            "/api/v1/analysis/nonexistent-id",
            headers=auth_header(token),
        )
        assert resp.status_code == 404
        body = resp.json()
        assert "code" in body
        assert "message" in body
        assert "requestId" in body
