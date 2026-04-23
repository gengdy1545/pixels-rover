import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import AsyncGenerator

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.task import AnalysisTask
from app.schemas.plan import AnalysisPlan
from app.schemas.response import AnalysisResponse
from app.schemas.harness import TaskEnvelope, BudgetExhausted, GuardrailViolation
from app.schemas.events import SSEEventType
from app.core.harness import RunContext, InputGuardrail
from app.core.task_interpreter import TaskInterpreter
from app.core.semantic_resolver import SemanticResolver
from app.core.planner import Planner
from app.core.step_executor import StepExecutor
from app.core.result_interpreter import ResultInterpreter
from app.storage.registry import BackendRegistry
from app.models.conversation import ConversationThread
from app.models.session import AnalysisSession, AnalysisStepRecord

logger = logging.getLogger(__name__)


def _sse_event(event_type: SSEEventType, data: dict) -> dict:
    return {"event": event_type.value, "data": json.dumps(data, ensure_ascii=False, default=str)}


class AnalysisService:
    """Orchestrates the full analysis pipeline with SSE streaming."""

    def __init__(
        self,
        task_interpreter: TaskInterpreter,
        semantic_resolver: SemanticResolver,
        planner: Planner,
        step_executor: StepExecutor,
        result_interpreter: ResultInterpreter,
        backend_registry: BackendRegistry,
        input_guardrail: InputGuardrail,
    ):
        self.task_interpreter = task_interpreter
        self.semantic_resolver = semantic_resolver
        self.planner = planner
        self.step_executor = step_executor
        self.result_interpreter = result_interpreter
        self.backend_registry = backend_registry
        self.input_guardrail = input_guardrail

    async def run_analysis_stream(
        self,
        question: str,
        user_id: int,
        envelope: TaskEnvelope,
        db: AsyncSession,
        thread_id: str,
        backend_id: str,
        schema_name: str | None = None,
        model_profile: str | None = None,
        auth_session_id: str | None = None,
    ) -> AsyncGenerator[dict, None]:
        # auth_session_id comes from the gateway-injected X-Auth-Session-Id
        # header (see app/auth.py and backend.md §3.1). Persisted on create
        # only; no consumption yet — see session.py docstring for the A1
        #加固 2 rationale.
        session_id = str(uuid.uuid4())
        ctx = RunContext(envelope)

        session = AnalysisSession(
            id=session_id,
            user_id=user_id,
            thread_id=thread_id,
            session_id=auth_session_id,
            question=question,
            backend_id=backend_id,
            schema_name=schema_name,
            model_profile=model_profile,
            status="received",
            envelope_json=envelope.model_dump(),
        )
        db.add(session)
        await db.commit()
        await self._touch_thread(db, thread_id)

        yield _sse_event(
            SSEEventType.STATUS_CHANGE,
            {
                "status": "received",
                "session_id": session_id,
                "thread_id": thread_id,
                "threadId": thread_id,
            },
        )

        # 1. Input check
        try:
            self.input_guardrail.check(question)
        except GuardrailViolation as e:
            yield _sse_event(SSEEventType.ERROR, {"code": "input_rejected", "message": str(e)})
            await self._finalize(db, session, "failed", error=str(e), ctx=ctx)
            return

        # 2. Task interpretation
        yield _sse_event(SSEEventType.STATUS_CHANGE, {"status": "understanding"})
        try:
            ctx.check_budget()
            available_schemas = await self.backend_registry.discover_all_schema_names()
            task = await self.task_interpreter.interpret(question, ctx, available_schemas)
        except BudgetExhausted as e:
            yield _sse_event(SSEEventType.ERROR, {"code": "budget_exhausted", "message": str(e)})
            await self._finalize(db, session, "failed", error=str(e), ctx=ctx)
            return
        except Exception as e:
            yield _sse_event(SSEEventType.ERROR, {"code": "task_parse_failed", "message": str(e)})
            await self._finalize(db, session, "failed", error=str(e), ctx=ctx)
            return

        yield _sse_event(SSEEventType.TASK_PARSED, task.model_dump())
        session.task_json = task.model_dump()
        await db.commit()

        if task.needs_clarification:
            yield _sse_event(SSEEventType.CLARIFICATION, {
                "question": task.clarification_question or "能否更具体地描述您的分析目标？"
            })
            await self._finalize(db, session, "clarification_needed", task=task, ctx=ctx)
            return

        # 3. Semantic resolution
        yield _sse_event(SSEEventType.STATUS_CHANGE, {"status": "resolving"})
        resolved = await self.semantic_resolver.resolve(task)

        if not resolved.metrics:
            available = await self.semantic_resolver.list_available_metrics()
            msg = (
                f"无法识别指标: {resolved.unresolved}。"
                f"可用指标: {[m.canonical_name for m in available]}"
            )
            yield _sse_event(SSEEventType.ERROR, {"code": "metric_not_found", "message": msg})
            await self._finalize(db, session, "failed", error=msg, task=task, ctx=ctx)
            return

        for w in resolved.warnings:
            ctx.add_warning(w)
            yield _sse_event(SSEEventType.WARNING, {"message": w})

        # 4. Planning
        yield _sse_event(SSEEventType.STATUS_CHANGE, {"status": "planning"})
        try:
            ctx.check_budget()
            plan = await self.planner.generate_plan(task, resolved, ctx)
        except BudgetExhausted as e:
            yield _sse_event(SSEEventType.ERROR, {"code": "budget_exhausted", "message": str(e)})
            await self._finalize(db, session, "failed", error=str(e), task=task, ctx=ctx)
            return
        except Exception as e:
            yield _sse_event(SSEEventType.ERROR, {"code": "plan_failed", "message": str(e)})
            await self._finalize(db, session, "failed", error=str(e), task=task, ctx=ctx)
            return

        yield _sse_event(SSEEventType.PLAN_CREATED, plan.model_dump())
        session.plan_json = plan.model_dump()
        await db.commit()
        await self._persist_steps(db, session_id, plan)

        # 5. Step execution
        yield _sse_event(SSEEventType.STATUS_CHANGE, {"status": "executing"})
        backend = self.backend_registry.get(backend_id)

        for step in plan.steps:
            if step.action == "summarize_results":
                break

            yield _sse_event(SSEEventType.STEP_STARTED, {
                "step_id": step.step_id, "description": step.description
            })

            try:
                ctx.check_budget()
                await self.step_executor.execute(step, resolved, ctx, plan.steps, backend)
            except BudgetExhausted:
                ctx.add_warning(f"预算耗尽，步骤 {step.step_id} 后终止")
                yield _sse_event(SSEEventType.WARNING, {"message": f"预算耗尽，提前终止"})
                await self._persist_steps(db, session_id, plan)
                break

            await self._persist_steps(db, session_id, plan)

            if step.status == "completed":
                yield _sse_event(SSEEventType.STEP_COMPLETED, {
                    "step_id": step.step_id,
                    "row_count": step.result.row_count if step.result else 0,
                })
                if step.result and step.result.sql:
                    yield _sse_event(SSEEventType.STEP_SQL, {
                        "step_id": step.step_id, "sql": step.result.sql
                    })
            else:
                yield _sse_event(SSEEventType.STEP_FAILED, {
                    "step_id": step.step_id, "error": step.error or "未知错误"
                })

        # 6. Generate summary
        yield _sse_event(SSEEventType.STATUS_CHANGE, {"status": "summarizing"})
        completed_steps = [
            s for s in plan.steps
            if s.status == "completed" and s.action == "generate_and_execute_sql"
        ]

        summary: str | None = None
        if not completed_steps:
            error_msg = "所有查询步骤均失败，无法生成分析结论"
            yield _sse_event(SSEEventType.ERROR, {"code": "all_steps_failed", "message": error_msg})
            await self._finalize(db, session, "failed", error=error_msg, task=task, plan=plan, ctx=ctx)
            return

        try:
            ctx.check_budget()
            summary = await self.result_interpreter.summarize(task, plan.steps, ctx)
        except Exception as e:
            ctx.add_warning("结论生成失败，仅返回原始查询结果")
            logger.error("Summary generation failed: %s", e)

        if summary:
            yield _sse_event(SSEEventType.SUMMARY_READY, {"summary": summary})

        # 7. Finalize
        has_failures = any(
            s.status == "failed" for s in plan.steps
            if s.action == "generate_and_execute_sql"
        )
        status = "partial" if has_failures else "completed"

        response = AnalysisResponse(
            session_id=session_id,
            thread_id=thread_id,
            status=status,
            task=task,
            plan=plan,
            step_results=plan.steps,
            summary=summary,
            warnings=ctx.warnings,
        )

        yield _sse_event(SSEEventType.ANALYSIS_DONE, response.model_dump())
        await self._finalize(
            db,
            session,
            status,
            task=task,
            plan=plan,
            summary=summary,
            ctx=ctx,
            thread_id=thread_id,
        )

    async def _finalize(
        self,
        db: AsyncSession,
        session: AnalysisSession,
        status: str,
        *,
        error: str | None = None,
        task: AnalysisTask | None = None,
        plan: AnalysisPlan | None = None,
        summary: str | None = None,
        ctx: RunContext | None = None,
        thread_id: str | None = None,
    ) -> None:
        session.status = status
        session.error = error
        if task:
            session.task_json = task.model_dump()
        if plan:
            session.plan_json = plan.model_dump()
        if summary:
            session.summary = summary
        if ctx:
            session.warnings = ctx.warnings
            session.steps_executed = ctx.steps_executed
            session.llm_calls_made = ctx.llm_calls_made
            session.sql_executions = ctx.sql_executions
            session.wall_time_ms = int(ctx.elapsed_sec * 1000)
        session.completed_at = datetime.utcnow()

        try:
            await db.merge(session)
            await db.commit()
            if plan:
                await self._persist_steps(db, session.id, plan)
            if thread_id:
                await self._touch_thread(db, thread_id)
        except Exception as e:
            logger.error("Failed to persist session: %s", e)

    async def _persist_steps(self, db: AsyncSession, session_id: str, plan: AnalysisPlan) -> None:
        try:
            await db.execute(delete(AnalysisStepRecord).where(AnalysisStepRecord.session_id == session_id))
            for index, step in enumerate(plan.steps, start=1):
                db.add(
                    AnalysisStepRecord(
                        session_id=session_id,
                        step_id=step.step_id,
                        sequence_number=index,
                        action=step.action,
                        description=step.description,
                        params_json=step.params.model_dump() if step.params else None,
                        sql_generated=step.result.sql if step.result and step.result.sql else None,
                        result_json=step.result.model_dump() if step.result else None,
                        status=step.status,
                        error=step.error,
                        duration_ms=step.duration_ms,
                    )
                )
            await db.commit()
        except Exception as e:
            logger.error("Failed to persist analysis steps for session %s: %s", session_id, e)
            await db.rollback()

    async def _touch_thread(self, db: AsyncSession, thread_id: str) -> None:
        try:
            await db.execute(
                update(ConversationThread)
                .where(ConversationThread.id == thread_id)
                .values(last_activity_at=datetime.utcnow())
            )
            await db.commit()
        except Exception as e:
            logger.error("Failed to update thread activity for %s: %s", thread_id, e)
            await db.rollback()
