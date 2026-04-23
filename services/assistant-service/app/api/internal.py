"""Internal readiness endpoint for assistant-service.

Contract (see docs/development/backend.md §7.2 and docs/development/gateway.md §4.1):

- ``GET /internal/ready`` reports "this service and its direct dependencies
  are ready to serve traffic". Probed dependencies:

    * MySQL connectivity (SELECT 1 via the async engine).
    * Alembic migration head (compare the DB's ``alembic_version`` row
      against the highest revision present in the bundled scripts; any
      mismatch -> 503 + SERVICE_NOT_READY).

- Only consumed by the gateway via an ``internal`` location
  (``/__ready_probe/assistant``). External reachability is blocked at the
  gateway layer (nginx ``internal;`` directive); this service does NOT
  require a shared-secret check here.

- Returns the §6.0 envelope. Success -> 200 with
  ``data.status == "UP"``; failure -> 503 with
  ``details.errorCode = "SERVICE_NOT_READY"`` and per-dependency checks in
  ``details.checks``. No per-dependency errorCode expansion -- consumers
  read ``checks[*].status`` for diagnostic detail.

- Failure here MUST NOT trigger container restart: it is a readiness
  signal, not a liveness signal (that is ``/health``).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.database import async_session_factory, engine

logger = logging.getLogger(__name__)

router = APIRouter()

# Alembic config path, resolved at import time. When running inside the
# container image (see services/assistant-service/Dockerfile) this is
# /app/alembic.ini; in test runs it can fall through to the module default,
# but the endpoint is only ever invoked by the gateway against the
# containerised process, so the container path is the path that matters.
_ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


async def _check_database(checks: dict[str, Any]) -> bool:
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = {"status": "UP"}
        return True
    except Exception as exc:
        logger.warning("/internal/ready: database check failed: %s", exc)
        checks["database"] = {
            "status": "DOWN",
            "error": f"{type(exc).__name__}: {exc}",
        }
        return False


async def _check_migration_head(checks: dict[str, Any]) -> bool:
    """Compare ``alembic_version`` in the DB against the highest script revision.

    Uses a short-lived sync-like connection via ``engine.begin()`` +
    ``run_sync`` to invoke Alembic's synchronous ``MigrationContext`` API.
    This keeps the check self-contained: no Alembic CLI process is spawned,
    and no extra pool is created.
    """
    if not _ALEMBIC_INI.exists():
        checks["migrations"] = {
            "status": "DOWN",
            "error": f"alembic.ini not found at {_ALEMBIC_INI}",
        }
        return False

    try:
        cfg = AlembicConfig(str(_ALEMBIC_INI))
        script = ScriptDirectory.from_config(cfg)
        expected_head = script.get_current_head()

        def _read_revision(sync_connection) -> str | None:
            ctx = MigrationContext.configure(sync_connection)
            return ctx.get_current_revision()

        async with engine.connect() as conn:
            current = await conn.run_sync(_read_revision)

        if expected_head is None:
            checks["migrations"] = {
                "status": "DOWN",
                "error": "no script head discovered; alembic/versions is empty?",
            }
            return False

        if current != expected_head:
            checks["migrations"] = {
                "status": "DOWN",
                "head": expected_head,
                "current": current,
            }
            return False

        checks["migrations"] = {"status": "UP", "head": expected_head}
        return True
    except Exception as exc:
        logger.warning("/internal/ready: migration check failed: %s", exc)
        checks["migrations"] = {
            "status": "DOWN",
            "error": f"{type(exc).__name__}: {exc}",
        }
        return False


@router.get("/internal/ready")
async def internal_ready() -> JSONResponse:
    checks: dict[str, Any] = {}

    db_ok = await _check_database(checks)
    migrations_ok = await _check_migration_head(checks)

    all_ok = db_ok and migrations_ok

    if all_ok:
        return JSONResponse(
            status_code=200,
            content={
                "code": 200,
                "message": "ready",
                "data": {
                    "status": "UP",
                    "service": "assistant-service",
                    "version": "0.1.0",
                    "checks": checks,
                },
            },
        )

    return JSONResponse(
        status_code=503,
        content={
            "code": 503,
            "message": "assistant-service is not ready: one or more dependencies DOWN",
            "details": {
                "errorCode": "SERVICE_NOT_READY",
                "category": "UPSTREAM",
                "checks": checks,
            },
        },
    )
