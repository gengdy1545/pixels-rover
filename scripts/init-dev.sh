#!/usr/bin/env bash
#
# One-click development environment initialization for Pixels Rover.
#
# This script checks prerequisites, prepares the environment,
# and initializes the database for local development.
#
# Usage:
#   ./scripts/init-dev.sh          Full initialization
#   ./scripts/init-dev.sh --check  Check prerequisites only
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_step()  { echo -e "${CYAN}[STEP]${NC}  $*"; }

ERRORS=0

# ---- Prerequisite Checks ----

check_command() {
    local cmd="$1"
    local label="${2:-$1}"
    local min_version="${3:-}"
    if command -v "$cmd" &>/dev/null; then
        local version
        version=$("$cmd" --version 2>&1 | head -1) || version="unknown"
        log_info "$label found: $version"
    else
        log_error "$label is NOT installed."
        ERRORS=$((ERRORS + 1))
    fi
}

check_prerequisites() {
    log_step "Checking prerequisites..."
    echo ""

    check_command python3 "Python 3.10+"
    check_command node "Node.js"
    check_command npm "npm"

    # Optional: Docker
    if command -v docker &>/dev/null; then
        log_info "Docker found: $(docker --version 2>&1 | head -1)"
    else
        log_warn "Docker is not installed (optional, needed for docker-compose mode)."
    fi

    # Check MySQL connectivity
    if command -v mysql &>/dev/null; then
        log_info "MySQL client found: $(mysql --version 2>&1 | head -1)"
    else
        log_warn "MySQL client not found. You can still use Docker MySQL."
    fi

    echo ""
    if [[ $ERRORS -gt 0 ]]; then
        log_error "$ERRORS required tool(s) missing. Please install them before continuing."
        exit 1
    fi
    log_info "All prerequisites satisfied."
}

# ---- Environment Setup ----

setup_python_env() {
    log_step "Setting up Python virtual environment..."
    local py_dir="$PROJECT_ROOT/services/assistant-service"

    if [[ ! -d "$py_dir/.venv" ]]; then
        python3 -m venv "$py_dir/.venv"
        log_info "Virtual environment created."
    else
        log_info "Virtual environment already exists."
    fi

    source "$py_dir/.venv/bin/activate"
    pip install --quiet -e "$py_dir"
    log_info "Python dependencies installed."
}

setup_python_dotenv() {
    local py_dir="$PROJECT_ROOT/services/assistant-service"
    if [[ ! -f "$py_dir/.env" ]] && [[ -f "$py_dir/.env.example" ]]; then
        cp "$py_dir/.env.example" "$py_dir/.env"
        log_warn "Created services/assistant-service/.env from .env.example."
        log_warn "  → Please edit it and set your LLM API key (ROVER_LLM_API_KEY)."
    else
        log_info "Python .env file already exists."
    fi
}

setup_frontend() {
    log_step "Installing frontend dependencies..."
    local fe_dir="$PROJECT_ROOT/frontend"

    if [[ ! -d "$fe_dir/node_modules" ]]; then
        cd "$fe_dir" && npm install
        log_info "Frontend dependencies installed."
    else
        log_info "Frontend node_modules already exists."
    fi
}

setup_docker_env() {
    if [[ ! -f "$PROJECT_ROOT/.env" ]] && [[ -f "$PROJECT_ROOT/.env.example" ]]; then
        cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
        log_warn "Created .env from .env.example at project root."
        log_warn "  → Please edit it and set your LLM API key."
    elif [[ -f "$PROJECT_ROOT/.env" ]]; then
        log_info "Root .env file already exists."
    fi
}

# ---- Summary ----

print_summary() {
    echo ""
    echo -e "${CYAN}============================================${NC}"
    echo -e "${CYAN}  Pixels Rover — Development Environment${NC}"
    echo -e "${CYAN}============================================${NC}"
    echo ""
    echo "  Full stack (Ory + assistant + gateway + frontend):"
    echo "    docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build"
    echo ""
    echo "  Frontend-only Vite dev loop (proxies /api → gateway on :80):"
    echo "    ./start.sh          # Frontend only, HMR; gateway must be up"
    echo ""
    echo "  Readiness / liveness (once compose is up):"
    echo "    curl http://localhost:80/gateway/live"
    echo "    curl http://localhost:80/gateway/ready"
    echo ""
    echo "  Note: ./start.sh java / python / --prod are removed — running"
    echo "        backends outside the gateway bypasses Ory / CSRF / CORS"
    echo "        / X-Request-Id contracts (see docs/development/gateway.md)."
    echo ""
    echo -e "${CYAN}============================================${NC}"
}

# ---- Main ----

MODE="${1:-full}"

case "$MODE" in
    --check)
        check_prerequisites
        ;;
    full|*)
        check_prerequisites
        echo ""
        setup_python_env
        setup_python_dotenv
        echo ""
        setup_frontend
        echo ""
        setup_docker_env
        print_summary
        ;;
esac
