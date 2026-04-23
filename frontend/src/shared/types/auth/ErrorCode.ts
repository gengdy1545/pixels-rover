/**
 * Business-domain error codes owned by `auth-service`.
 *
 * **Source of truth**:
 * `services/auth-service/src/main/java/io/pixelsdb/pixels/rover/config/common/ErrorCodeName.java`
 * (constants prefixed `AUTH_*`). Long-term this file is expected to be
 * generated from that service's OpenAPI `details.errorCode` enum; until then
 * it must be kept in lockstep manually -- the §17 audit check greps for
 * symmetric coverage.
 *
 * Do NOT add `GATEWAY_*` / `INTERNAL_*` here: those live in `infra.ts` (see
 * backend.md §6.3.2 for why the two namespaces are strictly disjoint).
 */
export type AuthErrorCode =
  | 'AUTH_INVALID_ARGUMENT'
  | 'AUTH_MISSING_PARAMETER'
  | 'AUTH_MISSING_HEADER'
  | 'AUTH_INVALID_CREDENTIALS'
  | 'AUTH_INVALID_TOKEN'
  | 'AUTH_INVALID_TOKEN_TYPE'
  | 'AUTH_REFRESH_TOKEN_MISSING'
  | 'AUTH_REFRESH_TOKEN_REUSED'
  | 'AUTH_SESSION_REVOKED'
  | 'AUTH_SESSION_NOT_FOUND'
  | 'AUTH_USER_NOT_FOUND'
  | 'AUTH_USER_ALREADY_EXISTS'
  | 'AUTH_CAPTCHA_INVALID'
  | 'AUTH_CAPTCHA_GENERATION_FAILED'
  | 'AUTH_ACCESS_DENIED'
  | 'AUTH_METHOD_NOT_ALLOWED'
  | 'AUTH_DEMO_MODE_READONLY'
  | 'AUTH_INVALID_PRINCIPAL';
