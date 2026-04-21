from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


def to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class CreateConversationRequest(CamelModel):
    title: str | None = None
    backend_id: str
    schema_name: str | None = None
    model_profile: str | None = None


class UpdateConversationRequest(CamelModel):
    title: str | None = None
    status: str | None = None


class ConversationThreadResponse(CamelModel):
    thread_id: str = Field(alias="threadId")
    title: str
    backend_id: str
    schema_name: str | None = None
    model_profile: str | None = None
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_activity_at: datetime | None = None


class ConversationHistoryItem(CamelModel):
    session_id: str
    thread_id: str
    status: str
    question: str
    task: dict | None = None
    plan: dict | None = None
    step_results: list[dict] = Field(default_factory=list)
    summary: str | None = None
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    stats: dict[str, int | None] = Field(default_factory=dict)
    created_at: datetime | None = None
    completed_at: datetime | None = None


class ConversationDetailResponse(CamelModel):
    thread: ConversationThreadResponse
    history: list[ConversationHistoryItem]
