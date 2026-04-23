#!/bin/sh
# APISIX gateway container entrypoint (Standalone YAML mode).

set -eu

CONF_DIR="/usr/local/apisix/conf"

python3 /usr/local/apisix/conf/validate-required-env.py \
  --yaml "${CONF_DIR}/required-env.yaml" \
  --service gateway

case "${GATEWAY_CSP_PROFILE}" in
  production)
    GATEWAY_CSP_HEADER="default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    ;;
  development)
    GATEWAY_CSP_HEADER="default-src 'self'; connect-src 'self' http: https: ws: wss:; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-eval'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    ;;
  *)
    echo "gateway entrypoint: impossible GATEWAY_CSP_PROFILE=${GATEWAY_CSP_PROFILE} after validator; validate-required-env.py out of sync" >&2
    exit 1
    ;;
esac
export GATEWAY_CSP_HEADER

envsubst '${CORS_ALLOWED_ORIGINS} ${GATEWAY_CSP_HEADER}' \
  < "${CONF_DIR}/apisix.yaml.template" \
  > "${CONF_DIR}/apisix.yaml"

envsubst \
  < "${CONF_DIR}/config.yaml.template" \
  > "${CONF_DIR}/config.yaml"

exec /docker-entrypoint.sh "$@"
