"""Integration tests for the OpenAPI error-envelope components.

Pins the ``§9.3 条 8`` contract: ``/openapi.json`` must declare
``ApiErrorDetails`` + ``ApiErrorResponse`` as top-level component schemas,
the ``errorCode`` field must enumerate every ``*_*`` string constant exported
from ``app.error_codes``, and the ``category`` field must enumerate every
``ErrorCategory`` value. These are the discoverability knobs API consumers
(frontend dispatcher, future codegen) key off.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app import error_codes
from app.error_codes import ErrorCategory
from app.schemas.api_error import ERROR_CODE_ENUM_VALUES


def _expected_error_code_values() -> set[str]:
    """Pull every SCREAMING_SNAKE_CASE string constant out of ``error_codes``.

    Mirrors the filter in :func:`app.schemas.api_error._collect_error_code_enum_values`
    so the test is the independent oracle — if a new constant slips through
    the filter in one place but not the other, the test catches the skew.
    """
    out: set[str] = set()
    for name, value in vars(error_codes).items():
        if name.startswith("_"):
            continue
        if not isinstance(value, str):
            continue
        if name != value:
            continue
        if not name.replace("_", "").isalnum() or not name.isupper():
            continue
        out.add(value)
    return out


class TestOpenApiErrorEnvelope:
    def test_error_code_enum_matches_module_exports(self) -> None:
        assert set(ERROR_CODE_ENUM_VALUES) == _expected_error_code_values()

    def test_error_code_enum_is_sorted(self) -> None:
        assert ERROR_CODE_ENUM_VALUES == sorted(ERROR_CODE_ENUM_VALUES)

    def test_error_code_enum_includes_every_prefix_family(self) -> None:
        prefixes = {value.split("_", 1)[0] for value in ERROR_CODE_ENUM_VALUES}
        # Every family that this service legitimately emits must be present.
        assert {"ANALYSIS", "GATEWAY", "INTERNAL"}.issubset(prefixes), prefixes


@pytest.mark.asyncio
class TestOpenApiEndpointShape:
    async def test_openapi_exposes_api_error_components(
        self, async_client: AsyncClient,
    ) -> None:
        resp = await async_client.get("/openapi.json")
        assert resp.status_code == 200
        doc = resp.json()

        components = (doc.get("components") or {}).get("schemas") or {}
        assert "ApiErrorDetails" in components, (
            "ApiErrorDetails schema missing from /openapi.json; the "
            "register_openapi_error_components() hook did not run"
        )
        assert "ApiErrorResponse" in components, (
            "ApiErrorResponse schema missing from /openapi.json"
        )

    async def test_error_code_enum_matches_source_constants(
        self, async_client: AsyncClient,
    ) -> None:
        resp = await async_client.get("/openapi.json")
        assert resp.status_code == 200
        doc = resp.json()
        details = doc["components"]["schemas"]["ApiErrorDetails"]
        error_code_field = details["properties"]["errorCode"]
        assert "enum" in error_code_field, (
            "ApiErrorDetails.errorCode must declare an explicit enum so API "
            "consumers can enumerate the closed set of emitted codes"
        )
        assert set(error_code_field["enum"]) == _expected_error_code_values()

    async def test_category_enum_matches_error_category(
        self, async_client: AsyncClient,
    ) -> None:
        resp = await async_client.get("/openapi.json")
        assert resp.status_code == 200
        doc = resp.json()
        schemas = doc["components"]["schemas"]
        details = schemas["ApiErrorDetails"]
        category_field = details["properties"]["category"]

        # pydantic emits the category as a $ref to a generated enum component
        # whose name is ``ErrorCategory`` (the class name). Resolve it.
        if "$ref" in category_field:
            ref = category_field["$ref"]
            assert ref == "#/components/schemas/ErrorCategory", ref
            category_schema = schemas["ErrorCategory"]
        else:
            category_schema = category_field

        assert "enum" in category_schema, category_schema
        assert set(category_schema["enum"]) == {c.value for c in ErrorCategory}

    async def test_business_prefix_AUTH_is_not_present(
        self, async_client: AsyncClient,
    ) -> None:
        """AUTH_* codes were retired with the old auth-service namespace.
        They must NOT appear in assistant-service's enum even if
        someone accidentally imports them."""
        resp = await async_client.get("/openapi.json")
        assert resp.status_code == 200
        doc = resp.json()
        enum = doc["components"]["schemas"]["ApiErrorDetails"][
            "properties"
        ]["errorCode"]["enum"]
        leaked = {v for v in enum if v.startswith("AUTH_")}
        assert leaked == set(), (
            f"AUTH_* codes leaked into assistant-service OpenAPI: {leaked}"
        )
