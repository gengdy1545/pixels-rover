/**
 * Conversation thread + session history shapes served by `assistant-service`.
 *
 * owning-service: assistant-service
 * source-of-truth: services/assistant-service/openapi.json#/components/schemas/
 *   — ConversationThread / ConversationHistoryItem / ... (generated from the
 *     pydantic models in services/assistant-service/app/schemas/conversation.py).
 *
 * Hand-mirrored per frontend.md §4.6 "手写契约镜像文件的顶部元数据" rule;
 * any field addition needs a paired assistant-service OpenAPI change.
 */
import type { AnalysisPlan, AnalysisTask, PlanStep, SessionStatus } from './analysis';

export interface ConversationThread {
  threadId: string;
  title: string;
  backendId: string;
  schemaName?: string | null;
  modelProfile?: string | null;
  status: 'active' | 'archived';
  createdAt?: string | null;
  updatedAt?: string | null;
  lastActivityAt?: string | null;
}

export interface ConversationHistoryItem {
  sessionId: string;
  threadId: string;
  status: SessionStatus;
  question: string;
  task?: AnalysisTask | null;
  plan?: AnalysisPlan | null;
  stepResults: PlanStep[];
  summary?: string | null;
  warnings: string[];
  error?: string | null;
  stats: {
    stepsExecuted?: number | null;
    llmCallsMade?: number | null;
    sqlExecutions?: number | null;
    wallTimeMs?: number | null;
  };
  createdAt?: string | null;
  completedAt?: string | null;
}

export interface ConversationDetail {
  thread: ConversationThread;
  history: ConversationHistoryItem[];
}

export interface CreateConversationRequest {
  title?: string;
  backendId: string;
  schemaName?: string;
  modelProfile?: string;
}

export interface UpdateConversationRequest {
  title?: string;
  status?: 'active' | 'archived';
}

