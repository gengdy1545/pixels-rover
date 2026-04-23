#!/bin/sh
# APISIX gateway container entrypoint (Standalone YAML mode).
#
# Responsibilities (see docs/development/gateway.md §1 + §6.7):
#   1. Fail-fast on missing / invalid required env vars by delegating
#      to validate-required-env.py, which reads the SSOT shape from
#      /usr/local/apisix/conf/required-env.yaml (services.gateway
#      block). Same discipline is applied in backend services -- see
#      backend.md §13.1.
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

# ---------------------------------------------------------------------
# Required env var hard validation (§14 / backend.md §13.1).
#
# ALL per-var shape (required / enum / forbidden placeholders / minimum
# length) lives in config/required-env.yaml — the SSOT shared by auth-
# service, assistant-service, and this gateway. validate-required-env.py
# exits non-zero with a FATAL line per violation; `set -eu` then aborts
# the container. Doing this BEFORE template splice / envsubst means we
# never produce a half-rendered apisix.yaml with blank introspection
# secrets / unknown CSP profile.
# ---------------------------------------------------------------------
python3 /usr/local/apisix/conf/validate-required-env.py \
  --yaml "${CONF_DIR}/required-env.yaml" \
  --service gateway

# ---------------------------------------------------------------------
# OpenAPI exposure profile (gateway.md §6.7).
#
# The validator above has already asserted GATEWAY_OPENAPI_PUBLIC ∈
# {"true", "false"}. This case block only picks the fragment — keep it
# narrow and let the YAML own the "what counts as valid" contract.
# ---------------------------------------------------------------------
case "${GATEWAY_OPENAPI_PUBLIC}" in
  true)
    openapi_fragment="${FRAGMENT_DIR}/openapi-public.yaml"
    ;;
  false)
    openapi_fragment="${FRAGMENT_DIR}/openapi-protected.yaml"
    ;;
  *)
    echo "gateway entrypoint: impossible GATEWAY_OPENAPI_PUBLIC=${GATEWAY_OPENAPI_PUBLIC} after validator; validate-required-env.py out of sync" >&2
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
