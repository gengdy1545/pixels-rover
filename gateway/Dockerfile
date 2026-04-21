FROM apache/apisix:3.9.1-debian

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gettext-base \
    && rm -rf /var/lib/apt/lists/*

COPY custom/apisix/plugins/gateway-auth.lua /usr/local/apisix/apisix/plugins/gateway-auth.lua
COPY config.yaml.template /usr/local/apisix/conf/config.yaml.template
COPY entrypoint.sh /entrypoint.sh
COPY bootstrap.sh /bootstrap.sh

RUN chmod +x /entrypoint.sh /bootstrap.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["docker-start"]
