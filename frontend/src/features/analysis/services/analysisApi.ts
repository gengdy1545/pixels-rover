/**
 * analysis feature 的 API 客户端封装（Stage 3 §10 PR-4 从 shared/api/modules/analysis 迁入）。
 *
 * 这里只放 analysis 域专属 endpoint：
 *   - `submitAnalysis`：POST `/api/v1/analysis` + 接 SSE 事件流，作为
 *     `model/store.ts` 里 `startAnalysis` 的真正调用面；
 *   - `getAnalysisResult`：按 sessionId 拉一份已完成分析（restoration /
 *     刷新历史记录用）。
 *
 * 不放：
 *   - `/api/v1/semantic/metrics` / `/dimensions`——挂在 assistant-service
 *     的 semantic 子树下，前端按消费侧聚合到 `features/semantic/`，避免
 *     analysis 缓存与语义元数据缓存同住一个 query namespace。
 *   - `/api/v1/conversations/*`——已属 conversation feature。
 *
 * SSE 流水线本体（`openSSEStream`）保留在 `shared/api/sse.ts`：它是通用
 * 基础设施（axios + ReadableStream + 事件 reframe），同时也被未来的
 * conversation 长轮询 / push 通道复用；不应该让 analysis feature 单独持有。
 *
 * 刻意不从 barrel 对外 re-export：唯一调用方就是本 feature 的
 * `model/store.ts`；其它代码要发起新分析请走 `useAnalysisStore.startAnalysis`，
 * SSE 生命周期与 reducer 才能保持一致。
 */

import { get } from '../../../shared/api/client';
import type { SSEConnection } from '../../../shared/types/sse';
import type {
  AnalysisRequest,
  AnalysisResponse,
} from '../../../shared/types/analysis';
import {
  openSSEStreamWithRetry,
  type RetryingSSECallbacks,
} from './sseRetry';

/**
 * Submit an analysis question via POST and consume the SSE stream.
 * Returns an `SSEConnection` handle so callers can abort mid-flight
 * (`store.cancelAnalysis()` calls `connection.abort()`).
 *
 * Goes through {@link openSSEStreamWithRetry} rather than the raw
 * {@link openSSEStream} primitive so pre-stream network / UPSTREAM
 * jitter gets auto-recovered per the policy in
 * ``features/analysis/model/sseErrorPolicy.ts``. Callers that want
 * finer control (e.g. a "Reconnecting (1/3)…" indicator) should wire
 * the retry-aware callbacks {@link RetryingSSECallbacks#onRetrying} /
 * {@link RetryingSSECallbacks#onApiError} alongside the usual
 * ``onEvent`` / ``onComplete``.
 */
export function submitAnalysis(
  request: AnalysisRequest,
  callbacks: RetryingSSECallbacks,
): SSEConnection {
  return openSSEStreamWithRetry('/api/v1/analysis', request, callbacks);
}

/** Get a completed analysis result by session ID. */
export function getAnalysisResult(sessionId: string): Promise<AnalysisResponse> {
  return get<AnalysisResponse>(`/api/v1/analysis/${sessionId}`);
}
