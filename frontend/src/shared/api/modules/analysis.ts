import { get } from '../client';
import { openSSEStream } from '../sse';
import type { SSECallbacks, SSEConnection } from '../../types/sse';
import type {
  AnalysisRequest,
  AnalysisResponse,
  SemanticMetric,
  SemanticDimension,
} from '../../types/analysis';

/**
 * Submit an analysis question via POST and consume the SSE stream.
 * Returns an SSEConnection handle for user cancellation.
 */
export function submitAnalysis(
  request: AnalysisRequest,
  callbacks: SSECallbacks,
): SSEConnection {
  return openSSEStream('/api/v1/analysis', request, callbacks);
}

/**
 * Get a completed analysis result by session ID.
 */
export function getAnalysisResult(sessionId: string): Promise<AnalysisResponse> {
  return get<AnalysisResponse>(`/api/v1/analysis/${sessionId}`);
}

/**
 * Get available semantic metrics.
 */
export function getSemanticMetrics(): Promise<SemanticMetric[]> {
  return get<SemanticMetric[]>('/api/v1/semantic/metrics');
}

/**
 * Get available semantic dimensions.
 */
export function getSemanticDimensions(): Promise<SemanticDimension[]> {
  return get<SemanticDimension[]>('/api/v1/semantic/dimensions');
}
