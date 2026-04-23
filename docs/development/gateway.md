# Gateway Architecture

APISIX is the only public entrypoint. It owns edge routing, security response
headers, CORS/CSP, request ids, liveness/readiness, and unsafe-method CSRF
validation. It does not own identity, sessions, credential validation, or
identity-header generation.

## Routing

- `/gateway/live` is liveness and never probes upstreams.
- `/gateway/ready` aggregates Kratos, Oathkeeper, Ory UI, and assistant-service readiness.
- `/ui/*`, `/self-service/*`, `/sessions/*`, and `/schemas/*` expose Ory UI and Kratos public browser-flow endpoints.
- `/api/v1/auth` and `/api/v1/auth/*` return 410 because the legacy auth API is retired.
- `/api/v1/*` is the single protected API edge. APISIX runs `gateway-csrf`, strips forged `X-Auth-*`, then proxies to Oathkeeper.
- `/*` serves the frontend.

Oathkeeper rules, not APISIX, own protected API path-to-upstream dispatch.

## Custom Plugins

`gateway-csrf` is intentionally narrow:

- It strips all client-supplied `X-Auth-*` headers before Oathkeeper runs.
- It enforces double-submit CSRF for unsafe methods by comparing the
  `XSRF-TOKEN` cookie with the `X-XSRF-TOKEN` header.
- It propagates or mints `X-Request-Id`.
- It sets `X-Forwarded-For`, `X-Forwarded-Proto`, and `X-Forwarded-Host`.
- It never authenticates users and never writes identity headers.

`gateway-ready` aggregates internal probe locations. A probe is ready only when
its response status is in the configured `success_statuses`; the default is
`[200]`. Ory UI explicitly allows 3xx because browser login endpoints may
redirect while still proving the process is reachable.

## Error Codes

Gateway-owned infrastructure codes live in `gateway/error-codes.json` and are
mirrored by `frontend/src/shared/types/infra.ts`.

Current gateway-emitted codes:

- `GATEWAY_CSRF_INVALID`: `gateway-csrf` rejected an unsafe request.
- `GATEWAY_NOT_READY`: `/gateway/ready` found at least one dependency down.

`GATEWAY_IDENTITY_MISSING` and `INTERNAL_AUTH_FAILED` are still registered as
cross-service infrastructure codes. Oathkeeper/Kratos 401 responses are not
rewritten into legacy gateway auth codes.

## Adding A Protected API

Add or update the Oathkeeper rule under `config/ory/oathkeeper/rules.yml`.
Do not add another APISIX protected route unless the new API needs a distinct
edge-level timeout or buffering policy. If that happens, keep the route
coarse, attach `gateway-csrf`, strip `X-Auth-*`, and update
`scripts/check-contracts.py`.
