"""
Shared test fixtures for Python analysis-service integration & auth tests.

Provides:
- Async TestClient backed by an in-memory SQLite database
- JWT token factory helpers (HS256 / RS256)
- Mock storage backend and analysis service
"""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.api_response import api_error
from app.config import Settings
from app.error_codes import INTERNAL_ERROR, resolve_error_code_name
from app.request_id import REQUEST_ID_HEADER, clear_request_id, ensure_request_id, set_request_id
from app.schemas.backend import BackendCapability, ColumnInfo, QueryResult, TableInfo
from app.storage.base import StorageBackend
from app.storage.registry import BackendRegistry

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

TEST_JWT_SECRET = "test-secret-for-integration-tests"
TEST_JWT_ISSUER = "pixels-rover-auth-service"
TEST_RSA_KID = "rsa-key-1"


def make_test_settings(*, algorithm: str = "HS256") -> Settings:
    """Build a Settings instance suitable for testing."""
    kwargs = dict(
        jwt_secret=TEST_JWT_SECRET,
        jwt_issuer=TEST_JWT_ISSUER,
        jwt_algorithm=algorithm,
        database_url="sqlite+aiosqlite://",  # in-memory
        duckdb_path=":memory:",
    )
    if algorithm == "RS256":
        kwargs.update(
            jwt_active_kid=TEST_RSA_KID,
            jwt_public_key_pem=RSA_PUBLIC_KEY,
        )
    return Settings(**kwargs)


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------


def make_access_token(
    *,
    user_id: int = 1,
    email: str = "testuser@example.com",
    issuer: str = TEST_JWT_ISSUER,
    secret: str = TEST_JWT_SECRET,
    algorithm: str = "HS256",
    extra_claims: dict | None = None,
    headers: dict | None = None,
) -> str:
    """Create a valid HS256 access token."""
    payload = {
        "sub": email,
        "uid": user_id,
        "type": "access",
        "iss": issuer,
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, secret, algorithm=algorithm, headers=headers)


def make_rs256_access_token(
    *,
    user_id: int = 1,
    email: str = "testuser@example.com",
    issuer: str = TEST_JWT_ISSUER,
    kid: str = TEST_RSA_KID,
    extra_claims: dict | None = None,
) -> str:
    """Create a valid RS256 access token signed with the test private key."""
    payload = {
        "sub": email,
        "uid": user_id,
        "type": "access",
        "iss": issuer,
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, RSA_PRIVATE_KEY, algorithm="RS256", headers={"kid": kid})


def make_expired_token(
    *,
    user_id: int = 1,
    email: str = "testuser@example.com",
    secret: str = TEST_JWT_SECRET,
) -> str:
    """Create an access token that is already expired."""
    import time

    payload = {
        "sub": email,
        "uid": user_id,
        "type": "access",
        "iss": TEST_JWT_ISSUER,
        "exp": int(time.time()) - 3600,  # expired 1 hour ago
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def make_refresh_token(
    *,
    user_id: int = 1,
    email: str = "testuser@example.com",
    secret: str = TEST_JWT_SECRET,
) -> str:
    """Create a refresh token (type=refresh, should be rejected by analysis service)."""
    payload = {
        "sub": email,
        "uid": user_id,
        "type": "refresh",
        "iss": TEST_JWT_ISSUER,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def auth_header(token: str) -> dict[str, str]:
    """Build an Authorization header dict."""
    return {"Authorization": f"Bearer {token}"}


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
    from app.api.semantic import router as semantic_router
    from app.api.backends import router as backends_router
    from app.config import get_settings
    from app.database import get_db
    from app.dependencies import get_backend_registry

    @asynccontextmanager
    async def noop_lifespan(app: FastAPI):
        yield

    app = FastAPI(title="Test App", lifespan=noop_lifespan)

    # --- Request-ID middleware (same as production) ---
    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        request_id = ensure_request_id(request.headers.get(REQUEST_ID_HEADER))
        set_request_id(request_id)
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        finally:
            clear_request_id()
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    # --- Exception handlers (same as production) ---
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": exc.detail, "code": exc.status_code}
        code = detail.get("code", exc.status_code)
        return JSONResponse(
            status_code=exc.status_code,
            content=api_error(
                code=code,
                message=detail.get("message", "Request failed"),
                error_code=detail.get("errorCode") or resolve_error_code_name(code),
            ),
            headers={REQUEST_ID_HEADER: getattr(request.state, "request_id", "")},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content=api_error(
                code=INTERNAL_ERROR,
                message="Internal server error",
                error_code=resolve_error_code_name(INTERNAL_ERROR),
            ),
            headers={REQUEST_ID_HEADER: getattr(request.state, "request_id", "")},
        )

    # --- Routers ---
    app.include_router(analysis_router)
    app.include_router(semantic_router)
    app.include_router(backends_router)

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


@pytest_asyncio.fixture
async def async_client(test_settings, mock_backend_registry) -> AsyncGenerator[AsyncClient, None]:
    """
    Provide an httpx AsyncClient wired to a fresh FastAPI app with:
    - In-memory SQLite database
    - Overridden settings (test JWT secret)
    - Mock backend registry (no real DuckDB / Pixels)
    """
    from app.database import Base

    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
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

    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
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
