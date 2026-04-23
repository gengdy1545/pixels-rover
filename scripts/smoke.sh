#!/usr/bin/env bash
# scripts/smoke.sh — Pixels Rover contract-layer smoke test
# ==========================================================
#
# Canonical spec: docs/development/backend.md §7 (contract-level readiness) +
# gateway.md §4.1 (/gateway/ready aggregation). Paired with
# scripts/check-contracts.py — either failure blocks merge.
#
# Scope:
#   This script only validates the CONTRACT layer — request/response envelopes,
#   gateway routing shape, auth chain wiring, identity-header injection, and
#   OpenAPI reachability. It does NOT exercise business flows (analysis runs,
#   LLM calls, conversation history, etc.) and MUST NOT be taken as proof of
#   end-to-end functional correctness.
#
# Stages (each stage aborts the run on first failure; on abort, container logs
# are dumped to stderr and the compose stack is left up unless SMOKE_KEEP_STACK
# is explicitly set to 0):
#
#   0. preflight         — local tool + env sanity (docker, curl, jq, python3)
#   1. boot              — `docker compose up -d --build` with dev overlay
#   2. readiness         — poll /gateway/ready with backoff + per-iteration
#                          `docker compose ps` watchdog that fails-fast on any
#                          container exit
#   3. schema existence  — SHOW DATABASES assertion for pixels_auth +
#                          pixels_analysis (bottom-line check; primary defence
#                          is the B1+B2 Alembic/Flyway migrators exiting 1)
#   4. contracts         — (a) /api/internal/* + /gateway/internal/* externally
#                              rejected (404; gateway declares no such routes)
#                          (b) /api/v1/<svc>/openapi.json reachable + parseable
#                              + the GATEWAY_* / INTERNAL_* errorCode enum it
#                              advertises is a subset of gateway/error-codes.json
#                          (c) legacy /api/v1/chat|query|metadata 404
#                          (d) gateway global X-Request-Id injection on both
#                              happy-path and 404 responses
#   5. auth chain        — register a random user, login, call a CSRF-exempt
#                          protected route, verify 200 + envelope shape. This
#                          is the only stage that exercises gateway-auth ->
#                          auth-service /api/internal/auth/introspect ->
#                          gateway X-Auth-* injection in one shot.
#
# Consumption of config/required-env.yaml (§14 SSOT):
#   The script sources the SSOT indirectly — it relies on the three startup-
#   validators (gateway entrypoint, RequiredEnvValidator, assistant required_env)
#   to FATAL on env misconfiguration, which is the spec's "hard validation at
#   boot". The only env surface this script itself touches is the compose
#   overlay selector (SMOKE_COMPOSE_FILES below), so that the script does not
#   fork its own env contract.
#
# Exit codes:
#   0  all contract checks pass
#   1  a contract check failed (offending assertion identified in the log)
#   2  preflight / environmental issue (missing tool, failed boot, etc.)
#

set -euo pipefail

# ---------------------------------------------------------------------------
# Config (override via env).
# ---------------------------------------------------------------------------
SMOKE_GATEWAY_PORT="${SMOKE_GATEWAY_PORT:-9080}"
SMOKE_GATEWAY_URL="http://127.0.0.1:${SMOKE_GATEWAY_PORT}"
SMOKE_READY_TIMEOUT_SEC="${SMOKE_READY_TIMEOUT_SEC:-240}"
SMOKE_READY_INITIAL_SLEEP="${SMOKE_READY_INITIAL_SLEEP:-2}"
SMOKE_READY_MAX_BACKOFF="${SMOKE_READY_MAX_BACKOFF:-8}"
SMOKE_KEEP_STACK="${SMOKE_KEEP_STACK:-0}"
SMOKE_NO_BUILD="${SMOKE_NO_BUILD:-0}"
SMOKE_SKIP_BOOT="${SMOKE_SKIP_BOOT:-0}"

# The dev overlay supplies defaults for every required env var so the stack
# actually boots from an otherwise empty .env; see docker-compose.dev.yml.
SMOKE_COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.dev.yml)

# MySQL credentials must match docker-compose.yml defaults (MYSQL_ROOT_PASSWORD
# :-rootpassword). In CI / production this script is never pointed at a stack
# that changed the defaults — if you need that, run `docker compose exec` by
# hand.
SMOKE_MYSQL_ROOT_PASSWORD="${MYSQL_ROOT_PASSWORD:-rootpassword}"

# Repo root is the script's parent directory.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# Output helpers. Colour only if stderr is a TTY.
# ---------------------------------------------------------------------------
if [[ -t 2 ]]; then
  C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'
  C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_CYAN=$'\033[36m'
else
  C_RESET=""; C_BOLD=""; C_RED=""; C_GREEN=""; C_YELLOW=""; C_CYAN=""
fi

stage()  { printf '\n%s==>%s %s%s%s\n' "$C_CYAN" "$C_RESET" "$C_BOLD" "$*" "$C_RESET" >&2; }
info()   { printf '    %s\n' "$*" >&2; }
ok()     { printf '    %s[ok]%s %s\n'   "$C_GREEN"  "$C_RESET" "$*" >&2; }
warn()   { printf '    %s[warn]%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
fail()   { printf '    %s[FAIL]%s %s\n' "$C_RED"    "$C_RESET" "$*" >&2; }

# ---------------------------------------------------------------------------
# Exit trap — dump container state + optionally tear down the stack.
# ---------------------------------------------------------------------------
_exit_code=0
SMOKE_COOKIE_JAR=""
cleanup() {
  local ec=$?
  _exit_code="$ec"
  if [[ -n "$SMOKE_COOKIE_JAR" ]]; then
    rm -f "$SMOKE_COOKIE_JAR" 2>/dev/null || true
  fi
  if (( ec != 0 )); then
    stage "FAILURE — dumping compose state + per-service logs (last 50 lines)"
    docker compose "${SMOKE_COMPOSE_FILES[@]}" ps || true
    local svc
    for svc in mysql auth-service assistant-service gateway; do
      echo
      echo "$C_YELLOW--- $svc ---$C_RESET" >&2
      docker compose "${SMOKE_COMPOSE_FILES[@]}" logs --tail=50 "$svc" || true
    done
  fi
  if (( SMOKE_KEEP_STACK == 0 )) && (( SMOKE_SKIP_BOOT == 0 )); then
    stage "Tearing down compose stack (SMOKE_KEEP_STACK=0)"
    docker compose "${SMOKE_COMPOSE_FILES[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  else
    info "Stack left running — teardown skipped."
  fi
  if (( ec == 0 )); then
    printf '\n%s==> smoke PASS%s\n' "$C_GREEN" "$C_RESET" >&2
  else
    printf '\n%s==> smoke FAIL (exit %d)%s\n' "$C_RED" "$ec" "$C_RESET" >&2
  fi
  exit "$ec"
}
trap cleanup EXIT

die()     { fail "$*"; exit 1; }
die_env() { fail "$*"; exit 2; }

# ---------------------------------------------------------------------------
# Stage 0 — preflight.
# ---------------------------------------------------------------------------
stage "Stage 0: preflight"
for bin in docker curl jq python3; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    die_env "required tool '$bin' not found on PATH"
  fi
done
if ! docker compose version >/dev/null 2>&1; then
  die_env "'docker compose' plugin not available (got 'docker' but not 'docker compose')"
fi
ok "required tools present: docker, docker compose, curl, jq, python3"

# The SSOT must be discoverable — not strictly needed at runtime (validators
# read it from container paths), but a missing YAML here means the caller
# cloned a broken tree.
[[ -f "config/required-env.yaml" ]] || die_env "config/required-env.yaml missing — broken tree"
[[ -f "gateway/error-codes.json" ]] || die_env "gateway/error-codes.json missing — broken tree"
ok "SSOT files present: config/required-env.yaml + gateway/error-codes.json"

# ---------------------------------------------------------------------------
# Stage 1 — boot compose stack (dev overlay).
# ---------------------------------------------------------------------------
if (( SMOKE_SKIP_BOOT == 1 )); then
  stage "Stage 1: compose up (SKIPPED via SMOKE_SKIP_BOOT=1 — expecting an already-running stack)"
else
  stage "Stage 1: compose up (dev overlay, GATEWAY_PORT=$SMOKE_GATEWAY_PORT)"
  # Tear down any previous state so jwt-keygen re-runs from a clean volume.
  docker compose "${SMOKE_COMPOSE_FILES[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true

  build_args=()
  if (( SMOKE_NO_BUILD == 0 )); then
    build_args+=(--build)
  fi

  GATEWAY_PORT="$SMOKE_GATEWAY_PORT" \
    docker compose "${SMOKE_COMPOSE_FILES[@]}" up -d "${build_args[@]}"
  ok "compose up issued"
fi

# ---------------------------------------------------------------------------
# Stage 2 — readiness poll with watchdog.
# ---------------------------------------------------------------------------
stage "Stage 2: readiness — poll $SMOKE_GATEWAY_URL/gateway/ready (budget ${SMOKE_READY_TIMEOUT_SEC}s)"

# Helper: check that no compose service has exited. Fails-fast the smoke run
# if any container left `running` — RequiredEnvValidator / Alembic / Flyway
# all crash the container on misconfiguration, and waiting the full readiness
# timeout just to then discover that would be wasteful.
assert_containers_running() {
  local ps_json
  ps_json="$(docker compose "${SMOKE_COMPOSE_FILES[@]}" ps --format json 2>/dev/null || true)"
  [[ -z "$ps_json" ]] && return 0
  # `docker compose ps --format json` emits either a JSON array (v2.21+) or
  # newline-delimited JSON objects (older). Normalise to an array.
  local normalised
  if [[ "${ps_json:0:1}" == "[" ]]; then
    normalised="$ps_json"
  else
    normalised="$(printf '%s' "$ps_json" | jq -s '.')"
  fi
  local bad
  bad="$(printf '%s' "$normalised" | jq -r '
    .[]
    | select(.Service != "jwt-keygen")
    | select((.State // "") != "running")
    | "\(.Service)=\(.State // "?")"
  ')"
  if [[ -n "$bad" ]]; then
    while IFS= read -r line; do
      fail "container not running: $line"
    done <<<"$bad"
    die "one or more services exited before /gateway/ready returned 200 — see dump below"
  fi
}

sleep "$SMOKE_READY_INITIAL_SLEEP"
deadline=$(( $(date +%s) + SMOKE_READY_TIMEOUT_SEC ))
backoff=1
ready=0
while (( $(date +%s) < deadline )); do
  assert_containers_running
  http_code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 \
    "$SMOKE_GATEWAY_URL/gateway/ready" || echo "000")"
  if [[ "$http_code" == "200" ]]; then
    ready=1
    break
  fi
  info "not ready yet (HTTP $http_code); sleeping ${backoff}s"
  sleep "$backoff"
  if (( backoff < SMOKE_READY_MAX_BACKOFF )); then
    backoff=$(( backoff * 2 ))
    (( backoff > SMOKE_READY_MAX_BACKOFF )) && backoff="$SMOKE_READY_MAX_BACKOFF"
  fi
done

if (( ready == 0 )); then
  die "/gateway/ready did not return 200 within ${SMOKE_READY_TIMEOUT_SEC}s"
fi
ok "/gateway/ready returned 200"

# ---------------------------------------------------------------------------
# Stage 3 — schema existence.
# ---------------------------------------------------------------------------
stage "Stage 3: schema existence (bottom-line check; primary defence is migrator exit 1)"
schema_probe() {
  local db="$1"
  local out
  if ! out="$(docker compose "${SMOKE_COMPOSE_FILES[@]}" exec -T mysql \
      mysql -u root -p"$SMOKE_MYSQL_ROOT_PASSWORD" \
      -sN -e "SHOW DATABASES LIKE '$db'" 2>/dev/null)"; then
    die "mysql client failed while probing for '$db'"
  fi
  if [[ "$out" != "$db" ]]; then
    die "expected database '$db' missing (migrator should have created it)"
  fi
}
schema_probe pixels_auth
schema_probe pixels_analysis
ok "pixels_auth + pixels_analysis both present"

# ---------------------------------------------------------------------------
# Stage 4 — contract assertions.
# ---------------------------------------------------------------------------
stage "Stage 4: contract assertions"

# curl wrapper that never aborts the script on non-2xx — we WANT the response
# for assertion. Captures body to stdout and exposes status/headers via env.
# Usage: smoke_request <METHOD> <PATH> [curl_extra_args...]
#        echo "$SMOKE_LAST_STATUS"   -> HTTP status (000 on transport error)
#        printf '%s' "$SMOKE_LAST_HEADERS" | grep -i x-request-id
SMOKE_LAST_STATUS=""
SMOKE_LAST_HEADERS=""
smoke_request() {
  local method="$1" path="$2"; shift 2
  local hdr_file body_file
  hdr_file="$(mktemp)"; body_file="$(mktemp)"
  SMOKE_LAST_STATUS="$(curl -sS -o "$body_file" -D "$hdr_file" \
    -w '%{http_code}' -X "$method" --max-time 15 \
    "$@" \
    "$SMOKE_GATEWAY_URL$path" || echo "000")"
  SMOKE_LAST_HEADERS="$(cat "$hdr_file")"
  cat "$body_file"
  rm -f "$hdr_file" "$body_file"
}
smoke_header() {
  printf '%s' "$SMOKE_LAST_HEADERS" | awk -v want="$1" '
    BEGIN { IGNORECASE=1 }
    tolower($1) == tolower(want ":") { sub(/^[^:]+:[ \t]*/, ""); sub(/\r$/, ""); print; exit }
  '
}

# -- 4a: /api/internal/* and /gateway/internal/* are not externally declared --
for hidden in \
    /api/internal/auth/introspect \
    /gateway/internal/invalidate_session; do
  smoke_request GET "$hidden" >/dev/null || true
  if [[ "$SMOKE_LAST_STATUS" != "404" ]]; then
    die "expected 404 for $hidden from outside (got $SMOKE_LAST_STATUS) — gateway leaking an internal route"
  fi
  ok "$hidden externally rejected with 404"
done

# -- 4b: OpenAPI reachability + parse + GATEWAY_*/INTERNAL_* errorCode subset --
errcodes_json="$(cat gateway/error-codes.json)"
for spec_path in /api/v1/auth/openapi.json /api/v1/analysis/openapi.json; do
  body="$(smoke_request GET "$spec_path")"
  if [[ "$SMOKE_LAST_STATUS" != "200" ]]; then
    die "OpenAPI spec $spec_path not reachable (status=$SMOKE_LAST_STATUS)"
  fi
  if ! printf '%s' "$body" | jq -e '.openapi' >/dev/null 2>&1; then
    die "OpenAPI spec $spec_path returned non-JSON or missing .openapi field"
  fi

  # Infra error-code subset check (C4 assertion tail). Extract every string
  # that looks like a GATEWAY_* or INTERNAL_* enum value anywhere inside the
  # spec's errorCode enums, then assert ⊆ error-codes.json keys.
  spec_tmp="$(mktemp)"
  printf '%s' "$body" >"$spec_tmp"
  subset_report="$(SMOKE_SPEC_FILE="$spec_tmp" SMOKE_ERRCODES_JSON="$errcodes_json" \
    python3 - <<'PY'
import json, os
registry = json.loads(os.environ["SMOKE_ERRCODES_JSON"])["codes"]
with open(os.environ["SMOKE_SPEC_FILE"], "r", encoding="utf-8") as fh:
    spec = json.load(fh)

def walk(node):
    if isinstance(node, dict):
        if "errorCode" in node and isinstance(node["errorCode"], dict):
            enum = node["errorCode"].get("enum")
            if isinstance(enum, list):
                for v in enum:
                    if isinstance(v, str):
                        yield v
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)

found = set(walk(spec))
infra = {v for v in found if v.startswith("GATEWAY_") or v.startswith("INTERNAL_")}
missing = sorted(infra - set(registry.keys()))
if missing:
    print("MISSING: " + ",".join(missing))
else:
    print("OK:" + str(len(infra)))
PY
)"
  rm -f "$spec_tmp"
  case "$subset_report" in
    OK:*)
      ok "$spec_path: ${subset_report#OK:} GATEWAY_*/INTERNAL_* enum values, all ⊆ error-codes.json"
      ;;
    MISSING:*)
      die "$spec_path advertises errorCode values not in gateway/error-codes.json: ${subset_report#MISSING: }"
      ;;
    *)
      die "internal: unexpected subset-report output for $spec_path: $subset_report"
      ;;
  esac
done

# -- 4c: legacy route sunset --
for legacy in \
    /api/v1/chat/conversations \
    /api/v1/query/run \
    /api/v1/metadata/schema; do
  smoke_request GET "$legacy" >/dev/null || true
  if [[ "$SMOKE_LAST_STATUS" != "404" ]]; then
    die "legacy route $legacy still reachable (status=$SMOKE_LAST_STATUS) — apisix.yaml declares a sunset route"
  fi
  ok "$legacy sunset confirmed (404)"
done

# -- 4d: X-Request-Id global injection on happy-path and 404 --
smoke_request GET / >/dev/null || true
rid_root="$(smoke_header X-Request-Id)"
[[ -n "$rid_root" ]] || die "GET / missing X-Request-Id header (gateway global response-rewrite not applied)"
ok "GET / carries X-Request-Id=$rid_root"

smoke_request GET /this-route-definitely-does-not-exist-xyz >/dev/null || true
rid_404="$(smoke_header X-Request-Id)"
[[ -n "$rid_404" ]] || die "404 response missing X-Request-Id (gateway global response-rewrite skips error responses)"
ok "404 response carries X-Request-Id=$rid_404"

# ---------------------------------------------------------------------------
# Stage 5 — end-to-end auth chain.
# ---------------------------------------------------------------------------
stage "Stage 5: end-to-end auth chain (register -> login -> gateway-auth -> introspect -> X-Auth-*)"

rand_suffix="$(tr -dc 'a-z0-9' </dev/urandom | head -c 8 || true)"
smoke_user="smoke_${rand_suffix}"
# 12-character password: letters + digits. The default validation in
# auth-service's RegisterRequest accepts this.
smoke_pass="SmokePass_${rand_suffix}"

register_payload=$(cat <<JSON
{"username":"$smoke_user","password":"$smoke_pass","nickname":"Smoke $rand_suffix","email":"$smoke_user@smoke.invalid"}
JSON
)
body="$(smoke_request POST /api/v1/auth/register \
  -H 'Content-Type: application/json' \
  --data-raw "$register_payload")"
if [[ "$SMOKE_LAST_STATUS" != "200" ]]; then
  die "register failed (status=$SMOKE_LAST_STATUS body=$body)"
fi
ok "register succeeded for user $smoke_user"

login_payload=$(cat <<JSON
{"username":"$smoke_user","password":"$smoke_pass"}
JSON
)
SMOKE_COOKIE_JAR="$(mktemp)"
body="$(curl -sS -o - -w '\n__STATUS__%{http_code}' \
  -X POST \
  -H 'Content-Type: application/json' \
  -c "$SMOKE_COOKIE_JAR" \
  --data-raw "$login_payload" \
  --max-time 15 \
  "$SMOKE_GATEWAY_URL/api/v1/auth/login")"
login_status="${body##*__STATUS__}"
login_body="${body%__STATUS__*}"
if [[ "$login_status" != "200" ]]; then
  die "login failed (status=$login_status body=$login_body)"
fi
ok "login succeeded; cookies persisted to jar"

# Pull XSRF-TOKEN out of the jar so the CSRF double-submit header is ready
# if a later stage wants to call a mutating protected endpoint.
xsrf_token="$(awk '$6 == "XSRF-TOKEN" { print $7 }' "$SMOKE_COOKIE_JAR" | tail -n1)"
[[ -n "$xsrf_token" ]] || warn "login did not set XSRF-TOKEN cookie — CSRF defence wiring may have regressed"

# Protected GET: the gateway-auth plugin MUST (1) read the access_token cookie,
# (2) call /api/internal/auth/introspect, (3) inject X-Auth-User-Id into the
# proxied request, and (4) assistant-service's IdentityHeaderValidationFilter
# MUST accept the injected header and return a real response envelope.
#
# /api/v1/analysis/backends is the cheapest protected route in the assistant
# namespace — it returns the list of configured analysis backends and never
# talks to the LLM, so it's appropriate for a contract-layer probe.
body="$(curl -sS -o - -w '\n__STATUS__%{http_code}' \
  -b "$SMOKE_COOKIE_JAR" \
  ${xsrf_token:+-H "X-XSRF-TOKEN: $xsrf_token"} \
  --max-time 15 \
  "$SMOKE_GATEWAY_URL/api/v1/analysis/backends")"
protected_status="${body##*__STATUS__}"
protected_body="${body%__STATUS__*}"

if [[ "$protected_status" != "200" ]]; then
  die "protected GET /api/v1/analysis/backends failed (status=$protected_status body=$protected_body)"
fi

# Envelope shape: { code:200, data:..., ... }. We accept any non-error shape
# as long as `code` equals the HTTP status (backend.md §6.2).
envelope_code="$(printf '%s' "$protected_body" | jq -r '.code // empty' 2>/dev/null || true)"
if [[ "$envelope_code" != "200" ]]; then
  die "protected GET envelope missing .code==200 (got: $envelope_code; body=$protected_body)"
fi
ok "protected GET returned 200 + envelope .code=200 — introspect + X-Auth-* chain confirmed"

# ---------------------------------------------------------------------------
# Success.
# ---------------------------------------------------------------------------
stage "All contract-layer smoke assertions passed"
