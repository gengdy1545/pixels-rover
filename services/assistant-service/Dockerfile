# ---- Build stage ----
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY app ./app

# Install the package and its dependencies into a virtual env
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir -e .

# ---- Runtime stage ----
FROM python:3.12-slim

WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Copy virtual env from builder
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build/app ./app
COPY --from=builder /build/pyproject.toml .

ENV PATH="/opt/venv/bin:$PATH"

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8090/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
