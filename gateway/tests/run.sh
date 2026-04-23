#!/usr/bin/env bash
# Run gateway Lua unit tests in a pinned APISIX image.
#
# First invocation builds the test image (~1-2 min); subsequent runs reuse
# the cached image and finish in seconds. The image is throwaway-safe --
# `docker image rm pixels-gateway-tests` forces a rebuild next run.
#
# Args after -- are forwarded to busted, e.g.:
#   ./run.sh -- --filter "apply_csrf"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATEWAY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
IMAGE_TAG="${PIXELS_GATEWAY_TEST_IMAGE:-pixels-gateway-tests:latest}"

if ! docker image inspect "${IMAGE_TAG}" >/dev/null 2>&1; then
    echo ">>> Building test image ${IMAGE_TAG} (one-time)..." >&2
    docker build -t "${IMAGE_TAG}" -f "${SCRIPT_DIR}/Dockerfile" "${SCRIPT_DIR}"
fi

# Mount the whole gateway/ subtree so spec files can reach ../custom/... via
# dofile(). Read-only: tests must never mutate source.
exec docker run --rm \
    -v "${GATEWAY_DIR}:/gw:ro" \
    -w /gw/tests \
    "${IMAGE_TAG}" "$@"
