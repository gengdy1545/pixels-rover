/**
 * Structured error thrown by the shared HTTP / SSE client on every non-2xx
 * response.
 *
 * The fields mirror the response envelope defined by backend.md §6.0:
 *
 * - `httpStatus` = raw HTTP status line (always populated).
 * - `message`    = envelope `message` (fallback to the HTTP reason phrase or
 *                  a transport-layer message when we have nothing else).
 * - `details`    = envelope `details` when present. Per backend.md §6.3,
 *                  ALL failure responses carry `errorCode` + `category`
 *                  except the §6.5 framework-level uncaught-exception
 *                  fallback; keep this optional rather than forcing callers
 *                  to guard on "what if the backend is buggy".
 * - `requestId`  = envelope `requestId` for log correlation.
 *
 * Consumers (stores, pages) SHOULD dispatch per backend.md §6.3.2's two-tier
 * strategy:
 *   1. switch (err.details?.errorCode) for precise UX
 *   2. fallback to err.details?.category for generic bucket handling
 *   3. last-resort fallback to err.httpStatus / err.message
 *
 * Extending Error keeps `instanceof Error` true for any code that currently
 * does `.catch(e: Error)` or inspects `e.message`.
 */
import type { ApiErrorDetails, ApiErrorResponse } from '../types/common';

export class ApiError extends Error {
  readonly httpStatus: number;
  readonly details?: ApiErrorDetails;
  readonly requestId?: string;

  constructor(params: {
    httpStatus: number;
    message: string;
    details?: ApiErrorDetails;
    requestId?: string;
  }) {
    super(params.message);
    this.name = 'ApiError';
    this.httpStatus = params.httpStatus;
    this.details = params.details;
    this.requestId = params.requestId;
    // Preserve prototype chain across transpilation targets
    Object.setPrototypeOf(this, ApiError.prototype);
  }

  /** Convenience accessor for backend.md §6.3.2 step 1 dispatch. */
  get errorCode() {
    return this.details?.errorCode;
  }

  /** Convenience accessor for backend.md §6.3.2 step 2 dispatch. */
  get category() {
    return this.details?.category;
  }
}

/**
 * Build an ApiError from a parsed envelope body. Tolerates malformed bodies
 * (missing `details`, missing `message`) so a buggy service cannot crash the
 * dispatch layer; it can only degrade the precision of the resulting error.
 */
export function apiErrorFromEnvelope(
  httpStatus: number,
  body: Partial<ApiErrorResponse> | undefined,
  fallbackMessage: string,
): ApiError {
  return new ApiError({
    httpStatus,
    message: body?.message || fallbackMessage,
    details: body?.details,
    requestId: body?.requestId,
  });
}
