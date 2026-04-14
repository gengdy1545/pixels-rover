from pydantic import BaseModel
from typing import Literal


class ResolvedMetric(BaseModel):
    user_term: str
    canonical_name: str
    display_name: str
    calculation: str
    source_table: str
    source_schema: str
    backend_id: str


class ResolvedDimension(BaseModel):
    user_term: str
    canonical_name: str
    display_name: str
    source_column: str
    source_table: str
    source_schema: str
    backend_id: str


class JoinPath(BaseModel):
    left_table: str
    right_table: str
    join_condition: str
    join_type: Literal["INNER", "LEFT"] = "INNER"


class ResolvedContext(BaseModel):
    metrics: list[ResolvedMetric] = []
    dimensions: list[ResolvedDimension] = []
    join_paths: list[JoinPath] = []
    unresolved: list[str] = []
    warnings: list[str] = []
