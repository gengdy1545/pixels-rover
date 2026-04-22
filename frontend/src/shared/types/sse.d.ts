import type {
  AnalysisTask,
  AnalysisPlan,
  AnalysisResponse,
  SSEStatusChangeData,
  SSEStepStartedData,
  SSEStepSqlData,
  SSEStepCompletedData,
  SSEStepFailedData,
  SSEErrorData,
} from './analysis';

// ════════════════════════════════════════
// SSE Event Map — maps event names to their typed payloads
// ════════════════════════════════════════

export interface SSEEventMap {
  status_change: SSEStatusChangeData;
  task_parsed: AnalysisTask;
  clarification: { question: string };
  plan_created: AnalysisPlan;
  step_started: SSEStepStartedData;
  step_sql: SSEStepSqlData;
  step_completed: SSEStepCompletedData;
  step_failed: SSEStepFailedData;
  summary_ready: { summary: string };
  analysis_done: AnalysisResponse;
  warning: { message: string };
  error: SSEErrorData;
}

export type SSEEventName = keyof SSEEventMap;

// ════════════════════════════════════════
// SSE Callbacks — type-safe event handler
// ════════════════════════════════════════

export interface SSECallbacks {
  /**
   * Called for each SSE event. The `data` parameter is typed according to the event name.
   */
  onEvent: <K extends SSEEventName>(eventType: K, data: SSEEventMap[K]) => void;
  /** Called when a non-recoverable error occurs. */
  onError?: (error: Error) => void;
  /** Called when the SSE stream ends normally. */
  onComplete?: () => void;
  /** Called when the connection is lost (network error). */
  onDisconnect?: (error: Error) => void;
}

// ════════════════════════════════════════
// SSE Connection handle — returned by the SSE client
// ════════════════════════════════════════

export interface SSEConnection {
  /** Abort the SSE stream (user cancellation). */
  abort: () => void;
  /** Whether the connection has been aborted by the user. */
  readonly aborted: boolean;
}
