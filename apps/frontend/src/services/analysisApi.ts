import api from './api';
import { refreshAccessToken } from './api';
import { createRequestId } from './requestId';
import { getCookie } from './cookie';
import type { ApiResponse } from '../types/api';
import type {
  AnalysisRequest,
  AnalysisResponse,
  BackendInfo,
  ColumnInfo,
  SSEEventType,
  SemanticDimension,
  SemanticMetric,
  TableInfo,
} from '../types/analysis';

export interface SSECallbacks {
  onEvent: (eventType: SSEEventType, data: unknown) => void;
  onError?: (error: Error) => void;
  onComplete?: () => void;
}

function requireData<T>(response: ApiResponse<T>, fallbackMessage: string): T {
  if (response.data === undefined) {
    throw new Error(response.message || fallbackMessage);
  }
  return response.data;
}

/**
 * Submit an analysis question via POST and consume the SSE stream.
 * Native EventSource only supports GET, so we use fetch + ReadableStream.
 * Cookies (access_token) are sent automatically via credentials: 'include'.
 */
export async function submitAnalysis(
  request: AnalysisRequest,
  callbacks: SSECallbacks,
): Promise<void> {
  const abortController = new AbortController();

  try {
    const sendAnalysisRequest = async () => fetch('/api/v1/analysis', {
      method: 'POST',
      credentials: 'include', // Send HttpOnly cookies automatically
      headers: {
        'Content-Type': 'application/json',
        'X-Request-Id': createRequestId(),
        ...(getCookie('XSRF-TOKEN') ? { 'X-XSRF-TOKEN': getCookie('XSRF-TOKEN')! } : {}),
      },
      body: JSON.stringify(request),
      signal: abortController.signal,
    });

    let response = await sendAnalysisRequest();

    if (response.status === 401) {
      await refreshAccessToken();
      response = await sendAnalysisRequest();
    }

    if (!response.ok) {
      let message = `HTTP ${response.status}: ${response.statusText}`;
      try {
        const errorPayload = (await response.json()) as ApiResponse;
        message = errorPayload.message || message;
      } catch {
        // Keep the default HTTP message when the body is not JSON.
      }
      throw new Error(message);
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
  const response = await api.get<ApiResponse<AnalysisResponse>>(`/api/v1/analysis/${sessionId}`);
  return requireData(response.data, 'Analysis result payload is empty');
}

/**
 * Get available semantic metrics.
 */
export async function getSemanticMetrics(): Promise<SemanticMetric[]> {
  const response = await api.get<ApiResponse<SemanticMetric[]>>('/api/v1/semantic/metrics');
  return requireData(response.data, 'Semantic metrics payload is empty');
}

/**
 * Get available semantic dimensions.
 */
export async function getSemanticDimensions(): Promise<SemanticDimension[]> {
  const response = await api.get<ApiResponse<SemanticDimension[]>>('/api/v1/semantic/dimensions');
  return requireData(response.data, 'Semantic dimensions payload is empty');
}

export async function getBackends(): Promise<BackendInfo[]> {
  const response = await api.get<ApiResponse<BackendInfo[]>>('/api/v1/backends');
  return requireData(response.data, 'Backend list payload is empty');
}

export async function getSchemas(backendId: string): Promise<string[]> {
  const response = await api.get<ApiResponse<{ schemas: string[] }>>(`/api/v1/backends/${backendId}/schemas`);
  return requireData(response.data, 'Schema list payload is empty').schemas;
}

export async function getTables(backendId: string, schema: string): Promise<TableInfo[]> {
  const response = await api.get<ApiResponse<{ tables: TableInfo[] }>>(
    `/api/v1/backends/${backendId}/schemas/${schema}/tables`,
  );
  return requireData(response.data, 'Table list payload is empty').tables;
}

export async function getColumns(backendId: string, schema: string, tableName: string): Promise<ColumnInfo[]> {
  const response = await api.get<ApiResponse<{ columns: ColumnInfo[] }>>(
    `/api/v1/backends/${backendId}/schemas/${schema}/tables/${tableName}/columns`,
  );
  return requireData(response.data, 'Column list payload is empty').columns;
}
