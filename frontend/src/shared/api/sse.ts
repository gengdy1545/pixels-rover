import type { ApiErrorResponse } from '../types/common';
import type { SSECallbacks, SSEConnection, SSEEventName, SSEEventMap } from '../types/sse';
import { buildCommonHeaders, refreshAccessToken } from './client';
import { apiErrorFromEnvelope } from './apiError';
import type { ApiError } from './apiError';

// ════════════════════════════════════════
// SSE Stream Client
// ════════════════════════════════════════

/**
 * Open a POST-based SSE stream.
 *
 * - Injects CSRF token and X-Request-Id via `buildCommonHeaders()`.
 * - Handles 401 by refreshing the token and retrying once.
 * - Returns an `SSEConnection` handle for user cancellation.
 * - Calls `onDisconnect` on network errors (distinguishable from business errors).
 */
export function openSSEStream(
  url: string,
  body: unknown,
  callbacks: SSECallbacks,
): SSEConnection {
  const abortController = new AbortController();
  let aborted = false;

  const connection: SSEConnection = {
    abort: () => {
      aborted = true;
      abortController.abort();
    },
    get aborted() {
      return aborted;
    },
  };

  // Fire-and-forget the async work; errors are routed to callbacks.
  consumeStream(url, body, abortController, callbacks).catch(() => {
    // All errors are already handled inside consumeStream.
  });

  return connection;
}

// ════════════════════════════════════════
// Internal helpers
// ════════════════════════════════════════

async function consumeStream(
  url: string,
  body: unknown,
  abortController: AbortController,
  callbacks: SSECallbacks,
): Promise<void> {
  try {
    // Capture the X-Request-Id once per logical SSE open (frontend.md §4.6
    // request-id reuse rule). The 401→refresh→retry path below MUST send the
    // SAME id as the initial attempt so backend logs can stitch the two
    // underlying fetches together. We do this by pulling the id out of the
    // first header bundle and threading it into the retry via the optional
    // ``existingRequestId`` parameter on ``buildCommonHeaders``.
    let streamRequestId: string | null = null;
    const buildRequest = () => {
      const commonHeaders = buildCommonHeaders(streamRequestId);
      streamRequestId = commonHeaders['X-Request-Id'];
      return new Request(url, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          ...commonHeaders,
        },
        body: JSON.stringify(body),
        signal: abortController.signal,
      });
    };

    let response = await fetch(buildRequest());

    // Handle 401: refresh token and retry once (reuses ``streamRequestId``
    // that was stashed by the first ``buildRequest()`` call).
    if (response.status === 401) {
      await refreshAccessToken();
      response = await fetch(buildRequest());
    }

    if (!response.ok) {
      const error = await extractHttpError(response);
      callbacks.onError?.(error);
      return;
    }

    const reader = response.body?.getReader();
    if (!reader) {
      callbacks.onError?.(new Error('Response body is not readable'));
      return;
    }

    await parseSSEStream(reader, callbacks);
    callbacks.onComplete?.();
  } catch (error) {
    if (abortController.signal.aborted) {
      // User-initiated cancellation — do not call onError.
      return;
    }

    // Network-level errors (e.g. connection lost, DNS failure)
    if (isNetworkError(error)) {
      callbacks.onDisconnect?.(error as Error);
    } else {
      callbacks.onError?.(error as Error);
    }
  }
}

/**
 * Parse an SSE text stream from a ReadableStream reader.
 * Handles multi-line `data:` fields and dispatches typed events.
 */
async function parseSSEStream(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  callbacks: SSECallbacks,
): Promise<void> {
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
        dispatchEvent(currentEvent, currentData, callbacks);
        currentEvent = null;
        currentData = null;
      }
    }
  }
}

function dispatchEvent(
  eventName: string,
  rawData: string,
  callbacks: SSECallbacks,
): void {
  try {
    const parsed = JSON.parse(rawData);
    callbacks.onEvent(eventName as SSEEventName, parsed as SSEEventMap[SSEEventName]);
  } catch {
    // Non-JSON data — pass as-is wrapped in an object
    callbacks.onEvent(eventName as SSEEventName, rawData as unknown as SSEEventMap[SSEEventName]);
  }
}

/**
 * Materialize an ApiError from a failed SSE open. We preserve the same
 * ApiError contract the axios client uses, so page-level `catch (e)` blocks
 * can dispatch uniformly on `e.details.errorCode` / `e.details.category`
 * regardless of whether the failure came from a regular request or an SSE
 * stream open.
 */
async function extractHttpError(response: Response): Promise<ApiError> {
  const fallback = `HTTP ${response.status}: ${response.statusText}`;
  let body: Partial<ApiErrorResponse> | undefined;
  try {
    body = (await response.json()) as Partial<ApiErrorResponse>;
  } catch {
    // Non-JSON body -- leave body undefined; apiErrorFromEnvelope will
    // fall back to the HTTP reason phrase.
  }
  return apiErrorFromEnvelope(response.status, body, fallback);
}

/**
 * Distinguish network errors (connection lost, DNS failure, timeout)
 * from other runtime errors.
 */
function isNetworkError(error: unknown): boolean {
  if (error instanceof TypeError) {
    // fetch throws TypeError for network failures
    return true;
  }
  if (error instanceof DOMException && error.name === 'AbortError') {
    return false; // User cancellation, not a network error
  }
  return false;
}
