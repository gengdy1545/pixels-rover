#!/bin/sh
# Assistant-service container entrypoint.
#
# Startup order (see docs/development/backend.md §12.2 and §7):
#   1. `alembic upgrade head`  — runs synchronously; any failure -> exit 1
#                                  before uvicorn binds to the port. This
#                                  guarantees that /health (§7.1) and
#                                  /internal/ready (§7.2) never respond in a
#                                  "process up but schema not at head" state.
#   2. `exec uvicorn ...`      — replaces the shell PID; uvicorn is now PID 1
#                                  so docker stop signal forwarding works.
#
# DO NOT move `alembic upgrade head` into FastAPI lifespan — by the time
# lifespan runs uvicorn has already started accepting connections, which
# would expose half-ready state to the gateway / clients.

set -eu

echo "[entrypoint] Running Alembic migrations (upgrade head)..."
alembic upgrade head
echo "[entrypoint] Alembic migrations complete; starting uvicorn."

exec uvicorn app.main:app --host 0.0.0.0 --port 8090
