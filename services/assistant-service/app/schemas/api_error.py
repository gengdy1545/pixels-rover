"""OpenAPI schemas for the unified failure envelope.

These pydantic models exist **only** to make the error-response shape visible
in the generated OpenAPI document (``/openapi.json``). They are not used as
call-site return types — that remains the ``api_error(...)`` helper which
produces the plain dict structure defined by ``backend.md §6.0``.

Why this file exists (``§9.3 condition 8`` in ``.notes/todolist.md``):

Without these schema components, ``/openapi.json`` exposes ``details`` as a
free-form object, which hides two things from API consumers:

1. **``details.errorCode`` enumeration** — the list of stable SCREAMING_SNAKE_CASE
   business codes emitted by this service. Consumers (frontend, future SDK
   codegen, doc tooling) cannot enumerate the closed set without grepping
   through ``app/api/**`` call sites.
2. **``details.category`` enumeration** — the coarse ``ErrorCategory`` used
   for the "unknown-errorCode-fall-back" branch in the frontend dispatcher
   (``backend.md §6.3.2``). Without it the frontend has no discoverable way
   to learn what category values may appear.

The shape mirrors ``app/api_response.py::api_error`` exactly so that if we
ever switch call sites to return typed models the envelope on the wire stays
byte-identical.

Cross-service alignment:

- ``errorCode`` enum values == the ``ANALYSIS_*`` / ``CONVERSATION_*`` /
  ``SEMANTIC_*`` / ``GATEWAY_*`` / ``INTERNAL_*`` constants exported from
  ``app.error_codes``. The value list is derived from that module at import
  time so new codes automatically appear in the OpenAPI enum without any
  manual duplication (the bidirectional alignment with the frontend TS union
  is already guarded by ``scripts/check-contracts.py::
  frontend-analysis-union-equals-python-source``).
- ``category`` is the same ``ErrorCategory`` string enum imported from
  ``app.error_codes``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app import error_codes
from app.error_codes import ErrorCategory


def _collect_error_code_enum_values() -> list[str]:
    """Return every ``SCREAMING_SNAKE_CASE`` string constant that lives in
    ``app.error_codes`` and is a plausible ``details.errorCode`` emission.

    Filtering rule: module attribute is a ``str`` with uppercase letters /
    underscores / digits only, does not start with an underscore, and the
    literal value equals the attribute name (guards against unrelated string
    constants that happen to be uppercase). This way adding a new constant
    to ``app/error_codes.py`` is enough — nothing to duplicate here.
    """
    out: list[str] = []
    for name, value in vars(error_codes).items():
        if name.startswith("_"):
            continue
        if not isinstance(value, str):
            continue
        if name != value:
            continue
        if not name.replace("_", "").isalnum() or not name.isupper():
            continue
        out.append(value)
    out.sort()
    return out


ERROR_CODE_ENUM_VALUES: list[str] = _collect_error_code_enum_values()


class ApiErrorDetails(BaseModel):
    """The ``details`` object carried by every non-2xx response.

    See ``backend.md §6.0``. ``errorCode`` + ``category`` are both mandatory
    (``backend.md §6.3.2``): the only exception is the "§6.5 wholly-unknown
    unhandled exception" safety-net which emits ``details: null`` and is
    documented separately.
    """

    model_config = ConfigDict(extra="allow")

    errorCode: str = Field(
        ...,
        description=(
            "Stable SCREAMING_SNAKE_CASE identifier for the failure. Business "
            "prefixes (ANALYSIS_* / CONVERSATION_* / SEMANTIC_*) are owned by "
            "this service; infrastructure prefixes (GATEWAY_* / INTERNAL_*) "
            "are injected by the gateway or the service-to-service auth "
            "filter and are reported for traceability."
        ),
        json_schema_extra={"enum": ERROR_CODE_ENUM_VALUES},
    )
    category: ErrorCategory = Field(
        ...,
        description=(
            "Coarse failure category. The frontend's fallback dispatcher "
            "(backend.md §6.3.2 step 2) keys off this field when the exact "
            "``errorCode`` is not yet recognized."
        ),
    )


class ApiErrorResponse(BaseModel):
    """The full non-2xx envelope (``backend.md §6.0``).

    Top-level ``code`` equals the HTTP status; ``data`` is always absent on
    failure; ``details`` is always present except for the §6.5 safety-net.
    """

    code: int = Field(
        ...,
        description=(
            "HTTP status code; strictly equal to the transport status line. "
            "Must NOT carry a 5-digit legacy business code (sunset, "
            "backend.md §6.3)."
        ),
    )
    message: str = Field(
        ...,
        description="Human-readable short description (do not leak internals).",
    )
    details: ApiErrorDetails | None = Field(
        None,
        description=(
            "Structured failure details. Present on every non-2xx response "
            "except the §6.5 wholly-unknown-exception safety-net."
        ),
    )
    requestId: str | None = Field(
        None,
        description=(
            "Request trace id; echoed from gateway-injected ``X-Request-Id`` "
            "or a ``missing-<8 hex>`` fallback when the header is absent "
            "(backend.md §5)."
        ),
    )


def register_openapi_error_components(app: Any) -> None:
    """Attach ``ApiErrorDetails`` + ``ApiErrorResponse`` as OpenAPI components.

    FastAPI only auto-generates component schemas for models it sees on
    concrete route signatures. The error envelope is produced by
    ``api_error(...)`` as a plain dict — which is the right call-site API
    (avoids forcing every route to declare an error ``response_model``) but
    hides the schema from ``/openapi.json``. This helper injects the two
    models into the generated document's ``components/schemas`` so API
    consumers can enumerate ``details.errorCode`` / ``details.category``
    values without grepping the Python source.

    Idempotent: re-calling on the same ``app`` instance is a no-op.
    """

    from fastapi.openapi.utils import get_openapi  # local import; optional

    if getattr(app, "_api_error_schemas_registered", False):
        return

    original = app.openapi

    def _openapi() -> dict[str, Any]:
        # FastAPI caches the schema on ``app.openapi_schema``; reuse that so
        # we don't regenerate on every request.
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        # ``model_json_schema`` emits nested enums / models under ``$defs``;
        # OpenAPI expects them flattened into ``components/schemas`` and any
        # ``$ref`` targets rewritten accordingly. Do both here so consumers
        # can follow the references we hand them.
        for model_cls in (ApiErrorDetails, ApiErrorResponse):
            model_schema = model_cls.model_json_schema(
                ref_template="#/components/schemas/{model}",
            )
            defs = model_schema.pop("$defs", {})
            for def_name, def_schema in defs.items():
                components.setdefault(def_name, def_schema)
            components[model_cls.__name__] = model_schema
        app.openapi_schema = schema
        return schema

    app.openapi = _openapi  # type: ignore[assignment]
    app._api_error_schemas_registered = True  # type: ignore[attr-defined]
    # Retain the original on the app for tests / introspection.
    app._original_openapi_fn = original  # type: ignore[attr-defined]
