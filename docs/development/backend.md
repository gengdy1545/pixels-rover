# Backend Architecture

Pixels Rover uses a gateway-first backend model. Browser traffic reaches
business services only through APISIX and Ory Oathkeeper.

## Identity Boundary

Kratos is the identity and session authority. Oathkeeper validates protected
API requests and writes these headers before forwarding to business services:

- `X-Auth-User-Id`: Kratos identity id, treated as an opaque string.
- `X-Auth-User-Email`: Kratos identity email trait.
- `X-Auth-Session-Id`: Kratos session id.

Business services must not call Kratos or Oathkeeper to re-check the current
request. They consume the injected headers and fail closed if required identity
headers are missing.

## Services

- `assistant-service` owns analysis, conversation, and semantic APIs under
  `/api/v1/analysis*`, `/api/v1/conversations*`, and `/api/v1/semantic*`.
- Kratos/Oathkeeper/Ory UI are third-party components configured under
  `config/ory/*`; they are not in-repo `services/` implementations.

The old in-repo auth service is retired. `pixels_auth` is no longer the
authentication/session source of truth.

## Data Ownership

Each in-repo business service owns its own database schema. `assistant-service`
uses `pixels_analysis` and manages its schema through Alembic. Kratos uses
`pixels_kratos` through Ory's migration tooling.

## Required Environment

`config/required-env.yaml` is the single source of truth for required runtime
environment variables. It is consumed by:

- `.env.example` generation.
- Gateway startup validation.
- The compose Ory required-env guard.
- Assistant-service startup validation.
- Smoke-test preflight assumptions.

Production must explicitly set Ory secrets and `PUBLIC_BASE_URL`; local
development gets safe defaults only through `docker-compose.dev.yml`.

## Error Envelope

Business services return the shared envelope shape:

- Success: `{ code, message, requestId?, data }`.
- Error: `{ code, message, requestId?, details: { errorCode, category, ... } }`.

Infrastructure error-code source of truth is `gateway/error-codes.json`.
Assistant-service business codes live in `services/assistant-service/app/error_codes.py`
and are mirrored in `frontend/src/shared/types/analysis/ErrorCode.ts`.

### Infrastructure Error Codes

The table below is generated from `gateway/error-codes.json`. Do not edit the
generated region by hand; update the JSON registry and run
`python3 scripts/generate-error-code-registry.py`.

<!-- AUTO-GENERATED-ERROR-CODE-REGISTRY:BEGIN -->

| `errorCode` | HTTP | `category` | 写入方 | 触发条件 | 文档锚点 |
|---|---|---|---|---|---|
| `GATEWAY_SUBJECT_MISMATCH` | `401` | `AUTH` | business-service | Verified JWT claims do not agree with the X-Auth-* header triple (e.g. sub != X-Auth-User-Id). Indicates the X-Auth-* headers were injected by a party other than Oathkeeper while the JWT itself was genuine — same silent-bypass vector §Task 8 closes. | backend.md §3.3 |
| `GATEWAY_SUBJECT_UNVERIFIED` | `401` | `AUTH` | business-service | Protected route received no Authorization: Bearer token, or the token failed JWKS signature / iss / aud / exp verification. Issued by the backend's Oathkeeper id_token mutator verifier (architecture-tasks §Task 8) — flips the historic X-Auth-* plaintext trust model to an integrity-protected one. | backend.md §3.3 |
| `GATEWAY_CSRF_INVALID` | `403` | `AUTH` | gateway:gateway-csrf | Unsafe HTTP method missing X-Xsrf-Token header, or header value did not match the XSRF-TOKEN cookie (double-submit failure). | gateway.md §5.2 |
| `GATEWAY_IDENTITY_MISSING` | `500` | `INTERNAL` | business-service | Protected route received a missing or malformed X-Auth-User-Id — Oathkeeper mutator was not applied or the request bypassed the gateway entirely. | backend.md §3.3 |
| `INTERNAL_AUTH_FAILED` | `500` | `INTERNAL` | business-service:InternalAuthFilter | /api/internal/* path received a request whose X-Internal-Auth header was missing or did not match the shared secret. Deliberately 500 (not 401/403) because any occurrence signals gateway routing drift, not a user-facing auth failure. | backend.md §8.6 |
| `GATEWAY_NOT_READY` | `503` | `UPSTREAM` | gateway:gateway-ready | GET /gateway/ready aggregated at least one upstream whose /internal/ready probe returned non-200 or timed out. | gateway.md §4.1 |

<!-- AUTO-GENERATED-ERROR-CODE-REGISTRY:END -->
