from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

engine = create_async_engine(
    get_settings().database_url,
    echo=get_settings().debug,
    pool_pre_ping=True,
)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:  # type: ignore[misc]
    async with async_session_factory() as session:
        yield session


# Application-table ownership belongs to Alembic (see alembic/env.py and
# docs/development/backend.md §12.2). The previous `init_db()` that called
# `Base.metadata.create_all()` was removed in the B1+B2 PR; Alembic runs
# `upgrade head` from the container entrypoint BEFORE uvicorn starts, so
# by the time any FastAPI lifespan code runs, tables are already at head.
#
# DO NOT add a `create_all()` fallback here — it would reopen the schema
# drift path that B1+B2 was introduced to close (CREATE TABLE semantics in
# the app bypass migration history, checksums, and review).
