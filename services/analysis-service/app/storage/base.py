from abc import ABC, abstractmethod
from app.schemas.backend import (
    BackendCapability, TableInfo, ColumnInfo, QueryResult, ValidationResult,
)


class StorageBackend(ABC):
    @property
    @abstractmethod
    def backend_id(self) -> str: ...

    @property
    @abstractmethod
    def backend_type(self) -> str: ...

    @property
    @abstractmethod
    def capabilities(self) -> set[BackendCapability]: ...

    def supports(self, cap: BackendCapability) -> bool:
        return cap in self.capabilities

    @abstractmethod
    async def get_schemas(self) -> list[str]: ...

    @abstractmethod
    async def get_tables(self, schema: str) -> list[TableInfo]: ...

    @abstractmethod
    async def get_columns(self, schema: str, table: str) -> list[ColumnInfo]: ...

    @abstractmethod
    async def execute_query(self, sql: str, schema: str, limit: int = 1000) -> QueryResult: ...

    async def validate_sql(self, sql: str, schema: str) -> ValidationResult:
        return ValidationResult(is_valid=True)
