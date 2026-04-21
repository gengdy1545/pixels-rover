#!/bin/sh
set -eu

envsubst '${APISIX_ADMIN_API_KEY}' \
  < /usr/local/apisix/conf/config.yaml.template \
  > /usr/local/apisix/conf/config.yaml

exec /docker-entrypoint.sh "$@"
