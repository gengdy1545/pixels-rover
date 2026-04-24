import re
import time
import logging
from typing import TypeVar, Type, Callable, Awaitable

from pydantic import BaseModel, ValidationError
import sqlglot

from app.schemas.harness import TaskEnvelope, BudgetExhausted, GuardrailViolation
from app.infra.llm import LLMClient

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class RunContext:
    """Tracks resource consumption for a single analysis session."""

    def __init__(self, envelope: TaskEnvelope):
        self.envelope = envelope
        self.steps_executed: int = 0
        self.llm_calls_made: int = 0
        self.sql_executions: int = 0
        self.start_time: float = time.time()
        self._warnings: list[str] = []

    def check_budget(self) -> None:
        e = self.envelope
        checks = [
            ("max_steps", self.steps_executed, e.max_steps),
            ("max_llm_calls", self.llm_calls_made, e.max_llm_calls),
            ("max_sql_executions", self.sql_executions, e.max_sql_executions),
            ("max_wall_time_sec", time.time() - self.start_time, e.max_wall_time_sec),
        ]
        for dim, current, limit in checks:
            if current >= limit:
                raise BudgetExhausted(dim, current, limit)

    def record_llm_call(self, tokens_in: int = 0, tokens_out: int = 0) -> None:
        self.llm_calls_made += 1

    def record_sql_execution(self) -> None:
        self.sql_executions += 1

    def record_step(self) -> None:
        self.steps_executed += 1

    def add_warning(self, message: str) -> None:
        self._warnings.append(message)

    @property
    def warnings(self) -> list[str]:
        return list(self._warnings)

    @property
    def elapsed_sec(self) -> float:
        return time.time() - self.start_time


class InputGuardrail:
    MAX_INPUT_CHARS = 2000
    INJECTION_PATTERNS = [
        r"(?i)\b(DROP|DELETE|INSERT|UPDATE|ALTER|TRUNCATE|EXEC)\b",
        r"(?i)(--|/\*)",
        r"(?i)ignore\s+previous\s+instructions",
        r"(?i)you\s+are\s+now\s+a",
        r"(?i)<\|?system\|?>",
    ]

    def check(self, text: str) -> None:
        if len(text) > self.MAX_INPUT_CHARS:
            raise GuardrailViolation(
                "input_length",
                f"输入长度 {len(text)} 超过限制 {self.MAX_INPUT_CHARS}",
            )
        for pattern in self.INJECTION_PATTERNS:
            if re.search(pattern, text):
                raise GuardrailViolation("injection_detected", "输入包含可疑模式")


class OutputGuardrail:
    """Parses LLM raw output into Pydantic models with one retry on failure."""

    def __init__(self, llm_client: LLMClient):
        self._llm = llm_client

    async def parse_llm_output(
        self,
        raw: str,
        schema: Type[T],
        ctx: RunContext,
        retry_prompt_fn: Callable[[str], list[dict]] | None = None,
    ) -> T:
        try:
            return schema.model_validate_json(raw)
        except (ValidationError, Exception) as first_error:
            if retry_prompt_fn is None:
                raise GuardrailViolation("output_parse", f"LLM 输出解析失败: {first_error}")

            logger.warning("LLM output parse failed, retrying: %s", first_error)
            retry_messages = retry_prompt_fn(str(first_error))
            retry_resp = await self._llm.call_json(retry_messages)
            ctx.record_llm_call(retry_resp.tokens_in, retry_resp.tokens_out)
            try:
                return schema.model_validate_json(retry_resp.content)
            except (ValidationError, Exception) as second_error:
                raise GuardrailViolation(
                    "output_parse",
                    f"LLM 输出解析重试后仍失败: {second_error}",
                )


def check_sql_safety(sql: str) -> None:
    """Ensure SQL is a single SELECT statement with no dangerous operations."""
    try:
        statements = sqlglot.parse(sql)
    except sqlglot.errors.ParseError as e:
        raise GuardrailViolation("sql_parse_failed", f"SQL 解析失败: {e}")

    if not statements or len(statements) != 1:
        raise GuardrailViolation("sql_multiple_statements", "只允许单条 SQL 语句")

    stmt = statements[0]
    if stmt is None:
        raise GuardrailViolation("sql_parse_failed", "SQL 解析结果为空")
    if stmt.key != "select":
        raise GuardrailViolation("sql_not_select", f"只允许 SELECT 语句，收到: {stmt.key.upper()}")
