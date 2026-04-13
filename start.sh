#!/usr/bin/env bash
#
# Automated startup script for Pixels Rover.
#
# Usage:
#   ./start.sh              Start both backend and frontend
#   ./start.sh backend      Start backend only
#   ./start.sh frontend     Start frontend only
#   ./start.sh --prod       Build frontend for production and start backend serving static files
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR"
FRONTEND_DIR="$SCRIPT_DIR/frontend"

BACKEND_PID=""
FRONTEND_PID=""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log_info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_step()  { echo -e "${CYAN}[STEP]${NC}  $*"; }

cleanup() {
    echo ""
    log_info "Shutting down..."

    if [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
        log_info "Stopping frontend (PID: $FRONTEND_PID)..."
        kill "$FRONTEND_PID" 2>/dev/null || true
        wait "$FRONTEND_PID" 2>/dev/null || true
    fi

    if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
        log_info "Stopping backend (PID: $BACKEND_PID)..."
        kill "$BACKEND_PID" 2>/dev/null || true
        wait "$BACKEND_PID" 2>/dev/null || true
    fi

    log_info "All services stopped."
    exit 0
}

trap cleanup SIGINT SIGTERM

check_prerequisites() {
    local missing=0

    if ! command -v java &>/dev/null; then
        log_error "Java is not installed. JDK 17+ is required."
        missing=1
    fi

    if ! command -v mvn &>/dev/null; then
        log_error "Maven is not installed."
        missing=1
    fi

    if ! command -v node &>/dev/null; then
        log_error "Node.js is not installed."
        missing=1
    fi

    if ! command -v npm &>/dev/null; then
        log_error "npm is not installed."
        missing=1
    fi

    if [[ $missing -eq 1 ]]; then
        log_error "Please install the missing prerequisites and try again."
        exit 1
    fi

    log_info "Prerequisites check passed (java, mvn, node, npm)."
}

start_backend() {
    log_step "Starting backend (Spring Boot) on port 8081..."
    cd "$BACKEND_DIR"
    mvn spring-boot:run -q &
    BACKEND_PID=$!
    log_info "Backend started (PID: $BACKEND_PID)."
}

start_frontend() {
    log_step "Installing frontend dependencies..."
    cd "$FRONTEND_DIR"

    if [[ ! -d "node_modules" ]]; then
        npm install
    else
        log_info "node_modules already exists, skipping npm install. Run 'npm install' manually if needed."
    fi

    log_step "Starting frontend dev server on port 3000..."
    npm run dev &
    FRONTEND_PID=$!
    log_info "Frontend started (PID: $FRONTEND_PID)."
}

build_frontend_prod() {
    log_step "Building frontend for production..."
    cd "$FRONTEND_DIR"

    if [[ ! -d "node_modules" ]]; then
        npm install
    fi

    npm run build
    log_info "Frontend production build completed. Output: frontend/dist/"
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
    echo "Usage: $0 [backend|frontend|--prod]"
    echo ""
    echo "  (no args)    Start both backend and frontend in development mode"
    echo "  backend      Start backend only"
    echo "  frontend     Start frontend dev server only"
    echo "  --prod       Build frontend for production and start backend"
    echo ""
}

# --- Main ---

print_banner

MODE="${1:-all}"

case "$MODE" in
    backend)
        check_prerequisites
        start_backend
        echo ""
        log_info "========================================="
        log_info "  Backend API is running at:"
        log_info "    👉  ${CYAN}http://localhost:8081${NC}"
        log_info "========================================="
        log_info "Press Ctrl+C to stop."
        echo ""
        wait "$BACKEND_PID"
        ;;
    frontend)
        check_prerequisites
        start_frontend
        echo ""
        log_info "========================================="
        log_info "  Frontend dev server is ready!"
        log_info "  Open your browser and visit:"
        log_info ""
        log_info "    👉  ${CYAN}http://localhost:3000${NC}"
        log_info ""
        log_info "  (API requests are proxied to backend at :8081)"
        log_info "========================================="
        log_info "Press Ctrl+C to stop."
        echo ""
        wait "$FRONTEND_PID"
        ;;
    --prod)
        check_prerequisites
        build_frontend_prod
        start_backend
        echo ""
        log_info "=========================================="
        log_info "  Production mode is ready!"
        log_info ""
        log_info "  Backend API → ${CYAN}http://localhost:8081${NC}"
        log_info ""
        log_info "  Frontend static files built at: frontend/dist/"
        log_info "  Serve them with nginx or similar, e.g.:"
        log_info "    👉  ${CYAN}http://localhost${NC} (via nginx)"
        log_info "=========================================="
        log_info "Press Ctrl+C to stop."
        echo ""
        wait "$BACKEND_PID"
        ;;
    all)
        check_prerequisites
        start_backend
        start_frontend
        echo ""
        log_info "=========================================="
        log_info "  All services are running!"
        log_info ""
        log_info "  Backend API → ${CYAN}http://localhost:8081${NC}"
        log_info "  Frontend UI → ${CYAN}http://localhost:3000${NC}"
        log_info ""
        log_info "  Open your browser and visit:"
        log_info "    👉  ${CYAN}http://localhost:3000${NC}"
        log_info "=========================================="
        log_info "Press Ctrl+C to stop all services."
        echo ""
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
