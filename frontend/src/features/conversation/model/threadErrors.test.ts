/**
 * @vitest-environment node
 *
 * Unit tests for ``classifyThreadError`` — the per-code UX dispatcher
 * (backend.md §6.3.2 step 1) that tells Home how to react when
 * ``useConversationQuery(threadId)`` rejects.
 *
 * What we pin here:
 *
 *   - The four ``ANALYSIS_*`` codes we know the backend emits map to the
 *     right ``kind`` + ``stripThreadIdFromUrl`` verdicts. Drift on either
 *     side (silently renaming a code, forgetting to handle a new one)
 *     would make the UX regress to "silent URL drop on any error", which
 *     is exactly the bug §13.3 was logged against.
 *   - ``UPSTREAM`` category with an **unrecognized** errorCode still lands
 *     on the ``transient`` branch — this is the bridge that keeps the
 *     degradation-mode contract working without listing every future
 *     ``ANALYSIS_*_UNAVAILABLE`` code explicitly.
 *   - Non-{@link ApiError} throwables (plain ``Error``, network oddities)
 *     land on ``unknown`` rather than crashing the effect.
 *
 * ``node`` env because the classifier is pure TS (no DOM, no fetch).
 */

import { describe, it, expect } from 'vitest';
import { ApiError } from '../../../shared/api';
import { classifyThreadError } from './threadErrors';
import type { AnalysisErrorCode } from '../../../shared/types/analysis/ErrorCode';
import type { ErrorCategory } from '../../../shared/types/common';

function apiErrorOf(
  errorCode: AnalysisErrorCode,
  category: ErrorCategory,
  httpStatus = 400,
): ApiError {
  return new ApiError({
    httpStatus,
    message: 'stub',
    details: { errorCode, category },
  });
}

describe('classifyThreadError()', () => {
  it('returns null when there is no error', () => {
    expect(classifyThreadError(null)).toBeNull();
    expect(classifyThreadError(undefined)).toBeNull();
    expect(classifyThreadError(false)).toBeNull();
  });

  it('maps ANALYSIS_THREAD_NOT_FOUND → gone (strip URL)', () => {
    const decision = classifyThreadError(
      apiErrorOf('ANALYSIS_THREAD_NOT_FOUND', 'USER_INPUT', 404),
    );
    expect(decision).toEqual({
      kind: 'gone',
      message: 'This conversation no longer exists.',
      stripThreadIdFromUrl: true,
    });
  });

  it('maps ANALYSIS_SESSION_NOT_FOUND → gone (strip URL)', () => {
    const decision = classifyThreadError(
      apiErrorOf('ANALYSIS_SESSION_NOT_FOUND', 'USER_INPUT', 404),
    );
    expect(decision?.kind).toBe('gone');
    expect(decision?.stripThreadIdFromUrl).toBe(true);
  });

  it('maps ANALYSIS_THREAD_ARCHIVED → archived (strip URL, distinct copy)', () => {
    const decision = classifyThreadError(
      apiErrorOf('ANALYSIS_THREAD_ARCHIVED', 'USER_INPUT', 409),
    );
    expect(decision?.kind).toBe('archived');
    expect(decision?.stripThreadIdFromUrl).toBe(true);
    expect(decision?.message).not.toEqual(
      'This conversation no longer exists.',
    );
    expect(decision?.message.toLowerCase()).toContain('archiv');
  });

  it('maps ANALYSIS_DATABASE_UNAVAILABLE (UPSTREAM) → transient (KEEP URL)', () => {
    // The degradation-mode contract (backend.md §6.7): the DB is down, the
    // thread itself is fine. We must NOT evict the selection — when the DB
    // comes back the user's query will naturally refetch into the same
    // detail pane on TanStack's refetch-on-reconnect default.
    const decision = classifyThreadError(
      apiErrorOf('ANALYSIS_DATABASE_UNAVAILABLE', 'UPSTREAM', 503),
    );
    expect(decision?.kind).toBe('transient');
    expect(decision?.stripThreadIdFromUrl).toBe(false);
  });

  it('maps any UPSTREAM error → transient (future-proof for new *_UNAVAILABLE codes)', () => {
    // ANALYSIS_BACKEND_UNAVAILABLE and ANALYSIS_UPSTREAM_UNAVAILABLE are
    // both UPSTREAM — same treatment as the DB case without needing a
    // per-code branch, so a future `ANALYSIS_LLM_*_UNAVAILABLE` added to
    // the backend doesn't regress to the "unknown" branch before we get
    // round to mirroring it here.
    const decision = classifyThreadError(
      apiErrorOf('ANALYSIS_BACKEND_UNAVAILABLE', 'UPSTREAM', 503),
    );
    expect(decision?.kind).toBe('transient');
  });

  it('maps unrecognized ApiError → unknown (strip URL, preserve message)', () => {
    const decision = classifyThreadError(
      apiErrorOf('ANALYSIS_INVALID_ARGUMENT', 'USER_INPUT', 400),
    );
    expect(decision?.kind).toBe('unknown');
    expect(decision?.stripThreadIdFromUrl).toBe(true);
  });

  it('maps framework-level error (no details) → unknown', () => {
    // §6.5 fallback: ApiError carries httpStatus but no details. We have
    // no errorCode / category to work with — treat as unknown and strip.
    const decision = classifyThreadError(
      new ApiError({
        httpStatus: 500,
        message: 'Server crashed',
      }),
    );
    expect(decision?.kind).toBe('unknown');
    expect(decision?.message).toBe('Server crashed');
  });

  it('maps plain Error (non-ApiError) → unknown with its message preserved', () => {
    const decision = classifyThreadError(new Error('Network down'));
    expect(decision?.kind).toBe('unknown');
    expect(decision?.message).toBe('Network down');
    expect(decision?.stripThreadIdFromUrl).toBe(true);
  });

  it('maps thrown non-Error values → unknown with a fallback message', () => {
    const decision = classifyThreadError('something weird');
    expect(decision?.kind).toBe('unknown');
    expect(decision?.message).toBe('Failed to load this conversation.');
  });
});
