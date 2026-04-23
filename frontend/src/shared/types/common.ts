/**
 * Shared cross-service API types.
 *
 * This module is the merge point for the `ErrorCode` union defined by
 * `docs/development/backend.md §6.3.2`. Every new service prefix must be
 * added here alongside its import, otherwise the compiler judges the new
 * errorCode as "already exhaustive" in `switch (err.details.errorCode)` and
 * silently falls through to the generic 5xx fallback -- which is the
 * historical hardest-to-find drift bug.
 *
 * owning-service: shared (cross-service envelope; genuinely unowned by any
 *   single backend service — every service produces responses in this shape).
 * source-of-truth: backend.md §6.0 (unified response envelope: `code` /
 *   `message` / `data | details` / `requestId`) + §6.3.2 (how per-service
 *   `ErrorCode` unions merge into the top-level union declared here).
 *   Per-service branches import from `./infra` (gateway), `./auth/ErrorCode`
 *   (auth-service), `./analysis/ErrorCode` (assistant-service), each of
 *   which carries its own owning-service + source-of-truth tags.
 *
 * Hand-mirrored per frontend.md §4.6 "手写契约镜像文件的顶部元数据" rule.
 */
import type { InfraErrorCode } from './infra';
import type { AuthErrorCode } from './auth/ErrorCode';
import type { AnalysisErrorCode } from './analysis/ErrorCode';

export type { InfraErrorCode, AuthErrorCode, AnalysisErrorCode };

/**
 * Union of every stable errorCode the frontend may observe under
 * `ApiErrorResponse.details.errorCode`. See backend.md §6.3.2.
 */
export type ErrorCode = InfraErrorCode | AuthErrorCode | AnalysisErrorCode;

/**
 * Coarse failure categories used for the "second-tier" fallback dispatch
 * (backend.md §6.3.2 step 2). Stay aligned with
 * `services/auth-service/.../ErrorCategory.java` and
 * `services/assistant-service/app/error_codes.py ErrorCategory`.
 */
export type ErrorCategory =
  | 'USER_INPUT'
  | 'AUTH'
  | 'RATE_LIMIT'
  | 'UPSTREAM'
  | 'INTERNAL';

/**
 * The `details` object carried by every non-2xx response (backend.md §6.0).
 *
 * `errorCode` and `category` are BOTH mandatory -- the frontend dispatch
 * contract (§6.3.2) keys off them in that order. The only exception is the
 * framework-level "unknown unhandled exception" fallback (§6.5), which the
 * type marks by making `details` itself optional on `ApiErrorResponse`.
 *
 * Services may attach additional hint fields (`field`, `retryAfterSec`, ...).
 * We keep `[key: string]: unknown` open-ended rather than enumerating, so
 * the shared client doesn't become a bottleneck for every hint extension.
 */
export interface ApiErrorDetails {
  errorCode: ErrorCode;
  category: ErrorCategory;
  [key: string]: unknown;
}

export interface ApiSuccessResponse<T> {
  /** Equals the HTTP status (§6.0). Always in 2xx for success envelopes. */
  code: number;
  message: string;
  requestId?: string;
  data: T;
}

export interface ApiErrorResponse {
  code: number;
  message: string;
  requestId?: string;
  /**
   * Absent **only** on the framework-level uncaught-exception fallback
   * (backend.md §6.5). In every other failure path this is present and
   * contains both `errorCode` and `category`.
   */
  details?: ApiErrorDetails;
}

export type ApiResponse<T = unknown> = ApiSuccessResponse<T> | ApiErrorResponse;

export interface PageParams {
  page: number;
  pageSize: number;
}
