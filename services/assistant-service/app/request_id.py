from contextvars import ContextVar
from uuid import uuid4

REQUEST_ID_HEADER = "X-Request-Id"
_request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


def set_request_id(request_id: str) -> None:
    _request_id_ctx.set(request_id)


def get_request_id() -> str | None:
    return _request_id_ctx.get()


def clear_request_id() -> None:
    _request_id_ctx.set(None)


def ensure_request_id(request_id: str | None) -> str:
    return request_id or str(uuid4())
