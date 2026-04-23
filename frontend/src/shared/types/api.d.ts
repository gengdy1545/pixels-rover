/**
 * Back-compat facade for code that still imports from `../types/api`.
 *
 * The real definitions moved to `./common` (alongside `./infra`,
 * `./auth/ErrorCode`, `./analysis/ErrorCode`) to implement the
 * backend.md §6.3.2 merge point. New code SHOULD import from `./common`
 * directly; this file exists only to avoid a mass-rename churn in the same
 * PR that shipped the envelope refactor.
 *
 * owning-service: shared (cross-service envelope)
 * source-of-truth: backend.md §6.0 (unified response envelope) +
 *   gateway/error-codes.json::code (for the ErrorCode union branch).
 *
 * This file is a pure re-export facade so the metadata lives here for
 * discoverability; the concrete shapes are declared in ./common per the
 * frontend.md §4.6 "手写契约镜像文件的顶部元数据" rule.
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
