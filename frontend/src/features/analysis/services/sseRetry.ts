/**
 * Retry-aware wrapper around the pure {@link openSSEStream} primitive.
 *
 * Purpose: apply the {@link classifySseError} decision tree around a
 * single logical "submit analysis" attempt so callers (``store.ts``)
 * observe one stable lifecycle:
 *
 *   startAnalysis → [optional onRetrying × N] → onEvent×… then one of
 *                   onApiError / onDisconnect(final) / onComplete
 *
 * Contract summary (see ``sseErrorPolicy.ts`` module docstring for the
 * full rationale):
 *
 *   - Pre-stream network errors (TypeError from fetch) are retried up
 *     to {@link MAX_PRE_STREAM_NETWORK_RETRIES} times with exponential
 *     backoff; ``onRetrying`` fires once per scheduled retry.
 *   - Pre-stream HTTP failure with ``category=UPSTREAM`` gets exactly
 *     ONE extra short-delay retry.
 *   - Any other ApiError (business errors like
 *     ``ANALYSIS_THREAD_NOT_FOUND``) surfaces via the new
 *     ``onApiError`` callback WITHOUT retrying.
 *   - Mid-stream disconnects (at least one event already observed) never
 *     retry — the backend has no reattach endpoint and retrying would
 *     double-bill the LLM call. Surfaced as a final ``onDisconnect``
 *     with an explanatory message.
 *   - User aborts are silent at every layer — the wrapper checks
 *     ``connection.aborted`` before every state transition and exits
 *     quietly if the caller cancelled us mid-backoff.
 *
 * Exposes {@link SSEConnection} so the caller's ``abort()`` still works
 * during the in-between-retries sleep window.
 */

import type {
  SSECallbacks,
  SSEConnection,
  SSEEventName,
  SSEEventMap,
} from '../../../shared/types/sse';
import { openSSEStream } from '../../../shared/api/sse';
import { ApiError } from '../../../shared/api';
import {
  classifySseError,
  MAX_PRE_STREAM_NETWORK_RETRIES,
  type SseRetryDecision,
} from '../model/sseErrorPolicy';

/**
 * Caller-visible callbacks for {@link openSSEStreamWithRetry}. Extends
 * the base {@link SSECallbacks} with two retry-aware signals:
 *
 *   - ``onRetrying``: fires right before each scheduled pre-stream
 *     retry, so the UI can show "Reconnecting (N/max)...".
 *   - ``onApiError``: fires when the open failed with a concrete
 *     backend {@link ApiError} (business error, or a
 *     retries-exhausted UPSTREAM). Separate from the base
 *     ``onError(Error)`` so the store can dispatch on
 *     ``errorCode`` / ``category`` without any ``instanceof`` gymnastics.
 *
 * We keep ``onError`` / ``onDisconnect`` for the base cases (non-ApiError
 * Errors and final network-retries-exhausted disconnects), matching
 * the existing mental model.
 */
export interface RetryingSSECallbacks extends SSECallbacks {
  onRetrying?: (info: {
    attempt: number;
    maxAttempts: number;
    delayMs: number;
    reason: 'network' | 'upstream';
  }) => void;
  onApiError?: (error: ApiError) => void;
}

/**
 * Open an SSE stream with pre-stream retry semantics.
 *
 * Returns an {@link SSEConnection} that bundles the abort handle for
 * *whichever* underlying stream is currently live (rotates across
 * retries). ``connection.aborted`` flips on first ``abort()`` call and
 * the wrapper short-circuits any future retries.
 */
export function openSSEStreamWithRetry(
  url: string,
  body: unknown,
  callbacks: RetryingSSECallbacks,
): SSEConnection {
  let aborted = false;
  let inner: SSEConnection | null = null;
  let streamStarted = false;
  let priorPreStreamAttempts = 0;
  let upstreamRetryUsed = false;

  const connection: SSEConnection = {
    abort: () => {
      aborted = true;
      inner?.abort();
    },
    get aborted() {
      return aborted;
    },
  };

  const runAttempt = () => {
    if (aborted) return;

    // Wrap onEvent to observe the "stream started" transition exactly
    // once, then pass through transparently.
    const wrappedCallbacks: SSECallbacks = {
      onEvent: <K extends SSEEventName>(
        eventType: K,
        data: SSEEventMap[K],
      ) => {
        streamStarted = true;
        callbacks.onEvent(eventType, data);
      },
      onComplete: () => {
        callbacks.onComplete?.();
      },
      onError: (err) => {
        handleFailure(err);
      },
      onDisconnect: (err) => {
        handleFailure(err);
      },
    };

    inner = openSSEStream(url, body, wrappedCallbacks);
  };

  const handleFailure = (err: Error) => {
    if (aborted) return;

    const decision: SseRetryDecision = classifySseError(err, {
      streamStarted,
      priorPreStreamAttempts,
      upstreamRetryUsed,
      abortedByUser: aborted,
    });

    dispatch(decision);
  };

  const dispatch = (decision: SseRetryDecision) => {
    switch (decision.kind) {
      case 'cancelled':
        return;
      case 'businessError':
        if (callbacks.onApiError) {
          callbacks.onApiError(decision.apiError);
        } else {
          // Fallback so we never swallow the failure if a caller forgot
          // to wire the new hook.
          callbacks.onError?.(decision.apiError);
        }
        return;
      case 'giveUpPreStream': {
        // "give up" after network/UPSTREAM exhaustion maps to the
        // existing onDisconnect mental model — "we tried to open the
        // stream and couldn't, user should click retry". We drop the
        // inner error from the Error chain (project's TS ``lib`` target
        // predates standardized ``Error.cause``); the wrapper's message
        // already captures the user-facing recovery hint, and the
        // original Error gets logged at the call site via the classify
        // decision DevTools trace if debugging is needed.
        callbacks.onDisconnect?.(new Error(decision.message));
        return;
      }
      case 'disconnectMidStream': {
        callbacks.onDisconnect?.(new Error(decision.message));
        return;
      }
      case 'retryPreStream': {
        priorPreStreamAttempts = decision.attempt;
        if (decision.reason === 'upstream') {
          upstreamRetryUsed = true;
        }
        callbacks.onRetrying?.({
          attempt: decision.attempt,
          maxAttempts: decision.maxAttempts,
          delayMs: decision.delayMs,
          reason: decision.reason,
        });
        // Schedule with setTimeout so aborting during the sleep still
        // short-circuits cleanly.
        setTimeout(() => {
          if (aborted) return;
          runAttempt();
        }, decision.delayMs);
        return;
      }
    }
  };

  runAttempt();
  return connection;
}

export { MAX_PRE_STREAM_NETWORK_RETRIES };
