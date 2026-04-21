from pydantic import BaseModel
from typing import Literal
from app.schemas.task import AnalysisTask
from app.schemas.plan import AnalysisPlan, PlanStep


class AnalysisResponse(BaseModel):
    session_id: str
    thread_id: str | None = None
    status: Literal["completed", "partial", "failed", "clarification_needed"]
    task: AnalysisTask
    plan: AnalysisPlan | None = None
    step_results: list[PlanStep] = []
    summary: str | None = None
    warnings: list[str] = []
    error: str | None = None
