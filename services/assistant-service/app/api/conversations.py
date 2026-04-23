import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_response import api_success
from app.auth import AuthenticatedUser, get_current_user
from app.database import get_db
from app.dependencies import get_backend_registry
from app.error_codes import (
    ANALYSIS_BACKEND_NOT_FOUND,
    ANALYSIS_INVALID_ARGUMENT,
    ANALYSIS_SCHEMA_UNAVAILABLE,
    ANALYSIS_THREAD_NOT_FOUND,
    ErrorCategory,
)
from app.models.conversation import ConversationThread
from app.models.session import AnalysisSession, AnalysisStepRecord
from app.schemas.conversation import (
    ConversationDetailResponse,
    ConversationHistoryItem,
    ConversationThreadResponse,
    CreateConversationRequest,
    UpdateConversationRequest,
)

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])


async def _get_owned_thread(db: AsyncSession, thread_id: str, user_id: str) -> ConversationThread:
    result = await db.execute(
        select(ConversationThread).where(
            ConversationThread.id == thread_id,
            ConversationThread.user_id == user_id,
        )
    )
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "message": "Conversation thread not found",
                "errorCode": ANALYSIS_THREAD_NOT_FOUND,
                "category": ErrorCategory.USER_INPUT.value,
            },
        )
    return thread


def _serialize_thread(thread: ConversationThread) -> ConversationThreadResponse:
    return ConversationThreadResponse(
        thread_id=thread.id,
        title=thread.title,
        backend_id=thread.backend_id,
        schema_name=thread.schema_name,
        model_profile=thread.model_profile,
        status=thread.status,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
        last_activity_at=thread.last_activity_at,
    )


def _serialize_step_record(step: AnalysisStepRecord) -> dict:
    return {
        "step_id": step.step_id,
        "action": step.action,
        "description": step.description or "",
        "params": step.params_json or {},
        "status": step.status,
        "result": step.result_json,
        "error": step.error,
        "duration_ms": step.duration_ms,
    }


def _serialize_session(
    session: AnalysisSession,
    step_records: list[AnalysisStepRecord],
) -> ConversationHistoryItem:
    if step_records:
        step_results = [_serialize_step_record(step) for step in step_records]
    else:
        plan_steps = ((session.plan_json or {}).get("steps") if isinstance(session.plan_json, dict) else None) or []
        step_results = plan_steps

    return ConversationHistoryItem(
        session_id=session.id,
        thread_id=session.thread_id,
        status=session.status,
        question=session.question,
        task=session.task_json,
        plan=session.plan_json,
        step_results=step_results,
        summary=session.summary,
        warnings=session.warnings or [],
        error=session.error,
        stats={
            "stepsExecuted": session.steps_executed,
            "llmCallsMade": session.llm_calls_made,
            "sqlExecutions": session.sql_executions,
            "wallTimeMs": session.wall_time_ms,
        },
        created_at=session.created_at,
        completed_at=session.completed_at,
    )


@router.post("")
async def create_conversation(
    request: CreateConversationRequest,
    db: AsyncSession = Depends(get_db),
    registry=Depends(get_backend_registry),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    try:
        backend = registry.get(request.backend_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "message": f"Backend '{request.backend_id}' not found",
                "errorCode": ANALYSIS_BACKEND_NOT_FOUND,
                "category": ErrorCategory.USER_INPUT.value,
            },
        ) from exc

    if request.schema_name:
        schemas = await backend.get_schemas()
        if request.schema_name not in schemas:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": f"Schema '{request.schema_name}' is not available on backend '{request.backend_id}'",
                    "errorCode": ANALYSIS_SCHEMA_UNAVAILABLE,
                    "category": ErrorCategory.USER_INPUT.value,
                },
            )

    title = (request.title or "").strip()
    if not title:
        title = request.schema_name or request.backend_id or "新对话"

    thread = ConversationThread(
        id=str(uuid.uuid4()),
        user_id=current_user.user_id,
        title=title,
        backend_id=request.backend_id,
        schema_name=request.schema_name,
        model_profile=request.model_profile,
        status="active",
    )
    db.add(thread)
    await db.commit()
    await db.refresh(thread)

    return api_success(_serialize_thread(thread).model_dump(by_alias=True))


@router.get("")
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    result = await db.execute(
        select(ConversationThread)
        .where(ConversationThread.user_id == current_user.user_id)
        .order_by(desc(ConversationThread.last_activity_at), desc(ConversationThread.created_at))
    )
    threads = result.scalars().all()
    payload = [_serialize_thread(thread).model_dump(by_alias=True) for thread in threads]
    return api_success(payload)


@router.get("/{thread_id}")
async def get_conversation(
    thread_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    thread = await _get_owned_thread(db, thread_id, current_user.user_id)

    sessions_result = await db.execute(
        select(AnalysisSession)
        .where(
            AnalysisSession.thread_id == thread.id,
            AnalysisSession.user_id == current_user.user_id,
        )
        .order_by(desc(AnalysisSession.created_at))
    )
    sessions = sessions_result.scalars().all()
    session_ids = [session.id for session in sessions]
    steps_by_session: dict[str, list[AnalysisStepRecord]] = defaultdict(list)

    if session_ids:
        step_result = await db.execute(
            select(AnalysisStepRecord)
            .where(AnalysisStepRecord.session_id.in_(session_ids))
            .order_by(AnalysisStepRecord.session_id, AnalysisStepRecord.sequence_number)
        )
        for step in step_result.scalars().all():
            steps_by_session[step.session_id].append(step)

    payload = ConversationDetailResponse(
        thread=_serialize_thread(thread),
        history=[_serialize_session(session, steps_by_session.get(session.id, [])) for session in sessions],
    )
    return api_success(payload.model_dump(by_alias=True))


@router.patch("/{thread_id}")
async def update_conversation(
    thread_id: str,
    request: UpdateConversationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    thread = await _get_owned_thread(db, thread_id, current_user.user_id)

    if request.title is not None:
        title = request.title.strip()
        if not title:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Title cannot be blank",
                    "errorCode": ANALYSIS_INVALID_ARGUMENT,
                    "category": ErrorCategory.USER_INPUT.value,
                },
            )
        thread.title = title

    if request.status is not None:
        if request.status not in {"active", "archived"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Status must be either 'active' or 'archived'",
                    "errorCode": ANALYSIS_INVALID_ARGUMENT,
                    "category": ErrorCategory.USER_INPUT.value,
                },
            )
        thread.status = request.status

    await db.commit()
    await db.refresh(thread)
    return api_success(_serialize_thread(thread).model_dump(by_alias=True))
