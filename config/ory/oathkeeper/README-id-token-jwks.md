# Oathkeeper `id_token` mutator signing keys — DEVELOPMENT ONLY
#
# This directory holds the JWKS document Oathkeeper signs with for the
# id_token mutator (architecture-tasks §Task 8). The file
# `id_token.jwks.json` in this directory is a DEVELOPMENT-ONLY sample
# key:
#
#   * `docker-compose.dev.yml` mounts it into Oathkeeper at
#     `/etc/config/oathkeeper/id_token.jwks.json` so first-time local
#     boots have a valid key without operator setup.
#   * Production and staging deployments MUST override this bind-mount
#     with a real private key provisioned outside the repo. The base
#     `docker-compose.yml` never mounts the dev sample.
#
# Rotation policy:
#   * Any commit to `id_token.jwks.json` forces every locally-running
#     Oathkeeper to re-read it and invalidates the backend JWKS cache
#     (`app.oathkeeper_jwt._JwksCache` TTL = 300s). The dev key is
#     stable across commits by design — rotating it would be noise.
#   * Production key rotation is out of scope for this directory; it
#     happens via the operator's secret management of choice (e.g.
#     sops-encrypted file, HashiCorp Vault template).
#
# Format: a JWKS document (`{"keys": [ ... ]}`) with exactly one RS256
# private JWK. Oathkeeper serves the PUBLIC projection of this key on
# `http://oathkeeper:4456/.well-known/jwks.json`, which is what the
# backend verifier fetches via `OATHKEEPER_JWKS_URL`.
