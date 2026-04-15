"""
Unified logging configuration for the analysis service.

Log format:
    <timestamp> <LEVEL> [analysis-service] [req:<requestId>] [user:<userId>] <logger> - <message>

Log level conventions:
    DEBUG - Development diagnostics (SQL statements, LLM request/response details)
    INFO  - Normal business flow (request received, task started/completed, login success)
    WARN  - Recoverable anomalies (token near expiry, LLM retry, budget approaching limit)
    ERROR - Unrecoverable failures (DB connection lost, unhandled exception, task failed)
"""

import logging

from app.request_id import get_request_id

SERVICE_NAME = "analysis-service"


class UnifiedFormatter(logging.Formatter):
    """Formatter that injects requestId and userId from context vars."""

    def format(self, record: logging.LogRecord) -> str:
        record.service = SERVICE_NAME
        record.request_id = get_request_id() or "N/A"
        record.user_id = getattr(record, "user_id", None) or "N/A"
        return super().format(record)


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logger with the unified format."""
    formatter = UnifiedFormatter(
        fmt=(
            "%(asctime)s %(levelname)-5s [%(service)s] "
            "[req:%(request_id)s] [user:%(user_id)s] "
            "%(name)s - %(message)s"
        ),
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    # Remove existing handlers to avoid duplicate output
    root.handlers.clear()
    root.addHandler(handler)

    # Suppress noisy third-party loggers
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("litellm").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
