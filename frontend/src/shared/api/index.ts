// ════════════════════════════════════════
// Unified API Client — single entry point for all API modules
// ════════════════════════════════════════

// API modules
//
// 当前仅 `analysis` 模块还住在 shared/api/modules——主要原因是 SSE 客户端
// 与 analysis endpoint 紧耦合（`submitAnalysis` 直接消费 `openSSEStream`），
// PR-4 会把 analysis pages / components / SSE-orchestrator 一起搬进
// `features/analysis/`，届时这一行也跟着撤下，shared/api 退回纯通用层
// （axios 实例 + envelope 解包 + 401 重放队列 + 通用 SSE）。
//
// 已迁的（不要再从这里 re-export）：
//   - `authApi`           → `features/auth/services/authApi.ts`         （Stage 3 §10 PR-2）
//   - `conversationApi`   → `features/conversation/services/conversationApi.ts` （Stage 3 §10 PR-3）
//   - `metadataApi`       → `features/schema/services/metadataApi.ts`   （Stage 3 §10 PR-3）
export { submitAnalysis, getAnalysisResult, getSemanticMetrics, getSemanticDimensions } from './modules/analysis';

// SSE client
export { openSSEStream } from './sse';

// HTTP client (for advanced usage)
export { httpClient, refreshAccessToken, buildCommonHeaders } from './client';
export { get, post, put, patch, del, postVoid, putVoid } from './client';

// Structured error class -- always thrown by the client / SSE layer on any
// non-2xx response; consumers dispatch via `err.details.errorCode` /
// `err.details.category` per backend.md §6.3.2.
export { ApiError } from './apiError';

// Re-export types for convenience
export type { SSECallbacks, SSEConnection, SSEEventName, SSEEventMap } from '../types/sse';
export type {
  ApiResponse,
  ApiSuccessResponse,
  ApiErrorResponse,
  ApiErrorDetails,
  ErrorCode,
  ErrorCategory,
  PageParams,
} from '../types/common';
