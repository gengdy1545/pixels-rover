# Frontend Architecture

The frontend is a first-party SPA. It does not own authentication. Login,
registration, settings, and logout flows are delegated to Ory Kratos/Ory UI.

## Auth Flow

- `/login` and `/register` are thin local entry pages that redirect to Kratos
  browser flows.
- Login state is a UI hint derived from `GET /sessions/whoami`.
- Protected API authorization is enforced by Oathkeeper behind the gateway.
- HTTP 401 responses redirect the browser to the Kratos login flow.

## API Client

The shared API client adds:

- `X-Request-Id` for correlation.
- `X-XSRF-TOKEN`, mirrored from the JS-readable `XSRF-TOKEN` cookie for
  unsafe requests.

The gateway validates CSRF before forwarding protected API requests to
Oathkeeper. Kratos keeps the authoritative session in HttpOnly cookies.

## Error Codes

Frontend hand-written contract mirrors live under `frontend/src/shared/types`.

- Infrastructure codes are mirrored from `gateway/error-codes.json`.
- Assistant-service business codes are mirrored from
  `services/assistant-service/app/error_codes.py`.

There is no frontend mirror for legacy auth business codes because the in-repo
auth service is retired. Kratos/Oathkeeper auth failures are handled by HTTP
status and browser flow redirects.
