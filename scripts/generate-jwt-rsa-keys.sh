#!/usr/bin/env sh
#
# Generate RS256 JWT key pair for development.
#
# Usage:
#   ./generate-jwt-rsa-keys.sh <output_dir> <kid>
#
# Example:
#   ./generate-jwt-rsa-keys.sh .tmp/jwt-keys dev-rsa-1
#
# Outputs:
#   <output_dir>/<kid>-private.pem
#   <output_dir>/<kid>-public.pem
#
# Note: the former "<kid>-public-keys.json" / "all-public-keys.json" merged-public-key
# artifacts were retired with the /api/v1/auth/jwks endpoint — see
# docs/design/jwt-rotation.md §1.2. auth-service discovers additional verification keys
# during rotation by enumerating every "<kid>-public.pem" in its configured public-keys
# directory; no JSON bundle is written or distributed.
#

set -eu

OUTPUT_DIR="${1:-.tmp/jwt-keys}"
KID="${2:-dev-rsa-1}"

PRIVATE_KEY="$OUTPUT_DIR/${KID}-private.pem"
PUBLIC_KEY="$OUTPUT_DIR/${KID}-public.pem"

mkdir -p "$OUTPUT_DIR"

if [ -f "$PRIVATE_KEY" ] && [ -f "$PUBLIC_KEY" ]; then
    echo "[INFO] JWT keys already exist at $OUTPUT_DIR (kid=$KID). Skipping generation."
    exit 0
fi

if ! command -v openssl >/dev/null 2>&1; then
    echo "[ERROR] openssl is required but not found." >&2
    exit 1
fi

echo "[INFO] Generating RS256 JWT key pair (kid=$KID)..."

openssl genpkey -algorithm RSA -out "$PRIVATE_KEY" -pkeyopt rsa_keygen_bits:2048 2>/dev/null
openssl rsa -pubout -in "$PRIVATE_KEY" -out "$PUBLIC_KEY" 2>/dev/null

echo "[INFO] JWT keys generated:"
echo "  Private key : $PRIVATE_KEY"
echo "  Public key  : $PUBLIC_KEY"
