from pydantic import BaseModel
from enum import Enum


class BackendCapability(str, Enum):
    EXECUTE_QUERY = "execute_query"
    GET_SCHEMAS = "get_schemas"
    GET_TABLES = "get_tables"
    GET_COLUMNS = "get_columns"
    VALIDATE_SQL = "validate_sql"


class TableInfo(BaseModel):
    name: str
    schema_name: str
    row_count: int | None = None


class ColumnInfo(BaseModel):
    name: str
    data_type: str
    is_nullable: bool = True


class QueryResult(BaseModel):
    columns: list[str] = []
    rows: list[list] = []
    row_count: int = 0
    execution_time_ms: int = 0


class ValidationResult(BaseModel):
    is_valid: bool
    error_message: str | None = None
