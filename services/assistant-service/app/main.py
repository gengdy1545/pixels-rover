import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError

import app.models  # noqa: F401 - import side-effect: populate Base.metadata for Alembic reflection in tests
from app.config import get_settings
from app.database import async_session_factory
from app.required_env import validate_or_die
from app.dependencies import get_duckdb_backend, get_backend_registry
from app.api_response import api_error, api_unknown_error
from app.error_codes import (
    ANALYSIS_DATABASE_UNAVAILABLE,
    ANALYSIS_INVALID_ARGUMENT,
    ErrorCategory,
)
from app.request_id import REQUEST_ID_HEADER, clear_request_id, resolve_request_id, set_request_id
from app.logging_config import setup_logging
from app.core.task_lifecycle import recover_zombie_sessions_on_startup, start_periodic_reaper
from app.seed import seed_duckdb, seed_semantic_layer
from app.api.analysis import router as analysis_router
from app.api.conversations import router as conversations_router
from app.api.semantic import router as semantic_router
from app.api.backends import router as backends_router
from app.api.internal import router as internal_router
from app.metrics import REQUEST_ID_MISSING_TOTAL
from app.schemas.api_error import register_openapi_error_components
from app.schemas.openapi_registry import register_openapi_response_components

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Pixels Rover assistant backend...")

    # NOTE: Application-table schema is managed by Alembic, which runs
    # `upgrade head` from the container entrypoint BEFORE uvicorn binds to
    # the port (see services/assistant-service/Dockerfile and
    # docs/development/backend.md §12.2). Do NOT add a fallback create_all()
    # or alembic.command.upgrade() call here — lifespan runs after uvicorn
    # is already listening, so any migration work at this point would
    # expose half-ready state to incoming traffic.

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

    logger.info("Pixels Rover assistant backend ready.")
    yield
    logger.info("Shutting down Pixels Rover assistant backend.")
    reaper_task.cancel()
    try:
        await reaper_task
    except Exception:
        pass


def create_app() -> FastAPI:
    # §14: fail-fast on missing / placeholder env vars BEFORE we read
    # settings (which would e.g. silently accept an empty LLM_API_KEY
    # and only surface it on the first /analysis request). validator
    # reads the SSOT shape from config/required-env.yaml — bind-mounted
    # at /app/config/required-env.yaml via docker-compose.yml. Tests
    # bypass by setting ROVER_REQUIRED_ENV_SKIP=1.
    validate_or_die()

    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description="Intelligent Assistant Orchestration System",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS is handled exclusively at the gateway layer (gateway.md §6.4 /
    # backend.md §11). Business services MUST NOT declare their own CORS
    # policy — doing so masks the gateway's policy in local / direct-probe
    # scenarios and makes the effective policy ambiguous.

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        # Consume X-Request-Id inbound for logging / task correlation only.
        # Do NOT write it back to the response: gateway's global response-rewrite
        # / request-id plugin is the sole writer of the outbound X-Request-Id
        # header (gateway.md §7.5 / §7.6). Writing it here would duplicate the
        # header and bypass the "single writer" invariant that check-contracts.py
        # enforces.
        request_id, is_fallback = resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
        set_request_id(request_id)
        request.state.request_id = request_id
        if is_fallback:
            # backend.md §5 rule 1: exactly one warning per fallback request,
            # carrying the triggering route so the upstream gateway misconfig
            # is investigable from the log aggregator alone.
            REQUEST_ID_MISSING_TOTAL.labels(route=request.url.path).inc()
            logger.warning(
                "request_id_missing=true route=%s method=%s fallback=%s",
                request.url.path, request.method, request_id,
            )
        try:
            response = await call_next(request)
        finally:
            clear_request_id()
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        errors = exc.errors()
        first_error = errors[0] if errors else {}
        field = " -> ".join(str(loc) for loc in first_error.get("loc", []))
        msg = first_error.get("msg", "Validation error")
        message = f"{field}: {msg}" if field else msg
        return JSONResponse(
            status_code=400,
            content=api_error(
                http_status=400,
                message=message,
                error_code=ANALYSIS_INVALID_ARGUMENT,
                category=ErrorCategory.USER_INPUT,
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
            logger.error(
                "HTTPException missing errorCode/category on path %s: status=%s detail=%s",
                request.url.path, exc.status_code, detail,
            )
            return JSONResponse(
                status_code=exc.status_code,
                content=api_unknown_error(http_status=exc.status_code, message=message),
            )

        try:
            category = ErrorCategory(category_raw)
        except ValueError:
            logger.error(
                "HTTPException has invalid category=%r on path %s; falling back to INTERNAL",
                category_raw, request.url.path,
            )
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
    async def database_unavailable_handler(
        request: Request, exc: DBAPIError,
    ):
        # backend.md §6.7 degradation-mode contract: transient ``pixels_analysis``
        # unavailability (connection refused, pool exhausted, query timeout,
        # driver-level disconnect) maps to HTTP 503 + ANALYSIS_DATABASE_UNAVAILABLE
        # + category=UPSTREAM. Only the narrow SQLAlchemy subtypes that signal
        # *transient* resource failure are caught here — a generic ``DBAPIError``
        # would also include statement-level bugs (constraint violations, syntax
        # errors) that MUST surface as a plain 500 so they get investigated
        # rather than absorbed into "DB flaky today" noise.
        logger.error(
            "pixels_analysis database unavailable on path %s: %s",
            request.url.path, exc, exc_info=exc,
        )
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
        logger.exception("Unhandled exception on path %s", request.url.path, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=api_unknown_error(http_status=500, message="Internal server error"),
        )

    # backends_router MUST be registered before analysis_router. Both share the
    # `/api/v1/analysis` prefix — backends_router owns exact `/api/v1/analysis/backends/*`
    # while analysis_router owns `GET /api/v1/analysis/{session_id}` (catch-all by path
    # param). Starlette matches routes in registration order, so if analysis_router
    # comes first, `/api/v1/analysis/backends` is captured as `session_id="backends"`
    # and the backends listing becomes permanently 404. This ordering is a hard rule.
    app.include_router(backends_router)
    app.include_router(analysis_router)
    app.include_router(conversations_router)
    app.include_router(semantic_router)
    # /internal/ready is consumed only by the gateway via an nginx
    # `internal;` location (docs/development/gateway.md §4.1). External
    # reachability is blocked at the gateway; this service performs no
    # additional auth check on it.
    app.include_router(internal_router)

    # OpenAPI component registration: expose the failure envelope shape
    # (ApiErrorDetails / ApiErrorResponse) so /openapi.json callers can
    # enumerate details.errorCode / details.category values without
    # grepping the Python source. See backend.md §6.0 + §6.3.2.
    register_openapi_error_components(app)

    # OpenAPI component registration: expose response-body pydantic models
    # (AnalysisResponse, PlanStep, ConversationHistoryItem, ...) so the
    # committed ``services/assistant-service/openapi.json`` snapshot — and
    # therefore the auto-generated ``frontend/src/shared/types/generated/
    # assistant.d.ts`` — stays in lock-step with the backend pydantic
    # definitions. Must be called AFTER register_openapi_error_components
    # so both decorators compose cleanly (each wraps the previous
    # ``app.openapi`` exactly once; wrapper order is irrelevant for the
    # cached schema payload, but the call order keeps the error-envelope
    # registration as the first layer for readability).
    register_openapi_response_components(app)

    @app.get("/health")
    async def health():
        # Process-level liveness only; MUST NOT probe database, DuckDB, or
        # any external dependency (docs/development/backend.md §7.1).
        # Dependency readiness lives on /internal/ready; mixing the two
        # caused docker/k8s to restart the container on transient MySQL
        # blips, which restarting assistant-service cannot fix.
        return JSONResponse(
            status_code=200,
            content={
                "status": "UP",
                "service": "assistant-service",
                "version": "0.1.0",
            },
        )

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        # Prometheus text-format exposition.
        #
        # Prometheus includes default process collectors plus the
        # assistant_request_id_missing_total invariant counter above. Public
        # gateway access to this path is explicitly denied by APISIX; only
        # in-network scrapers should hit the service port directly.
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
