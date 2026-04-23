/**
 * Back-compat facade for code that still imports from `../types/api`.
 *
 * The real definitions moved to `./common` (alongside `./infra`,
 * `./auth/ErrorCode`, `./analysis/ErrorCode`) to implement the
 * backend.md §6.3.2 merge point. New code SHOULD import from `./common`
 * directly; this file exists only to avoid a mass-rename churn in the same
 * PR that shipped the envelope refactor.
 */
export type {
  ApiResponse,
  ApiSuccessResponse,
  ApiErrorResponse,
  ApiErrorDetails,
  ErrorCode,
  ErrorCategory,
  PageParams,
} from './common';
