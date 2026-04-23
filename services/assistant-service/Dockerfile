# ---- Build stage ----
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY app ./app

RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir -e .

# ---- Runtime stage ----
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build/app ./app
COPY --from=builder /build/pyproject.toml .
# Alembic configuration + migrations (SSOT for pixels_analysis schema).
# See docs/development/backend.md §12.2. Migrations are applied by
# entrypoint.sh BEFORE uvicorn starts.
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV PATH="/opt/venv/bin:$PATH"

EXPOSE 8090

# Docker HEALTHCHECK uses /health (process-only liveness; see
# backend.md §7.1). /internal/ready is NOT used here because /internal/ready
# failure means a dependency (DB) is down, which is not solvable by
# container restart — it only belongs to /gateway/ready aggregation.
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD curl -f http://localhost:8090/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
