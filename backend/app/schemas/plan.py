from pydantic import BaseModel
from typing import Literal
from app.schemas.task import FilterCondition, TimeRange


class StepParams(BaseModel):
    purpose: str = ""
    metrics: list[str] | None = None
    filters: list[FilterCondition] | None = None
    time_range: TimeRange | None = None
    group_by: list[str] | None = None
    schema_name: str | None = None
    backend_id: str | None = None


class StepResult(BaseModel):
    sql: str | None = None
    columns: list[str] = []
    rows: list[list] = []
    row_count: int = 0
    execution_time_ms: int = 0
    summary: str | None = None


class PlanStep(BaseModel):
    step_id: str
    action: Literal["generate_and_execute_sql", "summarize_results"]
    description: str = ""
    params: StepParams = StepParams()
    status: Literal["pending", "running", "completed", "failed", "skipped"] = "pending"
    result: StepResult | None = None
    error: str | None = None
    duration_ms: int | None = None


class AnalysisPlan(BaseModel):
    steps: list[PlanStep] = []
    explanation: str = ""
