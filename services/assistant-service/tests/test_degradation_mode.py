"""Tests for the C3 degradation-mode contract (backend.md §6.7).

Covers the narrow invariant that a *transient* ``pixels_analysis`` failure
raised from any handler surfaces as:

- HTTP 503
- ``details.errorCode = "ANALYSIS_DATABASE_UNAVAILABLE"``
- ``details.category = "UPSTREAM"``

and that call-site-specific errors (constraint violations, typos in SQL)
do NOT get dressed up as upstream degradation — they fall through to the
§6.5 unknown-exception safety-net as plain 500 with no ``details`` field,
so they get investigated instead of absorbed into "DB flaky today" noise.
"""

from __future__ import annotations

from typing import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import (
    DataError,
    DBAPIError,
    DisconnectionError,
    IntegrityError,
    InterfaceError,
    OperationalError,
)

from app.api_response import api_error, api_unknown_error
from app.error_codes import ANALYSIS_DATABASE_UNAVAILABLE, ErrorCategory


def _build_handler_only_app() -> FastAPI:
    """A minimal FastAPI app wired with only the handlers under test.

    We deliberately do NOT reuse the full ``create_test_app`` fixture: those
    handlers live in ``conftest.py`` and already mirror production, but
    pulling in the whole app surface (schema bootstrapping, model imports,
    mock backend wiring) would make it hard to assert the mapping is driven
    by the exception type alone. This local app is the production handler
    contract viewed in isolation.
    """
    app = FastAPI()

    @app.exception_handler(OperationalError)
    @app.exception_handler(InterfaceError)
    async def database_unavailable_handler(request, exc: DBAPIError):
        return JSONResponse(
            status_code=503,
            content=api_error(
                http_status=503,
                message="Analysis service is temporarily unavailable",
                error_code=ANALYSIS_DATABASE_UNAVAILABLE,
                category=ErrorCategory.UPSTREAM,
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request, exc):
        return JSONResponse(
            status_code=500,
            content=api_unknown_error(http_status=500, message="Internal server error"),
        )

    router = APIRouter(prefix="/__tests_degradation")

    @router.get("/operational")
    async def raise_operational() -> None:
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    @router.get("/interface")
    async def raise_interface() -> None:
        raise InterfaceError("SELECT 1", {}, Exception("driver disconnected"))

    @router.get("/disconnect")
    async def raise_disconnect() -> None:
        raise DisconnectionError("peer reset")

    @router.get("/integrity")
    async def raise_integrity() -> None:
        raise IntegrityError(
            "INSERT INTO t VALUES (1)", {}, Exception("UNIQUE constraint"),
        )

    @router.get("/data-error")
    async def raise_data_error() -> None:
        raise DataError("SELECT 1", {}, Exception("bad numeric value"))

    app.include_router(router)
    return app


@pytest_asyncio.fixture
async def degradation_client() -> AsyncGenerator[AsyncClient, None]:
    app = _build_handler_only_app()
    # raise_app_exceptions=False mirrors production ASGI (uvicorn / starlette
    # ServerErrorMiddleware return 500 to the client instead of re-raising
    # the exception up into the caller). The test client default re-raises,
    # which would fail our "persistent errors bubble to 500" assertions
    # because the exception would surface as a pytest error before we ever
    # got to inspect the response status code.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


class TestDatabaseUnavailable503:
    """Transient pixels_analysis failure → 503 + ANALYSIS_DATABASE_UNAVAILABLE."""

    @pytest.mark.asyncio
    async def test_operational_error_maps_to_503_upstream(
        self, degradation_client: AsyncClient,
    ) -> None:
        resp = await degradation_client.get("/__tests_degradation/operational")
        assert resp.status_code == 503
        body = resp.json()
        assert body["code"] == 503
        assert body["details"]["errorCode"] == ANALYSIS_DATABASE_UNAVAILABLE
        assert body["details"]["category"] == ErrorCategory.UPSTREAM.value

    @pytest.mark.asyncio
    async def test_interface_error_maps_to_503_upstream(
        self, degradation_client: AsyncClient,
    ) -> None:
        resp = await degradation_client.get("/__tests_degradation/interface")
        assert resp.status_code == 503
        body = resp.json()
        assert body["code"] == 503
        assert body["details"]["errorCode"] == ANALYSIS_DATABASE_UNAVAILABLE
        assert body["details"]["category"] == ErrorCategory.UPSTREAM.value


class TestDatabaseErrorsNotWidened:
    """Persistent-data failures must stay as §6.5 500 safety-net, not 503."""

    @pytest.mark.asyncio
    async def test_integrity_error_is_plain_500_no_503(
        self, degradation_client: AsyncClient,
    ) -> None:
        # IntegrityError = constraint violation → caller bug / schema bug.
        # Must NOT surface as ANALYSIS_DATABASE_UNAVAILABLE.
        resp = await degradation_client.get("/__tests_degradation/integrity")
        assert resp.status_code == 500
        body = resp.json()
        details = body.get("details")
        if details is not None:
            assert details.get("errorCode") != ANALYSIS_DATABASE_UNAVAILABLE

    @pytest.mark.asyncio
    async def test_data_error_is_plain_500_no_503(
        self, degradation_client: AsyncClient,
    ) -> None:
        resp = await degradation_client.get("/__tests_degradation/data-error")
        assert resp.status_code == 500
        body = resp.json()
        details = body.get("details")
        if details is not None:
            assert details.get("errorCode") != ANALYSIS_DATABASE_UNAVAILABLE

    @pytest.mark.asyncio
    async def test_disconnection_error_not_in_503_allowlist(
        self, degradation_client: AsyncClient,
    ) -> None:
        # DisconnectionError is an engine-internal reconnect signal that
        # SQLAlchemy normally handles transparently via pool.Pool; by the
        # time it bubbles out of a request handler something else is wrong.
        # It is intentionally NOT in the 503 allow-list (only OperationalError
        # and InterfaceError are) — this test documents that explicit choice
        # so a future widening of the allow-list is a visible PR diff.
        resp = await degradation_client.get("/__tests_degradation/disconnect")
        assert resp.status_code == 500


class TestErrorCodeIsRegistered:
    """Belt-and-braces: the code string itself must be exported from
    app.error_codes so drifting its value in the module also fails a
    concrete assertion (not only the openapi/contract checks)."""

    def test_constant_value(self) -> None:
        assert ANALYSIS_DATABASE_UNAVAILABLE == "ANALYSIS_DATABASE_UNAVAILABLE"
