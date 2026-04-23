/**
 * analysis feature 的客户端 in-flight state（Stage 2 §12 拆分后）。
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
 * 第 3 类 Stage 2 迁到 TanStack Query（`features/semantic/`
 * `useSemanticMetricsQuery`）；这里只保留第 1 + 第 2 类——它们是**非 GET**
 * 的流式事件驱动 UI 状态，TanStack 处理不好、也不该强塞进去（TanStack
 * 的 query 是"幂等纯 GET"语义模型，SSE 事件流不是）。
 *
 * 注意：`_connection` 持有底下 SSE 客户端的 abort handle，是纯客户端副作
 * 用句柄，绝不能序列化或跨刷新持久化；任何把它搬进 TanStack 或 URL 的
 * 尝试都是误解。
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
} from '../shared/types/analysis';
import type { SSEEventName, SSEConnection } from '../shared/types/sse';
import type { ConversationHistoryItem } from '../shared/types/conversation';
import { submitAnalysis } from '../shared/api';

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
          get().handleSSEEvent(eventType, data as unknown);
        },
        onError: (error) => {
          set({ error: error.message, status: 'failed', isLoading: false, _connection: null });
        },
        onComplete: () => {
          set({ isLoading: false, _connection: null });
        },
        onDisconnect: (error) => {
          set({
            error: `Connection lost: ${error.message}. Please retry your analysis.`,
            status: 'failed',
            isLoading: false,
            _connection: null,
          });
        },
      },
    );

    set({ _connection: connection });
  },

  cancelAnalysis: () => {
    get()._connection?.abort();
    set({ isLoading: false, status: 'idle', _connection: null });
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
          steps: get().steps.map((s) =>
            s.step_id === payload.step_id
              ? { ...s, result: { ...s.result, sql: payload.sql, columns: s.result?.columns || [], rows: s.result?.rows || [], row_count: s.result?.row_count || 0, execution_time_ms: s.result?.execution_time_ms || 0 } }
              : s,
          ),
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
