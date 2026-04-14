from pydantic import BaseModel
from typing import Literal
from datetime import date


class TimeRange(BaseModel):
    start: date | None = None
    end: date | None = None
    preset: Literal[
        "today", "yesterday", "last_7_days", "last_30_days",
        "this_month", "last_month", "this_quarter", "last_quarter",
        "this_year", "last_year", "ytd",
    ] | None = None
    description: str = ""


class FilterCondition(BaseModel):
    dimension: str
    operator: Literal["=", "!=", "in", "not_in", ">", "<", ">=", "<=", "between"] = "="
    value: str | list[str] | None = None


class AnalysisTask(BaseModel):
    task_type: Literal["query", "compare", "diagnose"]
    raw_input: str = ""
    target_metrics: list[str] = []
    filters: list[FilterCondition] = []
    time_range: TimeRange | None = None
    comparison_baseline: TimeRange | None = None
    analysis_dimensions: list[str] = []
    confidence: float = 1.0
    needs_clarification: bool = False
    clarification_question: str | None = None
