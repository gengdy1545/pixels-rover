/**
 * Business-domain error codes owned by `assistant-service` (analysis / conversation
 * / semantic sub-domains all share the `ANALYSIS_*` prefix; if a sub-domain's
 * contract grows, split into `CONVERSATION_*` etc. per backend.md §6.3).
 *
 * **Source of truth**: `services/assistant-service/app/error_codes.py` string
 * constants prefixed `ANALYSIS_*`. Long-term replaced by OpenAPI-generated
 * types; until then kept in lockstep manually.
 *
 * Do NOT add `GATEWAY_*` / `INTERNAL_*` here: those live in `infra.ts`.
 */
export type AnalysisErrorCode =
  | 'ANALYSIS_INVALID_ARGUMENT'
  | 'ANALYSIS_THREAD_NOT_FOUND'
  | 'ANALYSIS_THREAD_ARCHIVED'
  | 'ANALYSIS_SESSION_NOT_FOUND'
  | 'ANALYSIS_BACKEND_NOT_FOUND'
  | 'ANALYSIS_SCHEMA_UNAVAILABLE';
