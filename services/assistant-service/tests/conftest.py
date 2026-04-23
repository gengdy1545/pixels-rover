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
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool

from app.api_response import api_error, api_unknown_error
from app.config import Settings
from app.error_codes import ANALYSIS_INVALID_ARGUMENT, ErrorCategory
from app.request_id import REQUEST_ID_HEADER, clear_request_id, ensure_request_id, set_request_id
from app.schemas.backend import BackendCapability, ColumnInfo, QueryResult, TableInfo
from app.storage.base import StorageBackend
from app.storage.registry import BackendRegistry

# Tests intentionally keep SQLite as a lightweight fixture even though runtime
# now defaults to MySQL.
os.environ.setdefault("ROVER_DATABASE_URL", "sqlite+aiosqlite://")

# ---------------------------------------------------------------------------
# RSA key pair for RS256 tests (same as in tests/test_auth.py)
# ---------------------------------------------------------------------------

RSA_PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDv4T16LB1TXAbE
CyjWC8x5axYM2hlr53lUk2f+lkT8NzFeW+lFh3D5M20hXpL29nnB6MGiBfLpXOpq
b4EmMaCLrXL7uQwgkxrtKRf2oS7ij4RXUskgDSKM+Zv6VNdXGPzK3XSJozS3/XSJ
O0Lc0fGmrumRWlbCMJ8cikDQaSum8ikfnb23/AWPauLI9bITzpDUIW3Xrr80SFeO
yNUwB6B6q8cgYWztfB8PZ+Kb7G6sFLa2l7q1pOdSvcCpypodi57AUGtv+m5h3J1e
fn8Ytv+VjuEdzDCVN9iKQrZt9pVAcl1MhAzC6tLb6ea6+VPCOzBU6Bt3BztaITyw
54DuV7bHAgMBAAECggEAdgAAXG1//YYbA+wTafvC2YWOgsL012o1+p9KfGeSRtml
rOucnCnMrqGYEN6zf83uRi+HtPqlLBubasEwMEggWCV6Fw7HwuxqRfi9g4J1jFiZ
+tTMADrF4MBW9LUwevVdQTPgBGbm441H+svOj86sx1hqqChe3kbJtmHiEUNzCDtK
npIpGXdu0ZuQnOMZhwcXJ7QjgBKbD0+B05GFKwAomw9AMkrIS4oXG68WXdXGcypb
PNcOADWW2CpV51xzl8oMvbnLh/vAbQE/BQVqVQfViGqdrRlC8P3QL4CYYsySDNoL
rbjfdf9d023SeqGUou7tY7c+JN9TSXexB/+d+W6coQKBgQD7ynRrCwAGRVwfAY/D
Q8J/7A+fLu/tDQqNEJo2eIMptZBsHTd3BSFGVc3OskZ2pfovneSS3ZkwWUZvswpp
OAlso0r0r7zIlDi7gilDD4XKZmuJDZ/frtnMg5mFbaQ21DLbPAAHijTEA0wGLy/s
PaXlomkK44IShT0aYTCPfkNaYQKBgQDz48/eSUJl8qVmeYVZ9ACQ+D4fkwvYhL1v
Po+/ByMtGvC2F9qXZ8g00ga5P8DgxQa1TXLG2EJrKVb/INOJAobzumZsVJO0/PE2
tcvzbO53+e/4W9d1y3xV9+iaiyGsSH1lAssnHChIuG90sr5woDuKyFAMXNwbL9x+
tpMmbS4yJwKBgQCRHmJyv2hINPmfNTsyg386U0e9q0PFEFsgao03D8Yo5+hRJ5Ws
F1zSOOnhU4ahI5BKmWn/65A6+XlLL5m0gwOLhaHR3OelgygfiilV6UBnIxifaSbX
uOL2qHJ3IHYg07Rr/uzVa6Z1wqCyf8fTFMTk0PJRwEZbfkd1SMbALTmMgQKBgEOu
ZcIvHGEETEg60vnaj8mrSjoi6XelpphXiTae+XEL997gkcXQhCu8WSdRfOojYzAv
FPn/i7cHWuAkMO/lpqO+h6vqcK8aPqpLGxUrlqXu01xdyFYlKRUGXiN9FtQjrcC5
XL02wCsmG7AL5nOE0+E4o5Y6ss5Mouj7K6zPQbGjAoGAZORm55LNypfuNA7llStp
aEb8uy06/e+Ey9AZvQqRu8NYfFoCwhQtXl5qNg6j7YuovxCtQCxiqe9zWdokYz+M
cffB8SkxFazha72dVKUcwPRNrS/UlYv1Txf684hilFIOncTYLWszTG7F3aB91O2a
/Lf0g2G//g1bw6VlhNAzsyw=
-----END PRIVATE KEY-----"""

RSA_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA7+E9eiwdU1wGxAso1gvM
eWsWDNoZa+d5VJNn/pZE/DcxXlvpRYdw+TNtIV6S9vZ5wejBogXy6Vzqam+BJjGg
i61y+7kMIJMa7SkX9qEu4o+EV1LJIA0ijPmb+lTXVxj8yt10iaM0t/10iTtC3NHx
pq7pkVpWwjCfHIpA0GkrpvIpH529t/wFj2riyPWyE86Q1CFt166/NEhXjsjVMAeg
eqvHIGFs7XwfD2fim+xurBS2tpe6taTnUr3AqcqaHYuewFBrb/puYdydXn5/GLb/
lY7hHcwwlTfYikK2bfaVQHJdTIQMwurS2+nmuvlTwjswVOgbdwc7WiE8sOeA7le2
xwIDAQAB
-----END PUBLIC KEY-----"""

# ---------------------------------------------------------------------------
# Test settings
# ---------------------------------------------------------------------------

TEST_JWT_ISSUER = "pixels-rover-auth-service"
TEST_RSA_KID = "rsa-key-1"


def make_test_settings(*, algorithm: str = "HS256") -> Settings:
    """Build a Settings instance suitable for testing."""
    _ = algorithm
    return Settings(
        database_url="sqlite+aiosqlite://",
        duckdb_path=":memory:",
    )


# ---------------------------------------------------------------------------
# Token helpers
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
    user_id: int = 1,
    email: str = "testuser@example.com",
    issuer: str = TEST_JWT_ISSUER,
    secret: str = "unused",
    algorithm: str = "HS256",
    extra_claims: dict | None = None,
    headers: dict | None = None,
) -> str:
    """Create a synthetic gateway token payload for tests."""
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


def make_rs256_access_token(
    *,
    user_id: int = 1,
    email: str = "testuser@example.com",
    issuer: str = TEST_JWT_ISSUER,
    kid: str = TEST_RSA_KID,
    extra_claims: dict | None = None,
) -> str:
    """Alias kept for legacy tests that now model gateway identity projection."""
    _ = kid
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
    user_id: int = 1,
    email: str = "testuser@example.com",
    secret: str = "unused",
) -> str:
    _ = secret
    payload = {
        "sub": email,
        "uid": user_id,
        "type": "access",
        "iss": TEST_JWT_ISSUER,
        "exp": 0,
        "sid": f"session-{user_id}",
    }
    return _encode_gateway_token(payload)


def make_refresh_token(
    *,
    user_id: int = 1,
    email: str = "testuser@example.com",
    secret: str = "unused",
) -> str:
    """Create a synthetic refresh token payload for gateway tests."""
    _ = secret
    payload = {
        "sub": email,
        "uid": user_id,
        "type": "refresh",
        "iss": TEST_JWT_ISSUER,
        "sid": f"session-{user_id}",
    }
    return _encode_gateway_token(payload)


def auth_header(token: str) -> dict[str, str]:
    """Simulate APISIX projecting a validated token into gateway identity headers."""
    payload = _decode_gateway_token(token)
    if not payload:
        return {
            "X-Auth-User-Id": "not-an-int",
            "X-Auth-User-Email": "",
        }

    if payload.get("iss") != TEST_JWT_ISSUER:
        return {
            "X-Auth-User-Id": "not-an-int",
            "X-Auth-User-Email": "",
        }

    if payload.get("type") != "access":
        return {
            "X-Auth-User-Id": "not-an-int",
            "X-Auth-User-Email": "",
        }

    if payload.get("exp") == 0:
        return {
            "X-Auth-User-Id": "not-an-int",
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
    # re-introduces response-side writes.
    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        request_id = ensure_request_id(request.headers.get(REQUEST_ID_HEADER))
        set_request_id(request_id)
        request.state.request_id = request_id
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
    """Provide test settings (HS256 by default)."""
    return make_test_settings(algorithm="HS256")


@pytest_asyncio.fixture
async def test_settings_rs256():
    """Provide test settings with RS256."""
    return make_test_settings(algorithm="RS256")


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
    - Overridden settings (test JWT secret)
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


@pytest_asyncio.fixture
async def async_client_rs256(test_settings_rs256, mock_backend_registry) -> AsyncGenerator[AsyncClient, None]:
    """
    Same as async_client but configured for RS256 JWT verification.
    """
    from app.database import Base
    _import_all_models()

    engine = _build_shared_memory_engine()
    test_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app = create_test_app(test_settings_rs256, mock_backend_registry, test_session_factory)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
