#!/bin/bash
set -e

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -e .
else
    source .venv/bin/activate
fi

if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    echo "[WARN] No .env file found. Copying from .env.example"
    echo "       Please edit services/analysis-service/.env with your LLM API key."
    cp .env.example .env
fi

echo "Starting Pixels Rover Python backend on port 8090..."
uvicorn app.main:app --host 0.0.0.0 --port 8090 --reload
