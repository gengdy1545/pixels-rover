/**
 * Business-domain error codes owned by `auth-service`.
 *
 * owning-service: auth-service
 * source-of-truth (primary):
 *   services/auth-service/src/main/java/io/pixelsdb/pixels/rover/config/common/
 *     ErrorCodeName.java — the `AUTH_*` string constants.
 * source-of-truth (long-term, once codegen lands):
 *   services/auth-service/openapi.json#/components/schemas/ApiErrorDetails/
 *     properties/errorCode/enum (the `AUTH_*` subset).
 *
 * The Java-side ⇄ TS-side bidirectional alignment is enforced by
 * `scripts/check-contracts.py::frontend-auth-union-equals-java-source`, so
 * adding or removing a code on exactly one side fails CI. The OpenAPI schema
 * is generated from the same Java constants, so it stays aligned by
 * construction.
 *
 * Do NOT add `GATEWAY_*` / `INTERNAL_*` here: those live in `infra.ts` (see
 * backend.md §6.3.2 for why the two namespaces are strictly disjoint).
 *
 * Hand-mirrored per frontend.md §4.6 "手写契约镜像文件的顶部元数据" rule.
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
  | 'AUTH_INVALID_PRINCIPAL'
  // Degradation-mode UPSTREAM code (backend.md §6.7).
  // Emitted when `pixels_auth` DB is transiently unreachable — see
  // ErrorCodeName.AUTH_DATABASE_UNAVAILABLE for the full contract.
  | 'AUTH_DATABASE_UNAVAILABLE';
