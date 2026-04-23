#!/usr/bin/env bash
#
# Frontend dev-server launcher (Vite).
#
# Scope — DELIBERATELY narrowed:
#   * This script used to also start auth-service (`mvn spring-boot:run`)
#     and assistant-service (`uvicorn`) directly on the host. Those
#     paths are GONE. They encouraged running backends WITHOUT the
#     gateway, which silently bypasses every contract enforced by
#     APISIX (CSRF, CORS, X-Request-Id injection, introspection,
#     security headers, readiness aggregation). The canonical local
#     path for anything that touches auth / business APIs is:
#
#         docker compose up --build
#
#   * What remains here is ONLY the Vite dev server, because a
#     browser-first feedback loop benefits from HMR and it proxies
#     /api to the gateway running in compose — i.e. this script still
#     sits BEHIND the gateway contract, not around it.
#
# Usage:
#   ./start.sh              # start Vite dev server (:3000)
#   ./start.sh -h|--help    # print usage
#
# All other invocations (arguments, `java`, `python`, `--prod`, `all`)
# are rejected to prevent muscle-memory from old workflows; the error
# message steers the user to `docker compose up` for the full stack.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$SCRIPT_DIR/frontend"

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

    if [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
        log_info "Stopping FRONTEND_PID (PID: $FRONTEND_PID)..."
        kill "$FRONTEND_PID" 2>/dev/null || true
        wait "$FRONTEND_PID" 2>/dev/null || true
    fi

    log_info "Frontend dev server stopped."
    exit 0
}

trap cleanup SIGINT SIGTERM

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
    # Plain echo (no color escapes) — print_usage is also emitted on
    # the error path where we can't assume a colour-capable terminal.
    echo "Usage: $0 [-h|--help]"
    echo ""
    echo "  (no args)    Start the frontend Vite dev server on :3000."
    echo "               /api/* is proxied to http://localhost:80 (gateway)."
    echo ""
    echo "  Full end-to-end topology (auth + assistant + gateway + frontend):"
    echo "    docker compose up --build"
    echo ""
    echo "  The former 'java' / 'python' / '--prod' modes have been removed."
    echo "  Running backends without the gateway bypasses every auth, CSRF,"
    echo "  CORS, and X-Request-Id contract and is no longer supported."
    echo ""
}

reject_legacy_mode() {
    local mode="$1"
    log_error "'$mode' mode has been removed from start.sh."
    log_error "Backends must run behind the APISIX gateway. Use:"
    log_error "    docker compose up --build"
    print_usage
    exit 1
}

# --- Main ---

print_banner

MODE="${1:-frontend}"

case "$MODE" in
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
    java|backend|python|--prod|all)
        reject_legacy_mode "$MODE"
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
