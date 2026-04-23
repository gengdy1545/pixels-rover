FROM apache/apisix:3.9.1-debian

USER root

# envsubst is needed by entrypoint.sh to render APISIX templates.
# curl is kept for /gateway/live probes and operator diagnostics.
# python3 + python3-yaml are consumed exclusively by
# validate-required-env.py (§14 / backend.md §13.1); keeping the
# dependency surface tiny (stdlib + PyYAML) lets the validator run in
# the same hermetic image without a build step.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gettext-base python3 python3-yaml \
    && rm -rf /var/lib/apt/lists/*

# Custom Lua plugins must live under /usr/local/apisix/apisix/plugins.
COPY custom/apisix/plugins/error_code_registry.lua /usr/local/apisix/apisix/plugins/error_code_registry.lua
COPY custom/apisix/plugins/gateway-ready.lua       /usr/local/apisix/apisix/plugins/gateway-ready.lua

# Boot configuration template (Standalone YAML mode). entrypoint.sh
# renders it to /usr/local/apisix/conf/config.yaml at container start.
COPY config.yaml.template /usr/local/apisix/conf/config.yaml.template

# Standalone YAML route table, rendered at container start by entrypoint.sh.
COPY apisix.yaml.template /usr/local/apisix/conf/apisix.yaml.template

# Gateway error-code registry — single source of truth for GATEWAY_* /
# INTERNAL_* codes (see backend.md §6.3.1). Baked into the image rather
# than bind-mounted: the plugins read it once at worker init, so rebuild
# is required when codes change (which is also the case for Lua plugin
# source changes). The JSON schema file rides along for discoverability.
COPY error-codes.json        /usr/local/apisix/conf/error-codes.json
COPY error-codes.schema.json /usr/local/apisix/conf/error-codes.schema.json

# Required-env validator (§14). The companion config/required-env.yaml
# is NOT baked into the image: it is bind-mounted from docker-compose.yml
# at /usr/local/apisix/conf/required-env.yaml so the three services
# (gateway / assistant-service plus deployment-secret generation) all read
# byte-identical
# contract definitions from the same on-host file. Missing bind-mount
# fails validate-required-env.py with a clear message — exactly the
# signal we want for misconfigured deployments.
COPY validate-required-env.py /usr/local/apisix/conf/validate-required-env.py
RUN chmod +x /usr/local/apisix/conf/validate-required-env.py

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# bootstrap.sh is intentionally NOT copied here -- it was the
# Traditional + etcd Admin API seeding script and was deleted along
# with the etcd / gateway-bootstrap services in the Standalone YAML
# migration (see docs/development/gateway.md §1.2).

ENTRYPOINT ["/entrypoint.sh"]
CMD ["docker-start"]
