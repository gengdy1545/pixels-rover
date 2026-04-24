"""OpenAPI registration for response-body schemas.

Background
----------
The assistant-service keeps its route handlers dict-shaped
(``return api_success({...})``) on purpose — see ``backend.md §6.0`` on the
unified failure envelope and the deliberate decision NOT to force every
handler to declare a ``response_model`` (which would double the schema
surface without improving type safety on the call-site, since business
logic already returns typed objects internally).

That choice is correct at the backend, but it has a downstream cost:
FastAPI's auto-generator (`fastapi.openapi.utils.get_openapi`) only
emits a ``components/schemas`` entry for a pydantic model if some route
declares it as ``response_model=`` or in ``request_body``. Response-only
models like ``AnalysisResponse`` / ``PlanStep`` / ``ConversationHistoryItem``
never appear on request bodies, so they are invisible in
``/openapi.json`` — which in turn means ``openapi-typescript`` cannot
generate TypeScript counterparts, defeating Task 4's "backend is the
single source of truth" goal.

This module closes that gap by explicitly registering a curated list of
pydantic response models into ``components/schemas`` after FastAPI's
default generator has run. The behaviour mirrors
``register_openapi_error_components``: we replace ``app.openapi`` with a
decorated version that folds additional ``model_json_schema()`` output
into the cached document.

Why an explicit list (not auto-discovery)
-----------------------------------------
The pydantic models in ``app.schemas.*`` include **internal-only** shapes
(``TaskEnvelope``, ``BudgetExhausted``, ``ResolvedContext``) that never
cross the wire. Exposing them would make the OpenAPI schema surface
speak for a contract the frontend cannot actually rely on. The explicit
list here is the single place a PR adds a model when the wire contract
grows — the same PR that lands a new response field.

Cross-service contract
----------------------
- The registered model list is consumed by
  ``scripts/export-openapi.py`` -> committed ``openapi.json`` ->
  ``frontend/src/shared/types/generated/assistant.d.ts`` (via
  ``openapi-typescript``). A change to any member here flows through
  in three deterministic steps.
- ``scripts/check-contracts.py`` asserts the snapshot and the generated
  ``.d.ts`` are both byte-identical to fresh re-renders, so drift
  surfaces at PR time as a failing check.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.schemas.backend import ColumnInfo, QueryResult, TableInfo, ValidationResult
from app.schemas.conversation import (
    ConversationDetailResponse,
    ConversationHistoryItem,
    ConversationThreadResponse,
)
from app.schemas.events import SSEEventType
from app.schemas.plan import AnalysisPlan, PlanStep, StepParams, StepResult
from app.schemas.response import AnalysisResponse
from app.schemas.semantic import (
    JoinPath,
    ResolvedContext,
    ResolvedDimension,
    ResolvedMetric,
)
from app.schemas.task import AnalysisTask, FilterCondition, TimeRange


# Ordered roughly by the backend layer each model represents
# (task -> plan -> response -> conversation -> semantic metadata ->
# backend metadata -> SSE event enum). Insertion order survives through
# the JSON snapshot because ``export-openapi.py`` writes with
# ``sort_keys=True`` — we only keep this list ordered here for readability
# of the diff when a new entry lands.
_RESPONSE_MODELS: tuple[type[BaseModel], ...] = (
    TimeRange,
    FilterCondition,
    AnalysisTask,
    StepParams,
    StepResult,
    PlanStep,
    AnalysisPlan,
    AnalysisResponse,
    ConversationThreadResponse,
    ConversationHistoryItem,
    ConversationDetailResponse,
    ResolvedMetric,
    ResolvedDimension,
    JoinPath,
    ResolvedContext,
    TableInfo,
    ColumnInfo,
    QueryResult,
    ValidationResult,
)


def _collected_sse_event_names() -> list[str]:
    """Return SSE event-name string literals in declaration order.

    ``SSEEventType`` is a ``str`` enum owning the wire vocabulary for the
    ``/api/v1/analysis`` stream (backend.md §6.6). Emitting the list as
    an OpenAPI string-enum gives the frontend a stable, grep-free
    reference for the stream event names.
    """
    return [member.value for member in SSEEventType]


def register_openapi_response_components(app: Any) -> None:
    """Attach curated response-body models as OpenAPI components.

    Idempotent — safe to call multiple times on the same ``app``.
    Installed by ``app.main.create_app()`` right next to
    ``register_openapi_error_components``; both share the same wrapper
    pattern (decorate ``app.openapi`` exactly once, cache via
    ``app.openapi_schema``).
    """
    if getattr(app, "_api_response_schemas_registered", False):
        return

    original_openapi = app.openapi

    def _openapi() -> dict[str, Any]:
        # Reuse FastAPI's cache; never re-render on every request.
        schema = original_openapi()
        components = schema.setdefault("components", {}).setdefault("schemas", {})

        # Fold each response model into ``components/schemas``; flatten
        # any nested ``$defs`` the same way ``register_openapi_error_components``
        # does so downstream ``$ref`` targets resolve to sibling keys
        # instead of orphan ``#/$defs/...`` references.
        for model_cls in _RESPONSE_MODELS:
            model_schema = model_cls.model_json_schema(
                ref_template="#/components/schemas/{model}",
            )
            defs = model_schema.pop("$defs", {})
            for def_name, def_schema in defs.items():
                components.setdefault(def_name, def_schema)
            # Do NOT overwrite an entry that FastAPI already produced —
            # request-body schemas (e.g. ``CreateConversationRequest``)
            # are shared between the two code paths and should keep the
            # auto-generator's definition. ``setdefault`` preserves that
            # precedence without silently masking drift.
            components.setdefault(model_cls.__name__, model_schema)

        # Expose the SSE event-name string enum; the frontend's
        # ``SSEEventName`` union is already byte-pinned against
        # ``SSEEventType`` by ``scripts/check-contracts.py`` (see the
        # ``sse-event-names-match-backend`` check), and surfacing the
        # enum in OpenAPI gives any future non-browser client the same
        # guarantee without a second check-contracts rule.
        components.setdefault(
            "SSEEventName",
            {
                "type": "string",
                "enum": _collected_sse_event_names(),
                "title": "SSEEventName",
                "description": (
                    "Server-sent event names emitted by "
                    "POST /api/v1/analysis. Mirrors "
                    "app.schemas.events.SSEEventType."
                ),
            },
        )

        app.openapi_schema = schema
        return schema

    app.openapi = _openapi  # type: ignore[assignment]
    app._api_response_schemas_registered = True  # type: ignore[attr-defined]
