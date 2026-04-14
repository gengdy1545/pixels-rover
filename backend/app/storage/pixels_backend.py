import asyncio
import logging
import time

import httpx

from app.storage.base import StorageBackend
from app.schemas.backend import (
    BackendCapability, TableInfo, ColumnInfo, QueryResult, ValidationResult,
)

logger = logging.getLogger(__name__)


class PixelsBackend(StorageBackend):
    """Pixels Server HTTP backend."""

    INITIAL_POLL_INTERVAL_SEC = 0.5
    MAX_POLL_INTERVAL_SEC = 5.0

    def __init__(
        self,
        backend_id: str,
        host: str = "localhost",
        port: int = 18890,
        execution_hint: str = "RELAXED",
        default_limit_rows: int = 1000,
        poll_timeout_sec: int = 300,
    ):
        self._id = backend_id
        self._base_url = f"http://{host}:{port}"
        self._execution_hint = execution_hint
        self._default_limit_rows = default_limit_rows
        self._poll_timeout_sec = poll_timeout_sec
        self._client = httpx.AsyncClient(timeout=30.0)

    @property
    def backend_id(self) -> str:
        return self._id

    @property
    def backend_type(self) -> str:
        return "pixels"

    @property
    def capabilities(self) -> set[BackendCapability]:
        return {
            BackendCapability.EXECUTE_QUERY,
            BackendCapability.GET_SCHEMAS,
            BackendCapability.GET_TABLES,
            BackendCapability.GET_COLUMNS,
        }

    async def get_schemas(self) -> list[str]:
        resp = await self._client.post(
            f"{self._base_url}/api/metadata/get-schemas",
            json={"username": ""},
        )
        data = resp.json()
        return [s["name"] for s in data.get("schemas", [])]

    async def get_tables(self, schema: str) -> list[TableInfo]:
        resp = await self._client.post(
            f"{self._base_url}/api/metadata/get-tables",
            json={"schemaName": schema},
        )
        data = resp.json()
        return [
            TableInfo(name=t["name"], schema_name=schema, row_count=t.get("rowCount"))
            for t in data.get("tables", [])
        ]

    async def get_columns(self, schema: str, table: str) -> list[ColumnInfo]:
        resp = await self._client.post(
            f"{self._base_url}/api/metadata/get-columns",
            json={"schemaName": schema, "tableName": table},
        )
        data = resp.json()
        return [
            ColumnInfo(name=c["name"], data_type=c.get("type", ""), is_nullable=True)
            for c in data.get("columns", [])
        ]

    async def execute_query(self, sql: str, schema: str, limit: int = 1000) -> QueryResult:
        start = time.monotonic()

        submit_resp = await self._client.post(
            f"{self._base_url}/api/query/submit-query",
            json={
                "query": sql,
                "executionHint": self._execution_hint,
                "limitRows": limit or self._default_limit_rows,
            },
        )
        submit_data = submit_resp.json()
        if submit_data.get("errorCode", 0) != 0:
            raise RuntimeError(f"Pixels submit failed: {submit_data.get('errorMessage')}")
        trace_token = submit_data["traceToken"]

        deadline = asyncio.get_event_loop().time() + self._poll_timeout_sec
        interval = self.INITIAL_POLL_INTERVAL_SEC
        while asyncio.get_event_loop().time() < deadline:
            status_resp = await self._client.post(
                f"{self._base_url}/api/query/get-query-status",
                json={"traceTokens": [trace_token]},
            )
            statuses = status_resp.json().get("queryStatuses", {})
            if statuses.get(trace_token) == "FINISHED":
                break
            await asyncio.sleep(interval)
            interval = min(interval * 1.5, self.MAX_POLL_INTERVAL_SEC)
        else:
            raise TimeoutError(f"Pixels query timed out after {self._poll_timeout_sec}s")

        result_resp = await self._client.post(
            f"{self._base_url}/api/query/get-query-result",
            json={"traceToken": trace_token},
        )
        data = result_resp.json()
        if data.get("errorCode", 0) != 0:
            raise RuntimeError(f"Pixels query failed: {data.get('errorMessage')}")

        column_names = data.get("columnNames", [])
        raw_rows = data.get("rows", [])
        rows = [list(row) for row in raw_rows if row is not None]
        elapsed_ms = int((time.monotonic() - start) * 1000)

        return QueryResult(
            columns=column_names,
            rows=rows,
            row_count=len(rows),
            execution_time_ms=elapsed_ms,
        )
