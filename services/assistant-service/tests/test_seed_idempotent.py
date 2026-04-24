"""Task 13 — idempotent seeding tests.

architecture-tasks.md §Task 13 acceptance gate (verbatim):
"seed 调两次，数据库不重复、不崩溃".

The `seed-functions-are-idempotent` contract (check-contracts.py) only
asserts the SOURCE SHAPE of the early-return path — the marker-row
SELECT before INSERT, the `return` statement. This pytest module is the
independent second defence line that proves the BEHAVIOUR: running each
seed entry point twice against the same (fresh) database must leave
the same row counts as a single call, with no unique-constraint
violation and no exception.

We deliberately do NOT reuse conftest.py's `async_client` fixture here
— that fixture builds a whole FastAPI app, overrides backends, and
never actually invokes the seed functions (because conftest injects a
mock registry instead). Testing seed() in isolation means we're
measuring exactly the invariant the contract names, not the sum of
FastAPI+SQLAlchemy+seeding behaviour.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.semantic import (
    SemanticDimension,
    SemanticJoinPath,
    SemanticMetric,
    SemanticSynonym,
)
from app.seed import seed_duckdb, seed_semantic_layer
from app.storage.duckdb_backend import DuckDBBackend


# ---------------------------------------------------------------------------
# DuckDB side — seed_duckdb() must be idempotent against rover_meta.seed_marker
# ---------------------------------------------------------------------------


@pytest.fixture
def fresh_duckdb() -> DuckDBBackend:
    """Build a pristine in-memory DuckDB backend for one test.

    Each test gets its own `:memory:` DB so state from a previous
    test (e.g. the marker row) cannot accidentally satisfy the
    idempotency check without the function actually being idempotent.
    """
    return DuckDBBackend(backend_id="duckdb-test", database=":memory:")


class TestSeedDuckDBIdempotent:
    """Acceptance for the "seed 调两次不重复、不崩溃" clause, DuckDB side."""

    def test_second_call_is_noop(self, fresh_duckdb):
        # First call performs the real work; second call must take the
        # marker-row early-return path and leave row counts untouched.
        seed_duckdb(fresh_duckdb)
        orders_after_first = fresh_duckdb.fetch_one_sql_sync(
            "SELECT COUNT(*) AS n FROM tpch.orders"
        )
        customers_after_first = fresh_duckdb.fetch_one_sql_sync(
            "SELECT COUNT(*) AS n FROM tpch.customer"
        )
        lineitems_after_first = fresh_duckdb.fetch_one_sql_sync(
            "SELECT COUNT(*) AS n FROM tpch.lineitem"
        )

        # Second call MUST NOT raise. A non-idempotent re-run would
        # blow up on the PRIMARY KEY of tpch.orders with "duplicate
        # key value", which is precisely the regression Task 13
        # forbids.
        seed_duckdb(fresh_duckdb)

        orders_after_second = fresh_duckdb.fetch_one_sql_sync(
            "SELECT COUNT(*) AS n FROM tpch.orders"
        )
        customers_after_second = fresh_duckdb.fetch_one_sql_sync(
            "SELECT COUNT(*) AS n FROM tpch.customer"
        )
        lineitems_after_second = fresh_duckdb.fetch_one_sql_sync(
            "SELECT COUNT(*) AS n FROM tpch.lineitem"
        )

        assert orders_after_second == orders_after_first, (
            "seed_duckdb second call changed tpch.orders row count "
            f"(before={orders_after_first} after={orders_after_second}); "
            "the marker-row early-return path is broken."
        )
        assert customers_after_second == customers_after_first
        assert lineitems_after_second == lineitems_after_first

    def test_marker_row_is_the_idempotency_anchor(self, fresh_duckdb):
        """Name the invariant directly, so a future refactor that keeps
        row counts stable by accident (e.g. by switching to INSERT OR
        IGNORE) still trips this test if it abandons the marker row."""
        seed_duckdb(fresh_duckdb)
        marker = fresh_duckdb.fetch_one_sql_sync(
            "SELECT name FROM rover_meta.seed_marker "
            "WHERE name = 'tpch-demo-v1'"
        )
        assert marker is not None, (
            "seed_duckdb did not write the 'tpch-demo-v1' marker row; "
            "the contract's idempotency claim depends on that row "
            "being the early-return gate on subsequent calls."
        )


# ---------------------------------------------------------------------------
# Semantic-layer side — seed_semantic_layer() must be idempotent via the
# SemanticMetric LIMIT 1 probe
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def fresh_db_session():
    """Fresh in-memory SQLite DB with the ORM metadata pre-created.

    Uses StaticPool + shared-cache URI so a single connection backs the
    whole fixture lifecycle — that's the same trick conftest.py uses
    for its async_client fixture, reused here in isolation.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///file:duckdb_idempotent_test?mode=memory&cache=shared&uri=true",
        echo=False,
        connect_args={"check_same_thread": False, "uri": True},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
class TestSeedSemanticLayerIdempotent:
    """Acceptance for the "seed 调两次不重复、不崩溃" clause, ORM side."""

    async def test_second_call_is_noop(self, fresh_db_session):
        await seed_semantic_layer(fresh_db_session)
        metrics_after_first = (
            await fresh_db_session.scalar(select(func.count(SemanticMetric.id)))
        )
        dims_after_first = (
            await fresh_db_session.scalar(select(func.count(SemanticDimension.id)))
        )
        syn_after_first = (
            await fresh_db_session.scalar(select(func.count(SemanticSynonym.id)))
        )
        joins_after_first = (
            await fresh_db_session.scalar(select(func.count(SemanticJoinPath.id)))
        )

        # A non-idempotent re-run would violate the unique constraint
        # on SemanticSynonym.term (by far the tightest constraint in
        # the semantic schema, which makes it the cheapest canary).
        await seed_semantic_layer(fresh_db_session)

        metrics_after_second = (
            await fresh_db_session.scalar(select(func.count(SemanticMetric.id)))
        )
        dims_after_second = (
            await fresh_db_session.scalar(select(func.count(SemanticDimension.id)))
        )
        syn_after_second = (
            await fresh_db_session.scalar(select(func.count(SemanticSynonym.id)))
        )
        joins_after_second = (
            await fresh_db_session.scalar(select(func.count(SemanticJoinPath.id)))
        )

        assert metrics_after_second == metrics_after_first
        assert dims_after_second == dims_after_first
        assert syn_after_second == syn_after_first
        assert joins_after_second == joins_after_first

    async def test_first_call_actually_seeds(self, fresh_db_session):
        """Guardrail against the pathological early-return: if the
        LIMIT 1 probe were always truthy (say, by accidentally reading
        a shared table), the function would be 'idempotent' in the
        trivial sense of 'never does anything'. Pin the first call to
        non-zero counts so a regression of that shape trips this test
        instead of silently passing the idempotency test above."""
        await seed_semantic_layer(fresh_db_session)
        metrics_count = (
            await fresh_db_session.scalar(select(func.count(SemanticMetric.id)))
        )
        synonyms_count = (
            await fresh_db_session.scalar(select(func.count(SemanticSynonym.id)))
        )
        assert metrics_count and metrics_count > 0
        assert synonyms_count and synonyms_count > 0
