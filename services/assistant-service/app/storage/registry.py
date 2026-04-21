import logging

from app.storage.base import StorageBackend

logger = logging.getLogger(__name__)


class BackendRegistry:
    """Manages storage backend instances and schema-to-backend routing."""

    def __init__(self) -> None:
        self._backends: dict[str, StorageBackend] = {}
        self._schema_map: dict[str, str] = {}

    def register(self, backend: StorageBackend) -> None:
        self._backends[backend.backend_id] = backend
        logger.info("Registered backend: %s (%s)", backend.backend_id, backend.backend_type)

    def map_schema(self, schema_name: str, backend_id: str) -> None:
        if backend_id not in self._backends:
            raise ValueError(f"Backend '{backend_id}' not registered")
        self._schema_map[schema_name] = backend_id

    def get(self, backend_id: str) -> StorageBackend:
        if backend_id not in self._backends:
            raise KeyError(f"Backend '{backend_id}' not found")
        return self._backends[backend_id]

    def get_for_schema(self, schema: str) -> StorageBackend:
        backend_id = self._schema_map.get(schema)
        if not backend_id:
            if len(self._backends) == 1:
                return next(iter(self._backends.values()))
            raise KeyError(f"No backend mapped for schema '{schema}'")
        return self.get(backend_id)

    def list_backends(self) -> list[StorageBackend]:
        return list(self._backends.values())

    async def discover_all_schema_names(self) -> list[str]:
        all_schemas: list[str] = []
        for backend in self._backends.values():
            try:
                schemas = await backend.get_schemas()
                all_schemas.extend(schemas)
            except Exception as e:
                logger.warning("Failed to discover schemas from %s: %s", backend.backend_id, e)
        return all_schemas
