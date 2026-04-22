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

