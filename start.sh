#!/usr/bin/env bash
#
# Unified startup script for Pixels Rover component development.
#
# Usage:
#   ./start.sh              Start auth-service + assistant-service + frontend dev server
#   ./start.sh java         Start auth-service only (:8081)
#   ./start.sh python       Start assistant-service only (:8090)
#   ./start.sh frontend     Start frontend dev server only (:3000)
#   ./start.sh --prod       Build frontend and start both backend services
#
# For the canonical end-to-end topology, prefer:
#   docker compose up --build
#
# The frontend dev server proxies /api to http://localhost:80, so it expects the
# APISIX gateway to be running separately.
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JAVA_DIR="$SCRIPT_DIR/services/auth-service"
PYTHON_DIR="$SCRIPT_DIR/services/assistant-service"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
JWT_KEYS_DIR="$SCRIPT_DIR/.tmp/jwt-keys"
JWT_DEFAULT_KID="${JWT_DEFAULT_KID:-dev-rsa-1}"
JWT_DEFAULT_PRIVATE_KEY_PATH="$JWT_KEYS_DIR/${JWT_DEFAULT_KID}-private.pem"
JWT_DEFAULT_PUBLIC_KEY_PATH="$JWT_KEYS_DIR/${JWT_DEFAULT_KID}-public.pem"

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

warn_if_gateway_missing() {
    if ! command -v curl &>/dev/null; then
        return 0
    fi

    if ! curl -fsS "http://localhost:80/gateway/live" >/dev/null 2>&1; then
        log_warn "Gateway is not reachable at http://localhost:80."
        log_warn "Frontend /api requests will fail until APISIX is running."
        log_warn "Use 'docker compose up --build' for the full topology."
    fi
}

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
    if [[ -n "${JWT_PRIVATE_KEY_PATH:-}" ]]; then
        log_info "Using externally provided JWT key configuration."
        return 0
    fi

    if [[ ! -f "$JWT_DEFAULT_PRIVATE_KEY_PATH" || ! -f "$JWT_DEFAULT_PUBLIC_KEY_PATH" ]]; then
        log_step "Generating local RS256 JWT keys for development..."
        bash "$SCRIPT_DIR/scripts/generate-jwt-rsa-keys.sh" "$JWT_KEYS_DIR" "$JWT_DEFAULT_KID" >/dev/null
    fi

    export JWT_ALGORITHM=RS256
    export JWT_ACTIVE_KID="$JWT_DEFAULT_KID"
    export JWT_PRIVATE_KEY_PATH="$JWT_DEFAULT_PRIVATE_KEY_PATH"
    export JWT_PUBLIC_KEY_PATH="$JWT_DEFAULT_PUBLIC_KEY_PATH"
    # Multi-kid verification source during rotation: the local key directory is
    # enumerated for every <kid>-public.pem. The former "<kid>-public-keys.json"
    # merged-public-key artifact (and its companion /api/v1/auth/jwks surface)
    # have been retired — see docs/design/jwt-rotation.md §1.2.
    export JWT_PUBLIC_KEYS_DIRECTORY="$JWT_KEYS_DIR"

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
    log_step "Starting Python backend (assistant) on port 8090..."
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
        log_warn "No .env file found. Copying from .env.example — please edit services/assistant-service/.env with your LLM API key."
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
    log_info "Frontend production build completed → frontend/dist/"
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
    echo "  (no args)    Start auth-service + assistant-service + frontend dev server"
    echo "  java         Start auth-service only (:8081)"
    echo "  python       Start assistant-service only (:8090)"
    echo "  frontend     Start frontend dev server only (:3000)"
    echo "  --prod       Build frontend and start both backend services"
    echo ""
    echo "  Full gateway topology: docker compose up --build"
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
        warn_if_gateway_missing
        echo ""
        log_info "========================================="
        log_info "  Frontend dev server is ready!"
        log_info "    ${CYAN}http://localhost:3000${NC}"
        log_info ""
        log_info "  Proxy: /api/* → ${CYAN}http://localhost:80${NC} (APISIX Gateway)"
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
        log_info "  Frontend static files   → frontend/dist/"
        log_info "=========================================="
        log_info "Press Ctrl+C to stop."
        wait
        ;;
    all)
        start_java
        start_python
        start_frontend
        warn_if_gateway_missing
        echo ""
        log_info "=========================================="
        log_info "  Component development mode is running!"
        log_info ""
        log_info "  Java Backend (Auth)      → ${CYAN}http://localhost:8081${NC}"
        log_info "  Python Backend (Analysis) → ${CYAN}http://localhost:8090${NC}"
        log_info "  Frontend UI              → ${CYAN}http://localhost:3000${NC}"
        log_info "  Frontend API entry       → ${CYAN}http://localhost:80${NC} (Gateway)"
        log_info "  JWT mode                 → ${CYAN}${JWT_ALGORITHM:-HS256}${NC}"
        log_info ""
        log_info "  For full end-to-end auth flow, start APISIX with:"
        log_info "    ${CYAN}docker compose up --build${NC}"
        log_info ""
        log_info "  Open UI: ${CYAN}http://localhost:3000${NC}"
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
