// ════════════════════════════════════════
// Unified API Client — single entry point for all API modules
// ════════════════════════════════════════

// API modules
//
// 注意：原 `authApi` 已迁至 `features/auth/services/authApi.ts`（Stage 3
// §10 PR-2）——`shared/api/` 只保留跨 feature 通用能力，feature 私有
// endpoint 归 feature 自己的 `services/` 目录。后续 PR-3 计划把
// conversationApi / metadataApi 同样迁进各自 feature。
export { submitAnalysis, getAnalysisResult, getSemanticMetrics, getSemanticDimensions } from './modules/analysis';
export { conversationApi } from './modules/conversations';
export { metadataApi } from './modules/metadata';

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
