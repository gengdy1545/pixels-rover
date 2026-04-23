/**
 * Pure classification of SSE-open failures into concrete recovery
 * decisions (backend.md §6.3.2 step-1, applied to the streaming surface).
 *
 * Why this lives in ``features/analysis/model/`` and not ``shared/api``:
 * the recovery policy bakes in **assistant-service-specific** operational
 * reality that does NOT belong in the reusable SSE primitive:
 *
 *   - ``POST /api/v1/analysis`` creates a **new** session on each call;
 *     the backend has no "reattach to in-flight session" endpoint. So
 *     naive mid-stream reconnect would duplicate LLM work + billing.
 *     We therefore only auto-retry **pre-stream** failures (where no
 *     session was ever assigned to the client); once even a single event
 *     has arrived, we escalate to the user rather than re-fire the POST.
 *   - ``UPSTREAM`` (§6.7 C3 degradation-mode) is worth exactly one
 *     short-delay retry at the open step — if the LLM / DB / backend is
 *     momentarily flaky, one retry is cheap and often papers over jitter;
 *     more than one feels like thrashing and hides real outages from the
 *     user.
 *   - Business-level errors (``ANALYSIS_THREAD_NOT_FOUND`` etc.) must
 *     never retry — the thread simply is not going to materialize from
 *     thin air, and retrying would make the error toast dance on screen.
 *
 * The ``SSECallbacks`` shape in ``shared/types/sse.d.ts`` already does
 * "routing by failure type" via separate ``onError`` (HTTP / ApiError)
 * vs ``onDisconnect`` (network TypeError). This module goes one level
 * finer: "given that routing, plus where we are in the stream lifecycle,
 * plus how many times we've already retried, what should the wrapper do
 * next?"
 *
 * Pure function, zero side effects — tests in
 * ``sseErrorPolicy.test.ts``.
 */

import { ApiError } from '../../../shared/api';

/** Maximum pre-stream network-error retries (1s, 2s, 4s → ~7s ceiling). */
export const MAX_PRE_STREAM_NETWORK_RETRIES = 3;
/** Base for exponential backoff on pre-stream network retries (ms). */
export const PRE_STREAM_BACKOFF_BASE_MS = 1000;
/** Fixed short delay for the one-shot UPSTREAM retry (ms). */
export const UPSTREAM_RETRY_DELAY_MS = 1500;

/** Outcome classifications. See module docstring for why each one exists. */
export type SseRetryDecision =
  /**
   * Caller aborted the connection via {@link SSEConnection.abort}. The
   * wrapper must stay silent — no retries, no toasts, no state changes
   * beyond winding down ``_connection``.
   */
  | { kind: 'cancelled' }
  /**
   * The POST hasn't emitted any SSE event yet AND the failure looks
   * retryable (network error, or HTTP failure with category=UPSTREAM
   * under the pre-stream retry budget). Wrapper should wait ``delayMs``
   * and re-open.
   */
  | {
      kind: 'retryPreStream';
      attempt: number;
      maxAttempts: number;
      delayMs: number;
      /** Why we think retrying is safe — used by logs / DevTools. */
      reason: 'network' | 'upstream';
    }
  /**
   * Pre-stream failure that the policy will no longer retry: either
   * ``attempt`` reached ``MAX_PRE_STREAM_NETWORK_RETRIES`` / the single
   * UPSTREAM shot was already spent, or the error isn't retryable at all.
   * Wrapper must fire the final ``onDisconnect`` / ``onError`` so the UI
   * can expose a "retry" button.
   */
  | {
      kind: 'giveUpPreStream';
      message: string;
      error: Error;
    }
  /**
   * Backend returned a concrete business error (4xx with
   * ``errorCode`` / ``category`` set, category ≠ UPSTREAM). Never retry —
   * ``ANALYSIS_THREAD_NOT_FOUND`` does not become a thread if you ask
   * again. Wrapper surfaces the ApiError so the store / UI can dispatch
   * per-code.
   */
  | { kind: 'businessError'; apiError: ApiError }
  /**
   * The stream HAD started (at least one SSE event observed) and then
   * disconnected. Because the backend has no reattach endpoint, we
   * cannot transparently recover; surface an explanatory message so the
   * UI can point the user at conversation history (where the partial
   * result will land once the backend session finishes on its own).
   */
  | {
      kind: 'disconnectMidStream';
      message: string;
      error: Error;
    };

export interface SseClassifyContext {
  /**
   * True once the wrapper has observed at least one ``onEvent`` callback
   * from the underlying ``openSSEStream``. Acts as the "stream started"
   * proxy — see the module docstring.
   */
  streamStarted: boolean;
  /** How many pre-stream retries have already happened (0 on first try). */
  priorPreStreamAttempts: number;
  /**
   * Whether the one-shot UPSTREAM retry budget has already been spent on
   * this open. Separated from the network-retry counter because UPSTREAM
   * gets exactly one, regardless of whether network retries were also
   * exercised earlier.
   */
  upstreamRetryUsed: boolean;
}

/**
 * Classify an error from either ``onError`` (ApiError / unexpected
 * Error) or ``onDisconnect`` (network TypeError) into an actionable
 * {@link SseRetryDecision}.
 *
 * ``abortedByUser`` short-circuits ahead of everything — if the caller
 * aborted, we don't care what flavour of error bubbled through; do
 * nothing.
 */
export function classifySseError(
  error: unknown,
  ctx: SseClassifyContext & { abortedByUser: boolean },
): SseRetryDecision {
  if (ctx.abortedByUser) {
    return { kind: 'cancelled' };
  }

  if (ctx.streamStarted) {
    // See module docstring: cannot reattach; degrade to "check history".
    const err = coerceError(error);
    return {
      kind: 'disconnectMidStream',
      message:
        'The analysis connection was interrupted. Your request may still be running on the server — check the conversation history in a moment to see the final result.',
      error: err,
    };
  }

  // --- Pre-stream path -------------------------------------------------

  if (error instanceof ApiError) {
    // UPSTREAM = degradation-mode (LLM / DB / external backend jitter).
    // One short-delay retry, then give up.
    if (error.category === 'UPSTREAM') {
      if (!ctx.upstreamRetryUsed) {
        return {
          kind: 'retryPreStream',
          attempt: ctx.priorPreStreamAttempts + 1,
          // "maxAttempts" here is "network budget"; the UPSTREAM retry
          // reuses the same attempt counter so the UI shows a single
          // unified progress number. We still communicate a soft ceiling
          // of MAX_PRE_STREAM_NETWORK_RETRIES so "reconnecting (N/3)"
          // reads sensibly.
          maxAttempts: MAX_PRE_STREAM_NETWORK_RETRIES,
          delayMs: UPSTREAM_RETRY_DELAY_MS,
          reason: 'upstream',
        };
      }
      return {
        kind: 'giveUpPreStream',
        message:
          error.message ||
          'The analysis service is temporarily unavailable. Please try again in a moment.',
        error,
      };
    }

    // Any other category = concrete business error. Never retry.
    return { kind: 'businessError', apiError: error };
  }

  // Non-ApiError → network-layer failure (TypeError from fetch, etc.).
  if (isNetworkErrorLike(error)) {
    if (ctx.priorPreStreamAttempts < MAX_PRE_STREAM_NETWORK_RETRIES) {
      const nextAttempt = ctx.priorPreStreamAttempts + 1;
      return {
        kind: 'retryPreStream',
        attempt: nextAttempt,
        maxAttempts: MAX_PRE_STREAM_NETWORK_RETRIES,
        delayMs: backoffDelayMs(nextAttempt),
        reason: 'network',
      };
    }
    return {
      kind: 'giveUpPreStream',
      message:
        'Could not reach the analysis service after several attempts. Check your connection and try again.',
      error: coerceError(error),
    };
  }

  // Unknown, non-network, non-ApiError — don't retry (we have no signal
  // that retrying would help, and silent retry on unknown failures hides
  // real bugs).
  return {
    kind: 'giveUpPreStream',
    message:
      coerceError(error).message ||
      'Something went wrong while starting the analysis.',
    error: coerceError(error),
  };
}

/**
 * Exponential backoff for pre-stream network retries.
 * attempt=1 → 1000ms, attempt=2 → 2000ms, attempt=3 → 4000ms.
 */
export function backoffDelayMs(attempt: number): number {
  const safeAttempt = Math.max(1, attempt);
  return PRE_STREAM_BACKOFF_BASE_MS * Math.pow(2, safeAttempt - 1);
}

function isNetworkErrorLike(error: unknown): boolean {
  if (error instanceof TypeError) return true;
  // DOMException(AbortError) is already filtered via abortedByUser;
  // anything else with "network" in the message is a best-effort signal.
  if (error instanceof Error) {
    return /network|fetch failed|failed to fetch/i.test(error.message);
  }
  return false;
}

function coerceError(error: unknown): Error {
  if (error instanceof Error) return error;
  return new Error(typeof error === 'string' ? error : 'Unknown SSE error');
}
