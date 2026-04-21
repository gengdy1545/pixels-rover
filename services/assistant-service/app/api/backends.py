import logging

from fastapi import APIRouter, Depends

from app.api_response import api_success
from app.auth import get_current_user
from app.dependencies import get_backend_registry

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/backends", tags=["backends"], dependencies=[Depends(get_current_user)])


@router.get("")
async def list_backends(registry=Depends(get_backend_registry)):
    backends = registry.list_backends()
    return api_success([
        {
            "backend_id": b.backend_id,
            "backend_type": b.backend_type,
            "capabilities": [c.value for c in b.capabilities],
        }
        for b in backends
    ])


@router.get("/{backend_id}/schemas")
async def list_schemas(backend_id: str, registry=Depends(get_backend_registry)):
    backend = registry.get(backend_id)
    schemas = await backend.get_schemas()
    return api_success({"schemas": schemas})


@router.get("/{backend_id}/schemas/{schema}/tables")
async def list_tables(backend_id: str, schema: str, registry=Depends(get_backend_registry)):
    backend = registry.get(backend_id)
    tables = await backend.get_tables(schema)
    return api_success({"tables": [t.model_dump() for t in tables]})


@router.get("/{backend_id}/schemas/{schema}/tables/{table}/columns")
async def list_columns(
    backend_id: str, schema: str, table: str,
    registry=Depends(get_backend_registry),
):
    backend = registry.get(backend_id)
    columns = await backend.get_columns(schema, table)
    return api_success({"columns": [c.model_dump() for c in columns]})
