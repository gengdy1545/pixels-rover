/**
 * Analysis-pipeline shapes served by `assistant-service`:
 *   • task-layer payloads (AnalysisTask, TimeRange, FilterCondition)
 *   • plan-layer payloads (AnalysisPlan, PlanStep)
 *   • session / response envelopes (AnalysisResponse, SessionStatus, ...)
 *   • SSE event payloads (SSEStatusChangeData, SSEStepCompletedData, ...).
 *
 * owning-service: assistant-service
 * source-of-truth: services/assistant-service/openapi.json#/components/schemas/
 *   — AnalysisTask / AnalysisPlan / AnalysisResponse / SSEStatusChangeData /
 *     ... (generated from the pydantic models in
 *     services/assistant-service/app/schemas/analysis.py and app/schemas/sse.py).
 *
 * Hand-mirrored per frontend.md §4.6 "手写契约镜像文件的顶部元数据" rule;
 * any field addition needs a paired assistant-service OpenAPI change so the
 * long-term plan (auto-generate this file) keeps working.
 */

// ════════════════════════════════════════
// Task Layer
// ════════════════════════════════════════

export interface TimeRange {
  start?: string | null;
  end?: string | null;
  preset?: string | null;
  description?: string;
}

export interface FilterCondition {
  dimension: string;
  operator: string;
  value?: string | string[] | null;
}

export interface AnalysisTask {
  task_type: 'query' | 'compare' | 'diagnose';
  raw_input: string;
  target_metrics: string[];
  filters: FilterCondition[];
  time_range?: TimeRange | null;
  comparison_baseline?: TimeRange | null;
  analysis_dimensions: string[];
  confidence: number;
  needs_clarification: boolean;
  clarification_question?: string | null;
}

// ════════════════════════════════════════
// Plan Layer
// ════════════════════════════════════════

export interface StepParams {
  purpose?: string;
  metrics?: string[] | null;
  filters?: FilterCondition[] | null;
  time_range?: TimeRange | null;
  group_by?: string[] | null;
  schema_name?: string | null;
  backend_id?: string | null;
}

export interface StepResult {
  sql?: string | null;
  columns: string[];
  rows: unknown[][];
  row_count: number;
  execution_time_ms: number;
  summary?: string | null;
}

export type StepStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped';

export interface PlanStep {
  step_id: string;
  action: 'generate_and_execute_sql' | 'summarize_results';
  description: string;
  params: StepParams;
  status: StepStatus;
  result?: StepResult | null;
  error?: string | null;
  duration_ms?: number | null;
}

export interface AnalysisPlan {
  steps: PlanStep[];
  explanation: string;
}

// ════════════════════════════════════════
// Response Layer
// ════════════════════════════════════════

export type AnalysisStatus =
  | 'completed'
  | 'partial'
  | 'failed'
  | 'clarification_needed';

export interface AnalysisResponse {
  session_id: string;
  thread_id?: string | null;
  status: AnalysisStatus;
  task: AnalysisTask;
  plan?: AnalysisPlan | null;
  step_results: PlanStep[];
  summary?: string | null;
  warnings: string[];
  error?: string | null;
}

// ════════════════════════════════════════
// SSE Events
// ════════════════════════════════════════

export type SSEEventType =
  | 'status_change'
  | 'task_parsed'
  | 'clarification'
  | 'plan_created'
  | 'step_started'
  | 'step_sql'
  | 'step_completed'
  | 'step_failed'
  | 'summary_ready'
  | 'analysis_done'
  | 'warning'
  | 'error';

export interface SSEStatusChangeData {
  status: string;
  session_id?: string;
  thread_id?: string;
  threadId?: string;
}

export interface SSEStepStartedData {
  step_id: string;
  description: string;
}

export interface SSEStepSqlData {
  step_id: string;
  sql: string;
}

export interface SSEStepCompletedData {
  step_id: string;
  row_count: number;
}

export interface SSEStepFailedData {
  step_id: string;
  error: string;
}

export interface SSEErrorData {
  code: string;
  message: string;
}

// ════════════════════════════════════════
// Backend / Metadata
// ════════════════════════════════════════

export interface BackendInfo {
  backend_id: string;
  backend_type: string;
  capabilities: string[];
}

export interface TableInfo {
  name: string;
  schema_name: string;
  row_count?: number | null;
}

export interface ColumnInfo {
  name: string;
  data_type: string;
  is_nullable: boolean;
}

// ════════════════════════════════════════
// Semantic Layer
// ════════════════════════════════════════

export interface SemanticMetric {
  id: number;
  name: string;
  display_name?: string;
  description?: string;
  calculation: string;
  source_table: string;
  source_schema: string;
  backend_id: string;
  data_type?: string;
}

export interface SemanticDimension {
  id: number;
  name: string;
  display_name?: string;
  source_column: string;
  source_table: string;
  source_schema: string;
  backend_id: string;
}

// ════════════════════════════════════════
// Request
// ════════════════════════════════════════

export interface AnalysisRequest {
  question: string;
  threadId: string;
  max_steps?: number;
  max_llm_calls?: number;
  max_wall_time_sec?: number;
  max_sql_executions?: number;
}

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
  | 'cancelled'
  | 'clarification_needed';
