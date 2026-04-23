from sqlalchemy import String, Text, Integer, JSON, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime

from app.database import Base


class AnalysisSession(Base):
    __tablename__ = "analysis_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer)
    thread_id: Mapped[str] = mapped_column(String(36), index=True)
    # Auth session id at the time this analysis was submitted (gateway
    # header X-Auth-Session-Id; see backend.md §3.1 / §7.2 and todolist
    # decision A1 / "A1 加固 2"). Recorded on create; currently NOT
    # consumed by any business logic — it is a zero-cost prerequisite
    # for a future "invalidate_session broadcasts active-stream close to
    # assistant-service" path. Nullable because older rows from before
    # this column was added will have NULL, and some callers (tests,
    # internal tooling) legitimately hit this service without the
    # gateway in the path.
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    question: Mapped[str] = mapped_column(Text)
    backend_id: Mapped[str] = mapped_column(String(128))
    schema_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_profile: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="received")
    task_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    plan_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings: Mapped[list | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    envelope_json: Mapped[dict] = mapped_column(JSON)
    steps_executed: Mapped[int] = mapped_column(Integer, default=0)
    llm_calls_made: Mapped[int] = mapped_column(Integer, default=0)
    sql_executions: Mapped[int] = mapped_column(Integer, default=0)
    wall_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AnalysisStepRecord(Base):
    __tablename__ = "analysis_steps"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    step_id: Mapped[str] = mapped_column(String(16))
    sequence_number: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    params_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    sql_generated: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
