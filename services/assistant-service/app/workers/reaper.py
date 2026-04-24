import asyncio
import logging

from app.logging_config import setup_logging
from app.core.task_lifecycle import run_periodic_reaper


async def main() -> None:
    setup_logging()
    logging.getLogger(__name__).info("Starting standalone assistant reaper")
    await run_periodic_reaper()


if __name__ == "__main__":
    asyncio.run(main())
