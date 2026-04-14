import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_db, async_session_factory
from app.dependencies import get_duckdb_backend, get_backend_registry
from app.seed import seed_duckdb, seed_semantic_layer
from app.api.analysis import router as analysis_router
from app.api.semantic import router as semantic_router
from app.api.backends import router as backends_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Pixels Rover backend...")

    await init_db()

    duckdb = get_duckdb_backend()
    seed_duckdb(duckdb)

    registry = get_backend_registry()
    registry.map_schema("tpch", "duckdb-local")

    async with async_session_factory() as db:
        await seed_semantic_layer(db)

    logger.info("Pixels Rover backend ready.")
    yield
    logger.info("Shutting down Pixels Rover backend.")


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

    app.include_router(analysis_router)
    app.include_router(semantic_router)
    app.include_router(backends_router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
