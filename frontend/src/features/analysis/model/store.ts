/**
 * analysis feature 的客户端 in-flight state（Stage 3 §10 PR-4 从
 * `stores/analysisStore.ts` 迁入；Stage 2 §12 已经先做过一轮职责收紧）。
 *
 * 收紧历史：旧版 store 同时承担了三种状态：
 *   1. SSE 驱动的 in-flight 分析状态（task / plan / steps / status /
 *      summary / warnings / error / isLoading / _connection）——由
 *      `startAnalysis` 打开 SSE 流，`handleSSEEvent` 在事件回调里推
 *      reducer；
 *   2. 单一场历史会话的只读回放（`restoreSession`）——从 conversation
 *      detail 的 history[0] 读出已完成分析数据，灌进 in-flight 形状
 *      以共用同一套渲染；
 *   3. 语义元数据缓存（`availableMetrics` + `loadMetrics`）——GET
 *      `/api/v1/semantic/metrics` 的纯服务端快照。
 *
 * 第 3 类 Stage 2 已迁到 TanStack Query（`features/semantic/`
 * `useSemanticMetricsQuery`）；这里只保留第 1 + 第 2 类——它们是**非 GET**
 * 的流式事件驱动 UI 状态，TanStack 处理不好、也不该强塞进去（TanStack
 * 的 query 是"幂等纯 GET"语义模型，SSE 事件流不是）。
 *
 * 注意：`_connection` 持有底下 SSE 客户端的 abort handle，是纯客户端副作
 * 用句柄，绝不能序列化或跨刷新持久化；任何把它搬进 TanStack 或 URL 的
 * 尝试都是误解。
 *
 * import 边界：`submitAnalysis` 来自同 feature 的 `services/analysisApi`，
 * 不再走 `shared/api` barrel——Stage 3 §10 PR-4 把 analysis endpoint
 * 收回 feature 私有，shared/api 只剩通用 HTTP / SSE 基础设施。
 */

import { create } from 'zustand';
import type {
  AnalysisTask,
  AnalysisPlan,
  PlanStep,
  AnalysisResponse,
  SessionStatus,
  SSEStatusChangeData,
  SSEStepStartedData,
  SSEStepSqlData,
  SSEStepCompletedData,
  SSEStepFailedData,
  SSEErrorData,
} from '../../../shared/types/analysis';
import type { SSEEventName, SSEConnection } from '../../../shared/types/sse';
import type { ConversationHistoryItem } from '../../../shared/types/conversation';
import { ApiError } from '../../../shared/api';
import { submitAnalysis } from '../services/analysisApi';
import { classifyThreadError } from '../../conversation';

/**
 * Client-side progress for pre-stream reconnect attempts driven by
 * {@link openSSEStreamWithRetry}. Non-null ONLY during the window
 * between a retryable failure and the next open attempt — the UI keys
 * off this to render a "Reconnecting (N/max)…" banner instead of the
 * normal "analyzing…" spinner.
 *
 * Not persisted; not serialized; purely a transient client effect.
 */
export interface ReconnectInfo {
  attempt: number;
  maxAttempts: number;
  delayMs: number;
  reason: 'network' | 'upstream';
}

interface AnalysisState {
  threadId: string | null;
  sessionId: string | null;
  status: SessionStatus;
  task: AnalysisTask | null;
  plan: AnalysisPlan | null;
  steps: PlanStep[];
  summary: string | null;
  warnings: string[];
  error: string | null;
  isLoading: boolean;
  /** Pre-stream reconnect progress; null except during a backoff window. */
  reconnectInfo: ReconnectInfo | null;
  /** Active SSE connection handle for user cancellation. */
  _connection: SSEConnection | null;

  startAnalysis: (question: string, threadId: string) => void;
  cancelAnalysis: () => void;
  handleSSEEvent: (eventType: SSEEventName, data: unknown) => void;
  prepareThread: (threadId: string | null) => void;
  restoreSession: (session: ConversationHistoryItem | null, threadId: string | null) => void;
  reset: () => void;
}

const initialState = {
  threadId: null,
  sessionId: null,
  status: 'idle' as SessionStatus,
  task: null,
  plan: null,
  steps: [],
  summary: null,
  warnings: [],
  error: null,
  isLoading: false,
  reconnectInfo: null as ReconnectInfo | null,
  _connection: null as SSEConnection | null,
};

export const useAnalysisStore = create<AnalysisState>((set, get) => ({
  ...initialState,

  startAnalysis: (question: string, threadId: string) => {
    get()._connection?.abort();

    set({
      ...initialState,
      threadId,
      isLoading: true,
      status: 'received',
    });

    const connection = submitAnalysis(
      { question, threadId },
      {
        onEvent: (eventType, data) => {
          // Clearing reconnectInfo here (rather than in onRetrying's
          // reciprocal "connected" hook, which doesn't exist) is how we
          // close the "Reconnecting (1/3)…" banner: the first event to
          // arrive after a successful re-open wipes the progress state.
          if (get().reconnectInfo) {
            set({ reconnectInfo: null });
          }
          get().handleSSEEvent(eventType, data as unknown);
        },
        onRetrying: (info) => {
          set({ reconnectInfo: info });
        },
        onApiError: (apiError) => {
          // Business-error dispatch (backend.md §6.3.2 step-1). Reuse
          // the conversation feature's classifier for thread / session
          // codes — it already knows the right copy for the overlap set
          // (``ANALYSIS_THREAD_NOT_FOUND`` / ``ANALYSIS_SESSION_NOT_FOUND``
          // / ``ANALYSIS_THREAD_ARCHIVED``). For analysis-specific codes
          // not in its table the decision falls through to ``unknown``
          // with ``apiError.message`` preserved, which is acceptable
          // fidelity until an analysis-specific classifier exists.
          const decision = classifyThreadError(apiError);
          set({
            error: decision?.message || apiError.message,
            status: 'failed',
            isLoading: false,
            reconnectInfo: null,
            _connection: null,
          });
        },
        onError: (error) => {
          // Non-ApiError failures (shouldn't normally happen — the
          // retry wrapper routes ApiErrors to ``onApiError``). Keep as
          // a safety net so unexpected throws don't leave the UI stuck
          // spinning.
          const apiMessage =
            error instanceof ApiError ? error.message : error.message;
          set({
            error: apiMessage,
            status: 'failed',
            isLoading: false,
            reconnectInfo: null,
            _connection: null,
          });
        },
        onComplete: () => {
          set({ isLoading: false, reconnectInfo: null, _connection: null });
        },
        onDisconnect: (error) => {
          // Reached here only after the retry wrapper has exhausted its
          // pre-stream budget OR the stream dropped mid-way (which we
          // intentionally don't auto-retry — see sseErrorPolicy.ts for
          // why). The wrapper already composed a user-facing message.
          set({
            error: error.message,
            status: 'failed',
            isLoading: false,
            reconnectInfo: null,
            _connection: null,
          });
        },
      },
    );

    set({ _connection: connection });
  },

  cancelAnalysis: () => {
    get()._connection?.abort();
    set({
      isLoading: false,
      status: 'idle',
      reconnectInfo: null,
      _connection: null,
    });
  },

  handleSSEEvent: (eventType: SSEEventName, data: unknown) => {
    const d = data as Record<string, unknown>;

    switch (eventType) {
      case 'status_change': {
        const payload = d as unknown as SSEStatusChangeData;
        set({
          status: payload.status as SessionStatus,
          threadId: payload.threadId || payload.thread_id || get().threadId,
          sessionId: payload.session_id || get().sessionId,
        });
        break;
      }
      case 'task_parsed':
        set({ task: d as unknown as AnalysisTask });
        break;
      case 'clarification':
        set({
          status: 'clarification_needed',
          error: (d as { question?: string }).question || '需要更多信息',
          isLoading: false,
        });
        break;
      case 'plan_created': {
        const plan = d as unknown as AnalysisPlan;
        set({ plan, steps: plan.steps || [] });
        break;
      }
      case 'step_started': {
        const payload = d as unknown as SSEStepStartedData;
        set({
          steps: get().steps.map((s) =>
            s.step_id === payload.step_id ? { ...s, status: 'running' as const } : s,
          ),
        });
        break;
      }
      case 'step_sql': {
        const payload = d as unknown as SSEStepSqlData;
        set({
          steps: get().steps.map((s) => {
            if (s.step_id !== payload.step_id) return s;
            // `s.result` may be null (no backend result yet) or partially
            // populated (an earlier step_sql landed before step_completed).
            // Merge in the incoming SQL while backfilling every required
            // StepResult field from prior state or a deterministic zero
            // value so the resulting object satisfies `StepResult` (no
            // `undefined` leaking into fields typed as `T | null`).
            const prev = s.result ?? null;
            return {
              ...s,
              result: {
                sql: payload.sql,
                columns: prev?.columns ?? [],
                rows: prev?.rows ?? [],
                row_count: prev?.row_count ?? 0,
                execution_time_ms: prev?.execution_time_ms ?? 0,
                summary: prev?.summary ?? null,
              },
            };
          }),
        });
        break;
      }
      case 'step_completed': {
        const payload = d as unknown as SSEStepCompletedData;
        set({
          steps: get().steps.map((s) =>
            s.step_id === payload.step_id
              ? { ...s, status: 'completed' as const }
              : s,
          ),
        });
        break;
      }
      case 'step_failed': {
        const payload = d as unknown as SSEStepFailedData;
        set({
          steps: get().steps.map((s) =>
            s.step_id === payload.step_id
              ? { ...s, status: 'failed' as const, error: payload.error }
              : s,
          ),
        });
        break;
      }
      case 'summary_ready':
        set({ summary: (d as { summary: string }).summary });
        break;
      case 'analysis_done': {
        const resp = d as unknown as AnalysisResponse;
        set({
          status: resp.status === 'completed' ? 'completed' : resp.status === 'partial' ? 'partial' : 'failed',
          threadId: resp.thread_id || get().threadId,
          summary: resp.summary || get().summary,
          warnings: resp.warnings || get().warnings,
          steps: resp.step_results || get().steps,
          isLoading: false,
        });
        break;
      }
      case 'warning':
        set({ warnings: [...get().warnings, (d as { message: string }).message] });
        break;
      case 'error': {
        const payload = d as unknown as SSEErrorData;
        set({ error: payload.message, status: 'failed', isLoading: false });
        break;
      }
    }
  },

  prepareThread: (threadId: string | null) => {
    set({
      ...initialState,
      threadId,
    });
  },

  restoreSession: (session: ConversationHistoryItem | null, threadId: string | null) => {
    if (!session) {
      get().prepareThread(threadId);
      return;
    }

    set({
      ...initialState,
      threadId: session.threadId,
      sessionId: session.sessionId,
      status: session.status,
      task: session.task || null,
      plan: session.plan || null,
      steps: session.stepResults || [],
      summary: session.summary || null,
      warnings: session.warnings || [],
      error: session.error || null,
    });
  },

  reset: () => {
    set({ ...initialState, threadId: get().threadId });
  },
}));
