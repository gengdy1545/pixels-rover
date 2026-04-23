/**
 * Business-domain error codes owned by `assistant-service` (analysis /
 * conversation / semantic sub-domains all share the `ANALYSIS_*` prefix;
 * if a sub-domain's contract grows, split into `CONVERSATION_*` etc. per
 * backend.md §6.3).
 *
 * owning-service: assistant-service
 * source-of-truth (primary):
 *   services/assistant-service/app/error_codes.py — the `ANALYSIS_*` /
 *     `CONVERSATION_*` / `SEMANTIC_*` string constants.
 * source-of-truth (long-term, once codegen lands):
 *   services/assistant-service/openapi.json#/components/schemas/ApiErrorDetails/
 *     properties/errorCode/enum (the assistant-service business subset).
 *
 * The Python-side ⇄ TS-side bidirectional alignment is enforced by
 * `scripts/check-contracts.py::frontend-analysis-union-equals-python-source`,
 * so adding or removing a code on exactly one side fails CI.
 *
 * Do NOT add `GATEWAY_*` / `INTERNAL_*` here: those live in `infra.ts`.
 *
 * Hand-mirrored per frontend.md §4.6 "手写契约镜像文件的顶部元数据" rule.
 */
export type AnalysisErrorCode =
  | 'ANALYSIS_INVALID_ARGUMENT'
  | 'ANALYSIS_THREAD_NOT_FOUND'
  | 'ANALYSIS_THREAD_ARCHIVED'
  | 'ANALYSIS_SESSION_NOT_FOUND'
  | 'ANALYSIS_BACKEND_NOT_FOUND'
  | 'ANALYSIS_SCHEMA_UNAVAILABLE'
  // Degradation-mode UPSTREAM codes (backend.md §6.7). The frontend's
  // per-page fallback dispatcher keys off these strings to scope degradation
  // to just the affected feature (analysis-only vs. site-wide) — see the
  // failure contract table in backend.md §6.7 for which routes fail together.
  | 'ANALYSIS_DATABASE_UNAVAILABLE'
  | 'ANALYSIS_UPSTREAM_UNAVAILABLE'
  | 'ANALYSIS_BACKEND_UNAVAILABLE';
