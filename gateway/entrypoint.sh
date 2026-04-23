#!/bin/sh
# APISIX gateway container entrypoint (Standalone YAML mode).
#
# Responsibilities (see docs/development/gateway.md §1):
#   1. Fail-fast on missing required env vars so gateway never boots
#      in a silently-broken state. The same fail-fast discipline is
#      applied in backend services -- see backend.md §13.1.
#   2. Render /usr/local/apisix/conf/config.yaml.template ->
#      /usr/local/apisix/conf/config.yaml via envsubst. In this PR
#      the template has no ${VAR} placeholders (secrets moved to
#      os.getenv() inside gateway-auth.lua), but the render step
#      stays so adding one is a one-line diff.
#   3. Exec APISIX's upstream docker-entrypoint.sh with the original
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

envsubst \
  < /usr/local/apisix/conf/config.yaml.template \
  > /usr/local/apisix/conf/config.yaml

exec /docker-entrypoint.sh "$@"
