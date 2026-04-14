import json
import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.harness import TaskEnvelope
from app.schemas.response import AnalysisResponse
from app.models.session import AnalysisSession
from app.dependencies import get_analysis_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/analysis", tags=["analysis"])


class AnalysisRequest(BaseModel):
    question: str
    user_id: int = 1
    max_steps: int = 10
    max_llm_calls: int = 20
    max_wall_time_sec: int = 180
    max_sql_executions: int = 5


@router.post("")
async def submit_analysis(
    request: AnalysisRequest,
    db: AsyncSession = Depends(get_db),
    analysis_service=Depends(get_analysis_service),
):
    """Submit an analysis question. Returns SSE stream of events."""
    envelope = TaskEnvelope(
        max_steps=request.max_steps,
        max_llm_calls=request.max_llm_calls,
        max_wall_time_sec=request.max_wall_time_sec,
        max_sql_executions=request.max_sql_executions,
    )

    async def event_generator():
        async for event in analysis_service.run_analysis_stream(
            question=request.question,
            user_id=request.user_id,
            envelope=envelope,
            db=db,
        ):
            yield f"event: {event['event']}\ndata: {event['data']}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{session_id}")
async def get_analysis_result(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a completed analysis result by session ID."""
    result = await db.execute(
        select(AnalysisSession).where(AnalysisSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        return {"error": "Session not found"}

    return {
        "session_id": session.id,
        "status": session.status,
        "question": session.question,
        "task": session.task_json,
        "plan": session.plan_json,
        "summary": session.summary,
        "warnings": session.warnings,
        "error": session.error,
        "stats": {
            "steps_executed": session.steps_executed,
            "llm_calls_made": session.llm_calls_made,
            "sql_executions": session.sql_executions,
            "wall_time_ms": session.wall_time_ms,
        },
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
    }
