/**
 * Shared cross-service API types.
 *
 * This module is the merge point for the `ErrorCode` union defined by
 * `docs/development/backend.md §6.3.2`. Every new service prefix must be
 * added here alongside its import, otherwise the compiler judges the new
 * errorCode as "already exhaustive" in `switch (err.details.errorCode)` and
 * silently falls through to the generic 5xx fallback -- which is the
 * historical hardest-to-find drift bug.
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
