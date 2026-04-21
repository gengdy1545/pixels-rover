// ════════════════════════════════════════
// Unified API Client — single entry point for all API modules
// ════════════════════════════════════════

// API modules
export { authApi } from './modules/auth';
export { submitAnalysis, getAnalysisResult, getSemanticMetrics, getSemanticDimensions } from './modules/analysis';
export { conversationApi } from './modules/conversations';
export { metadataApi } from './modules/metadata';

// SSE client
export { openSSEStream } from './sse';

// HTTP client (for advanced usage)
export { httpClient, refreshAccessToken, buildCommonHeaders } from './client';
export { get, post, put, patch, del, postVoid, putVoid } from './client';

// Re-export types for convenience
export type { SSECallbacks, SSEConnection, SSEEventName, SSEEventMap } from '../types/sse';
export type { ApiResponse, ErrorCode, PageParams } from '../types/api';
