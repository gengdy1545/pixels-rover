# Pixels Rover

Pixels Rover is a gateway-first web application. All browser traffic enters
through APISIX, identity is owned by Ory Kratos, protected API access is
mediated by Ory Oathkeeper, and business services consume only the identity
headers injected by Oathkeeper.

## Runtime Shape

```text
Browser
  |
  v
APISIX gateway
  |-- /ui/*, /self-service/*, /sessions/*, /schemas/* -> Ory UI / Kratos
  |-- /api/v1/auth*                                  -> 410 retired
  |-- /api/v1/*                                      -> gateway-csrf -> Oathkeeper
  |-- /*                                             -> frontend
                                                        |
                                                        v
                                                   assistant-service
```

APISIX owns routing, CORS/CSP/security headers, `X-Request-Id`,
`/gateway/live`, `/gateway/ready`, and unsafe-method CSRF validation through
the `gateway-csrf` plugin. Kratos owns browser identity/session state.
Oathkeeper owns protected API authorization and writes `X-Auth-User-Id`,
`X-Auth-User-Email`, and `X-Auth-Session-Id`.

## Directory Layout

```text
config/
  ory/                  # Kratos/Oathkeeper config and rules
  required-env.yaml     # required environment SSOT
gateway/                # APISIX image, templates, custom Lua plugins
frontend/               # Vite/React SPA
services/
  assistant-service/    # FastAPI business service
db/                     # MySQL first-boot schema bootstrap
docs/                   # development and runbook docs
```

`services/` contains only in-repo service implementations. Third-party service
configuration lives under `config/`. Real secrets and keys are not stored in
the repository; use `.env`, Docker secrets, or deployment-managed secret
stores.

## Local Development

Use the development overlay so local-only Ory defaults are explicit:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

The base compose file is production-oriented and requires explicit values for
`PUBLIC_BASE_URL`, Kratos secrets, Ory UI cookie secret, gateway CORS/CSP
settings, and assistant-service runtime settings. `.env.example` is generated
from `config/required-env.yaml`.

## Validation

Useful checks before opening a PR:

```bash
python3 scripts/check-contracts.py
docker compose -f docker-compose.yml -f docker-compose.dev.yml config
./gateway/tests/run.sh
cd frontend && npm test -- --run
```

For live contract smoke tests:

```bash
bash scripts/smoke.sh
```
