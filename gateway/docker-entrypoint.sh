#!/bin/sh
# Pixels Rover Gateway — Docker Entrypoint
#
# Substitutes environment variables in the nginx config template,
# then starts nginx. Only gateway-specific variables are substituted
# to avoid breaking nginx's own $variable syntax.

set -e

# Define which env vars to substitute (only our custom ones)
ENVSUBST_VARS='${COOKIE_SECURE} ${COOKIE_SAMESITE} ${COOKIE_DOMAIN} ${ACCESS_TOKEN_MAX_AGE} ${REFRESH_TOKEN_MAX_AGE} ${CORS_ALLOWED_ORIGINS} ${PIXELS_SERVER_UPSTREAM} ${TEXT2SQL_UPSTREAM}'

# Set defaults for cookie configuration
export COOKIE_SECURE="${COOKIE_SECURE:-false}"
export COOKIE_SAMESITE="${COOKIE_SAMESITE:-Lax}"
export COOKIE_DOMAIN="${COOKIE_DOMAIN:-}"
export ACCESS_TOKEN_MAX_AGE="${ACCESS_TOKEN_MAX_AGE:-3600}"
export REFRESH_TOKEN_MAX_AGE="${REFRESH_TOKEN_MAX_AGE:-604800}"

# Set default for CORS allowed origins ('*' allows all in dev)
export CORS_ALLOWED_ORIGINS="${CORS_ALLOWED_ORIGINS:-*}"

# Set defaults for Pixels Server and Text2SQL upstream addresses
export PIXELS_SERVER_UPSTREAM="${PIXELS_SERVER_UPSTREAM:-http://host.docker.internal:18890}"
export TEXT2SQL_UPSTREAM="${TEXT2SQL_UPSTREAM:-http://host.docker.internal/text2sql}"

# Substitute env vars in the nginx config template
envsubst "$ENVSUBST_VARS" < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf

echo "Gateway: cookie config — secure=$COOKIE_SECURE, sameSite=$COOKIE_SAMESITE, domain=$COOKIE_DOMAIN"
echo "Gateway: token max-age — access=${ACCESS_TOKEN_MAX_AGE}s, refresh=${REFRESH_TOKEN_MAX_AGE}s"
echo "Gateway: pixels-server=$PIXELS_SERVER_UPSTREAM, text2sql=$TEXT2SQL_UPSTREAM"

# Execute the CMD (nginx)
exec "$@"
