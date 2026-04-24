"""
Shared test fixtures for Python assistant-service integration & auth tests.

Provides:
- Async TestClient backed by an in-memory SQLite database
- Gateway identity header helpers
- Mock storage backend and assistant service
"""

import asyncio
import base64
import json
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool

from app.api_response import api_error, api_unknown_error
from app.config import Settings
from app.error_codes import (
    ANALYSIS_DATABASE_UNAVAILABLE,
    ANALYSIS_INVALID_ARGUMENT,
    ErrorCategory,
)
from app.request_id import REQUEST_ID_HEADER, clear_request_id, resolve_request_id, set_request_id
from app.schemas.backend import BackendCapability, ColumnInfo, QueryResult, TableInfo
from app.storage.base import StorageBackend
from app.storage.registry import BackendRegistry

# Tests intentionally keep SQLite as a lightweight fixture even though runtime
# now defaults to MySQL.
os.environ.setdefault("ROVER_DATABASE_URL", "sqlite+aiosqlite://")
os.environ.setdefault("ROVER_AUTH_HEADER_VERIFY", "false")

# ---------------------------------------------------------------------------
# Test settings
# ---------------------------------------------------------------------------

TEST_IDENTITY_ISSUER = "pixels-rover-oathkeeper-test"


def make_test_settings(*, algorithm: str = "HS256") -> Settings:
    """Build a Settings instance suitable for testing."""
    _ = algorithm
    return Settings(
        database_url="sqlite+aiosqlite://",
        duckdb_path=":memory:",
    )


# ---------------------------------------------------------------------------
# Synthetic identity projection helpers
# ---------------------------------------------------------------------------


def _encode_gateway_token(payload: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def _decode_gateway_token(token: str) -> dict | None:
    try:
        padded = token + "=" * (-len(token) % 4)
        return json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except Exception:
        return None


def gateway_identity_headers(
    *,
    user_id: int | str = 1,
    email: str = "testuser@example.com",
    session_id: str | None = "gateway-session-1",
) -> dict[str, str]:
    headers = {
        "X-Auth-User-Id": str(user_id),
        "X-Auth-User-Email": email,
    }
    if session_id is not None:
        headers["X-Auth-Session-Id"] = session_id
    return headers


def make_access_token(
    *,
    user_id: int | str = 1,
    email: str = "testuser@example.com",
    issuer: str = TEST_IDENTITY_ISSUER,
    secret: str = "unused",
    algorithm: str = "HS256",
    extra_claims: dict | None = None,
    headers: dict | None = None,
) -> str:
    """Create a synthetic payload that the test helper projects into identity headers."""
    _ = secret, algorithm, headers
    payload = {
        "sub": email,
        "uid": user_id,
        "type": "access",
        "iss": issuer,
        "sid": f"session-{user_id}",
    }
    if extra_claims:
        payload.update(extra_claims)
    return _encode_gateway_token(payload)


def make_expired_token(
    *,
    user_id: int | str = 1,
    email: str = "testuser@example.com",
    secret: str = "unused",
) -> str:
    _ = secret
    payload = {
        "sub": email,
        "uid": user_id,
        "type": "access",
        "iss": TEST_IDENTITY_ISSUER,
        "exp": 0,
        "sid": f"session-{user_id}",
    }
    return _encode_gateway_token(payload)


def make_refresh_token(
    *,
    user_id: int | str = 1,
    email: str = "testuser@example.com",
    secret: str = "unused",
) -> str:
    """Create a rejected non-access payload for gateway identity tests."""
    _ = secret
    payload = {
        "sub": email,
        "uid": user_id,
        "type": "refresh",
        "iss": TEST_IDENTITY_ISSUER,
        "sid": f"session-{user_id}",
    }
    return _encode_gateway_token(payload)


def auth_header(token: str) -> dict[str, str]:
    """Simulate Oathkeeper projecting a validated session into identity headers."""
    payload = _decode_gateway_token(token)
    if not payload:
        return {
            "X-Auth-User-Id": "",
            "X-Auth-User-Email": "",
        }

    if payload.get("iss") != TEST_IDENTITY_ISSUER:
        return {
            "X-Auth-User-Id": "",
            "X-Auth-User-Email": "",
        }

    if payload.get("type") != "access":
        return {
            "X-Auth-User-Id": "",
            "X-Auth-User-Email": "",
        }

    if payload.get("exp") == 0:
        return {
            "X-Auth-User-Id": "",
            "X-Auth-User-Email": "",
        }

    return gateway_identity_headers(
        user_id=payload.get("uid", 1),
        email=payload.get("sub", "testuser@example.com"),
        session_id=payload.get("sid"),
    )


# ---------------------------------------------------------------------------
# Mock storage backend
# ---------------------------------------------------------------------------


class MockStorageBackend(StorageBackend):
    """A minimal in-memory storage backend for testing."""

    @property
    def backend_id(self) -> str:
        return "mock-backend"

    @property
    def backend_type(self) -> str:
        return "mock"

    @property
    def capabilities(self) -> set[BackendCapability]:
        return {
            BackendCapability.EXECUTE_QUERY,
            BackendCapability.GET_SCHEMAS,
            BackendCapability.GET_TABLES,
            BackendCapability.GET_COLUMNS,
        }

    async def get_schemas(self) -> list[str]:
        return ["test_schema"]

    async def get_tables(self, schema: str) -> list[TableInfo]:
        return [TableInfo(name="test_table", schema_name=schema, row_count=100)]

    async def get_columns(self, schema: str, table: str) -> list[ColumnInfo]:
        return [
            ColumnInfo(name="id", data_type="INTEGER", is_nullable=False),
            ColumnInfo(name="name", data_type="VARCHAR", is_nullable=True),
            ColumnInfo(name="value", data_type="DOUBLE", is_nullable=True),
        ]

    async def execute_query(self, sql: str, schema: str, limit: int = 1000) -> QueryResult:
        return QueryResult(
            columns=["id", "name", "value"],
            rows=[[1, "test", 42.0]],
            row_count=1,
            execution_time_ms=5,
        )


# ---------------------------------------------------------------------------
# Lightweight test app factory (avoids heavy lifespan / LLM imports)
# ---------------------------------------------------------------------------


def create_test_app(settings: Settings, backend_registry: BackendRegistry, db_session_factory) -> FastAPI:
    """
    Build a minimal FastAPI app that mirrors the production app's routers,
    middleware, and exception handlers — but without the heavy lifespan
    (no DuckDB seed, no LLM client init, no real database init).
    """
    from app.api.analysis import router as analysis_router
    from app.api.conversations import router as conversations_router
    from app.api.semantic import router as semantic_router
    from app.api.backends import router as backends_router
    from app.config import get_settings
    from app.database import get_db
    from app.dependencies import get_backend_registry

    @asynccontextmanager
    async def noop_lifespan(app: FastAPI):
        yield

    app = FastAPI(title="Test App", lifespan=noop_lifespan)

    # --- Request-ID middleware (same as production; see app/main.py) ---
    # The middleware is consume-only: gateway is the sole writer of the
    # outbound X-Request-Id header (gateway.md §7.5). The test harness
    # mirrors that invariant so contract tests catch any regression that
    # re-introduces response-side writes. It also mirrors the backend.md §5
    # rule 1 "one warning per fallback" behavior so tests/test_request_id.py
    # can assert on the warning line.
    #
    # Counter parity — architecture-tasks §Task 15: the warning and the
    # Prometheus counter bump MUST happen at the same point. Mirroring
    # only the warning here (and not the counter) would let a future
    # regression silently break the alert pipeline while leaving the
    # test suite green. We import the module-level singleton from
    # app.metrics (not app.main) because the latter has create_app()
    # side effects at module bottom — validate_or_die() + FastAPI app
    # construction — which would fire during test collection and trip
    # on the missing /app/config bind-mount. app.metrics is a pure
    # singleton module, so importing it is side-effect-free while
    # still giving us the exact Counter instance Prometheus will
    # scrape in production.
    import logging as _logging
    from app.metrics import REQUEST_ID_MISSING_TOTAL as _REQUEST_ID_MISSING_TOTAL
    _request_id_logger = _logging.getLogger("app.main")

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        request_id, is_fallback = resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
        set_request_id(request_id)
        request.state.request_id = request_id
        if is_fallback:
            _REQUEST_ID_MISSING_TOTAL.labels(route=request.url.path).inc()
            _request_id_logger.warning(
                "request_id_missing=true route=%s method=%s fallback=%s",
                request.url.path, request.method, request_id,
            )
        try:
            response = await call_next(request)
        finally:
            clear_request_id()
        return response

    # --- Exception handlers (same as production, see app/main.py) ---
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        # Contract: pydantic/FastAPI validation failures surface as 400 + USER_INPUT,
        # matching app.main.validation_exception_handler. Without this override the
        # test app would fall back to FastAPI's built-in 422 response and break
        # the tests that assert the unified envelope shape.
        return JSONResponse(
            status_code=400,
            content=api_error(
                http_status=400,
                message="Request validation failed",
                error_code=ANALYSIS_INVALID_ARGUMENT,
                category=ErrorCategory.USER_INPUT,
                extras={"errors": exc.errors()},
            ),
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        error_code = detail.get("errorCode") if isinstance(detail, dict) else None
        category_raw = detail.get("category") if isinstance(detail, dict) else None
        message = detail.get("message", "Request failed") if isinstance(detail, dict) else str(exc.detail)
        extras = None
        if isinstance(detail, dict):
            extras = {
                k: v for k, v in detail.items()
                if k not in ("message", "errorCode", "category")
            } or None

        if not error_code or not category_raw:
            return JSONResponse(
                status_code=exc.status_code,
                content=api_unknown_error(http_status=exc.status_code, message=message),
            )

        try:
            category = ErrorCategory(category_raw)
        except ValueError:
            category = ErrorCategory.INTERNAL

        return JSONResponse(
            status_code=exc.status_code,
            content=api_error(
                http_status=exc.status_code,
                message=message,
                error_code=error_code,
                category=category,
                extras=extras,
            ),
        )

    @app.exception_handler(OperationalError)
    @app.exception_handler(InterfaceError)
    async def database_unavailable_handler(request: Request, exc: DBAPIError):
        # Mirror production degradation-mode contract (backend.md §6.7):
        # transient database unavailability → 503 + ANALYSIS_DATABASE_UNAVAILABLE.
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
    async def unhandled_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content=api_unknown_error(http_status=500, message="Internal server error"),
        )

    # --- Routers ---
    # Mirror the production registration order from main.py: backends_router first
    # so `/api/v1/analysis/backends` wins over analysis_router's `/{session_id}`.
    app.include_router(backends_router)
    app.include_router(analysis_router)
    app.include_router(conversations_router)
    app.include_router(semantic_router)

    # Mirror the production OpenAPI customization so tests/test_openapi_* can
    # assert on the exposed error envelope schemas (backend.md §6.0).
    from app.schemas.api_error import register_openapi_error_components
    register_openapi_error_components(app)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    # --- Dependency overrides ---
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_backend_registry] = lambda: backend_registry

    async def override_get_db():
        async with db_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    return app


# ---------------------------------------------------------------------------
# Application & database fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def event_loop():
    """Create a single event loop for the entire test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def test_settings():
    """Provide test settings."""
    return make_test_settings(algorithm="HS256")


@pytest_asyncio.fixture
async def mock_backend_registry():
    """Provide a BackendRegistry with a mock backend."""
    registry = BackendRegistry()
    mock_backend = MockStorageBackend()
    registry.register(mock_backend)
    registry.map_schema("test_schema", "mock-backend")
    return registry


def _build_shared_memory_engine():
    """Create a per-test SQLite engine whose state is reliably shared across
    every connection taken from the pool.

    History:
    - Using ``sqlite+aiosqlite://`` (anonymous in-memory) gave each aiosqlite
      connection its own private DB → "no such table" whenever the router
      opened a new connection.
    - ``StaticPool`` alone was not sufficient for aiosqlite because each
      async operation may dispatch to the worker thread in a way that does
      not preserve the shared in-memory handle reliably.
    - Named in-memory via ``file::memory:?cache=shared&uri=true`` works with
      aiosqlite *and* lets multiple connections see the same tables.
    """
    import uuid as _uuid

    shared_name = f"memdb_{_uuid.uuid4().hex}"
    url = f"sqlite+aiosqlite:///file:{shared_name}?mode=memory&cache=shared&uri=true"
    return create_async_engine(
        url,
        echo=False,
        connect_args={"check_same_thread": False, "uri": True},
        poolclass=StaticPool,
    )


def _import_all_models() -> None:
    """Force-import every ORM model module so SQLAlchemy's Base.metadata is
    fully populated before we call ``create_all``. Without this, models
    imported later (e.g. transitively via routers inside ``create_test_app``)
    are missing from the metadata when we create tables, and the first
    INSERT blows up with "no such table"."""
    import app.models.conversation  # noqa: F401
    import app.models.session  # noqa: F401
    import app.models.semantic  # noqa: F401


@pytest_asyncio.fixture
async def async_client(test_settings, mock_backend_registry) -> AsyncGenerator[AsyncClient, None]:
    """
    Provide an httpx AsyncClient wired to a fresh FastAPI app with:
    - In-memory SQLite database (shared across connections via StaticPool)
    - Overridden settings
    - Mock backend registry (no real DuckDB / Pixels)
    """
    from app.database import Base
    _import_all_models()

    engine = _build_shared_memory_engine()
    test_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app = create_test_app(test_settings, mock_backend_registry, test_session_factory)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
