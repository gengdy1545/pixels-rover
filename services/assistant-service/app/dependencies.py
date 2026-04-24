"""Dependency injection for FastAPI: singleton instances and per-request dependencies."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import get_settings
from app.storage.duckdb_backend import DuckDBBackend
from app.storage.registry import BackendRegistry
from app.infra.llm import LLMClient
from app.core.harness import InputGuardrail, OutputGuardrail
from app.core.semantic_resolver import SemanticResolver
from app.core import registry as core_registry
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
    # architecture-tasks §Task 16 acceptance clause 2 ("Replacing
    # Planner with a stub only requires swapping one symbol in a
    # registry, no edits inside `core/`"): every core seam is
    # resolved through :mod:`app.core.registry`. Swapping a
    # component — planner, step executor, interpreter — is a single
    # ``core_registry.register("<seam>", factory)`` call at startup
    # or in a pytest fixture. This file (one layer up from core/)
    # stays the ONLY place that knows each seam's concrete factory
    # signature, keeping the pluggability visible in the tree.
    llm = get_llm_client()
    guardrail = OutputGuardrail(llm)
    registry = get_backend_registry()

    planner_factory = core_registry.get("planner")
    step_executor_factory = core_registry.get("step_executor")
    result_interpreter_factory = core_registry.get("result_interpreter")
    task_interpreter_factory = core_registry.get("task_interpreter")

    return AnalysisService(
        task_interpreter=task_interpreter_factory(llm, guardrail),
        semantic_resolver=SemanticResolver(db),
        planner=planner_factory(llm, guardrail),
        step_executor=step_executor_factory(llm),
        result_interpreter=result_interpreter_factory(llm),
        backend_registry=registry,
        input_guardrail=get_input_guardrail(),
    )
