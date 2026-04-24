"""
Task lifecycle management: timeout enforcement, cancellation detection, and zombie recovery.

Strategies:
  - Cooperative timeout: RunContext.check_budget() is called between steps (existing).
  - Hard timeout: asyncio.wait_for wraps the entire analysis stream as a safety net.
  - Client disconnect: SSE generator detects asyncio.CancelledError when the client
    disconnects and marks the session as 'cancelled'.
  - Startup recovery: on service boot, all in-flight sessions are marked as 'failed'
    with a clear reason ("Service restarted, task aborted").
  - Periodic recovery: a background task scans for sessions that have exceeded
    2x max_wall_time_sec and marks them as 'timeout'.
"""

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models.session import AnalysisSession

logger = logging.getLogger(__name__)

# Statuses that indicate a session is still in-flight
IN_FLIGHT_STATUSES = (
    "received",
    "understanding",
    "resolving",
    "planning",
    "executing",
    "summarizing",
)

# How often the periodic reaper runs (seconds)
REAPER_INTERVAL_SEC = 300  # 5 minutes

# Sessions older than max_wall_time * this multiplier are considered zombies
ZOMBIE_WALL_TIME_MULTIPLIER = 2


async def recover_zombie_sessions_on_startup() -> int:
    """Mark all in-flight sessions as failed on service startup.

    Returns the number of sessions recovered.
    """
    async with async_session_factory() as db:
        result = await db.execute(
            update(AnalysisSession)
            .where(AnalysisSession.status.in_(IN_FLIGHT_STATUSES))
            .values(
                status="failed",
                error="Service restarted, task aborted",
                completed_at=datetime.utcnow(),
            )
        )
        await db.commit()
        count = result.rowcount  # type: ignore[attr-defined]
        if count > 0:
            logger.warning("Startup recovery: marked %d zombie session(s) as failed", count)
        else:
            logger.info("Startup recovery: no zombie sessions found")
        return count


async def _reap_zombie_sessions() -> int:
    """Find sessions that have been in-flight for too long and mark them as timeout.

    Returns the number of sessions reaped.
    """
    cutoff = datetime.utcnow() - timedelta(seconds=180 * ZOMBIE_WALL_TIME_MULTIPLIER)
    async with async_session_factory() as db:
        result = await db.execute(
            update(AnalysisSession)
            .where(
                AnalysisSession.status.in_(IN_FLIGHT_STATUSES),
                AnalysisSession.created_at < cutoff,
            )
            .values(
                status="failed",
                error="Task timed out (zombie reaper)",
                completed_at=datetime.utcnow(),
            )
        )
        await db.commit()
        count = result.rowcount  # type: ignore[attr-defined]
        if count > 0:
            logger.warning("Periodic reaper: marked %d zombie session(s) as failed", count)
        return count


async def run_periodic_reaper() -> None:
    """Run the periodic zombie reaper forever.

    This coroutine is shared by the API lifespan and the standalone
    ``python -m app.workers.reaper`` entrypoint.
    """
    while True:
        try:
            await asyncio.sleep(REAPER_INTERVAL_SEC)
            await _reap_zombie_sessions()
        except asyncio.CancelledError:
            logger.info("Periodic reaper shutting down")
            break
        except Exception:
            logger.exception("Periodic reaper encountered an error")


async def start_periodic_reaper() -> asyncio.Task:
    """Start the background periodic zombie reaper task."""
    task = asyncio.create_task(run_periodic_reaper(), name="zombie-reaper")
    logger.info("Periodic zombie reaper started (interval=%ds)", REAPER_INTERVAL_SEC)
    return task
