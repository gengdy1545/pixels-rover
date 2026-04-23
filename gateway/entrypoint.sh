#!/bin/sh
# APISIX gateway container entrypoint (Standalone YAML mode).
#
# Responsibilities (see docs/development/gateway.md §1 + §6.7):
#   1. Fail-fast on missing / invalid required env vars so gateway
#      never boots in a silently-broken state. Same discipline is
#      applied in backend services -- see backend.md §13.1.
#   2. Render /usr/local/apisix/conf/apisix.yaml.template ->
#      /usr/local/apisix/conf/apisix.yaml by splicing in one of the
#      mutually-exclusive OpenAPI route fragments at the
#      `#__OPENAPI_ROUTES__` marker line. Fragment selection is
#      driven by GATEWAY_OPENAPI_PUBLIC (strict enum; empty / typo
#      fails fast). See gateway.md §6.7 for why runtime conditional
#      routing is rejected here.
#   3. Render /usr/local/apisix/conf/config.yaml.template ->
#      /usr/local/apisix/conf/config.yaml via envsubst. Currently
#      the template has no ${VAR} placeholders (secrets moved to
#      os.getenv() inside gateway-auth.lua), but the render step
#      stays so adding one is a one-line diff.
#   4. Exec APISIX's upstream docker-entrypoint.sh with the original
#      CMD arguments. Using `exec` means APISIX becomes PID 1 and
#      docker stop signal forwarding works correctly.
#
# What this script deliberately does NOT do:
#   * No curl-based route seeding (that was the etcd + Admin API era;
#     bootstrap.sh is deleted in this PR).
#   * No "wait for etcd" loop (no etcd dependency).
#   * No "wait for upstreams healthy" loop. depends_on: service_started
#     plus APISIX's own per-request retry + /gateway/ready aggregation
#     is the correct readiness signal; blocking on upstream health
#     here would deadlock cold-start (services may come up in any order).

set -eu

CONF_DIR="/usr/local/apisix/conf"
FRAGMENT_DIR="${CONF_DIR}/fragments"

require_env() {
  var="$1"
  eval "value=\${$var:-}"
  if [ -z "${value}" ]; then
    echo "gateway entrypoint: required env var ${var} is missing; refusing to start" >&2
    exit 1
  fi
}

# INTERNAL_INTROSPECTION_SECRET is read at runtime by
# gateway-auth.lua via os.getenv(). Failing to set it means every
# introspect call would send an empty X-Internal-Auth and auth-service
# would reject with INTERNAL_AUTH_FAILED -- we want that failure at
# boot, not on the first request.
require_env INTERNAL_INTROSPECTION_SECRET

# ---------------------------------------------------------------------
# OpenAPI exposure profile (gateway.md §6.7).
#
# Strict enum. Empty / any other value is a fatal boot error — the
# docs explicitly forbid a default here so every deployment makes the
# public-vs-protected decision explicitly. Same pattern as (future)
# GATEWAY_CSP_PROFILE handling in §6.6.
# ---------------------------------------------------------------------
case "${GATEWAY_OPENAPI_PUBLIC:-}" in
  true)
    openapi_fragment="${FRAGMENT_DIR}/openapi-public.yaml"
    ;;
  false)
    openapi_fragment="${FRAGMENT_DIR}/openapi-protected.yaml"
    ;;
  "")
    echo "gateway entrypoint: GATEWAY_OPENAPI_PUBLIC is empty; must be exactly 'true' or 'false' (see gateway.md §6.7)" >&2
    exit 1
    ;;
  *)
    echo "gateway entrypoint: GATEWAY_OPENAPI_PUBLIC='${GATEWAY_OPENAPI_PUBLIC}' is invalid; must be exactly 'true' or 'false' (see gateway.md §6.7)" >&2
    exit 1
    ;;
esac

if [ ! -r "${openapi_fragment}" ]; then
  echo "gateway entrypoint: OpenAPI fragment ${openapi_fragment} is missing or unreadable; image is corrupt" >&2
  exit 1
fi

# Splice the selected fragment into apisix.yaml.template at the
# `#__OPENAPI_ROUTES__` marker line. awk gives us atomic
# line-replacement semantics without shell quoting gymnastics; sed
# `r` has awkward leading-newline behavior that polluts YAML
# indent.  The marker line MUST appear exactly once; the awk
# program counts occurrences and aborts if zero or > 1.
awk -v fragment="${openapi_fragment}" '
  BEGIN { spliced = 0 }
  /^#__OPENAPI_ROUTES__[[:space:]]*$/ {
    while ((getline frag_line < fragment) > 0) {
      print frag_line
    }
    close(fragment)
    spliced++
    next
  }
  { print }
  END {
    if (spliced == 0) {
      print "gateway entrypoint: #__OPENAPI_ROUTES__ marker not found in apisix.yaml.template" > "/dev/stderr"
      exit 2
    }
    if (spliced > 1) {
      print "gateway entrypoint: #__OPENAPI_ROUTES__ marker matched " spliced " times in apisix.yaml.template (must be exactly 1)" > "/dev/stderr"
      exit 2
    }
  }
' "${CONF_DIR}/apisix.yaml.template" > "${CONF_DIR}/apisix.yaml"

envsubst \
  < "${CONF_DIR}/config.yaml.template" \
  > "${CONF_DIR}/config.yaml"

exec /docker-entrypoint.sh "$@"
