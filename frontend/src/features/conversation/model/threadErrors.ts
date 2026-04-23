/**
 * Map an error raised by a conversation/thread query into a narrow UX
 * decision shape.
 *
 * backend.md §6.3.2 prescribes a two-tier dispatch: step 1 branches on
 * ``details.errorCode`` for precise copy, step 2 falls back to
 * ``details.category`` for generic bucketing. This module implements step 1
 * for the conversation-thread surface — the UI needs to tell apart:
 *
 *   - ``gone``       : the referenced thread / session truly no longer
 *                      exists for this user (backend returns
 *                      ``ANALYSIS_THREAD_NOT_FOUND`` /
 *                      ``ANALYSIS_SESSION_NOT_FOUND``). The currently
 *                      selected ``threadId`` in the URL is stale and should
 *                      be dropped.
 *   - ``archived``   : the thread exists but is archived and can no longer
 *                      accept runs (``ANALYSIS_THREAD_ARCHIVED``). Same URL
 *                      treatment as ``gone`` but different copy — the user
 *                      didn't do anything wrong, it's just read-only now.
 *   - ``transient``  : upstream (db / LLM / external backend) is
 *                      temporarily down. DO NOT strip the URL — the
 *                      selection is still valid; user should see a retry
 *                      hint and the query will naturally refetch on focus /
 *                      reconnect per our ``QueryClient`` defaults.
 *   - ``unknown``    : anything else (including the §6.5 framework-level
 *                      uncaught-exception fallback where ``details`` is
 *                      absent). Treat as "this session's state is
 *                      undefined" — surface a generic error and drop the
 *                      URL so the user lands in a known-good state rather
 *                      than staring at a blank detail pane.
 *
 * Kept inside ``features/conversation/model/`` because the mapping is
 * conversation-UX-specific; the raw `ANALYSIS_*` strings live in
 * ``shared/types/analysis/ErrorCode.ts`` but "what should Home do when
 * loading a thread fails" is a per-feature decision. The pure-data shape
 * ({@link ThreadErrorDecision}) means component code can delegate the
 * entire ``useEffect`` branching to one function call and stay React-free
 * here.
 */

import { ApiError } from '../../../shared/api';

export type ThreadErrorKind = 'gone' | 'archived' | 'transient' | 'unknown';

export interface ThreadErrorDecision {
  /** Coarse bucket the UI keys off. */
  kind: ThreadErrorKind;
  /** User-visible copy, already localized to the concrete error code. */
  message: string;
  /**
   * Whether the ``threadId`` search-param should be stripped from the URL.
   * ``gone`` / ``archived`` / ``unknown`` all drop the selection to keep
   * the app in a known-good state; ``transient`` preserves it so a retry /
   * refocus re-fetches into the same detail pane.
   */
  stripThreadIdFromUrl: boolean;
}

/**
 * Classify ``error`` (usually a TanStack Query's ``error`` field, which
 * axios has already narrowed to {@link ApiError} for non-2xx responses).
 * Returns ``null`` when there is no error — caller can just short-circuit
 * on that rather than maintaining a parallel ``if (error)`` guard.
 */
export function classifyThreadError(
  error: unknown,
): ThreadErrorDecision | null {
  if (!error) {
    return null;
  }

  if (error instanceof ApiError) {
    switch (error.errorCode) {
      case 'ANALYSIS_THREAD_NOT_FOUND':
      case 'ANALYSIS_SESSION_NOT_FOUND':
        return {
          kind: 'gone',
          message: 'This conversation no longer exists.',
          stripThreadIdFromUrl: true,
        };
      case 'ANALYSIS_THREAD_ARCHIVED':
        return {
          kind: 'archived',
          message:
            'This conversation has been archived and is read-only. Start a new conversation to continue.',
          stripThreadIdFromUrl: true,
        };
      default:
        break;
    }

    // Category-level fallback. UPSTREAM (C3 degradation-mode) is the one
    // case where we DO want to hold on to the URL — the thread is fine,
    // the backend is just down. Everything else (INTERNAL, stray AUTH at
    // this layer, unrecognized USER_INPUT shapes) is safer to strip.
    if (error.category === 'UPSTREAM') {
      return {
        kind: 'transient',
        message:
          'The analysis service is temporarily unavailable. Please try again in a moment.',
        stripThreadIdFromUrl: false,
      };
    }

    return {
      kind: 'unknown',
      message: error.message || 'Failed to load this conversation.',
      stripThreadIdFromUrl: true,
    };
  }

  // Non-ApiError (e.g. a plain Error from a network-layer oddity that
  // slipped through). We have no errorCode / category — treat as unknown.
  return {
    kind: 'unknown',
    message:
      error instanceof Error && error.message
        ? error.message
        : 'Failed to load this conversation.',
    stripThreadIdFromUrl: true,
  };
}
