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
#   <output_dir>/<kid>-public-keys.json
#

set -eu

OUTPUT_DIR="${1:-.tmp/jwt-keys}"
KID="${2:-dev-rsa-1}"

PRIVATE_KEY="$OUTPUT_DIR/${KID}-private.pem"
PUBLIC_KEY="$OUTPUT_DIR/${KID}-public.pem"
PUBLIC_KEYS_JSON="$OUTPUT_DIR/${KID}-public-keys.json"

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Skip if keys already exist
if [ -f "$PRIVATE_KEY" ] && [ -f "$PUBLIC_KEY" ] && [ -f "$PUBLIC_KEYS_JSON" ]; then
    echo "[INFO] JWT keys already exist at $OUTPUT_DIR (kid=$KID). Skipping generation."
    exit 0
fi

# Check for openssl
if ! command -v openssl >/dev/null 2>&1; then
    echo "[ERROR] openssl is required but not found." >&2
    exit 1
fi

echo "[INFO] Generating RS256 JWT key pair (kid=$KID)..."

# Generate 2048-bit RSA private key
openssl genpkey -algorithm RSA -out "$PRIVATE_KEY" -pkeyopt rsa_keygen_bits:2048 2>/dev/null

# Extract public key
openssl rsa -pubout -in "$PRIVATE_KEY" -out "$PUBLIC_KEY" 2>/dev/null

# Build public-keys.json (kid -> PEM mapping)
# Read the public key PEM, escape newlines for JSON
PUB_PEM=$(cat "$PUBLIC_KEY" | sed ':a;N;$!ba;s/\n/\\n/g')
printf '{\n  "%s": "%s"\n}\n' "$KID" "$PUB_PEM" > "$PUBLIC_KEYS_JSON"

echo "[INFO] JWT keys generated:"
echo "  Private key : $PRIVATE_KEY"
echo "  Public key  : $PUBLIC_KEY"
echo "  Public JSON : $PUBLIC_KEYS_JSON"
