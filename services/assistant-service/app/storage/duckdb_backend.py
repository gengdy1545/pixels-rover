import asyncio
import time
import uuid
import logging

import duckdb

from app.storage.base import StorageBackend
from app.schemas.backend import (
    BackendCapability, TableInfo, ColumnInfo, QueryResult, ValidationResult,
)

logger = logging.getLogger(__name__)


class DuckDBBackend(StorageBackend):
    """Embedded DuckDB backend.

    Concurrency model: shared connection + per-request cursor() via asyncio.to_thread.
    """

    def __init__(
        self,
        backend_id: str,
        database: str = ":memory:",
        read_only: bool = False,
        threads: int = 4,
        memory_limit: str = "4GB",
    ):
        self._id = backend_id
        self._conn = duckdb.connect(
            database=database,
            read_only=read_only,
            config={"threads": str(threads), "memory_limit": memory_limit},
        )

    @property
    def backend_id(self) -> str:
        return self._id

    @property
    def backend_type(self) -> str:
        return "duckdb"

    @property
    def capabilities(self) -> set[BackendCapability]:
        return {
            BackendCapability.EXECUTE_QUERY,
            BackendCapability.GET_SCHEMAS,
            BackendCapability.GET_TABLES,
            BackendCapability.GET_COLUMNS,
            BackendCapability.VALIDATE_SQL,
        }

    def _sync_get_schemas(self) -> list[str]:
        cursor = self._conn.cursor()
        try:
            result = cursor.execute(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name NOT IN ('information_schema', 'pg_catalog')"
            )
            return [row[0] for row in result.fetchall()]
        finally:
            cursor.close()

    async def get_schemas(self) -> list[str]:
        return await asyncio.to_thread(self._sync_get_schemas)

    def _sync_get_tables(self, schema: str) -> list[TableInfo]:
        cursor = self._conn.cursor()
        try:
            result = cursor.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = ?",
                [schema],
            )
            return [TableInfo(name=row[0], schema_name=schema) for row in result.fetchall()]
        finally:
            cursor.close()

    async def get_tables(self, schema: str) -> list[TableInfo]:
        return await asyncio.to_thread(self._sync_get_tables, schema)

    def _sync_get_columns(self, schema: str, table: str) -> list[ColumnInfo]:
        cursor = self._conn.cursor()
        try:
            result = cursor.execute(
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_schema = ? AND table_name = ?",
                [schema, table],
            )
            return [
                ColumnInfo(name=r[0], data_type=r[1], is_nullable=(r[2] == "YES"))
                for r in result.fetchall()
            ]
        finally:
            cursor.close()

    async def get_columns(self, schema: str, table: str) -> list[ColumnInfo]:
        return await asyncio.to_thread(self._sync_get_columns, schema, table)

    def _sync_execute(self, sql: str, schema: str, limit: int) -> QueryResult:
        cursor = self._conn.cursor()
        try:
            start = time.monotonic()
            cursor.execute(f"SET search_path='{schema}'")
            result = cursor.execute(sql)
            columns = [desc[0] for desc in result.description] if result.description else []
            raw_rows = result.fetchmany(limit)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            rows = [list(row) for row in raw_rows]
            return QueryResult(
                columns=columns,
                rows=rows,
                row_count=len(rows),
                execution_time_ms=elapsed_ms,
            )
        finally:
            cursor.close()

    async def execute_query(self, sql: str, schema: str, limit: int = 1000) -> QueryResult:
        return await asyncio.to_thread(self._sync_execute, sql, schema, limit)

    def _sync_validate(self, sql: str, schema: str) -> ValidationResult:
        cursor = self._conn.cursor()
        try:
            stmt_name = f"__val_{uuid.uuid4().hex[:8]}"
            cursor.execute(f"SET search_path='{schema}'")
            cursor.execute(f"PREPARE {stmt_name} AS {sql}")
            cursor.execute(f"DEALLOCATE {stmt_name}")
            return ValidationResult(is_valid=True)
        except duckdb.Error as e:
            return ValidationResult(is_valid=False, error_message=str(e))
        finally:
            cursor.close()

    async def validate_sql(self, sql: str, schema: str) -> ValidationResult:
        return await asyncio.to_thread(self._sync_validate, sql, schema)

    def execute_sql_sync(self, sql: str) -> None:
        """Run arbitrary SQL synchronously (for seeding data, etc.)."""
        self._conn.execute(sql)
