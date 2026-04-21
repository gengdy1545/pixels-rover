"""Dependency injection for FastAPI: singleton instances and per-request dependencies."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import get_settings
from app.storage.duckdb_backend import DuckDBBackend
from app.storage.registry import BackendRegistry
from app.core.llm_client import LLMClient
from app.core.harness import InputGuardrail, OutputGuardrail
from app.core.task_interpreter import TaskInterpreter
from app.core.semantic_resolver import SemanticResolver
from app.core.planner import Planner
from app.core.step_executor import StepExecutor
from app.core.result_interpreter import ResultInterpreter
from app.services.analysis_service import AnalysisService

_llm_client: LLMClient | None = None
_backend_registry: BackendRegistry | None = None
_duckdb_backend: DuckDBBackend | None = None
_input_guardrail: InputGuardrail | None = None


def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client


def get_input_guardrail() -> InputGuardrail:
    global _input_guardrail
    if _input_guardrail is None:
        _input_guardrail = InputGuardrail()
    return _input_guardrail


def get_duckdb_backend() -> DuckDBBackend:
    global _duckdb_backend
    if _duckdb_backend is None:
        settings = get_settings()
        _duckdb_backend = DuckDBBackend(
            backend_id="duckdb-local",
            database=settings.duckdb_path,
        )
    return _duckdb_backend


def get_backend_registry() -> BackendRegistry:
    global _backend_registry
    if _backend_registry is None:
        _backend_registry = BackendRegistry()
        duckdb = get_duckdb_backend()
        _backend_registry.register(duckdb)
    return _backend_registry


def get_analysis_service(db: AsyncSession = Depends(get_db)) -> AnalysisService:
    llm = get_llm_client()
    guardrail = OutputGuardrail(llm)
    registry = get_backend_registry()

    return AnalysisService(
        task_interpreter=TaskInterpreter(llm, guardrail),
        semantic_resolver=SemanticResolver(db),
        planner=Planner(llm, guardrail),
        step_executor=StepExecutor(llm),
        result_interpreter=ResultInterpreter(llm),
        backend_registry=registry,
        input_guardrail=get_input_guardrail(),
    )
