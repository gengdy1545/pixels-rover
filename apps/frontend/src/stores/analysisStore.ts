import { create } from 'zustand';
import type {
  AnalysisTask,
  AnalysisPlan,
  PlanStep,
  AnalysisResponse,
  SSEStatusChangeData,
  SSEStepStartedData,
  SSEStepSqlData,
  SSEStepCompletedData,
  SSEStepFailedData,
  SSEErrorData,
  SemanticMetric,
} from '../types/analysis';
import type { SSEEventName, SSEConnection } from '../types/sse';
import { submitAnalysis, getSemanticMetrics } from '../api';
import { useAuthStore } from './authStore';

export type SessionStatus =
  | 'idle'
  | 'received'
  | 'understanding'
  | 'resolving'
  | 'planning'
  | 'executing'
  | 'summarizing'
  | 'completed'
  | 'partial'
  | 'failed'
  | 'clarification_needed';

interface AnalysisState {
  sessionId: string | null;
  status: SessionStatus;
  task: AnalysisTask | null;
  plan: AnalysisPlan | null;
  steps: PlanStep[];
  summary: string | null;
  warnings: string[];
  error: string | null;
  isLoading: boolean;
  availableMetrics: SemanticMetric[];
  /** Active SSE connection handle for user cancellation. */
  _connection: SSEConnection | null;

  startAnalysis: (question: string) => void;
  cancelAnalysis: () => void;
  handleSSEEvent: (eventType: SSEEventName, data: unknown) => void;
  reset: () => void;
  loadMetrics: () => Promise<void>;
}

const initialState = {
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
  availableMetrics: [],

  startAnalysis: (question: string) => {
    // Cancel any existing connection
    get()._connection?.abort();

    set({ ...initialState, isLoading: true, status: 'received', availableMetrics: get().availableMetrics });

    const user = useAuthStore.getState().user;
    const userId = user?.id || 1;

    const connection = submitAnalysis(
      { question, user_id: userId },
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

  reset: () => {
    set({ ...initialState, availableMetrics: get().availableMetrics });
  },

  loadMetrics: async () => {
    try {
      const metrics = await getSemanticMetrics();
      set({ availableMetrics: metrics });
    } catch {
      // silently fail
    }
  },
}));
