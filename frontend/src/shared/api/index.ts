// ════════════════════════════════════════
// shared/api barrel — 通用 HTTP / SSE 基础设施唯一入口（PR-4 终态）。
// ════════════════════════════════════════
//
// 这一层只放"任何 feature 都会复用的 HTTP/SSE 基础能力"：
//   - axios 实例 + envelope 解包 + 401 重放队列（client.ts）
//   - 通用 SSE 客户端（sse.ts）
//   - `ApiError` 结构化异常（apiError.ts）
//   - HTTP / SSE / envelope 的类型 re-export
//
// 业务 endpoint 不再住在这里。它们按 feature 归属下沉到各自的
// services/，由该 feature 的 hook 独占调用：
//   - `authApi`         → `features/auth/services/authApi.ts`         （Stage 3 §10 PR-2）
//   - `conversationApi` → `features/conversation/services/conversationApi.ts` （Stage 3 §10 PR-3）
//   - `metadataApi`     → `features/schema/services/metadataApi.ts`   （Stage 3 §10 PR-3）
//   - `submitAnalysis` / `getAnalysisResult`
//                       → `features/analysis/services/analysisApi.ts` （Stage 3 §10 PR-4）
//   - `getSemanticMetrics` / `getSemanticDimensions`
//                       → `features/semantic/services/semanticApi.ts` （Stage 3 §10 PR-4）
//
// 不要再往这里加业务 endpoint：会反向破坏 lint-0（feature 边界）和 PR-4
// 之后形成的"shared/api 纯基础设施"约束。

// SSE client
export { openSSEStream } from './sse';

// HTTP client (for advanced usage)
export { httpClient, refreshAccessToken, buildCommonHeaders } from './client';
export { get, post, put, patch, del, postVoid, putVoid } from './client';

// Structured error class -- always thrown by the client / SSE layer on any
// non-2xx response; consumers dispatch via `err.details.errorCode` /
// `err.details.category` per backend.md §6.3.2.
export { ApiError } from './apiError';

// Category-driven error policy helpers (isRetryable / categorize /
// retryAfterSec). Features route through these instead of re-reading
// `err.httpStatus` — the SSOT for retryability / bucketing is the
// `category` + `retryable` columns in `gateway/error-codes.json`, and
// `errorPolicy.ts` is the single consumer-side mirror. See backend.md
// §6.3.2 two-tier dispatch contract.
export { isRetryable, categorize, retryAfterSec } from './errorPolicy';
export type { ApiErrorBucket } from './errorPolicy';

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
