# Build with:
#   docker build -t pixels-gateway-tests -f gateway/tests/Dockerfile gateway/tests
# Run via gateway/tests/run.sh.
#
# We layer on top of the exact APISIX image that production uses so that
# unit tests execute against the same OpenResty / lua-cjson / lua-resty-*
# set the plugin will see in production. This avoids "works on my machine"
# gaps caused by subtle cjson / resty version differences.
FROM apache/apisix:3.9.1-debian

USER root

# busted itself pulls in luaassert/luasystem/dkjson/etc. We pin nothing yet --
# busted's API is stable and transitive dep churn has not bitten us.
# luarocks needs a working C toolchain to build luasystem (a busted transitive
# dep). build-essential + lua5.1-dev are the smallest set that gets us there
# on the debian base.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        luarocks build-essential lua5.1 liblua5.1-0-dev \
    && rm -rf /var/lib/apt/lists/* \
    && luarocks install busted \
    && luarocks install lua-cjson

WORKDIR /gw/tests

# Default command runs the full spec tree; override from docker run for
# targeted spec files.
ENTRYPOINT ["busted", "--verbose", "spec/"]
