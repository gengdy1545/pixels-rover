#!/usr/bin/env bash
#
# Unified startup script for Pixels Rover.
#
# Usage:
#   ./start.sh              Start all services (Java + Python + Frontend)
#   ./start.sh java         Start Java backend only (auth, :8081)
#   ./start.sh python       Start Python backend only (analysis, :8090)
#   ./start.sh frontend     Start frontend dev server only (:3000)
#   ./start.sh --prod       Build frontend for production and start both backends
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JAVA_DIR="$SCRIPT_DIR/services/auth-service"
PYTHON_DIR="$SCRIPT_DIR/services/analysis-service"
FRONTEND_DIR="$SCRIPT_DIR/apps/frontend"
JWT_KEYS_DIR="$SCRIPT_DIR/.tmp/jwt-keys"
JWT_DEFAULT_KID="${JWT_DEFAULT_KID:-dev-rsa-1}"
JWT_DEFAULT_PRIVATE_KEY_PATH="$JWT_KEYS_DIR/${JWT_DEFAULT_KID}-private.pem"
JWT_DEFAULT_PUBLIC_KEY_PATH="$JWT_KEYS_DIR/${JWT_DEFAULT_KID}-public.pem"
JWT_DEFAULT_PUBLIC_KEYS_PATH="$JWT_KEYS_DIR/${JWT_DEFAULT_KID}-public-keys.json"

JAVA_PID=""
PYTHON_PID=""
FRONTEND_PID=""

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_step()  { echo -e "${CYAN}[STEP]${NC}  $*"; }

cleanup() {
    echo ""
    log_info "Shutting down..."

    for pid_var in FRONTEND_PID PYTHON_PID JAVA_PID; do
        pid="${!pid_var}"
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            log_info "Stopping $pid_var (PID: $pid)..."
            kill "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
        fi
    done

    log_info "All services stopped."
    exit 0
}

trap cleanup SIGINT SIGTERM

check_java() {
    if ! command -v java &>/dev/null; then
        log_error "Java is not installed. JDK 17+ is required."
        return 1
    fi
    if ! command -v mvn &>/dev/null; then
        log_error "Maven is not installed."
        return 1
    fi
    return 0
}

check_python() {
    if ! command -v python3 &>/dev/null; then
        log_error "Python 3 is not installed. Python 3.10+ is required."
        return 1
    fi
    return 0
}

check_node() {
    if ! command -v node &>/dev/null; then
        log_error "Node.js is not installed."
        return 1
    fi
    if ! command -v npm &>/dev/null; then
        log_error "npm is not installed."
        return 1
    fi
    return 0
}

ensure_dev_jwt_keys() {
    if [[ -n "${JWT_PRIVATE_KEY_PATH:-}" || -n "${ROVER_JWT_PUBLIC_KEYS_PATH:-}" ]]; then
        log_info "Using externally provided JWT key configuration."
        return 0
    fi

    if [[ ! -f "$JWT_DEFAULT_PRIVATE_KEY_PATH" || ! -f "$JWT_DEFAULT_PUBLIC_KEY_PATH" || ! -f "$JWT_DEFAULT_PUBLIC_KEYS_PATH" ]]; then
        log_step "Generating local RS256 JWT keys for development..."
        bash "$SCRIPT_DIR/scripts/generate-jwt-rsa-keys.sh" "$JWT_KEYS_DIR" "$JWT_DEFAULT_KID" >/dev/null
    fi

    export JWT_ALGORITHM=RS256
    export JWT_ACTIVE_KID="$JWT_DEFAULT_KID"
    export JWT_PRIVATE_KEY_PATH="$JWT_DEFAULT_PRIVATE_KEY_PATH"
    export JWT_PUBLIC_KEY_PATH="$JWT_DEFAULT_PUBLIC_KEY_PATH"
    export JWT_PUBLIC_KEYS_PATH="$JWT_DEFAULT_PUBLIC_KEYS_PATH"

    export ROVER_JWT_ALGORITHM=RS256
    export ROVER_JWT_ACTIVE_KID="$JWT_DEFAULT_KID"
    export ROVER_JWT_PUBLIC_KEY_PATH="$JWT_DEFAULT_PUBLIC_KEY_PATH"
    export ROVER_JWT_PUBLIC_KEYS_PATH="$JWT_DEFAULT_PUBLIC_KEYS_PATH"

    log_info "Development JWT mode: RS256 (kid=$JWT_DEFAULT_KID)."
}

start_java() {
    check_java || exit 1
    ensure_dev_jwt_keys
    log_step "Starting Java backend (auth) on port 8081..."
    cd "$JAVA_DIR"
    mvn spring-boot:run -q &
    JAVA_PID=$!
    log_info "Java backend started (PID: $JAVA_PID)."
}

start_python() {
    check_python || exit 1
    ensure_dev_jwt_keys
    log_step "Starting Python backend (analysis) on port 8090..."
    cd "$PYTHON_DIR"

    if [[ ! -d ".venv" ]]; then
        log_step "Creating Python virtual environment..."
        python3 -m venv .venv
        source .venv/bin/activate
        pip install --quiet -e .
    else
        source .venv/bin/activate
    fi

    if [[ ! -f ".env" ]] && [[ -f ".env.example" ]]; then
        log_warn "No .env file found. Copying from .env.example — please edit services/analysis-service/.env with your LLM API key."
        cp .env.example .env
    fi

    uvicorn app.main:app --host 0.0.0.0 --port 8090 --reload &
    PYTHON_PID=$!
    log_info "Python backend started (PID: $PYTHON_PID)."
}

start_frontend() {
    check_node || exit 1
    log_step "Installing frontend dependencies..."
    cd "$FRONTEND_DIR"

    if [[ ! -d "node_modules" ]]; then
        npm install
    else
        log_info "node_modules exists, skipping npm install."
    fi

    log_step "Starting frontend dev server on port 3000..."
    npm run dev &
    FRONTEND_PID=$!
    log_info "Frontend started (PID: $FRONTEND_PID)."
}

build_frontend_prod() {
    check_node || exit 1
    log_step "Building frontend for production..."
    cd "$FRONTEND_DIR"

    if [[ ! -d "node_modules" ]]; then
        npm install
    fi

    npm run build
    log_info "Frontend production build completed → apps/frontend/dist/"
}

print_banner() {
    echo -e "${CYAN}"
    echo "  ____  _          _       ____"
    echo " |  _ \\(_)_  _____| |___  |  _ \\ _____   _____ _ __"
    echo " | |_) | \\ \\/ / _ \\ / __| | |_) / _ \\ \\ / / _ \\ '__|"
    echo " |  __/| |>  <  __/ \\__ \\ |  _ < (_) \\ V /  __/ |"
    echo " |_|   |_/_/\\_\\___|_|___/ |_| \\_\\___/ \\_/ \\___|_|"
    echo -e "${NC}"
    echo ""
}

print_usage() {
    echo "Usage: $0 [java|python|frontend|--prod|-h]"
    echo ""
    echo "  (no args)    Start all services (Java + Python + Frontend)"
    echo "  java         Start Java backend only (auth, :8081)"
    echo "  python       Start Python backend only (analysis, :8090)"
    echo "  frontend     Start frontend dev server only (:3000)"
    echo "  --prod       Build frontend and start both backends"
    echo ""
}

# --- Main ---

print_banner

MODE="${1:-all}"

case "$MODE" in
    java|backend)
        start_java
        echo ""
        log_info "========================================="
        log_info "  Java Backend (Auth) running at:"
        log_info "    ${CYAN}http://localhost:8081${NC}"
        log_info "  JWT mode: ${CYAN}${JWT_ALGORITHM:-HS256}${NC}"
        log_info "========================================="
        log_info "Press Ctrl+C to stop."
        wait "$JAVA_PID"
        ;;
    python)
        start_python
        echo ""
        log_info "========================================="
        log_info "  Python Backend (Analysis) running at:"
        log_info "    ${CYAN}http://localhost:8090${NC}"
        log_info "  JWT mode: ${CYAN}${ROVER_JWT_ALGORITHM:-HS256}${NC}"
        log_info "========================================="
        log_info "Press Ctrl+C to stop."
        wait "$PYTHON_PID"
        ;;
    frontend)
        start_frontend
        echo ""
        log_info "========================================="
        log_info "  Frontend dev server is ready!"
        log_info "    ${CYAN}http://localhost:3000${NC}"
        log_info ""
        log_info "  Proxy: /api/v1/auth/* → :8081 (Java)"
        log_info "  Proxy: /api/*        → :8090 (Python)"
        log_info "========================================="
        log_info "Press Ctrl+C to stop."
        wait "$FRONTEND_PID"
        ;;
    --prod)
        build_frontend_prod
        start_java
        start_python
        echo ""
        log_info "=========================================="
        log_info "  Production mode is ready!"
        log_info ""
        log_info "  Java Backend (Auth)     → ${CYAN}http://localhost:8081${NC}"
        log_info "  Python Backend (Analysis)→ ${CYAN}http://localhost:8090${NC}"
        log_info "  Frontend static files   → apps/frontend/dist/"
        log_info "=========================================="
        log_info "Press Ctrl+C to stop."
        wait
        ;;
    all)
        start_java
        start_python
        start_frontend
        echo ""
        log_info "=========================================="
        log_info "  All services are running!"
        log_info ""
        log_info "  Java Backend (Auth)      → ${CYAN}http://localhost:8081${NC}"
        log_info "  Python Backend (Analysis) → ${CYAN}http://localhost:8090${NC}"
        log_info "  Frontend UI              → ${CYAN}http://localhost:3000${NC}"
        log_info "  JWT mode                 → ${CYAN}${JWT_ALGORITHM:-HS256}${NC}"
        log_info ""
        log_info "  Open: ${CYAN}http://localhost:3000${NC}"
        log_info "=========================================="
        log_info "Press Ctrl+C to stop all services."
        wait
        ;;
    -h|--help)
        print_usage
        exit 0
        ;;
    *)
        log_error "Unknown option: $MODE"
        print_usage
        exit 1
        ;;
esac
