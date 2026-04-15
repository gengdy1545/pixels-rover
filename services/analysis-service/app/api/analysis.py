import asyncio
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_response import api_success
from app.database import get_db, async_session_factory
from app.auth import AuthenticatedUser, get_current_user
from app.schemas.harness import TaskEnvelope
from app.schemas.events import SSEEventType
from app.schemas.response import AnalysisResponse
from app.models.session import AnalysisSession
from app.dependencies import get_analysis_service
from app.error_codes import RESOURCE_NOT_FOUND, RESOURCE_NOT_FOUND_NAME

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/analysis", tags=["analysis"])

# Hard timeout safety margin beyond the cooperative wall-time limit (seconds)
HARD_TIMEOUT_MARGIN_SEC = 30


class AnalysisRequest(BaseModel):
    question: str
    user_id: int | None = None
    max_steps: int = 10
    max_llm_calls: int = 20
    max_wall_time_sec: int = 180
    max_sql_executions: int = 5


@router.post("")
async def submit_analysis(
    request: AnalysisRequest,
    db: AsyncSession = Depends(get_db),
    analysis_service=Depends(get_analysis_service),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Submit an analysis question. Returns SSE stream of events."""
    envelope = TaskEnvelope(
        max_steps=request.max_steps,
        max_llm_calls=request.max_llm_calls,
        max_wall_time_sec=request.max_wall_time_sec,
        max_sql_executions=request.max_sql_executions,
    )
    hard_timeout = request.max_wall_time_sec + HARD_TIMEOUT_MARGIN_SEC

    async def event_generator():
        session_id: str | None = None
        try:
            async for event in analysis_service.run_analysis_stream(
                question=request.question,
                user_id=current_user.user_id,
                envelope=envelope,
                db=db,
            ):
                # Track session_id from the first status_change event
                if session_id is None and event.get("event") == SSEEventType.STATUS_CHANGE.value:
                    import json as _json
                    data = _json.loads(event["data"]) if isinstance(event["data"], str) else event["data"]
                    session_id = data.get("session_id")

                yield f"event: {event['event']}\ndata: {event['data']}\n\n"

        except asyncio.CancelledError:
            # Client disconnected (SSE connection dropped)
            logger.info("Client disconnected, cancelling analysis session: %s", session_id)
            if session_id:
                await _mark_session_cancelled(session_id, "Client disconnected")
            return

        except asyncio.TimeoutError:
            # Hard timeout exceeded
            logger.warning("Hard timeout (%ds) exceeded for session: %s", hard_timeout, session_id)
            error_event = {
                "event": SSEEventType.ERROR.value,
                "data": json.dumps({"code": "hard_timeout", "message": f"Analysis exceeded hard timeout ({hard_timeout}s)"}, ensure_ascii=False),
            }
            yield f"event: {error_event['event']}\ndata: {error_event['data']}\n\n"
            if session_id:
                await _mark_session_cancelled(session_id, f"Hard timeout ({hard_timeout}s) exceeded")

    async def timed_event_generator():
        """Wrap event_generator with asyncio.wait_for for hard timeout."""
        # We cannot use wait_for directly on an async generator, so we
        # collect and yield events with a per-iteration timeout instead.
        gen = event_generator()
        try:
            while True:
                try:
                    event_chunk = await asyncio.wait_for(gen.__anext__(), timeout=hard_timeout)
                    yield event_chunk
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    logger.warning("Hard timeout (%ds) reached during SSE streaming", hard_timeout)
                    error_data = json.dumps(
                        {"code": "hard_timeout", "message": f"Analysis exceeded hard timeout ({hard_timeout}s)"},
                        ensure_ascii=False,
                    )
                    yield f"event: error\ndata: {error_data}\n\n"
                    break
        except asyncio.CancelledError:
            logger.info("SSE stream cancelled (client disconnect)")
            return

    return StreamingResponse(
        timed_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _mark_session_cancelled(session_id: str, reason: str) -> None:
    """Mark a session as cancelled in the database."""
    try:
        async with async_session_factory() as db:
            await db.execute(
                update(AnalysisSession)
                .where(AnalysisSession.id == session_id)
                .values(
                    status="cancelled",
                    error=reason,
                    completed_at=datetime.utcnow(),
                )
            )
            await db.commit()
    except Exception:
        logger.exception("Failed to mark session %s as cancelled", session_id)


@router.get("/{session_id}")
async def get_analysis_result(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Get a completed analysis result by session ID."""
    result = await db.execute(
        select(AnalysisSession).where(AnalysisSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "message": "Session not found",
                "code": RESOURCE_NOT_FOUND,
                "errorCode": RESOURCE_NOT_FOUND_NAME,
            },
        )
    if session.user_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "message": "Session not found",
                "code": RESOURCE_NOT_FOUND,
                "errorCode": RESOURCE_NOT_FOUND_NAME,
            },
        )

    return api_success({
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
    })
