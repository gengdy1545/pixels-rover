import api from './api';
import type {
  AnalysisRequest,
  SSEEventType,
  SemanticMetric,
  SemanticDimension,
} from '../types/analysis';

export interface SSECallbacks {
  onEvent: (eventType: SSEEventType, data: unknown) => void;
  onError?: (error: Error) => void;
  onComplete?: () => void;
}

/**
 * Submit an analysis question via POST and consume the SSE stream.
 * Native EventSource only supports GET, so we use fetch + ReadableStream.
 */
export async function submitAnalysis(
  request: AnalysisRequest,
  callbacks: SSECallbacks,
): Promise<void> {
  const abortController = new AbortController();

  try {
    const response = await fetch('/api/v1/analysis', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${localStorage.getItem('accessToken') || ''}`,
      },
      body: JSON.stringify(request),
      signal: abortController.signal,
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const reader = response.body?.getReader();
    if (!reader) throw new Error('Response body is not readable');

    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      let currentEvent: string | null = null;
      let currentData: string | null = null;

      for (const line of lines) {
        if (line.startsWith('event: ')) {
          currentEvent = line.slice(7).trim();
        } else if (line.startsWith('data: ')) {
          currentData = line.slice(6);
        } else if (line === '' && currentEvent && currentData) {
          try {
            const parsed = JSON.parse(currentData);
            callbacks.onEvent(currentEvent as SSEEventType, parsed);
          } catch {
            // non-JSON data, pass as string
            callbacks.onEvent(currentEvent as SSEEventType, currentData);
          }
          currentEvent = null;
          currentData = null;
        }
      }
    }

    callbacks.onComplete?.();
  } catch (error) {
    if ((error as Error).name !== 'AbortError') {
      callbacks.onError?.(error as Error);
    }
  }
}

/**
 * Get a completed analysis result by session ID.
 */
export async function getAnalysisResult(sessionId: string) {
  const response = await api.get(`/api/v1/analysis/${sessionId}`);
  return response.data;
}

/**
 * Get available semantic metrics.
 */
export async function getSemanticMetrics(): Promise<SemanticMetric[]> {
  const response = await api.get('/api/v1/semantic/metrics');
  return response.data;
}

/**
 * Get available semantic dimensions.
 */
export async function getSemanticDimensions(): Promise<SemanticDimension[]> {
  const response = await api.get('/api/v1/semantic/dimensions');
  return response.data;
}
