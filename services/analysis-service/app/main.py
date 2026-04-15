import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import get_settings
from app.database import init_db, async_session_factory
from app.dependencies import get_duckdb_backend, get_backend_registry
from app.api_response import api_error
from app.error_codes import INTERNAL_ERROR, INVALID_ARGUMENT, resolve_error_code_name
from app.request_id import REQUEST_ID_HEADER, clear_request_id, ensure_request_id, set_request_id
from app.logging_config import setup_logging
from app.core.task_lifecycle import recover_zombie_sessions_on_startup, start_periodic_reaper
from app.seed import seed_duckdb, seed_semantic_layer
from app.api.analysis import router as analysis_router
from app.api.semantic import router as semantic_router
from app.api.backends import router as backends_router

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Pixels Rover backend...")

    await init_db()

    # Recover any zombie sessions left from a previous crash/restart
    await recover_zombie_sessions_on_startup()

    duckdb = get_duckdb_backend()
    seed_duckdb(duckdb)

    registry = get_backend_registry()
    registry.map_schema("tpch", "duckdb-local")

    async with async_session_factory() as db:
        await seed_semantic_layer(db)

    # Start periodic zombie reaper
    reaper_task = await start_periodic_reaper()

    logger.info("Pixels Rover backend ready.")
    yield
    logger.info("Shutting down Pixels Rover backend.")
    reaper_task.cancel()
    try:
        await reaper_task
    except Exception:
        pass


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description="Intelligent Data Analysis System",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        errors = exc.errors()
        first_error = errors[0] if errors else {}
        field = " -> ".join(str(loc) for loc in first_error.get("loc", []))
        msg = first_error.get("msg", "Validation error")
        message = f"{field}: {msg}" if field else msg
        return JSONResponse(
            status_code=422,
            content=api_error(
                code=INVALID_ARGUMENT,
                message=message,
                error_code=resolve_error_code_name(INVALID_ARGUMENT),
            ),
            headers={REQUEST_ID_HEADER: getattr(request.state, "request_id", "")},
        )

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
        logger.exception("Unhandled exception", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=api_error(
                code=INTERNAL_ERROR,
                message="Internal server error",
                error_code=resolve_error_code_name(INTERNAL_ERROR),
            ),
            headers={REQUEST_ID_HEADER: getattr(request.state, "request_id", "")},
        )

    app.include_router(analysis_router)
    app.include_router(semantic_router)
    app.include_router(backends_router)

    @app.get("/health")
    async def health():
        checks: dict[str, dict] = {}

        # Check SQLite/async database connectivity
        try:
            async with async_session_factory() as db:
                await db.execute(text("SELECT 1"))
            checks["database"] = {"status": "UP"}
        except Exception as e:
            logger.warning("Health check: database connection failed: %s", e)
            checks["database"] = {"status": "DOWN", "error": str(e)}

        # Check DuckDB connectivity
        try:
            duckdb = get_duckdb_backend()
            duckdb._conn.execute("SELECT 1").fetchone()
            checks["duckdb"] = {"status": "UP"}
        except Exception as e:
            logger.warning("Health check: DuckDB connection failed: %s", e)
            checks["duckdb"] = {"status": "DOWN", "error": str(e)}

        all_up = all(c.get("status") == "UP" for c in checks.values())
        status_code = 200 if all_up else 503
        return JSONResponse(
            status_code=status_code,
            content={
                "status": "UP" if all_up else "DOWN",
                "service": "analysis-service",
                "version": "0.1.0",
                "checks": checks,
            },
        )

    return app


app = create_app()
